# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Overlay mode: images floating over everything, see-through, letting
clicks pass to the app underneath (drawing over a reference in Photoshop,
Krita, Clip Studio…).

Two states, switched with a global hotkey (Ctrl+Alt+` by default, free in
Photoshop, Premiere and Blender) or the tray icon:
- through: clicks go to the app below; the overlay can't be touched
- grab: a bar to move it, a corner to resize, drag to pan, wheel to zoom

Only one overlay at a time; it remembers where it was and how see-through.
"""

import ctypes
import logging
import sys

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

logger = logging.getLogger(__name__)

DEFAULT_HOTKEY = 'Ctrl+Alt+`'
OPACITIES = (0.25, 0.4, 0.55, 0.7, 0.85, 1.0)

_current = None


# ---------- the global hotkey (Windows) ----------

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 1, 2, 4, 8, 0x4000
WM_HOTKEY = 0x0312
HOTKEY_ID = 0x5242   # 'RB'


def parse_hotkey(text):
    """'Ctrl+Alt+`' -> (Windows modifier flags, virtual key) or None."""
    parts = [p.strip() for p in text.replace(' ', '').split('+')]
    if len(parts) < 2 or not parts[-1]:
        # '+' itself as the key: 'Ctrl++'
        if text.endswith('++'):
            parts = text[:-2].split('+') + ['+']
        else:
            return None
    mods = 0
    for p in parts[:-1]:
        flag = {'ctrl': MOD_CONTROL, 'alt': MOD_ALT, 'shift': MOD_SHIFT,
                'win': MOD_WIN, 'meta': MOD_WIN}.get(p.lower())
        if flag is None:
            return None
        mods |= flag
    key = parts[-1]
    upper = key.upper()
    if len(key) == 1 and (key.isalpha() or key.isdigit()):
        vk = ord(upper)
    elif upper.startswith('F') and upper[1:].isdigit() and \
            1 <= int(upper[1:]) <= 24:
        vk = 0x6F + int(upper[1:])
    else:
        vk = {'`': 0xC0, '~': 0xC0, 'SPACE': 0x20, '-': 0xBD, '=': 0xBB,
              '[': 0xDB, ']': 0xDD, ';': 0xBA, "'": 0xDE, ',': 0xBC,
              '.': 0xBE, '/': 0xBF, '\\': 0xDC, 'PAUSE': 0x13,
              'SCROLLLOCK': 0x91, 'INS': 0x2D, 'INSERT': 0x2D,
              'HOME': 0x24, 'END': 0x23}.get(upper)
    if vk is None or not mods:
        return None
    return mods, vk


class Hotkey(QtCore.QAbstractNativeEventFilter):
    """A system-wide shortcut. It has to be global: while clicks pass
    through, the overlay never gets keys."""

    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.registered = False
        self.text = None
        # A hidden window that is never recreated, so the registration
        # survives the overlay's window being rebuilt
        self.window = QtWidgets.QWidget()
        self.hwnd = int(self.window.winId())
        QtWidgets.QApplication.instance().installNativeEventFilter(self)

    def register(self, text):
        self.unregister()
        self.text = text
        parsed = parse_hotkey(text)
        if sys.platform != 'win32' or parsed is None:
            return False
        mods, vk = parsed
        ok = ctypes.windll.user32.RegisterHotKey(
            ctypes.c_void_p(self.hwnd), HOTKEY_ID, mods | MOD_NOREPEAT, vk)
        self.registered = bool(ok)
        if not ok:
            logger.warning(f'Overlay hotkey {text} is taken by another app')
        return self.registered

    def unregister(self):
        if self.registered and sys.platform == 'win32':
            ctypes.windll.user32.UnregisterHotKey(
                ctypes.c_void_p(self.hwnd), HOTKEY_ID)
        self.registered = False

    def nativeEventFilter(self, event_type, message):
        if sys.platform == 'win32' and event_type in (
                b'windows_generic_MSG', b'windows_dispatcher_MSG'):
            from ctypes import wintypes
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                QtCore.QTimer.singleShot(0, self.callback)
                return True, 0
        return False, 0

    def close(self):
        self.unregister()
        QtWidgets.QApplication.instance().removeNativeEventFilter(self)
        self.window.deleteLater()


# ---------- what it shows ----------

class OverlayScene(QtWidgets.QGraphicsScene):
    """Just enough of a board's scene for board images to draw in."""
    Z_STEP = 0.001

    def __init__(self):
        super().__init__()
        self.max_z = self.min_z = 0
        self.active_mode = None

    def has_selection(self):
        return False

    def has_single_selection(self):
        return False


class OverlayView(QtWidgets.QGraphicsView):
    def __init__(self, parent):
        super().__init__(parent)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setStyleSheet('background: transparent')
        self.viewport().setAutoFillBackground(False)
        self.setBackgroundBrush(QtGui.QBrush(Qt.BrushStyle.NoBrush))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setRenderHints(QtGui.QPainter.RenderHint.SmoothPixmapTransform
                            | QtGui.QPainter.RenderHint.Antialiasing)
        self.setTransformationAnchor(
            QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)
        self.setViewportUpdateMode(
            QtWidgets.QGraphicsView.ViewportUpdateMode.FullViewportUpdate)

    def get_scale(self):
        return self.transform().m11()

    def wheelEvent(self, event):
        factor = 1.0015 ** event.angleDelta().y()
        self.scale(factor, factor)

    def fit(self):
        rect = self.scene().itemsBoundingRect()
        if not rect.isEmpty():
            self.setSceneRect(rect.adjusted(-rect.width() * 4,
                                            -rect.height() * 4,
                                            rect.width() * 4,
                                            rect.height() * 4))
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)


def copies(items):
    """Linked copies of board images, placed as they are on the board."""
    from beeref.rboard.subboards import linked_copy
    out = []
    for item in items:
        source = getattr(item, 'link_source', None) or item
        copy = linked_copy(source)
        copy.setTransform(item.transform())
        copy.setPos(item.pos())
        copy.setScale(item.scale())
        copy.setRotation(item.rotation())
        copy.setZValue(item.zValue())
        copy.setOpacity(item.opacity())
        copy.grayscale = item.grayscale
        copy.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable,
                     False)
        copy.setFlag(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        out.append(copy)
    return out


# ---------- the window ----------

class GrabBar(QtWidgets.QWidget):
    """Shown while the overlay can be touched: drag it to move the
    overlay; opacity, click-through and close on the right."""

    def __init__(self, overlay):
        super().__init__(overlay)
        self.overlay = overlay
        self.drag_from = None
        self.setAutoFillBackground(True)
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(10, 3, 4, 3)
        row.setSpacing(6)
        hint = QtWidgets.QLabel(
            f'overlay · drag here to move · '
            f'{overlay.hotkey_text()} to click through')
        row.addWidget(hint, 1)
        self.opacity = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(15, 100)
        self.opacity.setFixedWidth(110)
        self.opacity.setToolTip('see-through')
        self.opacity.setValue(round(overlay.windowOpacity() * 100))
        self.opacity.valueChanged.connect(
            lambda v: overlay.set_opacity(v / 100))
        row.addWidget(self.opacity)
        through = QtWidgets.QToolButton()
        through.setText('click through')
        through.clicked.connect(lambda: overlay.set_through(True))
        row.addWidget(through)
        close = QtWidgets.QToolButton()
        close.setText('×')
        close.setToolTip('close the overlay')
        close.clicked.connect(overlay.close)
        row.addWidget(close)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.drag_from = (e.globalPosition().toPoint()
                              - self.overlay.frameGeometry().topLeft())

    def mouseMoveEvent(self, e):
        if self.drag_from is not None:
            self.overlay.move(e.globalPosition().toPoint() - self.drag_from)

    def mouseReleaseEvent(self, e):
        self.drag_from = None
        self.overlay.remember()


class Overlay(QtWidgets.QWidget):
    def __init__(self, items, settings, title='overlay'):
        super().__init__(None, Qt.WindowType.Window
                         | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.settings = settings
        self.through = False
        self.setWindowTitle(f'R Board · {title}')
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.scene = OverlayScene()
        for copy in copies(items):
            self.scene.addItem(copy)
        self.view = OverlayView(self)
        self.view.setScene(self.scene)
        self.bar = None
        self.grip = QtWidgets.QSizeGrip(self)
        self.grip.resize(18, 18)
        self.hotkey = Hotkey(self.toggle)
        self.hotkey.register(self.hotkey_text())
        self.tray = self._make_tray()
        opacity = float(settings.value('Overlay/opacity', 0.7))
        self.setWindowOpacity(min(max(opacity, 0.15), 1.0))
        geometry = settings.value('Overlay/geometry')
        if not (isinstance(geometry, QtCore.QByteArray)
                and self.restoreGeometry(geometry)):
            screen = QtGui.QGuiApplication.primaryScreen().availableGeometry()
            self.resize(screen.width() // 3, screen.height() // 2)
            self.move(screen.right() - self.width() - 40, screen.top() + 80)
        self.bar = GrabBar(self)
        self.layout_children()

    # -- settings --

    def hotkey_text(self):
        return str(self.settings.value('Overlay/hotkey', DEFAULT_HOTKEY)
                   or DEFAULT_HOTKEY)

    def remember(self):
        self.settings.setValue('Overlay/geometry', self.saveGeometry())
        self.settings.setValue('Overlay/opacity', self.windowOpacity())

    def set_opacity(self, value):
        self.setWindowOpacity(value)
        self.remember()

    # -- states --

    def toggle(self):
        self.set_through(not self.through)

    def set_through(self, through):
        """Click-through or grab. Changing the input flag makes Qt rebuild
        the native window, so it's shown again after."""
        self.through = through
        geometry = self.geometry()
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, through)
        self.setGeometry(geometry)
        self.show()
        self.layout_children()
        if not through:
            self.raise_()
            self.activateWindow()
        if self.tray is not None:
            self.through_action.setChecked(through)

    # -- layout --

    def layout_children(self):
        bar_h = 0 if self.through or self.bar is None else 30
        if self.bar is not None:
            self.bar.setVisible(not self.through)
            self.bar.setGeometry(0, 0, self.width(), bar_h)
        self.view.setGeometry(0, bar_h, self.width(), self.height() - bar_h)
        self.grip.setVisible(not self.through)
        self.grip.move(self.width() - self.grip.width(),
                       self.height() - self.grip.height())
        self.grip.raise_()
        self.update()

    def resizeEvent(self, event):
        self.layout_children()

    def paintEvent(self, event):
        if self.through:
            return
        p = QtGui.QPainter(self)
        from beeref.rboard.ui.theme import tm
        p.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 40))
        pen = QtGui.QPen(tm().color('accent'), 2)
        p.setPen(pen)
        p.drawRect(self.rect().adjusted(1, 1, -1, -1))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.set_through(True)
            return
        super().keyPressEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, '_fitted', False):
            self._fitted = True
            QtCore.QTimer.singleShot(0, self.view.fit)

    # -- tray --

    def _make_tray(self):
        if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            return None
        from beeref.assets import BeeAssets
        tray = QtWidgets.QSystemTrayIcon(BeeAssets().logo, self)
        tray.setToolTip(f'R Board overlay · {self.hotkey_text()} '
                        'switches click-through')
        menu = QtWidgets.QMenu()
        self.through_action = menu.addAction('click through')
        self.through_action.setCheckable(True)
        self.through_action.toggled.connect(
            lambda on: on != self.through and self.set_through(on))
        see = menu.addMenu('see-through')
        for value in OPACITIES:
            see.addAction(f'{round(value * 100)}%',
                          lambda v=value: self.set_opacity(v))
        menu.addAction('fit images', self.view.fit)
        menu.addSeparator()
        menu.addAction('close overlay', self.close)
        tray.setContextMenu(menu)
        self._tray_menu = menu
        tray.activated.connect(
            lambda reason: self.toggle()
            if reason == QtWidgets.QSystemTrayIcon.ActivationReason.Trigger
            else None)
        tray.show()
        return tray

    def closeEvent(self, event):
        global _current
        self.remember()
        self.hotkey.close()
        if self.tray is not None:
            self.tray.hide()
        if _current is self:
            _current = None
        super().closeEvent(event)


def open_overlay(items, settings, title='overlay'):
    """Show these images as the overlay (replacing any open one)."""
    global _current
    if _current is not None:
        _current.close()
    _current = Overlay(items, settings, title)
    _current.show()
    _current.raise_()
    return _current


def current():
    return _current
