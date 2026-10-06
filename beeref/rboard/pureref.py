# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Read PureRef 2.x boards (.pur).

A 2.x board is an SQLite database wrapped in a short header. Format
facts from https://github.com/FyorDev/pur-2-file-format (independent
reverse-engineering); this reader is written from scratch.
"""

import html
import math
import os
import re
import sqlite3
import struct

import numpy as np

SQLITE_MAGIC = b'SQLite format 3\0'


class PureRefError(Exception):
    pass


class _Reader:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def take(self, n):
        if self.pos + n > len(self.data):
            raise PureRefError('Truncated field')
        value = self.data[self.pos:self.pos + n]
        self.pos += n
        return value

    def unpack(self, fmt):
        return struct.unpack('>' + fmt, self.take(struct.calcsize('>' + fmt)))

    def bytes_(self):
        (n,) = self.unpack('I')
        return None if n == 0xFFFFFFFF else self.take(n)

    def string(self):
        b = self.bytes_()
        return None if b is None else b.decode('utf-16-be')


def _unwrap(data):
    r = _Reader(data)
    version = r.string()
    if version not in ('2.0', '2.1'):
        raise PureRefError(
            f'This board uses the PureRef {version} format. Open it in '
            'PureRef 2 and save it once, then import it again.')
    r.unpack('I')
    (db_size,) = r.unpack('Q')
    r.string()
    r.string()
    if version != '2.0':
        r.bytes_()  # thumbnail
    header = r.pos
    if db_size < header or db_size + header != len(data):
        raise PureRefError('The board file is damaged (bad header).')
    db = data[db_size:] + data[header:db_size]
    if not db.startswith(SQLITE_MAGIC):
        raise PureRefError('The board file is damaged (no database).')
    return db


def _cell(value):
    # Qt stores serialized values as Latin-1 strings in TEXT cells
    return value.encode('latin1') if isinstance(value, str) else bytes(value)


def _variant(value):
    r = _Reader(_cell(value))
    type_id, _ = r.unpack('IB')
    if type_id == 1024:
        r.bytes_()  # custom type name
    return type_id, r


def _matrix(value):
    """QTransform -> 3x3 array, Qt's row-vector convention."""
    if value is None:
        return np.eye(3)
    type_id, r = _variant(value)
    if type_id != 80:
        raise PureRefError('Unexpected transform data')
    return np.array(r.unpack('9d')).reshape(3, 3)


def _path_bounds(value):
    _, r = _variant(value)
    (count,) = r.unpack('I')
    pts = [r.unpack('idd')[1:] for _ in range(count)]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _plain_text(markup):
    text = re.sub(r'(?i)<br\s*/?>|</p>', '\n', markup or '')
    text = re.sub(r'(?s)<head>.*?</head>|<[^>]+>', '', text)
    return html.unescape(text).strip()


def _font_px(markup):
    m = re.search(r'font-size:\s*([\d.]+)px', markup or '')
    return float(m.group(1)) if m else 22.0


def decompose(m):
    """Split a 3x3 row-vector affine matrix into the parts R Board items use:
    (x, y, scale, rotation in degrees, flip of 1 or -1)."""
    # Column-vector form of the linear part: x' = a*x + c*y, y' = b*x + d*y
    a, b, c, d = m[0, 0], m[0, 1], m[1, 0], m[1, 1]
    lin = np.array([[a, c], [b, d]])
    flip = -1 if np.linalg.det(lin) < 0 else 1
    if flip == -1:
        lin = np.diag([-1, 1]) @ lin
    scale = math.sqrt(abs(np.linalg.det(lin)))
    rotation = math.degrees(math.atan2(lin[1, 0], lin[0, 0])) % 360
    return m[2, 0], m[2, 1], scale, rotation, flip


def read(path, on_progress=None):
    """Parse a .pur board.

    :returns: list of dicts. Images: {'type': 'image', 'data': bytes,
        'crop': (x, y, w, h), 'transform': 3x3, 'name', 'z'}.
        Notes: {'type': 'text', 'text', 'font_px', 'transform', 'z'}.
    """
    with open(path, 'rb') as f:
        db_bytes = _unwrap(f.read())
    db = sqlite3.connect(':memory:')
    try:
        db.deserialize(db_bytes)
        items = {row[0]: row for row in db.execute(
            'SELECT id, parent, transform, z, name FROM items')}

        def scene_matrix(item_id):
            m = np.eye(3)
            seen = set()
            while item_id in items and item_id not in seen:
                seen.add(item_id)
                _, parent, tf, _, _ = items[item_id]
                m = m @ _matrix(tf)
                item_id = parent
            return m

        def z_of(item_id):
            return items[item_id][3] or 0

        base_dir = os.path.dirname(path)
        out = []
        rows = db.execute(
            'SELECT ii.id, ii.image_transform, ii.image_bounds, '
            'img.data, img.source FROM items_images ii '
            'JOIN images img ON img.id = ii.image').fetchall()
        for i, (iid, img_tf, bounds, data, source) in enumerate(rows):
            if data is None and source:
                # Linked image: try its stored path, then next to the board
                for candidate in (source, os.path.join(
                        base_dir, os.path.basename(source))):
                    if os.path.isfile(candidate):
                        with open(candidate, 'rb') as f:
                            data = f.read()
                        break
            if data is None:
                continue
            itf = _matrix(img_tf)
            l, t, r, b = _path_bounds(bounds)
            # Crop rectangle in image pixels (image_transform is a shift)
            crop = (l - itf[2, 0], t - itf[2, 1], r - l, b - t)
            out.append({
                'type': 'image',
                'data': bytes(data),
                'crop': crop,
                'transform': itf @ scene_matrix(iid),
                'name': items[iid][4] or '',
                'z': z_of(iid),
            })
            if on_progress:
                on_progress(i)

        for iid, text in db.execute('SELECT id, text FROM items_notes'):
            plain = _plain_text(text)
            if plain:
                out.append({
                    'type': 'text',
                    'text': plain,
                    'font_px': _font_px(text),
                    'transform': scene_matrix(iid),
                    'z': z_of(iid),
                })
        return out
    except sqlite3.Error as e:
        raise PureRefError(f'Could not read the board: {e}') from e
    finally:
        db.close()
