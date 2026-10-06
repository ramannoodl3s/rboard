# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Linking images with arrows on the board: drawing them, dragging a new
one out of an image's handle, picking a target with L, and the menus."""

import math
import os

from PyQt6 import QtCore, QtGui
from PyQt6.QtCore import Qt

from beeref.items import BeePixmapItem
from beeref.rboard import links
from beeref.rboard.ui import icons
from beeref.rboard.ui.theme import tm


HANDLE_R = 9         # link handle radius (px)
HANDLE_OFFSET = 16   # handle distance outside the image's right edge
ARROW_GAP = 6        # space between an arrow and the images it joins
HIT = 7              # how close a click must be to an arrow (px)


class LinksMixin:
    """Mixed into BeeGraphicsView (main board and sub boards)."""

    def rb_init_links(self):
        self.link_hover = None      # image showing the drag handle
        self.link_drag = None       # (source, viewport pos) while dragging
        self.link_pick = None       # source image while picking a target

    # ---------- geometry ----------

    def rb_viewport_rect(self, item):
        return QtCore.QRectF(self.mapFromScene(
            self.scene.itemsBoundingRect(items=[item])).boundingRect())

    def rb_handle_center(self, item):
        rect = self.rb_viewport_rect(item)
        return QtCore.QPointF(rect.right() + HANDLE_OFFSET, rect.center().y())

    def rb_link_lines(self):
        """[(source, target, start, end)] in viewport coordinates."""
        images = self.rb_images()
        if not any('links' in i.meta for i in images):
            return []
        out = []
        for a, b in links.edges(images):
            line = links.arrow_line(self.rb_viewport_rect(a),
                                    self.rb_viewport_rect(b), ARROW_GAP)
            if line:
                out.append((a, b, *line))
        return out

    def rb_link_at(self, pos):
        """The link (source, target) whose arrow is under a viewport
        point, if any."""
        p = QtCore.QPointF(pos)
        best = None
        for a, b, start, end in self.rb_link_lines():
            d = links.distance_to_segment(p, start, end)
            if d <= HIT and (best is None or d < best[0]):
                best = (d, a, b)
        return best[1:] if best else None

    def rb_image_at(self, pos):
        if isinstance(pos, QtCore.QPointF):
            pos = pos.toPoint()
        for item in self.items(pos):
            if isinstance(item, BeePixmapItem):
                return item
        return None

    # ---------- painting ----------

    def rb_paint_links(self, painter):
        lines = self.rb_link_lines()
        hover = self.link_hover
        show_handle = (hover is not None and self.link_drag is None
                       and not self.pen_active and self.link_pick is None)
        if not (lines or show_handle or self.link_drag):
            return
        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        color = tm().color('accent')
        for _, _, start, end in lines:
            self._paint_arrow(painter, start, end, color)
        if self.link_drag:
            source, pos = self.link_drag
            try:
                rect = self.rb_viewport_rect(source)
            except RuntimeError:
                rect = None
            if rect is not None:
                start = links.border_point(rect, pos)
                faded = QtGui.QColor(color)
                faded.setAlphaF(0.7)
                self._paint_arrow(painter, start, QtCore.QPointF(pos), faded,
                                  dashed=True)
        if show_handle:
            try:
                self._paint_handle(painter, self.rb_handle_center(hover))
            except RuntimeError:
                self.link_hover = None
        painter.restore()

    def _paint_arrow(self, painter, start, end, color, dashed=False):
        angle = math.atan2(end.y() - start.y(), end.x() - start.x())
        size = 12
        head = QtGui.QPolygonF([end] + [
            QtCore.QPointF(end.x() - size * math.cos(angle + s),
                           end.y() - size * math.sin(angle + s))
            for s in (0.42, -0.42)])
        # A dark outline under the arrow keeps it visible over busy images
        halo = QtGui.QColor(0, 0, 0, 150)
        for pen_color, width in ((halo, 5), (color, 2.5)):
            pen = QtGui.QPen(pen_color, width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            if dashed and pen_color is color:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(pen_color)
            painter.drawLine(start, end)
            painter.drawPolygon(head)
            painter.drawEllipse(start, 2.5, 2.5)

    def _paint_handle(self, painter, center):
        t = tm()
        painter.setPen(QtGui.QPen(t.color('surface-raised'), 2))
        painter.setBrush(t.color('accent'))
        painter.drawEllipse(center, HANDLE_R, HANDLE_R)
        icons.draw(painter, 'link', t.hex('on-accent'), QtCore.QRectF(
            center.x() - 8, center.y() - 8, 16, 16))

    # ---------- mouse ----------

    def rb_link_hover_update(self, pos):
        """Track which image shows the handle (it stays while the pointer
        moves from the image to its handle)."""
        if self.pen_active or self.link_drag:
            return
        current = self.link_hover
        if current is not None:
            try:
                rect = self.rb_viewport_rect(current).adjusted(
                    0, 0, HANDLE_OFFSET + HANDLE_R + 4, 0)
                if rect.contains(QtCore.QPointF(pos)) and \
                        current.scene() is self.scene:
                    if self.rb_on_handle(pos):
                        return
                    item = self.rb_image_at(pos)
                    if item is current or item is None:
                        return
            except RuntimeError:
                pass
        item = self.rb_image_at(pos)
        if item is not current:
            self.link_hover = item
            self.viewport().update()

    def rb_on_handle(self, pos):
        if self.link_hover is None:
            return False
        try:
            center = self.rb_handle_center(self.link_hover)
        except RuntimeError:
            return False
        return math.dist((pos.x(), pos.y()),
                         (center.x(), center.y())) <= HANDLE_R + 3

    def rb_link_event(self, event, kind):
        """Mouse handling for link dragging and picking. Returns True if
        the event was used."""
        pos = event.position()
        if kind == 'press':
            if event.button() != Qt.MouseButton.LeftButton:
                if self.link_pick is not None:
                    self.rb_cancel_link_pick()
                return False
            if self.link_pick is not None:
                target = self.rb_image_at(pos.toPoint())
                source = self.link_pick
                self.rb_cancel_link_pick()
                if target is not None and target is not source:
                    self.rb_add_link(source, target)
                return True
            if not self.pen_active and self.rb_on_handle(pos):
                self.link_drag = (self.link_hover, pos)
                self.viewport().setCursor(Qt.CursorShape.CrossCursor)
                return True
            return False
        if kind == 'move':
            if self.link_drag is not None:
                self.link_drag = (self.link_drag[0], pos)
                self.viewport().update()
                return True
            self.rb_link_hover_update(pos)
            if not self.pen_active and self.link_pick is None:
                if self.rb_on_handle(pos):
                    self.viewport().setCursor(Qt.CursorShape.CrossCursor)
                elif self.viewport().cursor().shape() == \
                        Qt.CursorShape.CrossCursor:
                    self.viewport().unsetCursor()
            return False
        # release
        if self.link_drag is not None:
            source = self.link_drag[0]
            self.link_drag = None
            self.viewport().unsetCursor()
            target = self.rb_image_at(pos.toPoint())
            if target is not None and target is not source:
                self.rb_add_link(source, target)
            self.viewport().update()
            return True
        return False

    # ---------- link mode (L) ----------

    def on_action_link_images(self):
        images = self.rb_selected(images_only=True)
        if not images:
            self.rb_notify('select an image to link from')
            return
        if len(images) == 1:
            self.rb_start_link_pick(images[0])
            return
        # Several: link them one after another in reading order
        from beeref.rboard import layouts
        rects = [self.scene.itemsBoundingRect(items=[i]) for i in images]
        order = layouts.reading_order(
            [(r.x(), r.y(), r.width(), r.height()) for r in rects])
        chain = [images[i] for i in order]
        self.rb_main().undo_stack.beginMacro('Link images')
        for a, b in zip(chain, chain[1:]):
            self.rb_add_link(a, b, notify=False)
        self.rb_main().undo_stack.endMacro()
        self.rb_notify(f'linked {len(chain)} images in a chain')

    def rb_start_link_pick(self, source):
        self.cancel_active_modes()
        self.link_pick = source
        self.viewport().setCursor(Qt.CursorShape.CrossCursor)
        self.rb_notify('click the image to link to · esc to cancel')

    def rb_cancel_link_pick(self):
        self.link_pick = None
        self.viewport().unsetCursor()

    # ---------- changing links ----------

    def rb_add_link(self, source, target, notify=True):
        target_id = links.uid(target)
        current = links.targets(source)
        if target_id in current:
            return
        stack = self.rb_main().undo_stack
        stack.beginMacro('Link images')
        # Linking back the other way replaces the old direction
        if links.uid(source) in links.targets(target):
            self.rb_remove_link(target, source)
        self.rb_meta_change([source], 'links', [current + [target_id]],
                            'Link images')
        stack.endMacro()
        if notify:
            self.rb_notify('linked · right-click an arrow to remove it')

    def rb_remove_link(self, source, target):
        target_id = target.meta.get('uid')
        kept = [t for t in links.targets(source) if t != target_id]
        self.rb_meta_change([source], 'links', [kept], 'Remove link')

    def rb_reverse_link(self, source, target):
        stack = self.rb_main().undo_stack
        stack.beginMacro('Reverse link')
        self.rb_remove_link(source, target)
        self.rb_add_link(target, source, notify=False)
        stack.endMacro()

    # ---------- menus ----------

    def rb_link_menu(self, link):
        source, target = link
        return [
            ('label', 'link'),
            ('item', f'{self.rb_short_name(source)} → '
             f'{self.rb_short_name(target)}', None, {'enabled': False}),
            ('item', 'reverse direction',
             lambda: self.rb_reverse_link(source, target)),
            ('item', 'open link tree', lambda: self.rb_open_link_tree(source),
             {'trailing_icon': 'subboard'}),
            ('sep',),
            ('item', 'remove link', lambda: self.rb_remove_link(source, target),
             {'danger': True}),
        ]

    @staticmethod
    def rb_short_name(item, length=28):
        name = os.path.splitext(os.path.basename(item.filename or ''))[0] \
            or 'image'
        return name if len(name) <= length else name[:length - 1] + '…'

    def rb_link_entries(self, item):
        """The image menu's links section."""
        images = self.rb_images()
        outgoing, incoming = links.linked(item, images)
        entries = [('sep',), ('label', 'links'),
                   ('item', 'link to another image…',
                    lambda: self.rb_start_link_pick(item),
                    {'icon': 'link', 'kbd': 'L',
                     'tooltip': 'or drag from the round handle on the '
                                'image'})]
        for other in outgoing:
            entries.append(('item', f'→ {self.rb_short_name(other)}',
                            lambda o=other: self.rb_show_item(o),
                            {'indent': 1, 'on_remove': lambda o=other:
                             self.rb_remove_link(item, o)}))
        for other in incoming:
            entries.append(('item', f'← {self.rb_short_name(other)}',
                            lambda o=other: self.rb_show_item(o),
                            {'indent': 1, 'on_remove': lambda o=other:
                             self.rb_remove_link(o, item)}))
        if outgoing or incoming:
            size = len(links.tree(item, images))
            entries.append(('item', 'open link tree',
                            lambda: self.rb_open_link_tree(item),
                            {'icon': 'layers', 'count': size,
                             'trailing_icon': 'subboard'}))
        return entries

    def rb_show_item(self, item):
        self.scene.clearSelection()
        item.setSelected(True)
        self.fit_rect(self.scene.itemsBoundingRect(items=[item]))

    def rb_open_link_tree(self, item):
        source = getattr(item, 'link_source', item)
        images, sources = self.rb_candidates()
        parent = self.board if self.is_subboard else None
        self.rb_manager().open_links(source, sources, parent)
