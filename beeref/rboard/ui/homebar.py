# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""The home bar: a floating icon bar anchored at the bottom right.

Hovering an icon opens its menu above it. The bar fades out when it
hasn't been used for a moment and fades back in when the pointer comes
near the bottom-right corner.
"""

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from beeref.rboard.ui import icons
from beeref.rboard.ui.menu import SHADOW, Card, OverlayMenu, paint_shadow
from beeref.rboard.ui.theme import is_sub, px, surface, tm


BUTTON = 28
GAP = 4
MARGIN = 16          # distance from the window corner
REVEAL_DISTANCE = 90  # how close the pointer must come to reveal the bar
FADE_MS = 120


class BarButton(QtWidgets.QAbstractButton):

    def __init__(self, bar, spec):
        super().__init__(bar.card)
        self.bar = bar
        self.spec = spec
        self.setFixedSize(BUTTON, BUTTON)
        self.setToolTip(spec['label'])
        self.setAccessibleName(spec['label'])
        self.setMouseTracking(True)
        self.hovered = False
        self.clicked.connect(lambda: bar.on_button_clicked(self))

    @property
    def active(self):
        state = self.spec.get('active')
        if callable(state):
            return bool(state())
        return self.bar.open_button is self

    def enterEvent(self, event):
        self.hovered = True
        self.update()
        self.bar.on_button_hovered(self)

    def leaveEvent(self, event):
        self.hovered = False
        self.update()

    def paintEvent(self, event):
        t = tm()
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = QtCore.QRectF(self.rect())
        enabled = self.spec.get('enabled', lambda: True)()
        if self.active:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(t.color('accent-soft'))
            p.drawRoundedRect(rect, px('radius-sm'), px('radius-sm'))
            color = t.hex('accent')
        elif self.hovered and enabled:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(surface('hover', self.bar.card.tinted))
            p.drawRoundedRect(rect, px('radius-sm'), px('radius-sm'))
            color = t.hex('ink')
        else:
            color = t.hex('ink-muted')
        if not enabled:
            p.setOpacity(0.45)
        icons.draw(p, self.spec['icon'], color, rect)


class BarSeparator(QtWidgets.QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(9, BUTTON)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setPen(tm().color('divider'))
        p.drawLine(4, 6, 4, BUTTON - 6)


class HomeBar(QtWidgets.QWidget):
    """Child widget of a board view.

    spec: list of groups; each group is a list of button dicts with
    'icon', 'label' and either 'menu' (callable returning menu entries)
    or 'action' (callable), plus optional 'active' and 'enabled'
    callables.
    """

    def __init__(self, view, spec, menu_host, settings=None):
        super().__init__(view)
        self.view = view
        self.menu_host = menu_host
        self.settings = settings
        self.open_button = None
        self.menu = None
        self.pinned = 0  # >0 keeps the bar visible (e.g. while drawing)
        self.card = Card(self, radius='radius-lg')
        self.card.tinted = is_sub(view)
        layout = QtWidgets.QHBoxLayout(self.card)
        layout.setContentsMargins(GAP, GAP, GAP, GAP)
        layout.setSpacing(GAP)
        self.buttons = []
        for gi, group in enumerate(spec):
            if gi:
                layout.addWidget(BarSeparator(self.card))
            for button_spec in group:
                button = BarButton(self, button_spec)
                self.buttons.append(button)
                layout.addWidget(button)
        self.card.adjustSize()
        self.resize(self.card.width() + 2 * SHADOW,
                    self.card.height() + 2 * SHADOW)
        self.card.move(SHADOW, SHADOW)

        self.opacity = QtWidgets.QGraphicsOpacityEffect(self)
        self.opacity.setOpacity(1.0)
        self.setGraphicsEffect(self.opacity)
        self.fade = QtCore.QPropertyAnimation(self.opacity, b'opacity', self)
        self.fade.setDuration(FADE_MS)
        self.fade.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self.fade.finished.connect(self._fade_finished)
        self.shown = True

        self.hide_timer = QtCore.QTimer(self, singleShot=True)
        self.hide_timer.timeout.connect(self.fade_out)
        self.menu_close_timer = QtCore.QTimer(self, singleShot=True)
        self.menu_close_timer.setInterval(350)
        self.menu_close_timer.timeout.connect(self._close_if_left)

        view.viewport().setMouseTracking(True)
        view.viewport().installEventFilter(self)
        self.setMouseTracking(True)
        self.reposition()
        self.show()
        self.raise_()
        self.schedule_hide()

    # -- geometry --

    def reposition(self):
        v = self.view
        x = v.width() - self.width() - MARGIN + SHADOW
        y = v.height() - self.height() - MARGIN + SHADOW
        self.move(max(x, 0), max(y, 0))

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        paint_shadow(p, self.card.geometry(), px('radius-lg'), 'float')

    def card_geometry(self):
        return self.card.geometry().translated(self.pos())

    def contains_global(self, global_pos):
        return self.card_geometry().contains(
            self.view.mapFromGlobal(global_pos))

    def near(self, view_pos):
        zone = self.card_geometry().adjusted(
            -REVEAL_DISTANCE, -REVEAL_DISTANCE, MARGIN, MARGIN)
        return zone.contains(view_pos)

    # -- visibility --

    def hide_delay(self):
        if self.settings is None:
            return 2000
        return int(self.settings.valueOrDefault(
            'Appearance/bar_hide_delay') * 1000)

    def schedule_hide(self):
        delay = self.hide_delay()
        if delay <= 0:
            self.hide_timer.stop()
            return
        self.hide_timer.start(delay)

    def keep_visible(self):
        return (self.pinned > 0 or self.menu is not None
                or self.underMouse())

    def fade_in(self):
        self.hide_timer.stop()
        if self.shown and self.fade.state() != \
                QtCore.QAbstractAnimation.State.Running:
            return
        self.shown = True
        self.setVisible(True)
        self.raise_()
        self._animate(1.0)

    def fade_out(self):
        if self.keep_visible() or self.hide_delay() <= 0:
            self.schedule_hide()
            return
        self.shown = False
        self._animate(0.0)

    def _animate(self, target):
        self.fade.stop()
        self.fade.setStartValue(self.opacity.opacity())
        self.fade.setEndValue(target)
        self.fade.start()

    def _fade_finished(self):
        if not self.shown:
            self.setVisible(False)

    def pin(self, on):
        self.pinned = max(0, self.pinned + (1 if on else -1))
        if self.pinned:
            self.fade_in()
        else:
            self.schedule_hide()

    def eventFilter(self, obj, event):
        etype = event.type()
        if etype == QtCore.QEvent.Type.MouseMove:
            if self.near(event.position().toPoint()):
                self.fade_in()
            elif self.shown:
                if not self.hide_timer.isActive():
                    self.schedule_hide()
        elif etype == QtCore.QEvent.Type.Leave:
            self.schedule_hide()
        elif etype == QtCore.QEvent.Type.Resize:
            QtCore.QTimer.singleShot(0, self.reposition)
        return False

    def enterEvent(self, event):
        self.fade_in()

    def leaveEvent(self, event):
        self.schedule_hide()
        if self.menu:
            self.menu_close_timer.start()

    # -- menus --

    def on_button_hovered(self, button):
        self.fade_in()
        if 'menu' not in button.spec:
            if self.menu:
                self.menu_close_timer.start()
            return
        if self.open_button is not button:
            self.open_menu(button)

    def on_button_clicked(self, button):
        if 'action' in button.spec:
            self.close_menu()
            button.spec['action']()
        elif self.open_button is button:
            self.close_menu()
        else:
            self.open_menu(button)

    def open_menu(self, button):
        self.menu_host.close_all()
        entries = button.spec['menu']()
        menu = OverlayMenu(self.view, entries,
                           on_activate=self.close_menu)
        button_pos = button.mapTo(self.view, QtCore.QPoint(0, 0))
        anchor = QtCore.QPoint(button_pos.x() + button.width() + 12,
                               self.card_geometry().top() - 6)
        self.menu_host.show(menu, anchor, align='above')
        menu.closed.connect(lambda: self._menu_closed(menu))
        self.menu = menu
        self.open_button = button
        self._watch_menu(menu)
        for b in self.buttons:
            b.update()

    def _watch_menu(self, menu):
        # Close the bar menu once the pointer has left both bar and menu
        menu.hover_changed.connect(
            lambda inside: self.menu_close_timer.stop() if inside
            else self.menu_close_timer.start())

    def _close_if_left(self):
        if not self.menu:
            return
        gpos = QtGui.QCursor.pos()
        if self.contains_global(gpos) or self.menu.contains_global(gpos):
            return
        self.close_menu()

    def _menu_closed(self, menu):
        if self.menu is menu:
            self.menu = None
            self.open_button = None
            for b in self.buttons:
                b.update()
            self.schedule_hide()

    def close_menu(self):
        if self.menu:
            self.menu.close_all()

    def update_theme(self):
        self.card.update_theme()
        for b in self.buttons:
            b.update()
        self.update()

    def refresh(self):
        for b in self.buttons:
            b.update()


class StatusPill(QtWidgets.QLabel):
    """Bottom-left status text ("24 images · 1 selected"), shown with the
    home bar."""

    def __init__(self, view, bar):
        super().__init__(view)
        self.view = view
        self.bar = bar
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.opacity = QtWidgets.QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity)
        bar.fade.valueChanged.connect(self.on_fade_value)
        bar.fade.finished.connect(self.on_fade_finished)
        self.update_theme()

    def on_fade_value(self, value):
        self.opacity.setOpacity(float(value))

    def on_fade_finished(self):
        self.setVisible(self.bar.shown and bool(self.text()))

    def update_theme(self):
        t = tm()
        self.setStyleSheet(
            f'background:{surface("surface-raised", is_sub(self.view)).name()};'
            f'color:{t.hex("ink-muted")};'
            'border-radius:12px;padding:0 10px;font-size:11px;')
        self.setFixedHeight(24)

    def set_text(self, text):
        self.setText(text)
        self.adjustSize()
        self.move(MARGIN, self.view.height() - self.height() - MARGIN)
        self.setVisible(bool(text) and self.bar.shown)
        self.raise_()

    def reposition(self):
        self.move(MARGIN, self.view.height() - self.height() - MARGIN)
