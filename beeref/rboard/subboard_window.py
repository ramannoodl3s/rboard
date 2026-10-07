# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""The window a sub board opens in."""

import html
import logging
import re

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

    # -- window-level toggles --
    # A docked board sits in the main window, so its menu bar, title bar,
    # full screen and always-on-top toggles are the main board's. Running
    # its own would swap in its menu bar and recreate the main window.

    def _main_toggle(self, action_id, checked):
        qaction = self.manager.main_view.bee_qactions.get(action_id)
        if qaction is not None and qaction.isChecked() != checked:
            qaction.setChecked(checked)

    def on_action_show_menubar(self, checked):
        if self.docked is not None:
            return self._main_toggle('show_menubar', checked)
        super().on_action_show_menubar(checked)

    def on_action_show_titlebar(self, checked):
        if self.docked is not None:
            return self._main_toggle('show_titlebar', checked)
        super().on_action_show_titlebar(checked)

    def on_action_fullscreen(self, checked):
        if self.docked is not None:
            return self._main_toggle('fullscreen', checked)
        super().on_action_fullscreen(checked)

    def on_action_always_on_top(self, checked):
        if self.docked is not None:
            return self._main_toggle('always_on_top', checked)
        super().on_action_always_on_top(checked)

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

    def refresh_description(self):
        self.description.refresh(self.board.description)
        self.tags.refresh()

    def repopulate(self):
        """Fill the board again (its images changed)."""
        self.view.clear_scene()
        self.populate()
        self.refresh_description()

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


URL = re.compile(r'(https?://[^\s<>"]+|www\.[^\s<>"]+)')


def linked_html(text):
    """Plain text -> HTML with web addresses as clickable links."""
    out = []
    for i, part in enumerate(URL.split(text)):
        if i % 2:
            href = part if part.startswith('http') else 'https://' + part
            # Trailing punctuation belongs to the sentence, not the link
            trail = ''
            while href[-1] in '.,;:!?)\'"' and len(href) > 8:
                trail = href[-1] + trail
                href, part = href[:-1], part[:-1]
            out.append(f'<a href="{html.escape(href, quote=True)}">'
                       f'{html.escape(part)}</a>{html.escape(trail)}')
        else:
            out.append(html.escape(part))
    return ''.join(out).replace('\n', '<br>')


class DescriptionStrip(QtWidgets.QLabel):
    """A sub board's description above it; links open in the browser and
    a double-click edits it."""

    def __init__(self, content):
        super().__init__()
        self.content = content
        self.setWordWrap(True)
        self.setOpenExternalLinks(True)
        self.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextBrowserInteraction)
        self.setContentsMargins(12, 6, 12, 6)
        self.setToolTip('double-click to edit')

    def refresh(self, text):
        from beeref.rboard.ui.theme import tm
        self.setStyleSheet(
            f'QLabel {{ background: {tm().hex("surface")}; '
            f'color: {tm().hex("ink")}; '
            f'border-bottom: 1px solid {tm().hex("divider")}; }}')
        accent = tm().hex('accent')
        self.setText(linked_html(text).replace(
            '<a href', f'<a style="color: {accent}" href'))
        self.setVisible(bool(text.strip()))

    def mouseDoubleClickEvent(self, event):
        edit_description(self.content.view, self.content.board)


class TagField(QtWidgets.QLineEdit):
    """Typing tags to add (commas between); Enter adds them, Esc or
    clicking away with nothing typed cancels."""

    def __init__(self, strip, column, names):
        super().__init__()
        self.strip = strip
        self.column = column
        self.done = False
        self.setPlaceholderText('tag, or a word…')
        self.setFixedWidth(180)
        completer = QtWidgets.QCompleter(sorted(names), self)
        completer.setCaseSensitivity(
            QtCore.Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(QtCore.Qt.MatchFlag.MatchContains)
        self.setCompleter(completer)
        self.returnPressed.connect(self.commit)

    def commit(self):
        if self.done:
            return
        self.done = True
        from beeref.rboard.ui.subboard_dialog import split_terms
        terms = split_terms(self.text())
        QtCore.QTimer.singleShot(
            0, lambda: self.strip.add_terms(self.column, terms))

    def cancel(self):
        if not self.done:
            self.done = True
            QtCore.QTimer.singleShot(0, self.strip.stop_adding)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key.Key_Escape:
            self.cancel()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        if self.completer().popup().isVisible():
            return
        if self.text().strip():
            self.commit()
        else:
            self.cancel()


class TagsStrip(QtWidgets.QWidget):
    """A sub board's tags above it, in an include column and a leave-out
    column: a tag's × takes it off, + adds one, and the board fills again
    with the images that match."""

    COLUMNS = (('include', 'include'), ('exclude', 'leave out'))

    def __init__(self, content):
        super().__init__()
        self.content = content
        self.adding = None   # the column a tag is being typed into
        self.row = QtWidgets.QHBoxLayout(self)
        self.row.setContentsMargins(12, 5, 12, 5)
        self.row.setSpacing(6)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground)

    def rule(self):
        from beeref.rboard.subboards import board_rule
        return board_rule(self.content.board)

    def refresh(self):
        from beeref.rboard.subboards import term_label
        from beeref.rboard.ui.theme import surface, tm
        while self.row.count():
            child = self.row.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        rule = self.rule()
        self.setVisible(rule is not None)
        if rule is None:
            return
        t = tm()
        self.setStyleSheet(
            f'TagsStrip {{ background: {surface("surface", True).name()};'
            f' border-bottom: 1px solid {t.hex("divider")}; }}'
            f' QLabel {{ color: {t.hex("ink-muted")}; }}'
            f' QToolButton {{ color: {t.hex("ink")}; border: none;'
            ' border-radius: 10px; padding: 1px 8px; }'
            f' QToolButton:hover {{ background: {t.hex("hover")}; }}'
            ' QToolButton[chip="true"] {'
            f' background: {t.hex("accent-soft")}; }}')
        for i, (column, caption) in enumerate(self.COLUMNS):
            if i:
                self.row.addSpacing(28)
            self.row.addWidget(QtWidgets.QLabel(caption))
            if column == 'include' and len(rule['include']) > 1:
                mode = QtWidgets.QToolButton()
                mode.setText('all of' if rule.get('mode', 'all') == 'all'
                             else 'any of')
                mode.setToolTip('images with all of these tags, or with any')
                mode.clicked.connect(self.toggle_mode)
                self.row.addWidget(mode)
            for term in rule[column]:
                chip = QtWidgets.QToolButton()
                chip.setProperty('chip', True)
                chip.setText(f'{term_label(term)}  ×')
                chip.setToolTip('take this tag off')
                chip.clicked.connect(
                    lambda _=False, c=column, x=term: self.remove(c, x))
                self.row.addWidget(chip)
            if self.adding == column:
                field = TagField(self, column, self.names())
                self.row.addWidget(field)
                QtCore.QTimer.singleShot(0, field.setFocus)
            else:
                plus = QtWidgets.QToolButton()
                plus.setText('+')
                plus.setToolTip('add a tag' if column == 'include'
                                else 'leave out a tag')
                plus.clicked.connect(
                    lambda _=False, c=column: self.start_adding(c))
                self.row.addWidget(plus)
        self.row.addStretch()

    def names(self):
        from beeref.rboard.subboards import term_index
        images = self.content.manager.candidates(self.content.board)
        return {n for n in term_index(images) if ':' not in n}

    def start_adding(self, column):
        self.adding = column
        self.refresh()

    def stop_adding(self):
        self.adding = None
        self.refresh()

    def add_terms(self, column, terms):
        self.adding = None
        rule = self.rule()
        have = {x.lower() for x in rule[column]}
        fresh = [t for t in terms if t.lower() not in have]
        if not fresh:
            self.refresh()
            return
        self.change(dict(rule, **{column: rule[column] + fresh}))

    def remove(self, column, term):
        rule = self.rule()
        self.change(dict(rule, **{column: [t for t in rule[column]
                                           if t != term]}))

    def toggle_mode(self):
        rule = self.rule()
        self.change(dict(rule, mode='any' if rule.get('mode', 'all') == 'all'
                         else 'all'))

    def change(self, rule):
        from beeref.rboard.subboards import change_rule
        manager = self.content.manager
        main = manager.main_view
        if main.rb_analyze(manager.candidates(self.content.board)) is None:
            self.refresh()
            return
        if not change_rule(manager, self.content.board, rule):
            main.rb_notify('no images match these tags')


def edit_description(view, board):
    text, ok = QtWidgets.QInputDialog.getMultiLineText(
        view, 'description',
        f'a note for "{board.title}" (web links become clickable):',
        board.description)
    if ok and text != board.description:
        from beeref.rboard.subboards import describe
        describe(view.rb_manager(), board, text.strip())


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
        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.description = DescriptionStrip(self)
        layout.addWidget(self.description)
        self.tags = TagsStrip(self)
        layout.addWidget(self.tags)
        layout.addWidget(self.view, 1)
        self.setCentralWidget(central)
        self.refresh_description()
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
        layout.setSpacing(0)
        self.description = DescriptionStrip(self)
        layout.addWidget(self.description)
        self.tags = TagsStrip(self)
        layout.addWidget(self.tags)
        layout.addWidget(self.view, 1)
        self.refresh_description()
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
