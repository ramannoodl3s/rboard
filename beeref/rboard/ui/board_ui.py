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
from beeref.rboard import attributes, pen as penlib
from beeref.rboard.ui import icons
from beeref.rboard.ui.dialogs import NoteDialog, TagField
from beeref.rboard.ui.homebar import HomeBar, StatusPill
from beeref.rboard.ui.menu import MenuHost, OverlayMenu, section_font
from beeref.rboard.ui.theme import px, tm, ui_font


NOTE_WIDTH = 220
ALL = {'all_if_none': True}  # bar arranges everything if nothing's selected
ATTRIBUTE_ICONS = {
    'shape': 'fit', 'channel': 'forward', 'board': 'image',
    'folder': 'folder', 'text': 'text', 'note': 'note', 'marks': 'pen',
    'cover': 'sparkle', 'tag': 'star-outline',
}


class TagPills(QtWidgets.QWidget):
    """The image menu's tag row: one pill per tag, plus '+ add tag'."""

    def __init__(self, menu, tags, on_open, on_remove, on_add, existing):
        super().__init__()
        self.menu = menu
        layout = FlowLayout(self, spacing=4)
        layout.setContentsMargins(36, 2, 10, 8)
        for tag in tags:
            layout.addWidget(Pill(tag, lambda t=tag: on_open(t),
                                  lambda t=tag: on_remove(t)))
        self.field = None
        self.add_pill = Pill('+ add tag', self.start_add, dashed=True)
        layout.addWidget(self.add_pill)
        self.on_add = on_add
        self.existing = existing
        self.setFixedHeight(layout.heightForWidth(300))

    def start_add(self):
        self.add_pill.hide()
        self.field = TagField(self.existing)
        self.field.setFixedWidth(150)
        self.field.submitted.connect(self.submit)
        self.layout().addWidget(self.field)
        self.setFixedHeight(self.layout().heightForWidth(self.width() or 300))
        self.field.setFocus()
        self.menu.card.adjustSize()
        self.menu.resize(self.menu.card.width() + 36,
                         self.menu.card.height() + 36)

    def submit(self, tag):
        self.menu.close_all()
        self.on_add(tag)

    def preferred_width(self):
        return 0


class Pill(QtWidgets.QWidget):
    def __init__(self, text, on_click, on_remove=None, dashed=False):
        super().__init__()
        self.text = text
        self.on_click = on_click
        self.on_remove = on_remove
        self.dashed = dashed
        self.hovered = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        fm = self.fontMetrics()
        extra = 16 if on_remove else 0
        self.setFixedSize(fm.horizontalAdvance(text) + 30 + extra, 22)
        self.setToolTip('open as sub board' if on_remove else '')

    def enterEvent(self, e):
        self.hovered = True
        self.update()

    def leaveEvent(self, e):
        self.hovered = False
        self.update()

    def remove_rect(self):
        return QtCore.QRectF(self.width() - 20, 3, 16, 16)

    def mouseReleaseEvent(self, e):
        if self.on_remove and self.remove_rect().contains(e.position()):
            self.on_remove()
        else:
            self.on_click()

    def paintEvent(self, e):
        t = tm()
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        pen = QtGui.QPen(t.color('control-border'), 1)
        if self.dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(t.color('hover') if self.hovered else Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(
            QtCore.QRectF(self.rect()).adjusted(.5, .5, -.5, -.5),
            11, 11)
        if not self.dashed:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QColor(t.hex('palette-violet')))
            p.drawEllipse(QtCore.QPointF(12, 11), 4, 4)
        p.setPen(t.color('ink'))
        p.drawText(QtCore.QRectF(22 if not self.dashed else 10, 0,
                                 self.width(), 22),
                   Qt.AlignmentFlag.AlignVCenter, self.text)
        if self.on_remove and self.hovered:
            icons.draw(p, 'close', t.hex('ink-muted'), self.remove_rect())


class FlowLayout(QtWidgets.QLayout):
    """Wrapping row layout for tag pills."""

    def __init__(self, parent=None, spacing=4):
        super().__init__(parent)
        self.items = []
        self.setSpacing(spacing)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, i):
        return self.items[i] if 0 <= i < len(self.items) else None

    def takeAt(self, i):
        return self.items.pop(i) if 0 <= i < len(self.items) else None

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._place(QtCore.QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect, apply=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        h = self.heightForWidth(260)
        return QtCore.QSize(160, h)

    def _place(self, rect, apply):
        m = self.contentsMargins()
        x, y = rect.x() + m.left(), rect.y() + m.top()
        line_h = 0
        right = rect.right() - m.right()
        for item in self.items:
            size = item.sizeHint()
            if x + size.width() > right and line_h:
                x = rect.x() + m.left()
                y += line_h + self.spacing()
                line_h = 0
            if apply:
                item.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), size))
            x += size.width() + self.spacing()
            line_h = max(line_h, size.height())
        return y + line_h - rect.y() + m.bottom()


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
            ('action', 'export_images', 'export images…'),
            ('sep',),
            ('action', 'quit', 'quit'),
        ]

    def rb_menu_add(self):
        return [
            ('action', 'insert_images', 'images…'),
            ('action', 'insert_text', 'text'),
            ('action', 'paste', 'paste'),
            ('sep',),
            ('action', 'import_arena', 'from Are.na…'),
            ('action', 'sync_arena', 'sync Are.na channels'),
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
            ('sep',), ('label', 'colour'),
            ('action', 'arrange_color_dominant', 'by dominant colour', ALL),
            ('action', 'arrange_color_average', 'by average colour', ALL),
            ('action', 'arrange_lightness', 'by lightness', ALL),
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
            ('action', 'generate_palette', 'make a palette…'),
            ('action', 'sample_color', 'pick a colour'),
            ('action', 'show_color_gamut', 'colour spread'),
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

    def rb_menu_view(self):
        entries = [
            ('action', 'fit_scene', 'fit board'),
            ('action', 'fit_selection', 'fit selection'),
            ('sep',),
            ('action', 'value_study', 'value study'),
            ('action', 'value_study_levels', 'value study tones…'),
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
                     'checked': current is None and self.is_subboard})]
        boards = manager.tree()
        if not boards:
            entries.append(('item', 'right-click an image to open one',
                            None, {'enabled': False, 'indent': 1}))
        for board in boards:
            entries.append((
                'item', board.title,
                lambda b=board: manager.show(b),
                {'indent': board.depth() + 1,
                 'kbd': f'{len(board.sources)} · {board.state}',
                 'checked': board is current}))
        entries.append(('sep',))
        if self.is_subboard:
            entries.append(('item', 'discard this sub board',
                            lambda: manager.discard(self.board)))
        entries += [
            ('item', 'close all sub boards', manager.close_all,
             {'enabled': any(b.window for b in boards)}),
            ('item', 'discard closed sub boards', manager.discard_cached,
             {'enabled': any(not b.window for b in boards)}),
        ]
        return entries

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
        item = self.rb_user_item_at(point)
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

    def rb_image_menu(self, item):
        images, sources = self.rb_candidates()
        if self.rb_analyze(images) is None:
            return []
        source = getattr(item, 'link_source', item)
        counts = attributes.counts(images)
        manager = self.rb_manager()
        parent = self.board if self.is_subboard else None

        def open_board(key, label):
            manager.open_attribute(key, label, sources, parent,
                                   anchor=source)

        w, h = int(item.crop.width()), int(item.crop.height())
        origin = ''
        if item.meta.get('arena_channel'):
            origin = ' · from ' + attributes.channel_name(
                item.meta['arena_channel'])
        title = os.path.basename(item.filename) if item.filename else 'image'
        entries = [('widget', lambda m: Header(title, f'{w} × {h}{origin}')),
                   ('sep',), ('label', 'open as sub board')]
        for key, label, dot, kind in attributes.attributes(item):
            if kind != 'auto':
                continue
            prefix = key.split(':')[0]
            entries.append((
                'item', label, lambda k=key, lb=label: open_board(k, lb),
                {'dot': dot, 'icon': ATTRIBUTE_ICONS.get(prefix),
                 'count': counts.get(key, 0), 'trailing_icon': 'subboard'}))
        similar = attributes.similar_to(item, images)
        if len(similar) > 1:
            entries.append((
                'item', 'visually similar',
                lambda: open_board('similar', 'similar images'),
                {'icon': 'eye', 'count': len(similar),
                 'trailing_icon': 'subboard'}))

        targets = self.rb_targets(item)
        tags = attributes.tags_of(item)
        entries += [('sep',), ('label', 'tags'), ('widget', lambda m: TagPills(
            m, tags,
            on_open=lambda t: open_board(f'tag:{t}', t),
            on_remove=lambda t: self.rb_remove_tag(targets, t),
            on_add=lambda t: self.rb_add_tag(targets, t),
            existing=attributes.all_tags(images)))]

        has_note = bool(item.meta.get('note'))
        entries += [
            ('sep',),
            ('item', 'edit note…' if has_note else 'add note…',
             lambda: self.rb_edit_note(targets), {'icon': 'note'}),
            ('item', 'copy text', lambda: self.rb_copy_text(item),
             {'kbd': 'Ctrl+Shift+T'}),
        ]
        if item.meta.get('source_url') or (
                item.filename and item.filename.startswith('http')):
            entries.append(('item', 'open source link',
                            self.on_action_open_source,
                            {'icon': 'open-external', 'kbd': 'Ctrl+L'}))
        if self.is_subboard:
            entries.append(('item', 'show in main board',
                            lambda: self.reveal_in_main(item),
                            {'icon': 'forward'}))
        entries += [
            ('sep',),
            ('action', 'copy', 'copy'),
            ('item', 'remove from sub board' if self.is_subboard
             else 'delete', self.on_action_delete_items,
             {'danger': True, 'kbd': 'Del'}),
        ]
        return entries

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
