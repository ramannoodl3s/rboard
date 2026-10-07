# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Palettes out of R Board: an image's colours (its colour study, else its
analysed palette), merged across images, written for painting apps.

Formats: .ase (Photoshop, Illustrator), .gpl (Krita, GIMP), .swatches
(Procreate) and a PNG strip with hex codes."""

import colorsys
import io
import json
import struct
import zipfile

import numpy as np
from PyQt6 import QtCore, QtGui

from beeref.rboard import analysis

FORMATS = [
    ('ase', 'Adobe swatches (*.ase)'),
    ('gpl', 'Krita / GIMP palette (*.gpl)'),
    ('swatches', 'Procreate swatches (*.swatches)'),
    ('png', 'PNG swatch strip (*.png)'),
]
PROCREATE_MAX = 30


# ---------- which colours ----------

def colours_of(item):
    """[(hex, share)] for one image: its colour study's levels when one is
    showing, else the 8 colours from its analysis."""
    if item.study_mode:
        study = item.color_study(start=False)
        if study is not None:
            return [(h, share) for h, share, *_ in study[1]]
    palette = item.meta.get('analysis', {}).get('palette') or []
    return [(h, share) for h, share in palette]


def merge(colour_lists, count=8, seed=0):
    """Several images' [(hex, share)] -> `count` colours by weighted
    k-means in Lab, most covering first. Each image counts the same."""
    hexes, weights = [], []
    for colours in colour_lists:
        total = sum(s for _, s in colours) or 1
        for h, s in colours:
            hexes.append(h)
            weights.append(s / total)
    if not hexes:
        return []
    rgb = np.array([analysis.from_hex(h) for h in hexes], np.uint8)
    lab = analysis.rgb_to_lab(rgb)
    w = np.array(weights)
    count = min(count, len(set(hexes)))
    # Start from the heaviest colours, spread out
    order = np.argsort(-w)
    centers = [lab[order[0]]]
    for i in order[1:]:
        if len(centers) == count:
            break
        if min(np.linalg.norm(lab[i] - c) for c in centers) > 8:
            centers.append(lab[i])
    rng = np.random.default_rng(seed)
    while len(centers) < count:
        centers.append(lab[rng.integers(len(lab))])
    centers = np.array(centers)
    for _ in range(20):
        labels = np.argmin(
            ((lab[:, None] - centers[None]) ** 2).sum(-1), 1)
        new = np.array([
            np.average(lab[labels == k], 0, w[labels == k])
            if (labels == k).any() else centers[k]
            for k in range(len(centers))])
        if np.allclose(new, centers):
            break
        centers = new
    share = np.array([w[labels == k].sum() for k in range(len(centers))])
    rgb_out = np.clip(np.round(analysis.lab_to_rgb(centers)), 0, 255)
    out = [(analysis.to_hex(c), float(s / share.sum()))
           for c, s in zip(rgb_out, share) if s > 0]
    return sorted(out, key=lambda c: -c[1])


# ---------- writers ----------

def _rgbf(hex_):
    return [v / 255 for v in analysis.from_hex(hex_)]


def ase_bytes(colours, name='R Board'):
    """Adobe Swatch Exchange: a group holding one RGB swatch per
    colour."""
    def utf16(text):
        data = (text + '\0').encode('utf-16-be')
        return struct.pack('>H', len(data) // 2) + data

    blocks = []
    group = utf16(name)
    blocks.append(struct.pack('>HI', 0xC001, len(group)) + group)
    for hex_, _ in colours:
        body = (utf16(hex_.lstrip('#')) + b'RGB '
                + struct.pack('>3f', *_rgbf(hex_)) + struct.pack('>H', 2))
        blocks.append(struct.pack('>HI', 0x0001, len(body)) + body)
    blocks.append(struct.pack('>HI', 0xC002, 0))
    return (b'ASEF' + struct.pack('>HHI', 1, 0, len(blocks))
            + b''.join(blocks))


def gpl_text(colours, name='R Board'):
    lines = ['GIMP Palette', f'Name: {name}',
             f'Columns: {min(len(colours), 8) or 1}', '#']
    for hex_, _ in colours:
        r, g, b = analysis.from_hex(hex_)
        lines.append(f'{r:3d} {g:3d} {b:3d}\t{hex_}')
    return '\n'.join(lines) + '\n'


def swatches_bytes(colours, name='R Board'):
    """Procreate: a zip with Swatches.json, colours in HSB (up to 30)."""
    swatches = []
    for hex_, _ in colours[:PROCREATE_MAX]:
        h, s, v = colorsys.rgb_to_hsv(*_rgbf(hex_))
        swatches.append({'hue': h, 'saturation': s, 'brightness': v,
                         'alpha': 1, 'colorSpace': 0})
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('Swatches.json',
                   json.dumps([{'name': name, 'swatches': swatches}]))
    return data.getvalue()


def strip_image(colours, swatch=160):
    """A row of swatches, each with its hex code and share below."""
    n = max(len(colours), 1)
    label_h = swatch // 3
    img = QtGui.QImage(n * swatch, swatch + label_h,
                       QtGui.QImage.Format.Format_RGB32)
    img.fill(QtGui.QColor('#ffffff'))
    p = QtGui.QPainter(img)
    font = p.font()
    font.setPixelSize(max(12, swatch // 9))
    p.setFont(font)
    for i, (hex_, share) in enumerate(colours):
        rect = QtCore.QRect(i * swatch, 0, swatch, swatch)
        p.fillRect(rect, QtGui.QColor(hex_))
        p.setPen(QtGui.QColor('#202020'))
        p.drawText(QtCore.QRect(i * swatch, swatch, swatch, label_h),
                   QtCore.Qt.AlignmentFlag.AlignCenter,
                   f'{hex_}  {share:.0%}')
    p.end()
    return img


def save(path, colours, name='R Board'):
    """Write colours to path, in the format its extension names."""
    ext = path.rsplit('.', 1)[-1].lower()
    if ext == 'png':
        if not strip_image(colours).save(path, 'PNG'):
            raise OSError(f'could not write {path}')
        return
    if ext == 'gpl':
        data = gpl_text(colours, name).encode('utf-8')
    elif ext == 'swatches':
        data = swatches_bytes(colours, name)
    elif ext == 'ase':
        data = ase_bytes(colours, name)
    else:
        raise ValueError(f'unknown palette format: .{ext}')
    with open(path, 'wb') as f:
        f.write(data)
