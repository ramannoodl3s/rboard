# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Pen marks: freehand lines, circles and arrows in basic colours.

A mark drawn on an image is stored in that image's metadata, in the
image's own coordinates, so it moves, scales and rotates with it and
shows up wherever the image does (including sub boards). A mark drawn on
empty canvas becomes a standalone StrokeItem.

Mark format: {'kind': 'free'|'circle'|'arrow', 'points': [[x, y], ...],
'color': '#rrggbb', 'width': float}. Circles and arrows use two points
(drag start and end).
"""

import math

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from beeref.items import BeeItemMixin, register_item


COLORS = [
    ('red', '#d24b3c'), ('orange', '#e08a3a'), ('yellow', '#e8c84a'),
    ('green', '#5aa469'), ('blue', '#4a7fd2'), ('purple', '#9a5fd0'),
    ('white', '#f2f2f2'), ('black', '#111111'),
]
WIDTHS = {'thin': 2.0, 'medium': 4.0, 'thick': 8.0}  # screen pixels
TOOLS = [('free', 'freehand'), ('circle', 'circle'), ('arrow', 'arrow'),
         ('eraser', 'eraser')]


def mark_path(mark):
    """The QPainterPath for a mark (in the mark's coordinates)."""
    pts = [QtCore.QPointF(x, y) for x, y in mark['points']]
    path = QtGui.QPainterPath()
    if not pts:
        return path
    kind = mark['kind']
    if kind == 'circle' and len(pts) >= 2:
        path.addEllipse(QtCore.QRectF(pts[0], pts[-1]).normalized())
    elif kind == 'arrow' and len(pts) >= 2:
        start, end = pts[0], pts[-1]
        path.moveTo(start)
        path.lineTo(end)
        angle = math.atan2(end.y() - start.y(), end.x() - start.x())
        head = mark['width'] * 4.5
        for side in (-1, 1):
            a = angle + math.pi + side * math.radians(28)
            path.moveTo(end)
            path.lineTo(end + QtCore.QPointF(math.cos(a), math.sin(a)) * head)
    else:
        path.moveTo(pts[0])
        for p in pts[1:]:
            path.lineTo(p)
        if len(pts) == 1:
            path.lineTo(pts[0] + QtCore.QPointF(0.01, 0))
    return path


def mark_pen(mark):
    pen = QtGui.QPen(QtGui.QColor(mark['color']), mark['width'])
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def paint_marks(painter, marks):
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for mark in marks:
        painter.setPen(mark_pen(mark))
        painter.drawPath(mark_path(mark))


def hit(mark, point, tolerance):
    """Whether point lies on the mark (within tolerance)."""
    stroker = QtGui.QPainterPathStroker()
    stroker.setWidth(mark['width'] + 2 * tolerance)
    return stroker.createStroke(mark_path(mark)).contains(point)


def transformed(mark, func, width_factor):
    """A copy of mark with points mapped through func(QPointF)->QPointF."""
    pts = [func(QtCore.QPointF(x, y)) for x, y in mark['points']]
    return {**mark, 'points': [[p.x(), p.y()] for p in pts],
            'width': mark['width'] * width_factor}


@register_item
class StrokeItem(BeeItemMixin, QtWidgets.QGraphicsItem):
    """A pen mark drawn on empty canvas."""

    TYPE = 'stroke'

    def __init__(self, mark=None, **kwargs):
        super().__init__()
        self.save_id = None
        self.mark = mark or {'kind': 'free', 'points': [], 'color': '#000000',
                             'width': 2}
        self.is_image = False
        self.init_selectable()

    @classmethod
    def create_from_data(cls, **kwargs):
        return cls(**kwargs.get('data', {}))

    def __str__(self):
        return f'Pen mark ({self.mark["kind"]})'

    def get_extra_save_data(self):
        return {'mark': self.mark}

    def bounding_rect_unselected(self):
        margin = self.mark['width'] / 2 + 1
        return mark_path(self.mark).boundingRect().marginsAdded(
            QtCore.QMarginsF(margin, margin, margin, margin))

    def shape(self):
        if self.has_selection_handles():
            return super().shape()
        stroker = QtGui.QPainterPathStroker()
        stroker.setWidth(max(self.mark['width'], 6))
        return stroker.createStroke(mark_path(self.mark))

    def paint(self, painter, option, widget):
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        paint_marks(painter, [self.mark])
        self.paint_selectable(painter, option, widget)

    def create_copy(self):
        item = StrokeItem(dict(self.mark))
        item.setPos(self.pos())
        item.setZValue(self.zValue())
        item.setScale(self.scale())
        item.setRotation(self.rotation())
        if self.flip() == -1:
            item.do_flip()
        return item

    def copy_to_clipboard(self, clipboard):
        pass
