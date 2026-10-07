# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Drawing a Model with moderngl (OpenGL 3.3): skinning in the vertex
shader, clay / textured / flat / silhouette shading, key, 2-point,
3-point or environment light, wireframe, ground grid and a soft ground
shadow."""

import math
from dataclasses import dataclass, field

import numpy as np

from .model import MAX_BONES

MESH_VS = """
#version 330
uniform mat4 view_proj;
uniform mat4 model;
uniform mat4 post;
uniform bool skinned;
uniform mat4 bones[%d];
in vec3 in_pos;
in vec3 in_norm;
in vec2 in_uv;
in vec4 in_joints;
in vec4 in_weights;
out vec3 v_world;
out vec3 v_norm;
out vec2 v_uv;
void main() {
    mat4 m = model;
    if (skinned) {
        m = bones[int(in_joints.x)] * in_weights.x
          + bones[int(in_joints.y)] * in_weights.y
          + bones[int(in_joints.z)] * in_weights.z
          + bones[int(in_joints.w)] * in_weights.w;
    }
    vec4 w = post * (m * vec4(in_pos, 1.0));
    v_world = w.xyz;
    v_norm = mat3(m) * in_norm;
    v_uv = in_uv;
    gl_Position = view_proj * w;
}
""" % MAX_BONES

MESH_FS = """
#version 330
#define PI 3.14159265
uniform int shading;
uniform vec4 base_color;
uniform bool has_tex;
uniform sampler2D tex;
uniform int n_lights;
uniform vec3 light_dir[3];
uniform vec3 light_col[3];
uniform vec3 ambient;
uniform bool use_env;
uniform vec3 sh[9];
uniform sampler2D env_blur;
uniform float env_rot;
uniform float env_strength;
uniform vec3 cam_pos;
uniform float exposure;
uniform bool solid;
uniform vec4 solid_color;
in vec3 v_world;
in vec3 v_norm;
in vec2 v_uv;
out vec4 frag;

vec3 sh_eval(vec3 n) {
    return sh[0] * 0.282095
        + sh[1] * 0.488603 * n.y + sh[2] * 0.488603 * n.z
        + sh[3] * 0.488603 * n.x
        + sh[4] * 1.092548 * n.x * n.y + sh[5] * 1.092548 * n.y * n.z
        + sh[6] * 0.315392 * (3.0 * n.z * n.z - 1.0)
        + sh[7] * 1.092548 * n.x * n.z
        + sh[8] * 0.546274 * (n.x * n.x - n.y * n.y);
}
vec3 rot_y(vec3 d, float a) {
    float c = cos(a), s = sin(a);
    return vec3(c * d.x + s * d.z, d.y, -s * d.x + c * d.z);
}
vec2 equirect(vec3 d) {
    return vec2(0.5 + atan(d.x, -d.z) / (2.0 * PI),
                acos(clamp(d.y, -1.0, 1.0)) / PI);
}
void main() {
    if (solid) { frag = solid_color; return; }
    if (shading == 3) { frag = vec4(0.0, 0.0, 0.0, 1.0); return; }
    vec3 n = normalize(v_norm);
    if (shading == 2)
        n = normalize(cross(dFdx(v_world), dFdy(v_world)));
    vec3 v = normalize(cam_pos - v_world);
    if (dot(n, v) < 0.0) n = -n;
    vec3 albedo = shading == 0 ? vec3(0.72) : base_color.rgb;
    if (shading == 1 && has_tex)
        albedo *= pow(texture(tex, v_uv).rgb, vec3(2.2));
    vec3 col;
    if (use_env) {
        vec3 irr = max(sh_eval(rot_y(n, -env_rot)), 0.0) * env_strength;
        vec3 r = rot_y(reflect(-v, n), -env_rot);
        vec3 spec = texture(env_blur, equirect(r)).rgb * env_strength;
        float f = 0.04 + 0.96 * pow(1.0 - max(dot(n, v), 0.0), 5.0);
        col = albedo * irr + spec * f * 0.6;
    } else {
        col = albedo * ambient;
        for (int i = 0; i < n_lights; i++) {
            float d = max(dot(n, light_dir[i]), 0.0);
            vec3 h = normalize(light_dir[i] + v);
            float s = pow(max(dot(n, h), 0.0), 40.0) * 0.12;
            col += (albedo * d + s * d) * light_col[i];
        }
    }
    col *= exposure;
    col = col / (1.0 + col);
    frag = vec4(pow(col, vec3(1.0 / 2.2)), 1.0);
}
"""

QUAD_VS = """
#version 330
in vec2 in_pos;
out vec2 v_ndc;
void main() { v_ndc = in_pos; gl_Position = vec4(in_pos, 0.999, 1.0); }
"""

BG_FS = """
#version 330
#define PI 3.14159265
uniform bool show_env;
uniform sampler2D env;
uniform mat4 inv_view_proj;
uniform float env_rot;
uniform float env_strength;
uniform float exposure;
uniform vec4 color;
in vec2 v_ndc;
out vec4 frag;
vec3 rot_y(vec3 d, float a) {
    float c = cos(a), s = sin(a);
    return vec3(c * d.x + s * d.z, d.y, -s * d.x + c * d.z);
}
void main() {
    if (!show_env) { frag = color; return; }
    vec4 a = inv_view_proj * vec4(v_ndc, -1.0, 1.0);
    vec4 b = inv_view_proj * vec4(v_ndc, 1.0, 1.0);
    vec3 d = rot_y(normalize(b.xyz / b.w - a.xyz / a.w), -env_rot);
    vec2 uv = vec2(0.5 + atan(d.x, -d.z) / (2.0 * PI),
                   acos(clamp(d.y, -1.0, 1.0)) / PI);
    vec3 c = texture(env, uv).rgb * env_strength * exposure;
    c = c / (1.0 + c);
    frag = vec4(pow(c, vec3(1.0 / 2.2)), 1.0);
}
"""

LINE_VS = """
#version 330
uniform mat4 view_proj;
in vec3 in_pos;
out vec3 v_world;
void main() { v_world = in_pos; gl_Position = view_proj * vec4(in_pos, 1.0); }
"""

LINE_FS = """
#version 330
uniform vec4 color;
uniform vec3 center;
uniform float radius;
in vec3 v_world;
out vec4 frag;
void main() {
    float fade = 1.0 - smoothstep(radius * 0.4, radius, distance(v_world, center));
    frag = vec4(color.rgb, color.a * fade);
}
"""

GROUND_VS = """
#version 330
uniform mat4 view_proj;
uniform vec3 center;
uniform float half_size;
uniform float ground;
in vec2 in_pos;
out vec2 v_uv;
void main() {
    vec3 p = vec3(center.x + in_pos.x * half_size, ground,
                  center.z + in_pos.y * half_size);
    v_uv = in_pos * 0.5 + 0.5;
    gl_Position = view_proj * vec4(p, 1.0);
}
"""

GROUND_FS = """
#version 330
uniform sampler2D mask;
uniform float strength;
uniform float texel;
in vec2 v_uv;
out vec4 frag;
void main() {
    float m = 0.0;
    for (int x = -2; x <= 2; x++)
        for (int y = -2; y <= 2; y++)
            m += texture(mask, v_uv + vec2(x, y) * texel * 2.0).r;
    m /= 25.0;
    frag = vec4(0.0, 0.0, 0.0, m * strength);
}
"""

SHADOW_SIZE = 1024


@dataclass
class Look:
    """How a frame is drawn."""
    shading: str = 'clay'          # clay, textured, flat, silhouette
    wire: bool = False
    grid: bool = True
    shadow: bool = True
    lighting: str = '3-point'      # key, 2-point, 3-point, environment
    light_yaw: float = 0.0         # radians, turns lights / environment
    strength: float = 1.0
    exposure: float = 1.0
    show_env: bool = False
    background: tuple = (0.16, 0.16, 0.17, 1.0)
    transparent: bool = False
    extra: dict = field(default_factory=dict)


def direction(yaw, elevation):
    ce = math.cos(elevation)
    return np.array([ce * math.sin(yaw), math.sin(elevation),
                     ce * math.cos(yaw)])


def lights_for(look):
    """[(direction to the light, colour)] and ambient for the light
    modes (world space, turned by light_yaw)."""
    y, k = look.light_yaw, look.strength
    key = (direction(y + math.radians(40), math.radians(40)),
           np.array([1.0, 0.97, 0.92]) * 2.6 * k)
    fill = (direction(y - math.radians(55), math.radians(15)),
            np.array([0.85, 0.9, 1.0]) * 0.9 * k)
    rim = (direction(y + math.radians(165), math.radians(35)),
           np.array([1.0, 1.0, 1.0]) * 2.0 * k)
    if look.lighting == 'key':
        return [key], np.full(3, 0.10)
    if look.lighting == '2-point':
        return [key, fill], np.full(3, 0.07)
    return [key, fill, rim], np.full(3, 0.06)


def flatten_matrix(light, ground):
    """Projects points onto the plane y = ground along `light`."""
    lx, ly, lz = light
    ly = max(ly, 0.25)
    m = np.eye(4)
    m[0] = [1, -lx / ly, 0, lx / ly * ground]
    m[1] = [0, 0, 0, ground]
    m[2] = [0, -lz / ly, 1, lz / ly * ground]
    return m


def _f32(m):
    """A 4x4 for GLSL (column-major bytes)."""
    return np.asarray(m, np.float32).T.copy().tobytes()


class Renderer:
    def __init__(self, ctx):
        self.ctx = ctx
        self.mesh_prog = ctx.program(vertex_shader=MESH_VS,
                                     fragment_shader=MESH_FS)
        self.bg_prog = ctx.program(vertex_shader=QUAD_VS,
                                   fragment_shader=BG_FS)
        self.line_prog = ctx.program(vertex_shader=LINE_VS,
                                     fragment_shader=LINE_FS)
        self.ground_prog = ctx.program(vertex_shader=GROUND_VS,
                                       fragment_shader=GROUND_FS)
        quad = np.array([-1, -1, 3, -1, -1, 3], np.float32)
        self.quad_vbo = ctx.buffer(quad.tobytes())
        self.bg_vao = ctx.vertex_array(self.bg_prog,
                                       [(self.quad_vbo, '2f', 'in_pos')])
        ground = np.array([-1, -1, 1, -1, -1, 1, 1, 1], np.float32)
        self.ground_vbo = ctx.buffer(ground.tobytes())
        self.ground_vao = ctx.vertex_array(
            self.ground_prog, [(self.ground_vbo, '2f', 'in_pos')])
        self.shadow_tex = ctx.texture((SHADOW_SIZE, SHADOW_SIZE), 1)
        self.shadow_tex.filter = (ctx.LINEAR, ctx.LINEAR)
        self.shadow_fbo = ctx.framebuffer(color_attachments=[self.shadow_tex])
        self.meshes = []
        self.model = None
        self.grid_vao = None
        self.env = None
        self.env_tex = self.env_blur_tex = None
        self.white = ctx.texture((1, 1), 4, b'\xff\xff\xff\xff')

    # -- uploading --

    def set_model(self, model):
        for m in self.meshes:
            for res in m['res']:
                res.release()
        self.meshes = []
        self.model = model
        prog = self.mesh_prog
        for mesh in model.meshes:
            n = len(mesh.positions)
            uvs = mesh.uvs if mesh.uvs is not None else \
                np.zeros((n, 2), np.float32)
            joints = (mesh.joints.astype(np.float32) if mesh.skinned
                      else np.zeros((n, 4), np.float32))
            weights = (mesh.weights.astype(np.float32) if mesh.skinned
                       else np.zeros((n, 4), np.float32))
            data = np.hstack([mesh.positions, mesh.normals, uvs, joints,
                              weights]).astype(np.float32)
            vbo = self.ctx.buffer(data.tobytes())
            ibo = self.ctx.buffer(mesh.indices.astype(np.uint32).tobytes())
            vao = self.ctx.vertex_array(
                prog, [(vbo, '3f 3f 2f 4f 4f', 'in_pos', 'in_norm', 'in_uv',
                        'in_joints', 'in_weights')], ibo)
            res = [vbo, ibo, vao]
            tex = None
            if mesh.texture is not None:
                img = mesh.texture
                raw = img.constBits().asstring(img.sizeInBytes())
                tex = self.ctx.texture((img.width(), img.height()), 4, raw)
                tex.build_mipmaps()
                tex.filter = (self.ctx.LINEAR_MIPMAP_LINEAR, self.ctx.LINEAR)
                res.append(tex)
            self.meshes.append({'mesh': mesh, 'vao': vao, 'tex': tex,
                                'res': res})

    def set_env(self, env):
        for t in (self.env_tex, self.env_blur_tex):
            if t is not None:
                t.release()
        self.env = env
        h, w, _ = env.image.shape
        self.env_tex = self.ctx.texture(
            (w, h), 3, env.image.astype(np.float16).tobytes(), dtype='f2')
        self.env_tex.filter = (self.ctx.LINEAR, self.ctx.LINEAR)
        self.env_tex.repeat_y = False
        bh, bw, _ = env.blurred.shape
        self.env_blur_tex = self.ctx.texture(
            (bw, bh), 3, env.blurred.astype(np.float16).tobytes(),
            dtype='f2')
        self.env_blur_tex.filter = (self.ctx.LINEAR, self.ctx.LINEAR)
        self.env_blur_tex.repeat_y = False

    def _grid(self, center, size, ground):
        step = 10 ** math.floor(math.log10(max(size, 1e-6) / 2))
        n = 20
        lines = []
        cx = round(center[0] / step) * step
        cz = round(center[2] / step) * step
        for i in range(-n, n + 1):
            lines += [cx + i * step, ground, cz - n * step,
                      cx + i * step, ground, cz + n * step,
                      cx - n * step, ground, cz + i * step,
                      cx + n * step, ground, cz + i * step]
        if self.grid_vao is not None:
            self.grid_vao.release()
            self.grid_vbo.release()
        self.grid_vbo = self.ctx.buffer(np.array(lines, np.float32).tobytes())
        self.grid_vao = self.ctx.vertex_array(
            self.line_prog, [(self.grid_vbo, '3f', 'in_pos')])
        self.grid_key = (round(size, 6), round(ground, 6))
        return n * step

    # -- drawing --

    def _draw_meshes(self, view_proj, globals_, skin, post=None,
                     solid=None):
        prog = self.mesh_prog
        prog['view_proj'].write(_f32(view_proj))
        prog['post'].write(_f32(post if post is not None else np.eye(4)))
        if len(skin):
            mats = np.zeros((MAX_BONES, 4, 4), np.float32)
            mats[:len(skin)] = skin
            prog['bones'].write(mats.transpose(0, 2, 1).copy().tobytes())
        prog['solid'].value = solid is not None
        if solid is not None:
            prog['solid_color'].value = tuple(solid)
        for m in self.meshes:
            mesh = m['mesh']
            prog['skinned'].value = bool(mesh.skinned and len(skin))
            model_m = globals_[mesh.node] if mesh.node >= 0 else np.eye(4)
            prog['model'].write(_f32(model_m))
            prog['base_color'].value = tuple(mesh.color)
            has_tex = m['tex'] is not None
            prog['has_tex'].value = has_tex
            (m['tex'] or self.white).use(0)
            prog['tex'].value = 0
            m['vao'].render()

    def render(self, fbo, size, view, proj, cam_pos, globals_, skin, look,
               bounds):
        ctx = self.ctx
        fbo.use()
        ctx.viewport = (0, 0, size[0], size[1])
        bg = (0, 0, 0, 0) if look.transparent else look.background
        fbo.clear(*bg, depth=1.0)
        view_proj = proj @ view
        lo, hi = bounds
        center = (lo + hi) / 2
        extent = float(np.linalg.norm(hi - lo)) or 1.0
        ground = float(lo[1])

        ctx.disable(ctx.DEPTH_TEST)
        ctx.enable(ctx.BLEND)
        # Alpha adds up separately, so a transparent export keeps the
        # shadow's own transparency
        ctx.blend_func = (ctx.SRC_ALPHA, ctx.ONE_MINUS_SRC_ALPHA,
                          ctx.ONE, ctx.ONE_MINUS_SRC_ALPHA)
        use_env = look.lighting == 'environment' and self.env is not None
        if not look.transparent:
            bp = self.bg_prog
            bp['show_env'].value = bool(use_env and look.show_env)
            bp['color'].value = tuple(look.background)
            bp['inv_view_proj'].write(_f32(np.linalg.inv(view_proj)))
            bp['env_rot'].value = look.light_yaw
            bp['env_strength'].value = look.strength
            bp['exposure'].value = look.exposure
            if self.env_tex is not None:
                self.env_tex.use(1)
                bp['env'].value = 1
            self.bg_vao.render()

        ctx.enable(ctx.DEPTH_TEST)
        if look.grid:
            if self.grid_vao is None or self.grid_key != (
                    round(extent, 6), round(ground, 6)):
                self.grid_radius = self._grid(center, extent, ground)
            lp = self.line_prog
            lp['view_proj'].write(_f32(view_proj))
            lp['color'].value = (0.5, 0.5, 0.52, 0.35)
            lp['center'].value = tuple(center)
            lp['radius'].value = self.grid_radius
            self.grid_vao.render(ctx.LINES)

        lights, ambient = lights_for(look)
        if look.shadow and look.shading != 'silhouette':
            self._shadow(globals_, skin, center, extent, ground,
                         np.array([0, 1.0, 0]) if use_env else lights[0][0])
            fbo.use()
            ctx.viewport = (0, 0, size[0], size[1])
            self._ground(fbo, view_proj, center, extent, ground)

        prog = self.mesh_prog
        prog['shading'].value = ['clay', 'textured', 'flat',
                                 'silhouette'].index(look.shading)
        prog['cam_pos'].value = tuple(cam_pos)
        prog['exposure'].value = look.exposure
        prog['use_env'].value = bool(use_env)
        if use_env:
            prog['sh'].write(np.asarray(self.env.sh, np.float32).tobytes())
            self.env_blur_tex.use(2)
            prog['env_blur'].value = 2
            prog['env_rot'].value = look.light_yaw
            prog['env_strength'].value = look.strength
        else:
            dirs = np.zeros((3, 3), np.float32)
            cols = np.zeros((3, 3), np.float32)
            for i, (d, c) in enumerate(lights):
                dirs[i], cols[i] = d, c
            prog['n_lights'].value = len(lights)
            prog['light_dir'].write(dirs.tobytes())
            prog['light_col'].write(cols.tobytes())
            prog['ambient'].value = tuple(ambient)
        ctx.disable(ctx.BLEND)
        self._draw_meshes(view_proj, globals_, skin)

        if look.wire:
            ctx.enable(ctx.BLEND)
            ctx.wireframe = True
            ctx.depth_func = '<='
            dark = look.shading != 'silhouette'
            self._draw_meshes(view_proj, globals_, skin,
                              solid=(0.05, 0.05, 0.06, 0.55) if dark
                              else (0.9, 0.9, 0.9, 0.5))
            ctx.wireframe = False
            ctx.depth_func = '<'

    def _shadow(self, globals_, skin, center, extent, ground, light):
        """The model flattened onto the ground along the light, seen from
        above, into a mask."""
        ctx = self.ctx
        half = extent * 1.2
        self.shadow_fbo.use()
        ctx.viewport = (0, 0, SHADOW_SIZE, SHADOW_SIZE)
        self.shadow_fbo.clear(0, 0, 0, 0)
        top = np.eye(4)
        top[0] = [1 / half, 0, 0, -center[0] / half]
        top[1] = [0, 0, 1 / half, -center[2] / half]
        top[2] = [0, 0, 0, 0]
        ctx.disable(ctx.DEPTH_TEST)
        ctx.disable(ctx.BLEND)
        self._draw_meshes(top, globals_, skin,
                          post=flatten_matrix(light, ground),
                          solid=(1, 1, 1, 1))

    def _ground(self, fbo, view_proj, center, extent, ground):
        """The shadow mask, softened, on the ground under the model."""
        ctx = self.ctx
        half = extent * 1.2
        ctx.enable(ctx.DEPTH_TEST)
        ctx.enable(ctx.BLEND)
        gp = self.ground_prog
        gp['view_proj'].write(_f32(view_proj))
        gp['center'].value = tuple(center)
        gp['half_size'].value = half
        gp['ground'].value = ground + extent * 1e-4
        gp['strength'].value = 0.45
        gp['texel'].value = 1.0 / SHADOW_SIZE
        self.shadow_tex.use(3)
        gp['mask'].value = 3
        fbo.depth_mask = False
        self.ground_vao.render(ctx.TRIANGLE_STRIP)
        fbo.depth_mask = True

    def hand_back(self):
        """Leave OpenGL as Qt expects before it paints text and shapes
        on top (else its glyph textures come out scrambled)."""
        ctx = self.ctx
        ctx.wireframe = False
        ctx.disable(ctx.DEPTH_TEST)
        self.white.use(0)                # active texture unit 0
        try:
            import ctypes
            gl = ctypes.windll.opengl32 if hasattr(ctypes, 'windll') else \
                ctypes.CDLL('libGL.so.1')
            gl.glPixelStorei(0x0CF5, 4)  # GL_UNPACK_ALIGNMENT
            gl.glPixelStorei(0x0D05, 4)  # GL_PACK_ALIGNMENT
            gl.glBindTexture(0x0DE1, 0)  # GL_TEXTURE_2D
        except Exception:
            pass

    # -- images --

    def snapshot(self, size, view, proj, cam_pos, globals_, skin, look,
                 bounds, samples=4):
        """The frame at `size` as RGBA bytes (top row first)."""
        ctx = self.ctx
        w, h = size
        samples = min(samples, ctx.max_samples)
        color = ctx.renderbuffer((w, h), 4, samples=samples)
        depth = ctx.depth_renderbuffer((w, h), samples=samples)
        ms = ctx.framebuffer([color], depth)
        out_tex = ctx.texture((w, h), 4)
        out = ctx.framebuffer([out_tex])
        try:
            self.render(ms, (w, h), view, proj, cam_pos, globals_, skin,
                        look, bounds)
            ctx.copy_framebuffer(out, ms)
            raw = out.read(components=4, alignment=1)
        finally:
            for res in (ms, out, color, depth, out_tex):
                res.release()
        rows = np.frombuffer(raw, np.uint8).reshape(h, w, 4)[::-1]
        return np.ascontiguousarray(rows).tobytes()
