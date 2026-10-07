# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Drawing guides over an image: rule of thirds, centre lines, diagonals
and the golden ratio. Which ones an image shows is kept in
item.meta['guides'] (a list of kinds) and saved with the board."""

from PyQt6 import QtCore, QtGui

PHI = (1 + 5 ** 0.5) / 2

KINDS = [
    ('thirds', 'rule of thirds'),
    ('center', 'centre lines'),
    ('diagonals', 'diagonals'),
    ('golden', 'golden ratio'),
]


def fractions(kind):
    """Where a kind's straight lines cross each axis, as fractions."""
    if kind == 'thirds':
        return (1 / 3, 2 / 3)
    if kind == 'center':
        return (0.5,)
    if kind == 'golden':
        return (1 - 1 / PHI, 1 / PHI)
    return ()


def lines(rect, kinds):
    """QLineFs for these kinds over rect."""
    out = []
    x0, y0, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    for kind in kinds:
        for f in fractions(kind):
            out.append(QtCore.QLineF(x0 + w * f, y0, x0 + w * f, y0 + h))
            out.append(QtCore.QLineF(x0, y0 + h * f, x0 + w, y0 + h * f))
        if kind == 'diagonals':
            out.append(QtCore.QLineF(rect.topLeft(), rect.bottomRight()))
            out.append(QtCore.QLineF(rect.topRight(), rect.bottomLeft()))
    return out


def paint(painter, rect, kinds):
    """Thin light lines with a dark edge, so they show on any image and
    stay one screen pixel wide at every zoom."""
    found = lines(rect, kinds)
    if not found:
        return
    painter.save()
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    painter.setClipRect(rect)
    for color, width in ((QtGui.QColor(0, 0, 0, 110), 3),
                         (QtGui.QColor(255, 255, 255, 210), 1)):
        pen = QtGui.QPen(color, width)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawLines(found)
    painter.restore()
