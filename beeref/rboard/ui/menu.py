# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Softclub menus: rounded overlay panels drawn inside the board window.

A menu is described by a list of entries (plain tuples) so the home bar,
right-click menus and the image menu all share one implementation:

    ('action', action_id[, label])     an existing app action
    ('item', label, callback, opts)    opts: kbd, icon, checked, enabled,
                                       danger, dot (colour), count
    ('label', text)                    section header
    ('sep',)
    ('submenu', label, entries_fn)     opens to the side on hover
    ('widget', factory)                factory(menu) -> QWidget
"""

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from beeref.rboard.ui import icons
from beeref.rboard.ui.theme import is_sub, px, surface, tm, ui_font


ROW_H = 28
SHADOW = 18  # room around the card for its shadow


def clean_label(text):
    """BeeRef action text -> Softclub menu label ("Fit &Scene" -> "fit
    scene"). Keeps proper names like Are.na and PureRef."""
    text = text.replace('&&', '\0').replace('&', '').replace('\0', '&')
    text = text.replace('...', '…')
    keep = ('Are.na', 'PureRef')
    out = text.lower()
    for word in keep:
        out = out.replace(word.lower(), word)
    return out


def section_font():
    font = ui_font(10, 'medium')
    font.setLetterSpacing(QtGui.QFont.SpacingType.PercentageSpacing, 110)
    font.setCapitalization(QtGui.QFont.Capitalization.AllUppercase)
    return font


class MenuRow(QtWidgets.QWidget):
    """One clickable menu row."""

    def __init__(self, menu, label, callback=None, kbd='', icon=None,
                 checked=None, enabled=True, danger=False, dot=None,
                 count=None, submenu=None, trailing_icon=None, indent=0,
                 hint='', on_remove=None, tooltip=''):
        super().__init__()
        self.menu = menu
        self.label = label
        self.callback = callback
        self.kbd = kbd
        self.icon = icon
        self.checked = checked
        self.enabled = enabled
        self.danger = danger
        self.dot = dot
        self.count = count
        self.submenu = submenu
        self.trailing_icon = trailing_icon
        self.indent = indent
        self.hint = hint
        self.on_remove = on_remove
        self.hovered = False
        self.setFixedHeight(ROW_H)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor if enabled
                       else Qt.CursorShape.ArrowCursor)
        if tooltip:
            self.setToolTip(tooltip)

    def extra_text(self):
        return ' · '.join(filter(None, (
            self.hint, str(self.count) if self.count is not None else '',
            self.kbd)))

    def preferred_width(self):
        fm = self.fontMetrics()
        width = 36 + 14 * self.indent + fm.horizontalAdvance(self.label) + 12
        right = self.extra_text()
        if right:
            width += 24 + fm.horizontalAdvance(right)
        if self.submenu or self.trailing_icon or self.on_remove:
            width += 22
        return width

    def remove_rect(self):
        return QtCore.QRectF(self.width() - 30, 0, 18, self.height())

    def enterEvent(self, event):
        self.hovered = True
        self.update()
        self.menu.on_row_hovered(self)

    def leaveEvent(self, event):
        self.hovered = False
        self.update()

    def mouseReleaseEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton and self.enabled
                and self.rect().contains(event.position().toPoint())):
            if self.on_remove and self.remove_rect().contains(
                    event.position()):
                remove = self.on_remove
                self.menu.close_all_menus()
                QtCore.QTimer.singleShot(0, remove)
                return
            if self.submenu:
                self.menu.open_submenu(self)
                return
            self.menu.activate(self)

    def paintEvent(self, event):
        t = tm()
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(4, 0, -4, 0)
        if self.hovered and self.enabled:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(surface('hover', self.menu.card.tinted))
            p.drawRoundedRect(rect, px('radius-sm'), px('radius-sm'))
        if not self.enabled:
            p.setOpacity(0.45)
        ink = t.color('danger' if self.danger else 'ink')
        muted = t.color('danger' if self.danger else 'ink-muted')

        slot = QtCore.QRectF(rect.x() + 8, 0, 16, self.height())
        if self.checked:
            icons.draw(p, 'check', t.hex('accent'), slot)
        elif self.dot:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QColor(self.dot))
            p.drawEllipse(slot.center(), 4, 4)
        elif self.icon:
            icons.draw(p, self.icon, muted.name(), slot)

        p.setPen(ink)
        left = 32 + 14 * self.indent
        text_rect = QtCore.QRectF(rect.x() + left, 0, rect.width() - left,
                                  self.height())
        p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, self.label)

        right = rect.right() - 10
        if self.on_remove and self.hovered:
            icons.draw(p, 'close', muted.name(), QtCore.QRectF(
                right - 16, 0, 16, self.height()))
            right -= 22
        elif self.submenu or self.trailing_icon:
            icons.draw(p, self.trailing_icon or 'chevron-right', muted.name(),
                       QtCore.QRectF(right - 16, 0, 16, self.height()))
            right -= 22
        elif self.on_remove:
            right -= 22
        extra = self.extra_text()
        if extra:
            p.setPen(muted)
            font = QtGui.QFont(self.font())
            font.setPixelSize(11)
            p.setFont(font)
            p.drawText(QtCore.QRectF(rect.x(), 0, right - rect.x(),
                                     self.height()),
                       Qt.AlignmentFlag.AlignVCenter
                       | Qt.AlignmentFlag.AlignRight, extra)


class SectionLabel(QtWidgets.QWidget):
    def __init__(self, text):
        super().__init__()
        self.text = text
        self.setFixedHeight(24)

    def preferred_width(self):
        return 40 + QtGui.QFontMetrics(section_font()).horizontalAdvance(
            self.text.upper())

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setFont(section_font())
        p.setPen(tm().color('ink-muted'))
        p.drawText(QtCore.QRectF(36, 6, self.width() - 36, 18),
                   Qt.AlignmentFlag.AlignVCenter, self.text)


class Separator(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(9)

    def preferred_width(self):
        return 0

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setPen(tm().color('divider'))
        p.drawLine(12, 4, self.width() - 12, 4)


def paint_shadow(painter, rect, radius, kind='popover'):
    """The design's soft shadow under a card (shadow-popover or
    shadow-float), drawn as stacked translucent rounded rects. Painted by
    the card's parent, since Qt can't nest graphics effects (the bar
    already uses one to fade)."""
    light = tm().theme['tone'] == 'light'
    blur, dy = (28, 10) if kind == 'popover' else (20, 6)
    strength = 0.18 if light else (0.55 if kind == 'popover' else 0.45)
    base = QtGui.QColor(32, 48, 60) if light else QtGui.QColor(0, 0, 0)
    steps = 10
    painter.save()
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    shadow = QtCore.QRectF(rect).translated(0, dy)
    for i in range(steps):
        spread = blur / 2 * (1 - i / steps)
        color = QtGui.QColor(base)
        color.setAlphaF(strength / steps * 1.4)
        painter.setBrush(color)
        r = shadow.adjusted(-spread, -spread, spread, spread)
        painter.drawRoundedRect(r, radius + spread, radius + spread)
    painter.restore()


class Card(QtWidgets.QFrame):
    """Rounded panel (shared by menus and bars). Its parent paints the
    shadow with paint_shadow()."""

    def __init__(self, parent=None, radius='radius-md', fill='surface-raised'):
        super().__init__(parent)
        self.radius = radius
        self.fill = fill
        self.tinted = False   # a sub board's

    def update_theme(self):
        self.update()

    def paintEvent(self, event):
        t = tm()
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setPen(QtGui.QPen(t.color('divider'), 1))
        p.setBrush(surface(self.fill, self.tinted))
        r = px(self.radius)
        p.drawRoundedRect(
            QtCore.QRectF(self.rect()).adjusted(.5, .5, -.5, -.5),
            r, r)


class OverlayMenu(QtWidgets.QWidget):
    """A menu drawn as a child of `host` (the board view)."""

    closed = QtCore.pyqtSignal()
    hover_changed = QtCore.pyqtSignal(bool)

    def enterEvent(self, event):
        self.hover_changed.emit(True)

    def leaveEvent(self, event):
        self.hover_changed.emit(False)

    def __init__(self, host, entries, min_width=200, parent_menu=None,
                 on_activate=None):
        super().__init__(host)
        self.host = host
        self.parent_menu = parent_menu
        self.child = None
        self.on_activate = on_activate
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.card = Card(self)
        self.card.tinted = is_sub(host)
        self.outer = QtWidgets.QVBoxLayout(self.card)
        self.outer.setContentsMargins(0, 4, 0, 4)
        self.outer.setSpacing(0)
        self.body = QtWidgets.QWidget()
        self.layout_ = QtWidgets.QVBoxLayout(self.body)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(0)
        self.scroll = None
        self.rows = []
        self.min_width = min_width
        self.build(entries)

    # -- building --

    def build(self, entries):
        width = self.min_width
        for entry in entries:
            widget = self._make(entry)
            if widget is None:
                continue
            self.layout_.addWidget(widget)
            if hasattr(widget, 'preferred_width'):
                width = max(width, widget.preferred_width())
            elif widget.sizeHint().width() > 0:
                width = max(width, widget.sizeHint().width())
        self.width_ = min(width, 420)
        self.relayout()

    def relayout(self):
        """Size the card to its rows; long menus scroll inside the window."""
        width = self.width_
        self.body.setFixedWidth(width)
        self.body.adjustSize()
        height = self.body.sizeHint().height() + 8
        limit = max(160, self.host.height() - 16)
        if getattr(self, 'max_height', None):
            limit = min(limit, self.max_height)
        if height > limit and self.scroll is None:
            self.scroll = QtWidgets.QScrollArea()
            self.scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
            self.scroll.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.scroll.setStyleSheet(
                'QScrollArea, QScrollArea > QWidget > QWidget '
                '{ background: transparent; }')
            self.scroll.setWidget(self.body)
            self.outer.addWidget(self.scroll)
        elif self.scroll is None and self.body.parent() is None:
            self.outer.addWidget(self.body)
        if self.scroll is not None:
            self.body.setFixedWidth(width)
            self.scroll.setFixedSize(width, min(height, limit) - 8)
        self.card.setFixedWidth(width)
        self.card.adjustSize()
        self.card.setFixedHeight(min(height, limit))
        self.resize(width + 2 * SHADOW, self.card.height() + 2 * SHADOW)
        self.card.move(SHADOW, SHADOW)

    def close_all_menus(self):
        root = self
        while root.parent_menu:
            root = root.parent_menu
        root.close_all()

    def _make(self, entry):
        kind = entry[0]
        if kind == 'sep':
            return Separator()
        if kind == 'label':
            return SectionLabel(entry[1])
        if kind == 'widget':
            return entry[1](self)
        if kind == 'submenu':
            opts = entry[3] if len(entry) > 3 else {}
            row = MenuRow(self, entry[1], submenu=entry[2], **opts)
            self.rows.append(row)
            return row
        if kind == 'action':
            from beeref.actions.actions import actions
            action = actions.get(entry[1])
            qa = getattr(self.host, 'bee_qactions', {}).get(entry[1])
            if action is None or qa is None:
                return None
            label = entry[2] if len(entry) > 2 else clean_label(action.text)
            opts = entry[3] if len(entry) > 3 else {}
            kbd = qa.shortcut().toString(
                QtGui.QKeySequence.SequenceFormat.NativeText)
            callback, enabled = qa.trigger, qa.isEnabled()
            scene = getattr(self.host, 'scene', None)
            target = getattr(self.host, 'rb_selection_target', None)
            if opts.get('all_if_none') and target is not None:
                # R Board: run on the board where the selection is;
                # with none, on the last selection, else everything
                view, how = target(apply=False)
                if how is not None:
                    callback = (lambda a=entry[1]:
                                self.host.rb_run_on_selection(a))
                    enabled = True
                    label += {'last': ' (last selection)',
                              'all': ' (all)'}.get(how, '')
            elif (opts.get('all_if_none') and not enabled
                    and scene is not None and scene.items()):
                # Work on every item when nothing is selected
                callback = self._select_all_then(action.callback)
                enabled = True
                label += ' (all)'
            row = MenuRow(self, label, callback=callback, kbd=kbd,
                          checked=qa.isChecked() if qa.isCheckable() else None,
                          enabled=enabled, icon=opts.get('icon'))
            self.rows.append(row)
            return row
        if kind == 'item':
            opts = entry[3] if len(entry) > 3 else {}
            row = MenuRow(self, entry[1], callback=entry[2], **opts)
            self.rows.append(row)
            return row
        raise ValueError(f'Unknown menu entry {entry!r}')

    def _select_all_then(self, callback_name):
        def run():
            self.host.scene.select_all_items()
            getattr(self.host, callback_name)()
        return run

    # -- showing --

    def popup(self, anchor, align='cursor'):
        """Show the menu. anchor is a QPoint in host coordinates.

        align='cursor': top-left at the anchor (flipped to fit).
        align='above':  right edge at anchor.x(), bottom at anchor.y().
        """
        host = self.host.rect()
        if align == 'above':
            # Taller than the room above the bar: scroll rather than
            # slide down over the bar
            room = anchor.y() - host.top() - 8
            if self.card.height() > room:
                self.max_height = max(120, room)
                self.relayout()
        w, h = self.width(), self.height()
        if align == 'above':
            x = anchor.x() - w + SHADOW
            y = anchor.y() - h + SHADOW
        else:
            x = anchor.x() - SHADOW
            y = anchor.y() - SHADOW
            if x + w > host.right():
                x = anchor.x() - w + SHADOW
            if y + h > host.bottom():
                y = anchor.y() - h + SHADOW
        x = max(host.left() - SHADOW, min(x, host.right() - w + SHADOW))
        y = max(host.top() - SHADOW, min(y, host.bottom() - h + SHADOW))
        self.move(x, y)
        self.show()
        self.raise_()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        paint_shadow(p, self.card.geometry(), px(self.card.radius))

    def card_geometry(self):
        """The visible card's rect in host coordinates."""
        return self.card.geometry().translated(self.pos())

    def contains_global(self, global_pos):
        menu = self
        while menu:
            if menu.card_geometry().contains(self.host.mapFromGlobal(
                    global_pos)):
                return True
            menu = menu.child
        return False

    # -- interaction --

    def on_row_hovered(self, row):
        if row.submenu:
            QtCore.QTimer.singleShot(120, lambda: self._maybe_open(row))
        elif self.child:
            self.child.close()
            self.child = None

    def _maybe_open(self, row):
        if row.hovered and (self.child is None
                            or self.child.source_row is not row):
            self.open_submenu(row)

    def open_submenu(self, row):
        if self.child:
            self.child.close()
        entries = row.submenu() if callable(row.submenu) else row.submenu
        child = OverlayMenu(self.host, entries, parent_menu=self,
                            on_activate=self.on_activate)
        child.source_row = row
        child.closed.connect(lambda: setattr(self, 'child', None)
                             if self.child is child else None)
        row_pos = row.mapTo(self.host, QtCore.QPoint(0, 0))
        # Open to the left (menus sit at the right of the window), or to
        # the right when there's no room
        x = row_pos.x() - child.width() + 2 * SHADOW - 4
        if x < 0:
            x = row_pos.x() + row.width() + 4 - SHADOW
        y = row_pos.y() - SHADOW - 4
        y = max(-SHADOW, min(y, self.host.height() - child.height() + SHADOW))
        child.move(x, y)
        child.show()
        child.raise_()
        self.child = child

    def activate(self, row):
        callback = row.callback
        root = self
        while root.parent_menu:
            root = root.parent_menu
        root.close_all()
        if root.on_activate:
            root.on_activate()
        if callback:
            # Run after the menu is gone so dialogs open cleanly
            QtCore.QTimer.singleShot(0, callback)

    def close_all(self):
        if self.child:
            self.child.close_all()
        self.close()

    def closeEvent(self, event):
        if self.child:
            self.child.close()
        self.closed.emit()
        super().closeEvent(event)

    def update_theme(self):
        self.card.update_theme()
        for w in self.card.findChildren(QtWidgets.QWidget):
            w.update()


class MenuHost(QtCore.QObject):
    """Closes a host's overlay menus on outside clicks and Escape. It only
    watches the app's events while one of its menus is open, so closed
    boards never get called back."""

    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.menus = []
        self.watching = False

    def show(self, menu, anchor, align='cursor'):
        self.close_all()
        self.menus.append(menu)
        menu.closed.connect(lambda: self._closed(menu))
        menu.popup(anchor, align)
        self._watch(True)
        return menu

    def _closed(self, menu):
        if menu in self.menus:
            self.menus.remove(menu)
        if not self.menus:
            self._watch(False)

    def _watch(self, on):
        app = QtWidgets.QApplication.instance()
        if on and not self.watching:
            app.installEventFilter(self)
        elif not on and self.watching:
            app.removeEventFilter(self)
        self.watching = on

    def close_all(self):
        for menu in list(self.menus):
            menu.close_all()

    def is_open(self):
        return bool(self.menus)

    def eventFilter(self, obj, event):
        if not getattr(self, 'menus', None):
            return False
        etype = event.type()
        if etype == QtCore.QEvent.Type.MouseButtonPress:
            gpos = event.globalPosition().toPoint()
            if not any(m.contains_global(gpos) for m in self.menus):
                bar = getattr(self.host, 'home_bar', None)
                if not (bar and bar.contains_global(gpos)):
                    self.close_all()
        elif (etype == QtCore.QEvent.Type.KeyPress
              and event.key() == Qt.Key.Key_Escape):
            self.close_all()
            return True
        return False
