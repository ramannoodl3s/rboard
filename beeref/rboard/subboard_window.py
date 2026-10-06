# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""The window a sub board opens in."""

import logging

from PyQt6 import QtCore, QtWidgets

from beeref import constants
from beeref.assets import BeeAssets
from beeref.items import BeeTextItem
from beeref.rboard import layouts
from beeref.rboard.subboards import (
    SUBBOARD_DISABLED, initial_placements, linked_copy)
from beeref.view import BeeGraphicsView


logger = logging.getLogger(__name__)


class SubBoardView(BeeGraphicsView):
    """A board view showing linked copies; nothing here is saved."""

    is_subboard = True

    def __init__(self, app, window, manager, board):
        self.manager = manager
        self.board = board
        super().__init__(app, window)
        self.welcome_overlay.hide()
        self.actiongroup_set_enabled('active_when_items_in_scene', True)

    # -- restrictions --

    def actiongroup_set_enabled(self, group, value):
        super().actiongroup_set_enabled(group, value)
        for action_id in SUBBOARD_DISABLED:
            if action_id in getattr(self, 'bee_qactions', {}):
                self.bee_qactions[action_id].setEnabled(False)

    def update_window_title(self):
        board = getattr(self, 'board', None)
        if board is None or callable(self.scene):
            return  # still being set up (self.scene is Qt's method yet)
        count = sum(1 for i in self.scene.items_for_save() if i.is_image)
        self.parent.setWindowTitle(
            f'{board.title} · {count} images — {constants.APPNAME}')

    def on_scene_changed(self, region):
        super().on_scene_changed(region)
        self.welcome_overlay.hide()
        self.update_window_title()

    def get_confirmation_unsaved_changes(self, msg):
        return True

    def on_action_quit(self):
        self.parent.close()

    def rb_handle_drop(self, urls):
        return True  # sub boards only hold linked images

    def dragEnterEvent(self, event):
        event.ignore()

    def clear_scene(self):
        self.scene.clear()
        self.undo_stack.clear()

    # -- linking back --

    @property
    def main_view(self):
        return self.manager.main_view

    def reveal_in_main(self, item):
        source = getattr(item, 'link_source', None)
        main = self.main_view
        if source is None or source.scene() is not main.scene:
            self.rb_notify('That image is no longer on the main board')
            return
        main.scene.clearSelection()
        source.setSelected(True)
        main.fit_rect(main.scene.itemsBoundingRect(items=[source]))
        window = main.parent
        window.showNormal()
        window.raise_()
        window.activateWindow()


class SubBoardWindow(QtWidgets.QMainWindow):

    def __init__(self, manager, board):
        main_window = manager.main_view.parent
        super().__init__(main_window, QtCore.Qt.WindowType.Window)
        self.manager = manager
        self.board = board
        self.discarding = False
        self.setWindowIcon(BeeAssets().logo)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        app = QtWidgets.QApplication.instance()
        self.view = SubBoardView(app, self, manager, board)
        self.setCentralWidget(self.view)
        geo = main_window.geometry()
        self.resize(max(480, int(geo.width() * 0.7)),
                    max(360, int(geo.height() * 0.7)))
        offset = 32 * (board.depth() + 1)
        self.move(geo.x() + offset, geo.y() + offset)
        self.populate()

    def add_header(self, text, x, y, scale):
        header = BeeTextItem(text)
        header.setScale(scale)
        header.setPos(x, y)
        header.is_header = True
        self.view.scene.addItem(header)

    def populate(self):
        scene = self.view.scene
        live = set(map(id, self.manager.live_sources(self.board)))
        if self.board.layout:
            for source, x, y, scale, z in self.board.layout:
                if id(source) not in live:
                    continue
                item = linked_copy(source)
                item.setScale(scale)
                item.setPos(x, y)
                item.setZValue(z)
                scene.addItem(item)
            for text, x, y, scale in self.board.headers:
                self.add_header(text, x, y, scale)
        elif self.board.sections:
            self.populate_sections(live)
        elif self.board.rows:
            self.populate_tree(live)
        else:
            items = []
            for source in self.board.sources:
                if id(source) in live:
                    item = linked_copy(source)
                    scene.addItem(item)
                    items.append(item)
            if items:
                gap = self.view.rb_gap(items)
                placements = initial_placements(items, scene, gap)
                for item, (x, y, factor) in zip(items, placements):
                    item.setScale(item.scale() * factor)
                    rect = scene.itemsBoundingRect(items=[item])
                    item.setPos(item.pos() + QtCore.QPointF(x, y)
                                - rect.topLeft())
                    item.setZValue(len(items) - items.index(item))
        self.view.undo_stack.clear()
        self.view.update_window_title()
        QtCore.QTimer.singleShot(0, self.view.on_action_fit_scene)

    def populate_sections(self, live):
        """Each section as its own block of justified rows under a
        heading, all lining up at the same width."""
        scene = self.view.scene
        blocks = []
        for title, sources in self.board.sections:
            items = []
            for source in sources:
                if id(source) in live:
                    item = linked_copy(source)
                    scene.addItem(item)
                    items.append(item)
            if items:
                blocks.append((title, items))
        everything = [i for _, items in blocks for i in items]
        if not everything:
            return
        gap = self.view.rb_gap(everything)
        rects = {i: scene.itemsBoundingRect(items=[i]) for i in everything}
        total = sum(r.width() * r.height() for r in rects.values())
        heights = sorted(r.height() for r in rects.values())
        label_h = heights[len(heights) // 2] * 0.3
        width = (total ** 0.5) * 1.6
        y = 0
        for title, items in blocks:
            probe = BeeTextItem(title)
            scale = label_h / max(probe.boundingRect().height(), 1)
            self.add_header(title, 0, y, scale)
            y += label_h * 1.6
            sizes = [(rects[i].width(), rects[i].height()) for i in items]
            placements = layouts.justified(sizes, gap, target=width,
                                           height=heights[len(heights) // 2])
            for item, (x, py, f) in zip(items, placements):
                item.setScale(item.scale() * f)
                rect = scene.itemsBoundingRect(items=[item])
                item.setPos(item.pos() + QtCore.QPointF(x, y + py)
                            - rect.topLeft())
            y += layouts.bounds(sizes, placements)[1] + gap * 8

    def populate_tree(self, live):
        """A link tree as a flowchart: one centred row per level, images
        at the same height, room between rows for the arrows."""
        scene = self.view.scene
        rows = []
        for sources in self.board.rows:
            items = []
            for source in sources:
                if id(source) in live:
                    item = linked_copy(source)
                    scene.addItem(item)
                    items.append(item)
            if items:
                rows.append(items)
        everything = [i for row in rows for i in row]
        if not everything:
            return
        gap = self.view.rb_gap(everything)
        heights = sorted(scene.itemsBoundingRect(items=[i]).height()
                         for i in everything)
        row_h = heights[len(heights) // 2]
        widths = []
        for row in rows:
            for item in row:
                rect = scene.itemsBoundingRect(items=[item])
                item.setScale(item.scale() * row_h / max(rect.height(), 1))
            widths.append(sum(scene.itemsBoundingRect(items=[i]).width()
                              for i in row) + gap * 4 * (len(row) - 1))
        widest = max(widths)
        y = 0
        for row, width in zip(rows, widths):
            x = (widest - width) / 2
            for item in row:
                rect = scene.itemsBoundingRect(items=[item])
                item.setPos(item.pos() + QtCore.QPointF(x, y)
                            - rect.topLeft())
                x += rect.width() + gap * 4
            y += row_h * 1.6

    def layout_snapshot(self):
        out = []
        for item in self.view.scene.items_for_save():
            source = getattr(item, 'link_source', None)
            if source is not None:
                out.append((source, item.pos().x(), item.pos().y(),
                            item.scale(), item.zValue()))
        return out

    def discard(self):
        self.discarding = True
        self.close()

    def header_snapshot(self):
        return [(i.toPlainText(), i.pos().x(), i.pos().y(), i.scale())
                for i in self.view.scene.items_for_save()
                if getattr(i, 'is_header', False)]

    def closeEvent(self, event):
        if not self.discarding and self.board.window is self:
            self.board.headers = self.header_snapshot()
            self.manager.on_window_closed(self.board, self.layout_snapshot())
        event.accept()
