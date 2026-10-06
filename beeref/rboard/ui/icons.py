# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Softclub icons: 16px line icons tinted with the theme's colours.

Line icons come from the Softclub design (plus a few drawn to the same
rules: 16px grid, 1.5px stroke, round caps). A handful of filled glyphs
(arrows, stars) come from the design's glyph pack.
"""

import json
import os

from PyQt6 import QtCore, QtGui
from PyQt6.QtSvg import QSvgRenderer


LINE = {
    'select': '<path d="M3 2.5 12.5 7 8.2 8.2 6.8 12.5z"/>',
    'pan': '<path d="M8 2v12M2 8h12M8 2 6.3 3.7M8 2l1.7 1.7M8 14l-1.7-1.7'
           'M8 14l1.7-1.7M2 8l1.7-1.7M2 8l1.7 1.7M14 8l-1.7-1.7M14 8l-1.7 '
           '1.7"/>',
    'zoom': '<circle cx="7" cy="7" r="4.25"/><path d="M10.2 10.2 13.5 13.5"/>',
    'crop': '<path d="M4.5 1.5v9a1 1 0 0 0 1 1h9M1.5 4.5h9a1 1 0 0 1 1 1v9"/>',
    'flip-h': '<path d="M8 1.5v13"/><path d="M6 4.5v7H2z"/>'
              '<path d="M10 4.5v7h4z"/>',
    'flip-v': '<path d="M1.5 8h13"/><path d="M4.5 6h7V2z"/>'
              '<path d="M4.5 10h7v4z"/>',
    'grayscale': '<circle cx="8" cy="8" r="5.5"/><path d="M8 2.5a5.5 5.5 0 0 '
                 '1 0 11z" fill="currentColor"/>',
    'text': '<path d="M3 4h10M8 4v9M6 13h4"/>',
    'lock': '<rect x="3.5" y="7" width="9" height="6.5" rx="1.5"/>'
            '<path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2"/>',
    'eye': '<path d="M1.5 8S4 3.5 8 3.5 14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 '
           '1.5 8z"/><circle cx="8" cy="8" r="1.8"/>',
    'grid': '<rect x="2.5" y="2.5" width="4.5" height="4.5" rx="1"/>'
            '<rect x="9" y="2.5" width="4.5" height="4.5" rx="1"/>'
            '<rect x="2.5" y="9" width="4.5" height="4.5" rx="1"/>'
            '<rect x="9" y="9" width="4.5" height="4.5" rx="1"/>',
    'layers': '<path d="M8 2 14 5.5 8 9 2 5.5z"/>'
              '<path d="M2 8.5 8 12l6-3.5"/>',
    'plus': '<path d="M8 3v10M3 8h10"/>',
    'minus': '<path d="M3 8h10"/>',
    'close': '<path d="M3.5 3.5l9 9M12.5 3.5l-9 9"/>',
    'check': '<path d="M3 8.5 6.5 12 13 4.5"/>',
    'chevron-down': '<path d="M4 6l4 4 4-4"/>',
    'chevron-right': '<path d="M6 4l4 4-4 4"/>',
    'trash': '<path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5"/>',
    'image': '<rect x="2" y="3" width="12" height="10" rx="2"/>'
             '<circle cx="6" cy="6.8" r="1.2"/>'
             '<path d="M2.5 12l3.5-3.5 2.5 2.5 2-2 3 3"/>',
    'folder': '<path d="M2 4.5a1 1 0 0 1 1-1h3l1.5 1.5H13a1 1 0 0 1 1 1V12a1 '
              '1 0 0 1-1 1H3a1 1 0 0 1-1-1z"/>',
    'settings': '<path d="M2.5 5h6M11.5 5h2M2.5 11h2M7.5 11h6"/>'
                '<circle cx="10" cy="5" r="1.5"/><circle cx="6" cy="11" '
                'r="1.5"/>',
    'always-on-top': '<path d="M3 2.5h10M8 14V5.5M4.8 8.7 8 5.5l3.2 3.2"/>',
    'opacity': '<path d="M8 2.5S3.5 7 3.5 9.5a4.5 4.5 0 0 0 9 0C12.5 7 8 2.5 '
               '8 2.5z"/>',
    'fit': '<path d="M2.5 6V2.5H6M10 2.5h3.5V6M13.5 10v3.5H10'
           'M6 13.5H2.5V10"/>',
    'undo': '<path d="M4 6.5h5.5a3 3 0 0 1 0 6H6M4 6.5l2.5-2.5M4 6.5l2.5 '
            '2.5"/>',
    'redo': '<path d="M12 6.5H6.5a3 3 0 0 0 0 6H10M12 6.5 9.5 4M12 6.5 9.5 '
            '9"/>',
    'search': '<circle cx="7" cy="7" r="4.25"/><path d="M10.2 10.2 13.5 '
              '13.5"/>',
    # Drawn for R Board to the same rules
    'pen': '<path d="M3 13l.9-3.4 6.9-6.9a1.4 1.4 0 0 1 2 2L5.9 11.6z"/>'
           '<path d="M9.6 3.9l2 2"/>',
    'note': '<rect x="2.5" y="2.5" width="11" height="11" rx="2"/>'
            '<path d="M5 6h6M5 8.5h6M5 11h3"/>',
    'tag': '<path d="M2.5 3.5a1 1 0 0 1 1-1h4l6 6-5 5-6-6z"/>'
           '<circle cx="5.5" cy="5.5" r="1"/>',
    'subboard': '<rect x="2" y="4.5" width="9" height="9" rx="1.5"/>'
                '<path d="M5 2.5h7a1.5 1.5 0 0 1 1.5 1.5v7"/>',
    'palette': '<circle cx="5" cy="5.5" r="2"/><circle cx="11" cy="5.5" '
               'r="2"/><circle cx="8" cy="11" r="2"/>',
    'circle': '<ellipse cx="8" cy="8" rx="5.5" ry="4.5"/>',
    'arrow': '<path d="M3 13 13 3M7 3h6v6"/>',
    'eraser': '<path d="M6.5 13.5h7M2.8 9.7l6-6a1.4 1.4 0 0 1 2 0l2.5 '
              '2.5a1.4 1.4 0 0 1 0 2l-5.3 5.3H6.5z"/><path d="M5.8 6.7l4.5 '
              '4.5"/>',
    'download': '<path d="M8 2.5v8M4.8 7.3 8 10.5l3.2-3.2M2.5 13.5h11"/>',
}

with open(os.path.join(os.path.dirname(__file__), 'softclub_glyphs.json'),
          encoding='utf-8') as f:
    GLYPHS = json.load(f)  # filled: open-external, forward, sort, sparkle…


def svg(name, color):
    """An SVG document for an icon in the given colour."""
    if name in GLYPHS:
        g = GLYPHS[name]
        return (f'<svg xmlns="http://www.w3.org/2000/svg" '
                f'viewBox="{g["viewBox"]}" fill="{color}">'
                f'{g["body"].replace("currentColor", color)}</svg>')
    body = LINE[name].replace('currentColor', color)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" '
            f'fill="none" stroke="{color}" stroke-width="1.5" '
            f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>')


_cache = {}


def pixmap(name, color, size=16, dpr=1.0):
    color = QtGui.QColor(color).name()
    key = (name, color, size, dpr)
    if key not in _cache:
        renderer = QSvgRenderer(QtCore.QByteArray(svg(name, color).encode()))
        side = round(size * dpr)
        pm = QtGui.QPixmap(side, side)
        pm.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pm)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        # Keep glyph aspect ratios: fit the viewBox inside the square
        view = renderer.viewBoxF()
        scale = side / max(view.width(), view.height(), 1)
        w, h = view.width() * scale, view.height() * scale
        renderer.render(painter, QtCore.QRectF(
            (side - w) / 2, (side - h) / 2, w, h))
        painter.end()
        pm.setDevicePixelRatio(dpr)
        _cache[key] = pm
    return _cache[key]


def draw(painter, name, color, rect):
    """Paint an icon centred in rect (a QRectF/QRect)."""
    size = 16
    dpr = painter.device().devicePixelRatioF() if painter.device() else 1.0
    pm = pixmap(name, color, size, dpr)
    x = rect.x() + (rect.width() - size) / 2
    y = rect.y() + (rect.height() - size) / 2
    painter.drawPixmap(QtCore.QPointF(x, y), pm)


def has(name):
    return name in LINE or name in GLYPHS
