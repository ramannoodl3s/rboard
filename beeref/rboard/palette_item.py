# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""A palette on the board: a row of color swatches with hex codes.

Copy (Ctrl+C) puts the hex codes on the clipboard; the color sampler (S)
picks a single swatch.
"""

import logging

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from beeref.items import BeeItemMixin, register_item


logger = logging.getLogger(__name__)


@register_item
class BeePaletteItem(BeeItemMixin, QtWidgets.QGraphicsItem):

    TYPE = 'palette'
    SWATCH = 100       # swatch size in item coordinates
    LABEL_HEIGHT = 30

    def __init__(self, colors=None, **kwargs):
        super().__init__()
        self.save_id = None
        self.colors = list(colors or [])
        self.is_image = False
        self.init_selectable()
        logger.debug(f'Initialized {self}')

    @classmethod
    def create_from_data(cls, **kwargs):
        data = kwargs.get('data', {})
        return cls(**data)

    def __str__(self):
        return f'Palette {" ".join(self.colors)}'

    def get_extra_save_data(self):
        return {'colors': self.colors}

    def bounding_rect_unselected(self):
        return QtCore.QRectF(0, 0, self.SWATCH * max(len(self.colors), 1),
                             self.SWATCH + self.LABEL_HEIGHT)

    def swatch_index_at(self, local_pos):
        if 0 <= local_pos.y() <= self.SWATCH:
            index = int(local_pos.x() // self.SWATCH)
            if 0 <= index < len(self.colors):
                return index

    def sample_color_at(self, pos):
        index = self.swatch_index_at(self.mapFromScene(pos))
        if index is not None:
            return QtGui.QColor(self.colors[index])

    def paint(self, painter, option, widget):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(0, 0, 0, 40))
        painter.drawRect(self.bounding_rect_unselected())

        font = QtGui.QFont()
        font.setPixelSize(int(self.LABEL_HEIGHT * 0.55))
        painter.setFont(font)
        for i, color in enumerate(self.colors):
            x = i * self.SWATCH
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QColor(color))
            painter.drawRect(QtCore.QRectF(x, 0, self.SWATCH, self.SWATCH))
            painter.setPen(QtGui.QColor(220, 220, 220))
            painter.drawText(
                QtCore.QRectF(x, self.SWATCH, self.SWATCH, self.LABEL_HEIGHT),
                Qt.AlignmentFlag.AlignCenter, color)
        self.paint_selectable(painter, option, widget)

    def create_copy(self):
        item = BeePaletteItem(self.colors)
        item.setPos(self.pos())
        item.setZValue(self.zValue())
        item.setScale(self.scale())
        item.setRotation(self.rotation())
        if self.flip() == -1:
            item.do_flip()
        return item

    def copy_to_clipboard(self, clipboard):
        clipboard.setText(' '.join(self.colors))
