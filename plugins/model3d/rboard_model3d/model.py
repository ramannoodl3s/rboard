# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""A loaded 3D model: meshes, a node hierarchy (bones are nodes), skins,
and the math to pose it.

Conventions: Y up, right-handed, column vectors (p' = M @ p), quaternions
as (x, y, z, w). A pose is per node: a move and a rotation in the node's
own rest space, applied on top of its rest transform (as in Blender's
pose mode)."""

import math

import numpy as np

MAX_BONES = 128


# ---------- quaternions and matrices ----------

def quat_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return np.array([aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw,
                     aw * bw - ax * bx - ay * by - az * bz])


def quat_axis_angle(axis, angle):
    axis = np.asarray(axis, np.float64)
    n = np.linalg.norm(axis)
    if n < 1e-12:
        return np.array([0.0, 0.0, 0.0, 1.0])
    s = math.sin(angle / 2) / n
    return np.array([axis[0] * s, axis[1] * s, axis[2] * s,
                     math.cos(angle / 2)])


def quat_normalize(q):
    q = np.asarray(q, np.float64)
    n = np.linalg.norm(q)
    return q / n if n > 0 else np.array([0.0, 0.0, 0.0, 1.0])


def quat_to_mat3(q):
    x, y, z, w = quat_normalize(q)
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def mat3_to_quat(m):
    t = m[0, 0] + m[1, 1] + m[2, 2]
    if t > 0:
        s = math.sqrt(t + 1) * 2
        q = [(m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s,
             (m[1, 0] - m[0, 1]) / s, s / 4]
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        q = [s / 4, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s,
             (m[2, 1] - m[1, 2]) / s]
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        q = [(m[0, 1] + m[1, 0]) / s, s / 4, (m[1, 2] + m[2, 1]) / s,
             (m[0, 2] - m[2, 0]) / s]
    else:
        s = math.sqrt(1 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        q = [(m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, s / 4,
             (m[1, 0] - m[0, 1]) / s]
    return quat_normalize(q)


def trs(t=(0, 0, 0), r=(0, 0, 0, 1), s=(1, 1, 1)):
    m = np.eye(4)
    m[:3, :3] = quat_to_mat3(r) * np.asarray(s, np.float64)[None, :]
    m[:3, 3] = t
    return m


def decompose(m):
    """(t, r quaternion, s) of an affine 4x4."""
    t = m[:3, 3].copy()
    cols = m[:3, :3]
    s = np.linalg.norm(cols, axis=0)
    s = np.where(s > 1e-12, s, 1.0)
    rot = cols / s[None, :]
    if np.linalg.det(rot) < 0:
        s[0] = -s[0]
        rot[:, 0] = -rot[:, 0]
    return t, mat3_to_quat(rot), s


def perspective(fov_y, aspect, near, far):
    f = 1 / math.tan(fov_y / 2)
    m = np.zeros((4, 4))
    m[0, 0], m[1, 1] = f / aspect, f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = 2 * far * near / (near - far)
    m[3, 2] = -1
    return m


def orthographic(height, aspect, near, far):
    m = np.eye(4)
    m[0, 0] = 2 / (height * aspect)
    m[1, 1] = 2 / height
    m[2, 2] = -2 / (far - near)
    m[2, 3] = -(far + near) / (far - near)
    return m


def look_at(eye, target, up=(0, 1, 0)):
    eye, target = np.asarray(eye, float), np.asarray(target, float)
    f = target - eye
    f /= np.linalg.norm(f)
    r = np.cross(f, up)
    if np.linalg.norm(r) < 1e-9:
        r = np.cross(f, (0, 0, 1))
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    m = np.eye(4)
    m[0, :3], m[1, :3], m[2, :3] = r, u, -f
    m[:3, 3] = -m[:3, :3] @ eye
    return m


def lens_to_fov(mm, sensor=36.0):
    """Vertical field of view for a lens on a full-frame sensor (as
    Blender's camera, with a 16:9 frame)."""
    return 2 * math.atan((sensor * 9 / 16) / (2 * mm))


# ---------- the model ----------

class Node:
    def __init__(self, name, parent=-1, t=(0, 0, 0), r=(0, 0, 0, 1),
                 s=(1, 1, 1)):
        self.name = name
        self.parent = parent
        self.t = np.asarray(t, np.float64)
        self.r = quat_normalize(r)
        self.s = np.asarray(s, np.float64)
        self.is_bone = False

    def rest(self):
        return trs(self.t, self.r, self.s)


class Mesh:
    """Triangles; positions in the space of `node` (or, when skinned, in
    bind space: joint globals @ inverse binds place them)."""

    def __init__(self, positions, indices, normals=None, uvs=None,
                 joints=None, weights=None, color=(0.8, 0.8, 0.8, 1.0),
                 texture=None, node=-1, name=''):
        self.positions = np.ascontiguousarray(positions, np.float32)
        self.indices = np.ascontiguousarray(indices, np.uint32).ravel()
        self.normals = (np.ascontiguousarray(normals, np.float32)
                        if normals is not None else
                        smooth_normals(self.positions, self.indices))
        self.uvs = (np.ascontiguousarray(uvs, np.float32)
                    if uvs is not None else None)
        self.joints = joints     # (N, 4) indices into model.joints
        self.weights = weights   # (N, 4), rows sum to 1
        self.color = tuple(color)
        self.texture = texture   # QImage or None
        self.node = node
        self.name = name

    @property
    def skinned(self):
        return self.joints is not None

    @property
    def triangles(self):
        return len(self.indices) // 3


def smooth_normals(positions, indices):
    tris = positions[indices.reshape(-1, 3)]
    face = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    normals = np.zeros_like(positions)
    for k in range(3):
        np.add.at(normals, indices.reshape(-1, 3)[:, k], face)
    n = np.linalg.norm(normals, axis=1, keepdims=True)
    return (normals / np.where(n > 0, n, 1)).astype(np.float32)


class Model:
    def __init__(self, nodes, meshes, joints=(), inverse_binds=None,
                 name=''):
        self.nodes = list(nodes)
        self.meshes = list(meshes)
        # One joint list shared by all skinned meshes: node indices
        self.joints = list(joints)
        self.inverse_binds = (np.asarray(inverse_binds, np.float64)
                              if inverse_binds is not None
                              else np.zeros((0, 4, 4)))
        self.name = name
        for j in self.joints:
            self.nodes[j].is_bone = True
        self._order = self._parents_first()
        self._size_cache = None

    def _parents_first(self):
        order, seen = [], set()

        def visit(i):
            if i in seen:
                return
            p = self.nodes[i].parent
            if p >= 0:
                visit(p)
            seen.add(i)
            order.append(i)
        for i in range(len(self.nodes)):
            visit(i)
        return order

    @property
    def triangles(self):
        return sum(m.triangles for m in self.meshes)

    @property
    def rigged(self):
        return bool(self.joints) and any(m.skinned for m in self.meshes)

    def children(self, i):
        return [k for k, n in enumerate(self.nodes) if n.parent == i]

    # -- posing --

    def globals(self, pose=None):
        """World matrix of every node with a pose {node: (move, quat)}."""
        out = [None] * len(self.nodes)
        for i in self._order:
            node = self.nodes[i]
            local = node.rest()
            if pose and i in pose:
                move, rot = pose[i]
                local = local @ trs(move, rot)
            out[i] = local if node.parent < 0 else out[node.parent] @ local
        return out

    def skin_matrices(self, globals_):
        if not self.joints:
            return np.zeros((0, 4, 4), np.float32)
        return np.array([globals_[j] @ ib for j, ib in
                         zip(self.joints, self.inverse_binds)], np.float32)

    def bounds(self, pose=None):
        """(min, max) of all vertices as posed (skinned on the CPU, once
        per call; for fitting the camera, not for drawing)."""
        g = self.globals(pose)
        skin = self.skin_matrices(g)
        lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
        for mesh in self.meshes:
            p = np.c_[mesh.positions, np.ones(len(mesh.positions))]
            if mesh.skinned and len(skin):
                m = np.einsum('nk,nkij->nij', mesh.weights,
                              skin[mesh.joints])
                world = np.einsum('nij,nj->ni', m, p)[:, :3]
            else:
                node_m = g[mesh.node] if mesh.node >= 0 else np.eye(4)
                world = (p @ node_m.T)[:, :3]
            if len(world):
                lo = np.minimum(lo, world.min(0))
                hi = np.maximum(hi, world.max(0))
        if not np.isfinite(lo).all():
            return np.zeros(3), np.ones(3)
        return lo, hi

    # -- bones for display --

    def bone_segments(self, globals_):
        """[(joint index, head, tail)] in world space. A bone's tail is its
        first child bone's head, else it continues its parent's length
        along its own Y (Blender's bones point down local Y)."""
        heads = {j: globals_[j][:3, 3] for j in self.joints}
        joint_set = set(self.joints)
        out = []
        for j in self.joints:
            kids = [k for k in self.children(j) if k in joint_set]
            head = heads[j]
            if kids:
                tail = np.mean([heads[k] for k in kids], axis=0)
                if np.linalg.norm(tail - head) < 1e-9:
                    tail = None
            else:
                tail = None
            if tail is None:
                parent = self.nodes[j].parent
                length = (np.linalg.norm(head - heads[parent])
                          if parent in heads else 0) or self._size() * 0.1
                axis = globals_[j][:3, 1]
                n = np.linalg.norm(axis)
                axis = axis / n if n > 0 else np.array([0, 1.0, 0])
                tail = head + axis * length * 0.5
            out.append((j, head, tail))
        return out

    def _size(self):
        if self._size_cache is None:
            lo, hi = self.bounds()
            self._size_cache = float(np.linalg.norm(hi - lo)) or 1.0
        return self._size_cache
