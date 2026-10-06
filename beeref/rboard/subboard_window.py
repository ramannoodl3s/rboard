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

    def __init__(self, app, window, manager, board, docked=None):
        self.manager = manager
        self.board = board
        self.docked = docked   # the DockedBoard when shown in an area
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
        if self.docked is not None:
            self.docked.title_changed()  # shown in the area header
            return
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
        (self.docked or self.parent).close()

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


class BoardContent:
    """Filling a sub board's view with linked copies, and remembering
    its layout. Shared by sub boards in areas and in their own windows."""

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
            placed = {id(entry[0]) for entry in self.board.layout}
            self.place_after([s for s in self.board.sources
                              if id(s) in live and id(s) not in placed])
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

    def place_after(self, sources):
        """Add images in a row below what's on the board already."""
        if not sources:
            return
        scene = self.view.scene
        bottom = scene.itemsBoundingRect().bottom() if scene.items() else 0
        items = []
        for source in sources:
            item = linked_copy(source)
            scene.addItem(item)
            items.append(item)
        gap = self.view.rb_gap(items)
        for item, (x, y, factor) in zip(
                items, initial_placements(items, scene, gap)):
            item.setScale(item.scale() * factor)
            rect = scene.itemsBoundingRect(items=[item])
            item.setPos(item.pos() + QtCore.QPointF(x, bottom + gap * 4 + y)
                        - rect.topLeft())

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

    def header_snapshot(self):
        return [(i.toPlainText(), i.pos().x(), i.pos().y(), i.scale())
                for i in self.view.scene.items_for_save()
                if getattr(i, 'is_header', False)]


class SubBoardWindow(QtWidgets.QMainWindow, BoardContent):
    """A sub board in its own window."""

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
        self.view.rb_area = None
        self.populate()

    def focus(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def discard(self):
        self.discarding = True
        self.close()

    def closeEvent(self, event):
        if not self.discarding and self.board.window is self:
            self.board.headers = self.header_snapshot()
            self.manager.on_window_closed(self.board, self.layout_snapshot())
        event.accept()


class DockedBoard(QtWidgets.QWidget, BoardContent):
    """A sub board shown in an area of the main window."""

    def __init__(self, manager, board, area):
        super().__init__()
        self.manager = manager
        self.board = board
        self.area = area
        self.released = False
        app = QtWidgets.QApplication.instance()
        # Window-level actions (menu bar, always on top…) act on the main
        # window, which this view sits in
        self.view = SubBoardView(app, manager.main_view.parent, manager,
                                 board, docked=self)
        self.view.setParent(self)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        board.window = self
        # Stay fitted to the area until you zoom or pan yourself
        self.keep_fitted = True
        self.view.viewport().installEventFilter(self)
        self.populate()
        manager.changed.emit()

    def eventFilter(self, obj, event):
        if event.type() in (QtCore.QEvent.Type.Wheel,
                            QtCore.QEvent.Type.MouseButtonPress):
            self.keep_fitted = False
        return False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.keep_fitted and self.width() > 50 and self.height() > 50:
            QtCore.QTimer.singleShot(0, self.refit)

    def refit(self):
        if self.keep_fitted and not self.released:
            self.view.on_action_fit_scene()

    def title_changed(self):
        area = getattr(self, 'rb_area', None)
        if area is not None:
            area.header.update()

    def release(self):
        """Leaving the area: keep the layout so the board reopens the same
        way, and let go of the view."""
        if self.released:
            return
        self.released = True
        if self.board.window is self:
            self.board.headers = self.header_snapshot()
            self.manager.on_window_closed(self.board, self.layout_snapshot())
        self.view.subboard_closing = True
        self.deleteLater()

    def close(self):
        """Close the area showing this board (the board stays cached)."""
        area = getattr(self, 'rb_area', None)
        if area is not None and area.screen is not None \
                and area in area.screen.areas:
            area.screen.close_area_keeping(area)
        else:
            self.release()
        return True

    def discard(self):
        """The board is being thrown away: close without caching."""
        if self.board.window is self:
            self.board.window = None
        self.released = True
        self.close()

    def focus(self):
        area = getattr(self, 'rb_area', None)
        if area is not None:
            screen = area.screen
            if screen.maximized is not None and screen.maximized is not area:
                screen.toggle_maximize()
            window = screen.window()
            window.showNormal()
            window.raise_()
            window.activateWindow()
        self.view.setFocus()
