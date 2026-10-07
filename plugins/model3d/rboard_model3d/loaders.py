# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Reading .obj, .gltf/.glb and binary .fbx into a Model, within fixed
limits so nothing loads that would make the viewer crawl."""

import base64
import json
import math
import os
import struct
import zlib

import numpy as np

from .model import (MAX_BONES, Mesh, Model, Node, decompose,
                    quat_axis_angle, quat_mul, trs)

MAX_FILE_MB = 50
MAX_TRIANGLES = 1_000_000
MAX_TEXTURE = 2048
EXTENSIONS = ('.obj', '.fbx', '.glb', '.gltf')


class LoadError(Exception):
    pass


# ---------- entry point ----------

def file_size(path):
    """Bytes the model needs from disk (glTF counts its buffer files)."""
    size = os.path.getsize(path)
    if path.lower().endswith('.gltf'):
        try:
            with open(path, encoding='utf-8') as f:
                doc = json.load(f)
            for buf in doc.get('buffers', []):
                uri = buf.get('uri', '')
                if uri and not uri.startswith('data:'):
                    extra = os.path.join(os.path.dirname(path), uri)
                    if os.path.exists(extra):
                        size += os.path.getsize(extra)
        except (OSError, ValueError):
            pass
    return size


def check_size(path):
    if not os.path.isfile(path):
        raise LoadError('the model file was not found')
    mb = file_size(path) / 1e6
    if mb > MAX_FILE_MB:
        raise LoadError(f'the model is {mb:.0f} MB; the limit is '
                        f'{MAX_FILE_MB} MB')


def load(path, progress=lambda f: None):
    """A Model from a file, or LoadError saying why not."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in EXTENSIONS:
        raise LoadError(f'{ext or "that"} files aren\'t supported; use '
                        '.obj, .fbx, .glb or .gltf')
    check_size(path)
    progress(0.05)
    try:
        if ext == '.obj':
            model = load_obj(path)
        elif ext == '.fbx':
            model = load_fbx(path, progress)
        else:
            model = load_gltf(path)
    except LoadError:
        raise
    except Exception as e:
        raise LoadError(f'could not read the model: {e}') from e
    if not model.meshes:
        raise LoadError('the file has no meshes')
    tris = model.triangles
    if tris > MAX_TRIANGLES:
        raise LoadError(f'the model has {tris:,} triangles; the limit is '
                        f'{MAX_TRIANGLES:,}')
    if len(model.joints) > MAX_BONES:
        raise LoadError(f'the rig has {len(model.joints)} bones; the limit '
                        f'is {MAX_BONES}')
    model.name = os.path.splitext(os.path.basename(path))[0]
    progress(1.0)
    return model


def load_texture(data=None, path=None):
    """A QImage (RGBA, at most MAX_TEXTURE px) or None."""
    from PyQt6 import QtCore, QtGui
    img = QtGui.QImage()
    if data is not None:
        img.loadFromData(data)
    elif path and os.path.isfile(path):
        img.load(path)
    if img.isNull():
        return None
    if max(img.width(), img.height()) > MAX_TEXTURE:
        img = img.scaled(MAX_TEXTURE, MAX_TEXTURE,
                         QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                         QtCore.Qt.TransformationMode.SmoothTransformation)
    return img.convertToFormat(QtGui.QImage.Format.Format_RGBA8888)


def _find_texture(folder, name):
    """A texture file by the name a model gives it, looking next to the
    model and in common texture folders."""
    if not name:
        return None
    name = name.replace('\\', '/')
    tries = [name, os.path.basename(name)]
    for sub in ('', 'textures', 'Textures', 'tex', 'images'):
        for t in tries:
            path = os.path.join(folder, sub, t) if sub else \
                os.path.join(folder, t)
            if os.path.isfile(path):
                return path
    return None


# ---------- OBJ ----------

def _read_mtl(path):
    materials, current = {}, None
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            for line in f:
                parts = line.split()
                if not parts:
                    continue
                if parts[0] == 'newmtl':
                    current = ' '.join(parts[1:])
                    materials[current] = {'color': (0.8, 0.8, 0.8, 1.0),
                                          'map': None}
                elif current and parts[0] == 'Kd' and len(parts) >= 4:
                    materials[current]['color'] = (
                        float(parts[1]), float(parts[2]), float(parts[3]),
                        1.0)
                elif current and parts[0] == 'map_Kd':
                    materials[current]['map'] = parts[-1]
    except OSError:
        pass
    return materials


def load_obj(path):
    folder = os.path.dirname(path)
    v, vt, vn = [], [], []
    groups = {}          # material -> list of (v, vt, vn) corner triples
    material = None
    materials = {}
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            if not line or line[0] == '#':
                continue
            parts = line.split()
            if not parts:
                continue
            tag = parts[0]
            if tag == 'v':
                v.append(parts[1:4])
            elif tag == 'vt':
                vt.append(parts[1:3])
            elif tag == 'vn':
                vn.append(parts[1:4])
            elif tag == 'f':
                corners = []
                for c in parts[1:]:
                    ids = c.split('/')
                    vi = int(ids[0])
                    ti = int(ids[1]) if len(ids) > 1 and ids[1] else 0
                    ni = int(ids[2]) if len(ids) > 2 and ids[2] else 0
                    corners.append((vi if vi > 0 else len(v) + vi + 1,
                                    ti if ti >= 0 else len(vt) + ti + 1,
                                    ni if ni >= 0 else len(vn) + ni + 1))
                faces = groups.setdefault(material, [])
                for k in range(1, len(corners) - 1):   # fan
                    faces.extend((corners[0], corners[k], corners[k + 1]))
            elif tag == 'usemtl':
                material = ' '.join(parts[1:])
            elif tag == 'mtllib':
                materials.update(_read_mtl(os.path.join(
                    folder, ' '.join(parts[1:]))))
    pos = np.array(v, np.float32).reshape(-1, 3)
    uv = np.array(vt, np.float32).reshape(-1, 2) if vt else None
    nor = np.array(vn, np.float32).reshape(-1, 3) if vn else None
    meshes = []
    for name, corners in groups.items():
        if not corners:
            continue
        c = np.array(corners, np.int64)
        unique, inverse = np.unique(c, axis=0, return_inverse=True)
        mesh_pos = pos[unique[:, 0] - 1]
        mesh_uv = (uv[unique[:, 1] - 1].copy() if uv is not None and
                   (unique[:, 1] > 0).all() else None)
        if mesh_uv is not None:
            mesh_uv[:, 1] = 1 - mesh_uv[:, 1]   # OBJ v goes up
        mesh_n = (nor[unique[:, 2] - 1] if nor is not None and
                  (unique[:, 2] > 0).all() else None)
        info = materials.get(name, {})
        texture = None
        if info.get('map') and mesh_uv is not None:
            texture = load_texture(path=_find_texture(folder, info['map']))
        meshes.append(Mesh(mesh_pos, inverse.ravel(), mesh_n, mesh_uv,
                           color=info.get('color', (0.8, 0.8, 0.8, 1.0)),
                           texture=texture, node=0, name=name or ''))
    return Model([Node('root')], meshes)


# ---------- glTF / GLB ----------

COMPONENTS = {5120: np.int8, 5121: np.uint8, 5122: np.int16,
              5123: np.uint16, 5125: np.uint32, 5126: np.float32}
WIDTHS = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}


def load_gltf(path):
    folder = os.path.dirname(path)
    with open(path, 'rb') as f:
        raw = f.read()
    binary = None
    if raw[:4] == b'glTF':
        length = struct.unpack_from('<I', raw, 8)[0]
        offset = 12
        doc = None
        while offset < length:
            size, kind = struct.unpack_from('<II', raw, offset)
            chunk = raw[offset + 8:offset + 8 + size]
            if kind == 0x4E4F534A:
                doc = json.loads(chunk.decode('utf-8'))
            elif kind == 0x004E4942:
                binary = chunk
            offset += 8 + size
    else:
        doc = json.loads(raw.decode('utf-8'))

    buffers = []
    for buf in doc.get('buffers', []):
        uri = buf.get('uri')
        if uri is None:
            buffers.append(binary)
        elif uri.startswith('data:'):
            buffers.append(base64.b64decode(uri.split(',', 1)[1]))
        else:
            with open(os.path.join(folder, uri), 'rb') as f:
                buffers.append(f.read())

    def view_bytes(index):
        bv = doc['bufferViews'][index]
        data = buffers[bv['buffer']]
        start = bv.get('byteOffset', 0)
        return data[start:start + bv['byteLength']], bv.get('byteStride')

    def accessor(index):
        acc = doc['accessors'][index]
        dtype = np.dtype(COMPONENTS[acc['componentType']])
        width = WIDTHS[acc['type']]
        count = acc['count']
        if 'bufferView' not in acc:
            out = np.zeros((count, width), dtype)
        else:
            data, stride = view_bytes(acc['bufferView'])
            offset = acc.get('byteOffset', 0)
            item = dtype.itemsize * width
            if stride and stride != item:
                rows = np.frombuffer(data, np.uint8, count=stride * (count - 1)
                                     + item, offset=offset)
                rows = np.lib.stride_tricks.as_strided(
                    rows, (count, item), (stride, 1))
                out = np.frombuffer(rows.copy().tobytes(), dtype).reshape(
                    count, width)
            else:
                out = np.frombuffer(data, dtype, count * width,
                                    offset).reshape(count, width)
        if acc.get('normalized') and dtype.kind in 'iu':
            out = out.astype(np.float32) / np.iinfo(dtype).max
        return out

    images = {}

    def texture_for(material):
        pbr = material.get('pbrMetallicRoughness', {})
        info = pbr.get('baseColorTexture')
        if info is None:
            return None
        tex = doc['textures'][info['index']]
        src = tex.get('source')
        if src is None:
            return None
        if src not in images:
            image = doc['images'][src]
            if 'bufferView' in image:
                data, _ = view_bytes(image['bufferView'])
                images[src] = load_texture(data=bytes(data))
            elif image.get('uri', '').startswith('data:'):
                images[src] = load_texture(data=base64.b64decode(
                    image['uri'].split(',', 1)[1]))
            else:
                images[src] = load_texture(path=_find_texture(
                    folder, image.get('uri', '')))
        return images[src]

    nodes = []
    for i, n in enumerate(doc.get('nodes', [])):
        if 'matrix' in n:
            m = np.array(n['matrix'], np.float64).reshape(4, 4).T
            t, r, s = decompose(m)
        else:
            t = n.get('translation', (0, 0, 0))
            r = n.get('rotation', (0, 0, 0, 1))
            s = n.get('scale', (1, 1, 1))
        nodes.append(Node(n.get('name', f'node {i}'), -1, t, r, s))
    for i, n in enumerate(doc.get('nodes', [])):
        for child in n.get('children', []):
            nodes[child].parent = i

    # One joint list for every skin
    joints, inverse_binds, skin_maps = [], [], []
    for skin in doc.get('skins', []):
        ibm = (accessor(skin['inverseBindMatrices']).reshape(-1, 4, 4)
               .transpose(0, 2, 1) if 'inverseBindMatrices' in skin
               else np.tile(np.eye(4), (len(skin['joints']), 1, 1)))
        mapping = []
        for j, node in enumerate(skin['joints']):
            mapping.append(len(joints))
            joints.append(node)
            inverse_binds.append(ibm[j])
        skin_maps.append(np.array(mapping, np.int64))

    meshes = []
    for i, n in enumerate(doc.get('nodes', [])):
        if 'mesh' not in n:
            continue
        mesh = doc['meshes'][n['mesh']]
        skin = n.get('skin')
        for prim in mesh.get('primitives', []):
            if prim.get('mode', 4) != 4:
                continue
            attrs = prim['attributes']
            pos = accessor(attrs['POSITION'])
            idx = (accessor(prim['indices']).ravel()
                   if 'indices' in prim else np.arange(len(pos)))
            normals = accessor(attrs['NORMAL']) if 'NORMAL' in attrs else None
            uvs = (accessor(attrs['TEXCOORD_0'])
                   if 'TEXCOORD_0' in attrs else None)
            joints_a = weights_a = None
            if skin is not None and 'JOINTS_0' in attrs:
                joints_a = skin_maps[skin][accessor(attrs['JOINTS_0'])
                                           .astype(np.int64)]
                weights_a = accessor(attrs['WEIGHTS_0']).astype(np.float32)
                total = weights_a.sum(1, keepdims=True)
                weights_a = weights_a / np.where(total > 0, total, 1)
            color = (0.8, 0.8, 0.8, 1.0)
            texture = None
            if 'material' in prim:
                material = doc['materials'][prim['material']]
                color = tuple(material.get('pbrMetallicRoughness', {})
                              .get('baseColorFactor', color))
                if uvs is not None:
                    texture = texture_for(material)
            meshes.append(Mesh(pos, idx, normals, uvs, joints_a, weights_a,
                               color, texture, node=i,
                               name=mesh.get('name', '')))
    if not nodes:
        nodes = [Node('root')]
    return Model(nodes, meshes, joints,
                 inverse_binds if joints else None)


# ---------- FBX (binary 7.x) ----------

FBX_MAGIC = b'Kaydara FBX Binary  \x00'


def read_fbx_tree(data):
    """[(name, properties, children)] of a binary FBX file."""
    if not data.startswith(FBX_MAGIC):
        if data[:200].lstrip().startswith(b';') or b'FBXHeaderExtension' \
                in data[:2000]:
            raise LoadError('this is a text (ASCII) FBX; re-export it as '
                            'binary FBX or as GLB')
        raise LoadError('not an FBX file')
    version = struct.unpack_from('<I', data, 23)[0]
    wide = version >= 7500
    head = struct.Struct('<QQQB' if wide else '<IIIB')
    null = head.size + 0

    def read_props(offset, count):
        props = []
        for _ in range(count):
            code = data[offset:offset + 1]
            offset += 1
            if code == b'Y':
                props.append(struct.unpack_from('<h', data, offset)[0])
                offset += 2
            elif code == b'C':
                props.append(bool(data[offset]))
                offset += 1
            elif code in b'IFDL' and len(code):
                fmt = {b'I': '<i', b'F': '<f', b'D': '<d', b'L': '<q'}[code]
                props.append(struct.unpack_from(fmt, data, offset)[0])
                offset += struct.calcsize(fmt)
            elif code in (b'f', b'd', b'l', b'i', b'b'):
                n, enc, size = struct.unpack_from('<III', data, offset)
                offset += 12
                raw = data[offset:offset + size]
                offset += size
                if enc == 1:
                    raw = zlib.decompress(raw)
                dtype = {b'f': np.float32, b'd': np.float64, b'l': np.int64,
                         b'i': np.int32, b'b': np.uint8}[code]
                props.append(np.frombuffer(raw, dtype, n))
            elif code in (b'S', b'R'):
                n = struct.unpack_from('<I', data, offset)[0]
                offset += 4
                raw = data[offset:offset + n]
                offset += n
                props.append(raw.decode('utf-8', 'replace') if code == b'S'
                             else bytes(raw))
            else:
                raise LoadError(f'unknown FBX property type {code!r}')
        return props

    def read_node(offset):
        end, count, plen, nlen = head.unpack_from(data, offset)
        if end == 0:
            return None, offset + null
        offset += head.size
        name = data[offset:offset + nlen].decode('ascii', 'replace')
        offset += nlen
        props = read_props(offset, count)
        offset += plen
        children = []
        while offset < end:
            child, offset = read_node(offset)
            if child is None:
                break
            children.append(child)
        return (name, props, children), end

    nodes, offset = [], 27
    while offset < len(data) - null:
        node, offset = read_node(offset)
        if node is None:
            break
        nodes.append(node)
    return nodes


def _child(node, name):
    for c in node[2]:
        if c[0] == name:
            return c
    return None


def _p70(node):
    """Properties70 of an FBX object as {name: values}."""
    out = {}
    block = _child(node, 'Properties70')
    for p in (block[2] if block else []):
        if p[0] == 'P' and p[1]:
            out[p[1][0]] = p[1][4:]
    return out


def _euler(degrees, order=0):
    """FBX Euler angles (degrees) -> quaternion. order 0 = XYZ (X first)."""
    x, y, z = (math.radians(a) for a in degrees)
    qx = quat_axis_angle((1, 0, 0), x)
    qy = quat_axis_angle((0, 1, 0), y)
    qz = quat_axis_angle((0, 0, 1), z)
    seq = {0: 'xyz', 1: 'xzy', 2: 'yzx', 3: 'yxz', 4: 'zxy', 5: 'zyx'}
    q = np.array([0.0, 0.0, 0.0, 1.0])
    parts = {'x': qx, 'y': qy, 'z': qz}
    for axis in seq.get(order, 'xyz'):
        q = quat_mul(parts[axis], q)   # later axes apply after earlier
    return q


def _local_matrix(props):
    t = props.get('Lcl Translation', (0, 0, 0))
    r = props.get('Lcl Rotation', (0, 0, 0))
    s = props.get('Lcl Scaling', (1, 1, 1))
    order = int(props.get('RotationOrder', (0,))[0]) \
        if 'RotationOrder' in props else 0
    pre = _euler(props.get('PreRotation', (0, 0, 0)))
    post = _euler(props.get('PostRotation', (0, 0, 0)))
    rot = quat_mul(quat_mul(pre, _euler(r, order)),
                   np.array([-post[0], -post[1], -post[2], post[3]]))
    return trs(t, rot, s)


def _geometric(props):
    t = props.get('GeometricTranslation', (0, 0, 0))
    r = props.get('GeometricRotation', (0, 0, 0))
    s = props.get('GeometricScaling', (1, 1, 1))
    return trs(t, _euler(r), s)


def _layer(geom, name, field, count_corners, poly_vertex):
    """Per-corner values of a layer element (normals, UVs)."""
    layer = _child(geom, name)
    if layer is None:
        return None
    values = _child(layer, field)
    if values is None:
        return None
    width = 2 if field == 'UV' else 3
    values = np.asarray(values[1][0], np.float64).reshape(-1, width)
    mapping = _child(layer, 'MappingInformationType')[1][0]
    reference = _child(layer, 'ReferenceInformationType')[1][0]
    index_node = _child(layer, field + 'Index') or \
        _child(layer, field + 'sIndex')
    if mapping == 'ByPolygonVertex':
        idx = np.arange(count_corners)
    elif mapping in ('ByVertice', 'ByVertex'):
        idx = poly_vertex
    else:
        return None
    if reference == 'IndexToDirect' and index_node is not None:
        idx = np.asarray(index_node[1][0], np.int64)[idx]
    return values[np.clip(idx, 0, len(values) - 1)]


def load_fbx(path, progress=lambda f: None):
    folder = os.path.dirname(path)
    with open(path, 'rb') as f:
        data = f.read()
    tree = read_fbx_tree(data)
    progress(0.3)
    top = {n[0]: n for n in tree}
    objects = top.get('Objects')
    if objects is None:
        raise LoadError('the FBX has no objects')
    settings = _p70(top.get('GlobalSettings', ('', [], [])))
    up = int(settings.get('UpAxis', (1,))[0])
    up_sign = int(settings.get('UpAxisSign', (1,))[0])

    by_id = {}
    for obj in objects[2]:
        if obj[1]:
            by_id[obj[1][0]] = obj
    parent_of, children_of, prop_links = {}, {}, []
    for c in (top.get('Connections') or ('', [], []))[2]:
        if c[0] != 'C':
            continue
        kind, child, parent = c[1][0], c[1][1], c[1][2]
        if kind == 'OO':
            parent_of.setdefault(child, []).append(parent)
            children_of.setdefault(parent, []).append(child)
        elif kind == 'OP':
            prop_links.append((child, parent, c[1][3] if len(c[1]) > 3
                               else ''))
            children_of.setdefault(parent, []).append(child)

    def name_of(obj):
        return obj[1][1].split('\x00')[0] if len(obj[1]) > 1 else ''

    models = [i for i, o in by_id.items() if o[0] == 'Model']
    index = {mid: k for k, mid in enumerate(models)}
    nodes = []
    for mid in models:
        props = _p70(by_id[mid])
        t, r, s = decompose(_local_matrix(props))
        nodes.append(Node(name_of(by_id[mid]), -1, t, r, s))
    for mid in models:
        for p in parent_of.get(mid, []):
            if p in index:
                nodes[index[mid]].parent = index[p]
    # Convert Z-up files to Y-up with one extra root
    if up == 2:
        root = Node('up axis', -1, r=quat_axis_angle(
            (1, 0, 0), -math.pi / 2 * up_sign))
        nodes.append(root)
        for n in nodes[:-1]:
            if n.parent < 0:
                n.parent = len(nodes) - 1

    joints, inverse_binds, joint_index = [], [], {}

    def joint_for(model_id, link):
        if model_id not in joint_index:
            joint_index[model_id] = len(joints)
            joints.append(index[model_id])
            inverse_binds.append(np.linalg.inv(link))
        return joint_index[model_id]

    def texture_of(material_id):
        for child in children_of.get(material_id, []):
            tex = by_id.get(child)
            if tex is None or tex[0] != 'Texture':
                continue
            for vid in children_of.get(child, []):
                video = by_id.get(vid)
                if video and video[0] == 'Video':
                    content = _child(video, 'Content')
                    if content and content[1] and content[1][0]:
                        img = load_texture(data=content[1][0])
                        if img is not None:
                            return img
            for field in ('RelativeFilename', 'FileName'):
                node = _child(tex, field)
                if node and node[1]:
                    found = _find_texture(folder, node[1][0])
                    if found:
                        return load_texture(path=found)
        return None

    meshes = []
    geometries = [i for i, o in by_id.items()
                  if o[0] == 'Geometry' and len(o[1]) > 2 and
                  o[1][2] == 'Mesh']
    for gi, gid in enumerate(geometries):
        progress(0.3 + 0.6 * gi / max(len(geometries), 1))
        geom = by_id[gid]
        verts = _child(geom, 'Vertices')
        polys = _child(geom, 'PolygonVertexIndex')
        if verts is None or polys is None:
            continue
        cp = np.asarray(verts[1][0], np.float64).reshape(-1, 3)
        raw = np.asarray(polys[1][0], np.int64)
        ends = raw < 0
        poly_vertex = np.where(ends, ~raw, raw)
        # Triangles by fanning each polygon
        end_at = np.flatnonzero(ends)
        starts = np.r_[0, end_at[:-1] + 1]
        tri = []
        for s, e in zip(starts, end_at):
            for k in range(s + 1, e):
                tri.append((s, k, k + 1))
        tri = np.array(tri, np.int64).reshape(-1, 3)
        corners = len(poly_vertex)
        normals = _layer(geom, 'LayerElementNormal', 'Normals', corners,
                         poly_vertex)
        uvs = _layer(geom, 'LayerElementUV', 'UV', corners, poly_vertex)
        # Expand to one vertex per corner, then share identical corners
        key = [poly_vertex[:, None]]
        if normals is not None:
            key.append(np.round(normals * 1e4))
        if uvs is not None:
            key.append(np.round(uvs * 1e5))
        key = np.concatenate([k.astype(np.float64).reshape(corners, -1)
                              for k in key], 1)
        unique, first, inverse = np.unique(
            key, axis=0, return_index=True, return_inverse=True)
        inverse = inverse.ravel()
        corner_of_vertex = first
        positions = cp[poly_vertex[corner_of_vertex]]
        indices = inverse[tri].ravel()
        mesh_normals = normals[corner_of_vertex] if normals is not None \
            else None
        mesh_uvs = uvs[corner_of_vertex] if uvs is not None else None
        if mesh_uvs is not None:
            mesh_uvs = mesh_uvs.copy()
            mesh_uvs[:, 1] = 1 - mesh_uvs[:, 1]   # FBX v goes up

        model_ids = [p for p in parent_of.get(gid, []) if p in index]
        if not model_ids:
            continue
        owner = model_ids[0]
        owner_props = _p70(by_id[owner])
        geo_m = _geometric(owner_props)

        # Skin: clusters per bone, weights per control point
        skin_joints = skin_weights = None
        for did in children_of.get(gid, []):
            skin = by_id.get(did)
            if skin is None or skin[0] != 'Deformer' or \
                    (len(skin[1]) > 2 and skin[1][2] != 'Skin'):
                continue
            cp_joints = [[] for _ in range(len(cp))]
            for cid in children_of.get(did, []):
                cluster = by_id.get(cid)
                if cluster is None or cluster[0] != 'Deformer':
                    continue
                bone = [m for m in children_of.get(cid, []) if m in index]
                link = _child(cluster, 'TransformLink')
                if not bone or link is None:
                    continue
                # 'Transform' is stored in bone space: the mesh at bind
                # time relative to the bone, i.e. already the inverse bind
                # matrix (the FBX SDK presents it in world space, but the
                # file doesn't hold that; Blender reads it the same way)
                xform = _child(cluster, 'Transform')
                bind = (np.asarray(xform[1][0], np.float64).reshape(4, 4).T
                        if xform is not None else np.linalg.inv(
                            np.asarray(link[1][0], np.float64)
                            .reshape(4, 4).T))
                j = joint_for(bone[0], np.linalg.inv(bind))
                ids = _child(cluster, 'Indexes')
                ws = _child(cluster, 'Weights')
                if ids is None or ws is None:
                    continue
                for vi, w in zip(ids[1][0], ws[1][0]):
                    if 0 <= vi < len(cp) and w > 0:
                        cp_joints[vi].append((w, j))
            jj = np.zeros((len(cp), 4), np.int64)
            ww = np.zeros((len(cp), 4), np.float32)
            for vi, lst in enumerate(cp_joints):
                lst.sort(reverse=True)
                for k, (w, j) in enumerate(lst[:4]):
                    jj[vi, k], ww[vi, k] = j, w
            total = ww.sum(1, keepdims=True)
            ww = ww / np.where(total > 0, total, 1)
            vidx = poly_vertex[corner_of_vertex]
            skin_joints, skin_weights = jj[vidx], ww[vidx]
            break

        if skin_joints is None and (geo_m != np.eye(4)).any():
            p = np.c_[positions, np.ones(len(positions))] @ geo_m.T
            positions = p[:, :3]

        color, texture = (0.8, 0.8, 0.8, 1.0), None
        for mid in children_of.get(owner, []):
            mat = by_id.get(mid)
            if mat is None or mat[0] != 'Material':
                continue
            props = _p70(mat)
            diffuse = props.get('DiffuseColor') or props.get('Diffuse')
            if diffuse and len(diffuse) >= 3:
                color = (float(diffuse[0]), float(diffuse[1]),
                         float(diffuse[2]), 1.0)
            if mesh_uvs is not None:
                texture = texture_of(mid)
            break
        meshes.append(Mesh(positions, indices, mesh_normals, mesh_uvs,
                           skin_joints, skin_weights, color, texture,
                           node=index[owner], name=name_of(by_id[owner])))
    progress(0.95)
    model = Model(nodes, meshes, joints,
                  inverse_binds if joints else None)
    return model
