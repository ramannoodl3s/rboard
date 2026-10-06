# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""The Softclub interface on a board view: home bar menus, the reduced
right-click menus, the image menu (attributes and tags), the layers menu,
note callouts and the pen tool."""

import math
import os

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from beeref import commands
from beeref.items import BeePixmapItem, BeeTextItem
from beeref.rboard import attributes, pen as penlib, semantic
from beeref.rboard.ui import icons
from beeref.rboard.ui.dialogs import NoteDialog, TagField
from beeref.rboard.ui.homebar import HomeBar, StatusPill
from beeref.rboard.ui.menu import (
    ROW_H, MenuHost, OverlayMenu, section_font)
from beeref.rboard.ui.theme import px, tm, ui_font


NOTE_WIDTH = 220
# Bar arrange commands work on everything when nothing's selected
ALL = {'all_if_none': True}
SORT = {'all_if_none': True, 'icon': 'sort'}
ATTRIBUTE_ICONS = {
    'shape': 'fit', 'channel': 'forward', 'board': 'image',
    'folder': 'folder', 'text': 'text', 'note': 'note', 'marks': 'pen',
    'cover': 'sparkle', 'tag': 'star-outline', 'looks': 'sparkle',
}


class AddTagRow(QtWidgets.QWidget):
    """'+ add tag…' in the tags menu; turns into a field when clicked."""

    def __init__(self, menu, existing, on_add):
        super().__init__()
        self.menu = menu
        self.existing = existing
        self.on_add = on_add
        self.hovered = False
        self.field = None
        self.setFixedHeight(ROW_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def preferred_width(self):
        return 0

    def enterEvent(self, e):
        self.hovered = True
        self.update()

    def leaveEvent(self, e):
        self.hovered = False
        self.update()

    def mouseReleaseEvent(self, e):
        if self.field is None:
            self.start()

    def start(self):
        self.field = TagField(self.existing)
        self.field.setParent(self)
        self.field.setGeometry(32, 2, self.width() - 44, self.height() - 4)
        self.field.submitted.connect(self.submit)
        self.field.show()
        self.field.setFocus()
        self.update()

    def submit(self, tag):
        self.menu.close_all_menus()
        self.on_add(tag)

    def paintEvent(self, e):
        if self.field is not None:
            return
        t = tm()
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(4, 0, -4, 0)
        if self.hovered:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(t.color('hover'))
            p.drawRoundedRect(rect, px('radius-sm'), px('radius-sm'))
        icons.draw(p, 'plus', t.hex('ink-muted'),
                   QtCore.QRectF(rect.x() + 8, 0, 16, self.height()))
        p.setPen(t.color('ink-muted'))
        p.drawText(QtCore.QRectF(rect.x() + 32, 0, rect.width() - 32,
                                 self.height()),
                   Qt.AlignmentFlag.AlignVCenter, 'add tag…')


class StudyToggle(QtWidgets.QWidget):
    """'colour study' with three switches: value, colour, off."""

    MODES = (('value', 'value'), ('color', 'colour'), (None, 'off'))

    def __init__(self, menu, current, on_pick):
        super().__init__()
        self.menu = menu
        self.current = current
        self.on_pick = on_pick
        self.hovered = None
        self.setFixedHeight(ROW_H + 6)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def preferred_width(self):
        return 300

    def segments(self):
        fm = self.fontMetrics()
        x = self.width() - 10
        out = []
        for mode, label in reversed(self.MODES):
            w = fm.horizontalAdvance(label) + 20
            x -= w
            out.append((mode, label, QtCore.QRectF(x, 5, w, ROW_H - 4)))
            x -= 4
        return list(reversed(out))

    def mouseMoveEvent(self, e):
        hit = next((m for m, _, r in self.segments()
                    if r.contains(e.position())), 'none')
        if hit != self.hovered:
            self.hovered = hit
            self.update()

    def leaveEvent(self, e):
        self.hovered = None
        self.update()

    def mouseReleaseEvent(self, e):
        for mode, _, rect in self.segments():
            if rect.contains(e.position()):
                self.menu.close_all_menus()
                QtCore.QTimer.singleShot(0, lambda m=mode: self.on_pick(m))
                return

    def paintEvent(self, e):
        t = tm()
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        icons.draw(p, 'palette', t.hex('ink-muted'),
                   QtCore.QRectF(12, 0, 16, self.height()))
        p.setPen(t.color('ink'))
        p.drawText(QtCore.QRectF(36, 0, 120, self.height()),
                   Qt.AlignmentFlag.AlignVCenter, 'colour study')
        for mode, label, rect in self.segments():
            on = mode == self.current
            p.setPen(QtGui.QPen(t.color('accent' if on else 'control-border'),
                                1))
            p.setBrush(t.color('accent') if on else (
                t.color('hover') if self.hovered == mode
                else Qt.BrushStyle.NoBrush))
            p.drawRoundedRect(rect.adjusted(.5, .5, -.5, -.5), 9, 9)
            p.setPen(t.color('on-accent' if on else 'ink'))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)


class NoteHover(QtCore.QObject):
    """Tracks which image with a note is under the pointer."""

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        view.viewport().installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Type.MouseMove:
            item = self.view.rb_user_item_at(event.position().toPoint())
            if not (isinstance(item, BeePixmapItem)
                    and item.meta.get('note')):
                item = None
            if item is not self.view.note_hover_item:
                self.view.note_hover_item = item
                self.view.viewport().update()
        elif event.type() == QtCore.QEvent.Type.Leave:
            if self.view.note_hover_item is not None:
                self.view.note_hover_item = None
                self.view.viewport().update()
        return False


class BoardUIMixin:
    """Mixed into BeeGraphicsView (main board and sub boards)."""

    # ---------- setup ----------

    def rb_init_ui(self):
        self.menu_host = MenuHost(self)
        if not self.is_subboard:
            from beeref.rboard.subboards import SubBoardManager
            self.subboards = SubBoardManager(self)
            self.subboards.changed.connect(self.rb_update_status)
        self.home_bar = HomeBar(self, self.rb_bar_spec(), self.menu_host,
                                self.settings)
        self.status_pill = StatusPill(self, self.home_bar)
        self.note_hover_item = None
        self.note_hover = NoteHover(self)
        self.rb_init_links()
        self.pen_active = False
        self._pen_points = None
        self._pen_preview = None
        self.status_timer = QtCore.QTimer(self, singleShot=True)
        self.status_timer.setInterval(150)
        self.status_timer.timeout.connect(self.rb_update_status)
        self.scene.selectionChanged.connect(self.status_timer.start)
        self.scene.changed.connect(self._rb_scene_changed)
        tm().changed.connect(self.rb_on_theme_changed)
        self.rb_on_theme_changed()

    def _rb_scene_changed(self, region):
        self.status_timer.start()
        if self.link_hover is not None or any(
                'links' in i.meta for i in self.rb_images()):
            # Arrows and the link handle follow images that moved
            self.viewport().update()

    def rb_manager(self):
        return self.manager if self.is_subboard else self.subboards

    def rb_main(self):
        return self.manager.main_view if self.is_subboard else self

    def rb_on_theme_changed(self):
        self.setBackgroundBrush(QtGui.QBrush(tm().color('canvas')))
        for item in self.scene.items():
            if isinstance(item, BeeTextItem):
                item.setDefaultTextColor(tm().color('ink'))
        self.scene.update()
        self.home_bar.update_theme()
        self.status_pill.update_theme()
        self.menu_host.close_all()
        if getattr(self, 'search_bar', None):
            self.search_bar.update_theme()
        self.viewport().update()

    def rb_update_status(self):
        try:
            images = sum(1 for i in self.scene.items_for_save() if i.is_image)
            selected = len(self.scene.selectedItems(user_only=True))
        except RuntimeError:
            return  # scene is being torn down
        parts = []
        if images:
            parts.append(f'{images} image{"" if images == 1 else "s"}')
        if selected:
            parts.append(f'{selected} selected')
        if not self.is_subboard and self.subboards.boards:
            n = len(self.subboards.boards)
            parts.append(f'{n} sub board{"" if n == 1 else "s"}')
        if self.pen_active:
            parts.append('pen on · esc to stop')
        progress = getattr(self, '_content_progress', None)
        if progress:
            parts.append(f'reading content {progress[0]}/{progress[1]}')
        self.status_pill.set_text(' · '.join(parts))

    def rb_on_resize(self):
        if hasattr(self, 'home_bar'):
            self.home_bar.reposition()
            self.status_pill.reposition()
            if getattr(self, 'search_bar', None):
                self.search_bar.reposition()

    # ---------- home bar ----------

    def rb_bar_spec(self):
        undo = {'icon': 'undo', 'label': 'undo', 'action':
                self.on_action_undo,
                'enabled': self.undo_stack.canUndo}
        redo = {'icon': 'redo', 'label': 'redo', 'action':
                self.on_action_redo,
                'enabled': self.undo_stack.canRedo}
        file_ = {'icon': 'folder', 'label': 'file', 'menu': self.rb_menu_file}
        add = {'icon': 'plus', 'label': 'add', 'menu': self.rb_menu_add}
        arrange = {'icon': 'grid', 'label': 'arrange',
                   'menu': self.rb_menu_arrange}
        image = {'icon': 'image', 'label': 'image',
                 'menu': self.rb_menu_image}
        find = {'icon': 'search', 'label': 'find', 'menu': self.rb_menu_find}
        draw = {'icon': 'pen', 'label': 'pen', 'menu': self.rb_menu_pen,
                'action': lambda: self.bee_qactions['pen_mode'].toggle(),
                'active': lambda: self.pen_active}
        notes = {'icon': 'note', 'label': 'notes and tags',
                 'menu': self.rb_menu_notes}
        layers = {'icon': 'layers', 'label': 'layers',
                  'menu': self.rb_menu_layers}
        view = {'icon': 'eye', 'label': 'view', 'menu': self.rb_menu_view}
        settings = {'icon': 'settings', 'label': 'settings',
                    'menu': self.rb_menu_settings,
                    'action': self.on_action_settings}
        if self.is_subboard:
            return [[undo, redo], [arrange, image, find], [draw, notes],
                    [layers, view, settings]]
        return [[undo, redo], [file_, add], [arrange, image, find],
                [draw, notes], [layers, view, settings]]

    def rb_menu_file(self):
        recent = self.settings.get_recent_files(existing_only=True)

        def recent_entries():
            if not recent:
                return [('item', 'no recent boards', None,
                         {'enabled': False})]
            return [('item', os.path.basename(path),
                     lambda p=path: self.on_action_open_recent_file(p),
                     {'kbd': f'Ctrl+{(i + 1) % 10}'})
                    for i, path in enumerate(recent[:10])]

        return [
            ('action', 'new_scene', 'new board'),
            ('action', 'open', 'open board…'),
            ('submenu', 'open recent', recent_entries),
            ('sep',),
            ('action', 'save', 'save'),
            ('action', 'save_as', 'save as…'),
            ('sep',),
            ('action', 'import_pureref', 'import PureRef board…'),
            ('action', 'export_scene', 'export board as image…'),
            ('action', 'export_selection', 'export selection as image…'),
            ('action', 'export_images', 'export images…'),
            ('sep',),
            ('action', 'quit', 'quit'),
        ]

    def rb_menu_add(self):
        return [
            ('action', 'insert_images', 'images…'),
            ('action', 'insert_text', 'text'),
            ('action', 'paste', 'paste'),
        ]

    def rb_menu_arrange(self):
        return [
            ('label', 'layout'),
            ('action', 'arrange_justified', 'justified rows', ALL),
            ('action', 'arrange_masonry', 'masonry columns', ALL),
            ('action', 'arrange_grid', 'equal-size grid', ALL),
            ('action', 'arrange_optimal', 'tightly packed', ALL),
            ('submenu', 'by file name', lambda: [
                ('action', 'arrange_horizontal', 'in a row', ALL),
                ('action', 'arrange_vertical', 'in a column', ALL),
                ('action', 'arrange_square', 'in a square', ALL)]),
            ('sep',), ('label', 'content'),
            ('action', 'group_content', 'group by content…', ALL),
            ('sep',), ('label', 'colour'),
            ('action', 'sort_color', 'sort by colour…', SORT),
            ('sep',), ('label', 'size'),
            ('action', 'normalize_height', 'same height', ALL),
            ('action', 'normalize_width', 'same width', ALL),
            ('action', 'normalize_size', 'same area', ALL),
        ]

    def rb_menu_image(self):
        return [
            ('action', 'crop', 'crop'),
            ('action', 'flip_horizontally', 'flip horizontally'),
            ('action', 'flip_vertically', 'flip vertically'),
            ('action', 'grayscale', 'grayscale'),
            ('action', 'change_opacity', 'opacity…'),
            ('submenu', 'reset', lambda: [
                ('action', 'reset_scale', 'size'),
                ('action', 'reset_rotation', 'rotation'),
                ('action', 'reset_flip', 'flip'),
                ('action', 'reset_crop', 'crop'),
                ('action', 'reset_transforms', 'everything')]),
            ('sep',), ('label', 'colour'),
            ('action', 'color_study', 'colour study (value, colour, off)',
             {'icon': 'palette'}),
            ('action', 'sample_color', 'pick a colour'),
            ('action', 'show_color_gamut', 'colour spread'),
            ('sep',), ('label', 'content'),
            ('action', 'index_content', 'read image content'),
            ('sep',), ('label', 'text and links'),
            ('action', 'extract_text', 'copy text from image'),
            ('action', 'index_text', 'read text in all images'),
            ('action', 'open_source', 'open source link'),
            ('sep',),
            ('action', 'raise_to_top', 'bring to front'),
            ('action', 'lower_to_bottom', 'send to back'),
            ('action', 'copy', 'copy'),
            ('action', 'delete', 'delete'),
        ]

    def rb_menu_find(self):
        return [
            ('action', 'find_text', 'find text…'),
            ('action', 'find_by_color', 'find by colour…'),
            ('action', 'select_duplicates', 'select duplicates'),
            ('sep',),
            ('action', 'select_all', 'select all'),
            ('action', 'deselect_all', 'select none'),
        ]

    def rb_menu_pen(self):
        color = self.settings.valueOrDefault('Pen/color')
        width = self.settings.valueOrDefault('Pen/width')
        tool = self.settings.valueOrDefault('Pen/tool')

        def set_(key, value):
            self.settings.setValue(key, value)
            if not self.pen_active:
                self.bee_qactions['pen_mode'].setChecked(True)

        entries = [
            ('label', 'pen'),
            ('widget', lambda menu: Swatches(menu, color,
                                             lambda c: set_('Pen/color', c))),
        ]
        for value, label in penlib.TOOLS:
            entries.append(('item', label,
                            lambda v=value: set_('Pen/tool', v),
                            {'checked': value == tool,
                             'icon': {'free': 'pen', 'circle': 'circle',
                                      'arrow': 'arrow',
                                      'eraser': 'eraser'}[value]}))
        entries.append(('sep',))
        entries.append(('label', 'line'))
        for value in penlib.WIDTHS:
            entries.append(('item', value, lambda v=value: set_('Pen/width',
                                                                v),
                            {'checked': value == width}))
        entries += [
            ('sep',),
            ('action', 'pen_mode', 'stop drawing' if self.pen_active
             else 'start drawing'),
            ('item', 'clear marks on selected images', self.rb_clear_marks,
             {'enabled': any(i.meta.get('marks') for i in
                             self.rb_selected(images_only=True))}),
        ]
        return entries

    def rb_menu_notes(self):
        return [
            ('action', 'add_note', 'note on selected image…'),
            ('action', 'show_notes', 'always show notes'),
            ('sep',),
            ('action', 'tag_images', 'tag selected images…'),
        ]

    def rb_menu_area(self):
        """View > Area, as in Blender."""
        if self.is_subboard and getattr(self, 'rb_area', None) is None:
            return [('item', 'dock in the main window',
                     lambda: self.manager.dock(self.board))]
        area = getattr(self, 'rb_area', None)
        screen = getattr(self.rb_main(), 'rb_screen', None)
        if screen is None or area is None:
            return [('item', 'no areas here', None, {'enabled': False})]
        return screen.area_entries(area)

    def on_action_area_maximize(self):
        area = getattr(self, 'rb_area', None)
        if area is not None:
            area.screen.toggle_maximize(area)

    def on_action_area_focus(self):
        area = getattr(self, 'rb_area', None)
        if area is not None:
            area.screen.toggle_focus(area)

    def rb_menu_view(self):
        entries = [
            ('submenu', 'area', self.rb_menu_area, {'icon': 'grid'}),
            ('sep',),
            ('action', 'fit_scene', 'fit board'),
            ('action', 'fit_selection', 'fit selection'),
            ('sep',),
            ('action', 'always_on_top', 'always on top'),
            ('action', 'fullscreen', 'fullscreen'),
        ]
        if not self.is_subboard:
            entries += [
                ('action', 'show_titlebar', 'title bar'),
                ('action', 'show_menubar', 'menu bar'),
                ('action', 'show_scrollbars', 'scrollbars'),
                ('sep',),
                ('action', 'move_window', 'move window'),
            ]
        return entries

    def rb_menu_settings(self):
        return [
            ('action', 'settings', 'settings…'),
            ('action', 'keyboard_settings', 'keyboard & mouse…'),
            ('sep',),
            ('action', 'help', 'help'),
            ('action', 'about', 'about'),
            ('action', 'debuglog', 'debug log'),
        ]

    # ---------- layers ----------

    def rb_menu_layers(self):
        manager = self.rb_manager()
        main = self.rb_main()
        current = self.board if self.is_subboard else None
        name = os.path.basename(main.filename) if main.filename \
            else 'main board'
        n_main = sum(1 for i in main.scene.items_for_save() if i.is_image)
        entries = [('label', 'layers'),
                   ('item', name, self.rb_focus_main,
                    {'icon': 'image', 'count': n_main,
                     'checked': current is None and self.is_subboard}),
                   ('action', 'new_subboard', 'new sub board…',
                    {'icon': 'plus'})]
        boards = manager.tree()
        if not boards:
            entries.append(('item', 'or right-click an image for one',
                            None, {'enabled': False, 'indent': 1}))
        for board in boards:
            state = ' · '.join(filter(None, (
                board.state, 'tree' if board.is_tree else
                ('kept' if board.saved else ''))))
            entries.append((
                'submenu', board.title,
                lambda b=board: self.rb_board_entries(b),
                {'indent': board.depth() + 1,
                 'icon': 'link' if board.is_tree else
                 ('star-outline' if board.saved else 'layers'),
                 'hint': state, 'count': len(board.sources),
                 'checked': board is current}))
        entries.append(('sep',))
        entries += [
            ('item', 'close all sub boards', manager.close_all,
             {'enabled': any(b.window for b in boards)}),
            ('item', 'discard closed sub boards', manager.discard_cached,
             {'enabled': any(not b.window and not b.kept for b in boards),
              'tooltip': "kept boards and trees stay"}),
        ]
        return entries

    def rb_board_entries(self, board):
        """What you can do with one sub board, from the layers menu."""
        manager = self.rb_manager()
        state = board.state
        entries = [('item', 'show' if state != 'closed' else 'open',
                    lambda: manager.show(board), {'icon': 'subboard'})]
        if state == 'window':
            entries.append(('item', 'dock in the main window',
                            lambda: manager.dock(board)))
        else:
            entries.append(('item', 'pop out to a window',
                            lambda: manager.pop_out(board)))
        if board.is_tree:
            entries.append(('item', 'trees are always kept', None,
                            {'enabled': False, 'checked': True}))
        else:
            entries.append(('item', 'keep in this board file',
                            lambda: self.rb_keep_board(board,
                                                       not board.saved),
                            {'checked': board.saved}))
        entries += [('sep',),
                    ('item', 'remove', lambda: self.rb_remove_board(board),
                     {'danger': True})]
        return entries

    def rb_keep_board(self, board, saved):
        """Keep a sub board in the board file (undoable, so the board
        shows unsaved changes)."""
        from beeref.rboard.subboards import ManagerChange
        manager = self.rb_manager()
        self.rb_main().undo_stack.push(ManagerChange(
            'Keep sub board' if saved else "Don't keep sub board",
            lambda: manager.set_saved(board, saved),
            lambda: manager.set_saved(board, not saved)))
        if saved:
            self.rb_notify(f'"{board.title}" is kept · save the board to '
                           'store it')

    def rb_remove_board(self, board):
        manager = self.rb_manager()
        if board.kept:
            answer = QtWidgets.QMessageBox.question(
                self, 'remove sub board',
                f'remove "{board.title}"? it\'s kept in the board file; '
                'this takes it out (the images stay on the board).')
            if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                return
            from beeref.rboard.subboards import ManagerChange
            main = self.rb_main()
            main.undo_stack.push(ManagerChange(
                'Remove sub board', lambda: manager.discard(board),
                lambda: manager.add(board)))
        else:
            manager.discard(board)

    def on_action_new_subboard(self):
        """Make a sub board from tags to include and to leave out."""
        from beeref.rboard import semantic
        from beeref.rboard.ui.subboard_dialog import SubBoardDialog
        images, sources = self.rb_candidates()
        if not images:
            self.rb_notify('add some images first')
            return
        if self.rb_analyze(images) is None:
            return
        self.rb_main().rb_refresh_profile()
        by_meaning = semantic.installed('text') and any(
            semantic.vector(i) is not None for i in images)
        dialog = SubBoardDialog(self, sources, by_meaning)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        parent = self.board if self.is_subboard else None
        board = self.rb_manager().open_query(dialog.title(), dialog.rule(),
                                             sources, parent)
        if dialog.save.isChecked():
            self.rb_keep_board(board, True)

    def rb_focus_main(self):
        window = self.rb_main().parent
        window.showNormal()
        window.raise_()
        window.activateWindow()

    # ---------- right-click ----------

    def rb_user_item_at(self, viewport_pos):
        for item in self.items(viewport_pos):
            if hasattr(item, 'save_id'):
                return item
        return None

    def rb_context_menu(self, point):
        if self.pen_active:
            return
        self._rb_menu_point = point
        item = self.rb_user_item_at(point)
        link = self.rb_link_at(point) if item is None else None
        if link is not None:
            self.menu_host.show(OverlayMenu(self, self.rb_link_menu(link),
                                            min_width=220), point)
            return
        if item is not None and not item.isSelected():
            self.scene.clearSelection()
            item.setSelected(True)
        if isinstance(item, BeePixmapItem):
            entries = self.rb_image_menu(item)
            width = 300
        elif item is not None:
            entries = [
                ('action', 'copy', 'copy'),
                ('action', 'cut', 'cut'),
                ('action', 'raise_to_top', 'bring to front'),
                ('action', 'lower_to_bottom', 'send to back'),
                ('action', 'export_selection', 'export selection as image…'),
                ('sep',),
                ('action', 'delete', 'delete'),
            ]
            width = 200
        else:
            entries = [
                ('action', 'paste', 'paste'),
                ('action', 'insert_images', 'add images…'),
                ('action', 'insert_text', 'add text'),
                ('sep',),
                ('action', 'select_all', 'select all'),
                ('action', 'fit_scene', 'fit board'),
            ]
            if self.is_subboard:
                entries = [e for e in entries if e[0] != 'action' or
                           e[1] not in ('paste', 'insert_images',
                                        'insert_text')]
            width = 200
        if entries:
            menu = OverlayMenu(self, entries, min_width=width)
            self.menu_host.show(menu, point)

    # ---------- image menu ----------

    def rb_candidates(self):
        """(images to count attributes over, their main-board sources)."""
        images = self.rb_images()
        if self.is_subboard:
            sources = [i.link_source for i in images
                       if getattr(i, 'link_source', None) is not None
                       and i.link_source.scene() is self.rb_main().scene]
            return images, sources
        return images, images

    def rb_open_attribute(self, item, key, label):
        """Open the sub board for one of the image's tags."""
        images, sources = self.rb_candidates()
        source = getattr(item, 'link_source', item)
        parent = self.board if self.is_subboard else None
        self.rb_manager().open_attribute(key, label, sources, parent,
                                         anchor=source)

    def rb_tag_entries(self, item):
        """One list of the image's tags, each opening its sub board: the
        main ones (colour, tone, kind, mood, style), your tags, then
        everything else that was found."""
        images, _ = self.rb_candidates()
        counts = attributes.counts(images)
        targets = self.rb_targets(item)
        main, tags, auto = attributes.grouped(item)

        def row(key, label, dot, **extra):
            prefix = key.split(':')[0]
            opts = {'dot': dot, 'icon': ATTRIBUTE_ICONS.get(prefix),
                    'hint': attributes.HINTS.get(prefix, ''),
                    'count': counts.get(key, 0),
                    'tooltip': 'open as a sub board'}
            opts.update(extra)
            return ('item', label,
                    lambda: self.rb_open_attribute(item, key, label), opts)

        entries = [('label', 'main')]
        entries += [row(k, label, dot) for k, label, dot, _ in main]
        if semantic.vector(item) is None:
            entries.append(('item', 'find kind, mood and style…',
                            self.on_action_index_content,
                            {'icon': 'sparkle', 'tooltip':
                             'reads what the images show (on this computer)'}))
        entries += [('sep',), ('label', 'your tags')]
        entries += [row(k, label, dot, on_remove=lambda t=label:
                        self.rb_remove_tag(targets, t))
                    for k, label, dot, _ in tags]
        entries.append(('widget', lambda m: AddTagRow(
            m, attributes.all_tags(images),
            lambda t: self.rb_add_tag(targets, t))))
        entries += [('sep',), ('label', 'found')]
        entries += [row(k, label, dot) for k, label, dot, _ in auto]
        similar = attributes.similar_to(item, images)
        if len(similar) > 1:
            entries.append(('item', 'visually similar',
                            lambda: self.rb_open_attribute(
                                item, 'similar', 'similar images'),
                            {'icon': 'eye', 'count': len(similar),
                             'tooltip': 'open as a sub board'}))
        return entries

    def rb_study_entries(self, item, targets):
        """Colour study switches, and the levels' hex codes while it's
        showing."""
        def pick(mode):
            self.rb_set_study(targets, mode)
            point = getattr(self, '_rb_menu_point', None)
            if point is not None:  # show the menu again, with the codes
                self.rb_context_menu(point)

        entries = [('widget', lambda m: StudyToggle(m, item.study_mode,
                                                    pick))]
        if not item.study_mode:
            return entries
        levels = item.color_study()[item.study_mode][1]

        def copy(text, what):
            QtWidgets.QApplication.clipboard().setText(text)
            self.scene.internal_clipboard = []
            self.rb_notify(f'copied {what}')

        for hex_, share, lightness in levels:
            hint = (f'L {lightness:.0f} · {share:.0%}'
                    if item.study_mode == 'value' else f'{share:.0%}')
            entries.append(('item', hex_, lambda h=hex_: copy(h, h),
                            {'dot': hex_, 'hint': hint, 'indent': 1,
                             'tooltip': 'copy this hex code'}))
        codes = '\n'.join(h for h, *_ in levels)
        entries.append(('item', 'copy all hex codes',
                        lambda: copy(codes, f'{len(levels)} hex codes'),
                        {'indent': 1}))
        return entries

    def rb_image_menu(self, item):
        images, sources = self.rb_candidates()
        if self.rb_analyze(images) is None:
            return []
        self.rb_main().rb_refresh_profile()
        main, tags, auto = attributes.grouped(item)
        w, h = int(item.crop.width()), int(item.crop.height())
        origin = ''
        if item.meta.get('arena_channel'):
            origin = ' · from ' + attributes.channel_name(
                item.meta['arena_channel'])
        title = os.path.basename(item.filename) if item.filename else 'image'
        summary = ', '.join(label for key, label, *_ in main
                            if key.split(':')[0] in ('kind', 'mood'))
        entries = [('widget', lambda m: Header(title, f'{w} × {h}{origin}')),
                   ('sep',),
                   ('submenu', 'tags', lambda: self.rb_tag_entries(item),
                    {'icon': 'tag', 'hint': summary}),
                   ]
        targets = self.rb_targets(item)
        entries += self.rb_study_entries(item, targets)
        board_key = self.board.key if self.is_subboard else ''
        if board_key.startswith('tag:'):
            # Confirm or drop suggestions straight from the tag's board
            tag = board_key[4:]
            has = tag in attributes.tags_of(item)
            entries += [(
                'item', f'remove from “{tag}”' if has else f'add to “{tag}”',
                (lambda: self.rb_remove_tag(targets, tag)) if has
                else (lambda: self.rb_add_tag(targets, tag)),
                {'icon': 'star-outline'})]
        entries += self.rb_link_entries(item)

        has_note = bool(item.meta.get('note'))
        entries += [
            ('sep',),
            ('item', 'edit note…' if has_note else 'add note…',
             lambda: self.rb_edit_note(targets), {'icon': 'note'}),
            ('item', 'copy text', lambda: self.rb_copy_text(item),
             {'kbd': self.rb_kbd('extract_text')}),
        ]
        if item.meta.get('source_url') or (
                item.filename and item.filename.startswith('http')):
            entries.append(('item', 'open source link',
                            self.on_action_open_source,
                            {'icon': 'open-external',
                             'kbd': self.rb_kbd('open_source')}))
        if self.is_subboard:
            entries.append(('item', 'show in main board',
                            lambda: self.reveal_in_main(item),
                            {'icon': 'forward'}))
        selected = self.scene.selectedItems(user_only=True)
        if item.isSelected() and len(selected) > 1:
            entries.append(('action', 'export_selection',
                            f'export the {len(selected)} selected as one '
                            'image…'))
        entries += [
            ('sep',),
            ('action', 'copy', 'copy'),
            ('item', 'remove from sub board' if self.is_subboard
             else 'delete', self.on_action_delete_items,
             {'danger': True, 'kbd': 'Del'}),
        ]
        return entries

    def rb_kbd(self, action_id):
        """An action's current shortcut, for showing in a menu."""
        qaction = getattr(self, 'bee_qactions', {}).get(action_id)
        if qaction is None:
            return ''
        return qaction.shortcut().toString(
            QtGui.QKeySequence.SequenceFormat.NativeText)

    def rb_targets(self, item):
        """The image plus the rest of the selection if it's selected."""
        if item.isSelected():
            selected = self.rb_selected(images_only=True)
            if item in selected:
                return selected
        return [item]

    def rb_meta_change(self, items, key, values, text):
        """Change linked data (note, tags, marks) undoably on the main
        board, then repaint every board showing these images."""
        stack = self.rb_main().undo_stack
        stack.push(commands.SetItemMeta(items, key, values, text))
        self.rb_manager().refresh_views()
        self.rb_main().viewport().update()

    def rb_add_tag(self, items, tag):
        values = [sorted(set(i.meta.get('tags', [])) | {tag}) for i in items]
        self.rb_meta_change(items, 'tags', values, 'Add tag')
        self.rb_notify(f'tagged {len(items)} image'
                       f'{"" if len(items) == 1 else "s"} "{tag}"')

    def rb_remove_tag(self, items, tag):
        values = [[t for t in i.meta.get('tags', []) if t != tag]
                  for i in items]
        self.rb_meta_change(items, 'tags', values, 'Remove tag')

    def rb_edit_note(self, items):
        current = items[0].meta.get('note', '')
        dialog = NoteDialog(self, current, len(items))
        if dialog.exec() and dialog.result_text is not None:
            self.rb_meta_change(items, 'note',
                                [dialog.result_text] * len(items),
                                'Edit note')

    def rb_copy_text(self, item):
        self.scene.clearSelection()
        item.setSelected(True)
        text = item.meta.get('ocr_text')
        if text:
            QtWidgets.QApplication.clipboard().setText(text)
            self.rb_notify('copied the text in this image')
        else:
            self.on_action_extract_text()

    # ---------- note / tag actions ----------

    def on_action_add_note(self):
        images = self.rb_selected(images_only=True)
        if not images:
            self.rb_notify('select an image first')
            return
        self.rb_edit_note(images)

    def on_action_show_notes(self, checked):
        self.settings.setValue('Appearance/show_notes', checked)
        self.viewport().update()

    def on_action_tag_images(self):
        images = self.rb_selected(images_only=True)
        if not images:
            self.rb_notify('select images to tag first')
            return
        tag, ok = QtWidgets.QInputDialog.getText(
            self, 'tag images', f'tag for {len(images)} image'
            f'{"" if len(images) == 1 else "s"}:')
        tag = ' '.join(tag.strip().lower().split())
        if ok and tag:
            self.rb_add_tag(images, tag)

    def on_action_settings(self):
        from beeref.rboard.ui.settings_dialog import SettingsDialog
        SettingsDialog(self)

    # ---------- note callouts ----------

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        if not hasattr(self, 'note_hover_item'):
            return
        self.rb_paint_links(painter)
        show_all = self.settings.valueOrDefault('Appearance/show_notes')
        items = []
        if show_all:
            items = [i for i in self.rb_images() if i.meta.get('note')]
        else:
            selected = [i for i in self.rb_selected(images_only=True)
                        if i.meta.get('note')]
            if len(selected) <= 3:
                items = selected
            hover = self.note_hover_item
            try:
                if hover is not None and hover not in items and \
                        hover.scene() is self.scene:
                    items.append(hover)
            except RuntimeError:  # the image was deleted
                self.note_hover_item = None
        if not items:
            return
        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        viewport = self.viewport().rect()
        for item in items:
            box = self.mapFromScene(self.scene.itemsBoundingRect(
                items=[item])).boundingRect()
            if not box.intersects(viewport):
                continue
            self.rb_paint_note(painter, item.meta['note'], box, viewport)
        painter.restore()

    def rb_paint_note(self, painter, text, box, viewport):
        t = tm()
        body = ui_font(12)
        fm = QtGui.QFontMetrics(body)
        inner = NOTE_WIDTH - 24
        text_rect = fm.boundingRect(QtCore.QRect(0, 0, inner, 2000),
                                    Qt.TextFlag.TextWordWrap, text)
        height = text_rect.height() + 40
        x = box.right() + 28
        if x + NOTE_WIDTH > viewport.right() - 8:
            x = box.left() - 28 - NOTE_WIDTH
        x = max(8, x)
        y = max(8, min(box.top() - 8, viewport.bottom() - height - 8))
        card = QtCore.QRectF(x, y, NOTE_WIDTH, height)
        anchor = QtCore.QPointF(box.right() if x > box.right() else box.left(),
                                box.top() + min(24, box.height() / 2))
        target = QtCore.QPointF(card.left() if x > box.right()
                                else card.right(), card.top() + 18)
        painter.setPen(QtGui.QPen(t.color('ink-muted'), 1.2))
        painter.drawLine(anchor, target)
        painter.setBrush(t.color('ink-muted'))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(anchor, 2.5, 2.5)
        painter.setPen(QtGui.QPen(t.color('divider'), 1))
        painter.setBrush(t.color('surface-raised'))
        painter.drawRoundedRect(card, px('radius-md'), px('radius-md'))
        painter.setFont(section_font())
        painter.setPen(t.color('ink-muted'))
        painter.drawText(card.adjusted(12, 10, -12, 0), 'note')
        painter.setFont(body)
        painter.setPen(t.color('ink'))
        painter.drawText(card.adjusted(12, 28, -12, -10),
                         Qt.TextFlag.TextWordWrap, text)

    # ---------- pen ----------

    def on_action_pen_mode(self, checked):
        self.cancel_active_modes()
        self.pen_active = checked
        self.scene.clearSelection()
        if checked:
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.viewport().unsetCursor()
            self.rb_pen_cancel()
        self.home_bar.pin(checked)
        self.home_bar.refresh()
        self.rb_update_status()

    def rb_pen_width_px(self):
        return penlib.WIDTHS[self.settings.valueOrDefault('Pen/width')]

    def rb_pen_event(self, event, kind):
        """Handle mouse events while drawing. Returns True if consumed."""
        if not self.pen_active:
            return False
        if kind == 'press' and event.button() != Qt.MouseButton.LeftButton:
            return False
        if kind != 'press' and self._pen_points is None:
            return False
        pos = self.mapToScene(event.position().toPoint())
        tool = self.settings.valueOrDefault('Pen/tool')
        if kind == 'press':
            if tool == 'eraser':
                self._pen_points = []
                self._pen_erase_at(pos)
                return True
            self._pen_points = [pos]
            self._pen_preview = QtWidgets.QGraphicsPathItem()
            preview_pen = QtGui.QPen(
                QtGui.QColor(self.settings.valueOrDefault('Pen/color')),
                self.rb_pen_width_px())
            preview_pen.setCosmetic(True)
            preview_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            preview_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            self._pen_preview.setPen(preview_pen)
            self._pen_preview.setZValue(1e9)
            self.scene.addItem(self._pen_preview)
            return True
        if kind == 'move':
            if tool == 'eraser':
                self._pen_erase_at(pos)
                return True
            last = self._pen_points[-1]
            if math.dist((last.x(), last.y()), (pos.x(), pos.y())) * \
                    self.get_scale() < 1.5:
                return True
            if tool == 'free':
                self._pen_points.append(pos)
            else:
                self._pen_points = [self._pen_points[0], pos]
            mark = self._pen_mark(self._pen_points, tool, 1)
            self._pen_preview.setPath(penlib.mark_path(mark))
            return True
        # release
        points = self._pen_points
        self._pen_points = None
        self.rb_pen_cancel()
        if tool != 'eraser' and points:
            self._pen_commit(points, tool)
        return True

    def _pen_mark(self, points, tool, width):
        return {'kind': tool, 'points': [[p.x(), p.y()] for p in points],
                'color': self.settings.valueOrDefault('Pen/color'),
                'width': width}

    def rb_pen_cancel(self):
        if self._pen_preview is not None:
            if self._pen_preview.scene():
                self.scene.removeItem(self._pen_preview)
            self._pen_preview = None

    def _image_under(self, scene_points):
        """The image most of these points fall on, if any."""
        votes = {}
        sample = scene_points[::max(1, len(scene_points) // 8)] + \
            scene_points[-1:]
        for p in sample:
            for item in self.scene.items(p):
                if isinstance(item, BeePixmapItem):
                    votes[item] = votes.get(item, 0) + 1
                    break
        if not votes:
            return None
        item, n = max(votes.items(), key=lambda kv: kv[1])
        return item if n * 2 >= len(sample) else None

    def _pen_commit(self, points, tool):
        width_px = self.rb_pen_width_px()
        if tool in ('circle', 'arrow') and len(points) < 2:
            return
        target = self._image_under(points)
        if target is not None:
            local = [target.mapFromScene(p) for p in points]
            mark = self._pen_mark(
                local, tool, width_px / self.get_scale() / target.scale())
            marks = list(target.meta.get('marks', [])) + [mark]
            self.rb_meta_change([target], 'marks', [marks], 'Draw')
        else:
            origin = points[0]
            rel = [p - origin for p in points]
            mark = self._pen_mark(rel, tool, width_px / self.get_scale())
            item = penlib.StrokeItem(mark)
            item.setPos(origin)
            self.undo_stack.push(commands.InsertItems(self.scene, [item]))
            self.scene.clearSelection()

    def _pen_erase_at(self, pos):
        tolerance = 4 / self.get_scale()
        for item in self.scene.items(pos):
            if isinstance(item, penlib.StrokeItem):
                self.undo_stack.push(commands.DeleteItems(self.scene, [item]))
                return
            if isinstance(item, BeePixmapItem):
                marks = item.meta.get('marks', [])
                local = item.mapFromScene(pos)
                keep = [m for m in marks if not penlib.hit(
                    m, local, tolerance / item.scale())]
                if len(keep) != len(marks):
                    self.rb_meta_change([item], 'marks', [keep], 'Erase')
                return

    def rb_clear_marks(self):
        images = [i for i in self.rb_selected(images_only=True)
                  if i.meta.get('marks')]
        if images:
            self.rb_meta_change(images, 'marks', [[] for _ in images],
                                'Clear marks')


class Header(QtWidgets.QWidget):
    """Image menu header: file name and a caption line."""

    def __init__(self, title, sub):
        super().__init__()
        self.title = title
        self.sub = sub
        self.setFixedHeight(46)

    def preferred_width(self):
        fm = self.fontMetrics()
        return min(380, 28 + max(fm.horizontalAdvance(self.title),
                                 fm.horizontalAdvance(self.sub)))

    def paintEvent(self, event):
        t = tm()
        p = QtGui.QPainter(self)
        font = ui_font(12, 'medium')
        p.setFont(font)
        p.setPen(t.color('ink'))
        fm = QtGui.QFontMetrics(font)
        p.drawText(QtCore.QRectF(14, 6, self.width() - 24, 18),
                   Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(self.title, Qt.TextElideMode.ElideMiddle,
                                 self.width() - 28))
        small = QtGui.QFont(self.font())
        small.setPixelSize(11)
        p.setFont(small)
        p.setPen(t.color('ink-muted'))
        p.drawText(QtCore.QRectF(14, 24, self.width() - 24, 16),
                   Qt.AlignmentFlag.AlignVCenter, self.sub)


class Swatches(QtWidgets.QWidget):
    """Pen colour picker row."""

    def __init__(self, menu, current, on_pick):
        super().__init__()
        self.menu = menu
        self.current = current
        self.on_pick = on_pick
        self.setFixedHeight(30)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def preferred_width(self):
        return 36 + len(penlib.COLORS) * 22 + 12

    def swatch_rects(self):
        return [(hex_, QtCore.QRectF(36 + i * 22, 6, 16, 16))
                for i, (_, hex_) in enumerate(penlib.COLORS)]

    def mouseReleaseEvent(self, event):
        for hex_, rect in self.swatch_rects():
            if rect.adjusted(-3, -3, 3, 3).contains(event.position()):
                self.menu.close_all()
                self.on_pick(hex_)
                return

    def paintEvent(self, event):
        t = tm()
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        for (name, hex_), (_, rect) in zip(penlib.COLORS,
                                           self.swatch_rects()):
            if hex_ == self.current:
                p.setPen(QtGui.QPen(t.color('focus-ring'), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(rect.adjusted(-3, -3, 3, 3))
            p.setPen(QtGui.QPen(t.color('divider'), 1))
            p.setBrush(QtGui.QColor(hex_))
            p.drawEllipse(rect)
