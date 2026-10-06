# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Areas: the main window split into rectangles, the way Blender does it
(https://docs.blender.org/manual/en/latest/interface/window_system/areas.html).

Each area shows one board (the main board or a sub board), picked from
the menu at the left of its header.

- Resizing: drag the border between areas. Ctrl snaps to halves, thirds
  and quarters; Shift moves aligned borders together.
- Splitting: drag from an area corner left/right to split it vertically,
  up/down to split it horizontally.
- Joining: drag from a corner into the neighbouring area (they must share
  a full edge). The area that will be absorbed is darkened.
- Swapping contents: Ctrl-drag from a corner to another area.
- New window: Shift-drag from a corner (sub boards only).
- Esc or right-click before releasing cancels.
- Area options (right-click a border): Vertical Split, Horizontal Split
  (Tab switches), Join Left/Right/Up/Down, Swap Areas.
- View > Area: Toggle Maximize Area (Ctrl+Space), Focus Mode
  (Ctrl+Alt+Space), Duplicate Area into New Window, Close Area.

Area rectangles are kept as fractions of the window (0..1), so the
layout survives resizing and can be saved in the board file.
"""

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from beeref.rboard.ui import icons
from beeref.rboard.ui.menu import ROW_H, MenuHost, OverlayMenu
from beeref.rboard.ui.theme import px, tm, ui_font

GAP = 4            # px between areas
CORNER = 14        # px, corner action zone
MIN_SIZE = 140     # px, smallest an area can get
DRAG_START = 8     # px the pointer moves before a corner gesture starts
EPS = 1e-6
SNAPS = (1 / 4, 1 / 3, 1 / 2, 2 / 3, 3 / 4)


def near(a, b):
    return abs(a - b) < 1e-4


class Area(QtWidgets.QWidget):
    """One rectangle of the window: a header and a board."""

    def __init__(self, screen, rect):
        super().__init__(screen)
        self.screen = screen
        self.rect_ = list(rect)   # [x0, y0, x1, y1] as fractions
        self.content = None       # main view, DockedBoard or EmptyArea
        self.header = AreaHeader(self)
        self.corners = [CornerZone(self, c) for c in range(4)]
        self.setAutoFillBackground(False)

    # -- content --

    def set_content(self, widget):
        if self.content is not None and self.content is not widget:
            self.content.setParent(None)
        self.content = widget
        widget.setParent(self)
        widget.rb_area = self
        view = getattr(widget, 'view', widget)
        if isinstance(view, QtWidgets.QGraphicsView):
            view.rb_area = self
            # Resizing an area keeps what's in the middle in the middle
            view.setResizeAnchor(
                QtWidgets.QGraphicsView.ViewportAnchor.AnchorViewCenter)
        widget.show()
        self.layout_children()
        self.header.update()
        for corner in self.corners:
            corner.raise_()

    def view(self):
        """The board view shown here, if any."""
        c = self.content
        if c is None:
            return None
        return getattr(c, 'view', c if hasattr(c, 'scene') else None)

    def title(self):
        c = self.content
        if c is None or isinstance(c, EmptyArea):
            return 'choose a board'
        if hasattr(c, 'board'):
            return c.board.title
        filename = getattr(c, 'filename', None)
        import os
        return os.path.basename(filename) if filename else 'main board'

    def is_main(self):
        return self.content is self.screen.main_view

    # -- geometry --

    def pixel_rect(self):
        w, h = self.screen.width(), self.screen.height()
        x0, y0, x1, y1 = self.rect_
        half = GAP / 2
        left = round(x0 * w + (half if x0 > EPS else 0))
        top = round(y0 * h + (half if y0 > EPS else 0))
        right = round(x1 * w - (half if x1 < 1 - EPS else 0))
        bottom = round(y1 * h - (half if y1 < 1 - EPS else 0))
        return QtCore.QRect(left, top, max(right - left, 1),
                            max(bottom - top, 1))

    def layout_children(self):
        w, h = self.width(), self.height()
        header_h = 0 if self.screen.focus_mode else ROW_H + 4
        self.header.setGeometry(0, 0, w, header_h)
        self.header.setVisible(header_h > 0)
        if self.content is not None:
            self.content.setGeometry(0, header_h, w, h - header_h)
        for corner in self.corners:
            corner.place()

    def resizeEvent(self, event):
        self.layout_children()


class AreaHeader(QtWidgets.QWidget):
    """The strip at the top of an area: the board menu on the left (like
    Blender's editor type menu) and 'back to previous' when maximized."""

    def __init__(self, area):
        super().__init__(area)
        self.area = area
        self.hovered = None
        self.setMouseTracking(True)

    def board_rect(self):
        fm = QtGui.QFontMetrics(ui_font(12))
        w = fm.horizontalAdvance(self.area.title()) + 52
        return QtCore.QRectF(6, 3, min(w, self.width() - 12),
                             self.height() - 6)

    def back_rect(self):
        if self.area.screen.maximized is not self.area:
            return QtCore.QRectF()
        fm = QtGui.QFontMetrics(ui_font(12))
        w = fm.horizontalAdvance('back to previous') + 24
        return QtCore.QRectF(self.width() - w - 6, 3, w, self.height() - 6)

    def mouseMoveEvent(self, e):
        hit = ('board' if self.board_rect().contains(e.position()) else
               'back' if self.back_rect().contains(e.position()) else None)
        if hit != self.hovered:
            self.hovered = hit
            self.update()

    def leaveEvent(self, e):
        self.hovered = None
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton:
            self.area.screen.area_menu(self.area, e.globalPosition())
            return
        if self.back_rect().contains(e.position()):
            self.area.screen.toggle_maximize(self.area)
        elif self.board_rect().contains(e.position()):
            self.area.screen.board_menu(self.area)

    def paintEvent(self, e):
        t = tm()
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), t.color('surface'))
        p.setFont(ui_font(12))
        rect = self.board_rect()
        if self.hovered == 'board':
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(t.color('hover'))
            p.drawRoundedRect(rect, px('radius-sm'), px('radius-sm'))
        icon = ('image' if self.area.is_main() else
                'layers' if self.area.view() else 'plus')
        icons.draw(p, icon, t.hex('ink-muted'),
                   QtCore.QRectF(rect.x() + 6, 0, 16, self.height()))
        p.setPen(t.color('ink'))
        p.drawText(rect.adjusted(28, 0, -20, 0),
                   Qt.AlignmentFlag.AlignVCenter, self.area.title())
        icons.draw(p, 'chevron-right', t.hex('ink-muted'), QtCore.QRectF(
            rect.right() - 18, 0, 16, self.height()))
        back = self.back_rect()
        if not back.isNull():
            p.setPen(QtGui.QPen(t.color('control-border'), 1))
            p.setBrush(t.color('hover') if self.hovered == 'back'
                       else Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(back, 9, 9)
            p.setPen(t.color('ink'))
            p.drawText(back, Qt.AlignmentFlag.AlignCenter, 'back to previous')


class CornerZone(QtWidgets.QWidget):
    """An area corner: dragging from here splits, joins, swaps or makes a
    new window (Blender's action zones)."""

    # 0 top-left, 1 top-right, 2 bottom-left, 3 bottom-right
    def __init__(self, area, corner):
        super().__init__(area)
        self.area = area
        self.corner = corner
        self.setFixedSize(CORNER, CORNER)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.hovered = False

    def place(self):
        w, h = self.area.width(), self.area.height()
        x = 0 if self.corner in (0, 2) else w - CORNER
        y = 0 if self.corner in (0, 1) else h - CORNER
        self.move(x, y)
        self.raise_()

    def enterEvent(self, e):
        self.hovered = True
        self.update()

    def leaveEvent(self, e):
        self.hovered = False
        self.update()

    def paintEvent(self, e):
        if not self.hovered:
            return
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        color = tm().color('accent')
        color.setAlpha(170)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        w = CORNER
        pts = {0: [(0, 0), (w, 0), (0, w)], 1: [(0, 0), (w, 0), (w, w)],
               2: [(0, 0), (0, w), (w, w)], 3: [(w, 0), (w, w), (0, w)]}
        p.drawPolygon(QtGui.QPolygonF(
            [QtCore.QPointF(*pt) for pt in pts[self.corner]]))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.area.screen.begin_corner(self.area, self.corner, e)
        else:
            self.area.screen.cancel_gesture()

    def mouseMoveEvent(self, e):
        self.area.screen.corner_move(e)

    def mouseReleaseEvent(self, e):
        self.area.screen.corner_release(e)


class EmptyArea(QtWidgets.QWidget):
    """A fresh area before a board is chosen for it."""

    def __init__(self, area):
        super().__init__()
        self.area = area
        layout = QtWidgets.QVBoxLayout(self)
        layout.addStretch()
        button = QtWidgets.QPushButton('choose a board for this area')
        button.clicked.connect(lambda: area.screen.board_menu(area))
        row = QtWidgets.QHBoxLayout()
        row.addStretch()
        row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)
        layout.addStretch()

    def paintEvent(self, e):
        QtGui.QPainter(self).fillRect(self.rect(), tm().color('canvas'))


class Overlay(QtWidgets.QWidget):
    """Previews for splits, joins and swaps, drawn over the areas."""

    def __init__(self, screen):
        super().__init__(screen)
        self.screen = screen
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.line = None      # (x0, y0, x1, y1) px
        self.dark = None      # QRect to darken (area being joined)
        self.mark = None      # QRect to outline (swap / new window target)

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        accent = tm().color('accent')
        if self.dark is not None:
            p.fillRect(self.dark, QtGui.QColor(0, 0, 0, 120))
        if self.mark is not None:
            p.setPen(QtGui.QPen(accent, 3))
            p.drawRect(self.mark.adjusted(1, 1, -2, -2))
        if self.line is not None:
            p.setPen(QtGui.QPen(accent, 2))
            p.drawLine(*[round(v) for v in self.line])

    def clear(self):
        self.line = self.dark = self.mark = None
        self.hide()


class Screen(QtWidgets.QWidget):
    """The main window's areas."""

    changed = QtCore.pyqtSignal()

    def __init__(self, parent, main_view):
        super().__init__(parent)
        self.main_view = main_view
        main_view.rb_screen = self
        self.areas = []
        self.maximized = None      # area shown alone
        self.saved_rects = None    # layout to go back to
        self.focus_mode = False
        self.border = None         # resizing: (axis, edges, start)
        self.gesture = None        # corner drag state
        self.split_mode = None     # interactive split from the area menu
        self.setMouseTracking(True)
        self.overlay = Overlay(self)
        self.overlay.hide()
        self.menu_host = MenuHost(self)
        first = self.add_area([0, 0, 1, 1])
        first.set_content(main_view)

    # ---------- basics ----------

    def add_area(self, rect, content=None):
        area = Area(self, rect)
        self.areas.append(area)
        area.set_content(content or EmptyArea(area))
        area.show()
        self.relayout()
        return area

    def relayout(self):
        for area in self.areas:
            visible = self.maximized is None or area is self.maximized
            area.setVisible(visible)
            if visible:
                area.setGeometry(self.rect() if self.maximized
                                 else area.pixel_rect())
                area.layout_children()
        self.overlay.setGeometry(self.rect())
        self.overlay.raise_()

    def resizeEvent(self, event):
        self.relayout()

    def paintEvent(self, event):
        QtGui.QPainter(self).fillRect(self.rect(), tm().color('surface'))

    def area_at(self, pos):
        for area in self.areas:
            if area.isVisible() and area.geometry().contains(pos):
                return area
        return None

    def area_of(self, board):
        for area in self.areas:
            if getattr(area.content, 'board', None) is board:
                return area
        return None

    def boards_shown(self):
        return [a.content.board for a in self.areas
                if hasattr(a.content, 'board')]

    def notify(self, text):
        self.main_view.rb_notify(text)

    # ---------- borders (resizing) ----------

    def border_at(self, pos):
        """The border under a gap point: ('x' or 'y', coordinate)."""
        w, h = max(self.width(), 1), max(self.height(), 1)
        fx, fy = pos.x() / w, pos.y() / h
        tol_x, tol_y = (GAP + 2) / w, (GAP + 2) / h
        for area in self.areas:
            x0, y0, x1, y1 = area.rect_
            if y0 - EPS <= fy <= y1 + EPS:
                for c in (x0, x1):
                    if EPS < c < 1 - EPS and abs(fx - c) <= tol_x:
                        return 'x', c, fy
            if x0 - EPS <= fx <= x1 + EPS:
                for c in (y0, y1):
                    if EPS < c < 1 - EPS and abs(fy - c) <= tol_y:
                        return 'y', c, fx
        return None

    def edges_on(self, axis, c, at, connected=True):
        """Area edges lying on the line axis=c: [(area, index)] where index
        is 0/2 (low side) or 1/3 (high side) of rect_. With `connected`,
        only the chain of edges touching the point `at` along the line."""
        lo, hi = (0, 2) if axis == 'x' else (1, 3)
        span_lo, span_hi = (1, 3) if axis == 'x' else (0, 2)
        edges = []
        for area in self.areas:
            r = area.rect_
            if near(r[lo], c):
                edges.append((area, lo, r[span_lo], r[span_hi]))
            if near(r[hi], c):
                edges.append((area, hi, r[span_lo], r[span_hi]))
        if not connected:
            return [(a, i) for a, i, _, _ in edges]
        # Grow the chain of overlapping spans from the point
        start, end = at, at
        chosen = []
        grew = True
        while grew:
            grew = False
            for edge in edges:
                if edge in chosen:
                    continue
                if edge[2] <= end + EPS and edge[3] >= start - EPS:
                    chosen.append(edge)
                    start, end = min(start, edge[2]), max(end, edge[3])
                    grew = True
        return [(a, i) for a, i, _, _ in chosen]

    def move_edges(self, axis, edges, value):
        size = self.width() if axis == 'x' else self.height()
        margin = MIN_SIZE / max(size, 1)
        lo, hi = (0, 2) if axis == 'x' else (1, 3)
        # Keep every touched area at least MIN_SIZE wide/tall
        low_limit, high_limit = margin, 1 - margin
        for area, index in edges:
            r = area.rect_
            if index == hi:   # this area's far edge: can't pass its near one
                low_limit = max(low_limit, r[lo] + margin)
            else:
                high_limit = min(high_limit, r[hi] - margin)
        if low_limit > high_limit:
            return
        value = min(max(value, low_limit), high_limit)
        for area, index in edges:
            area.rect_[index] = value
        self.relayout()

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self.split_mode:
            self.split_preview(pos)
            return
        if self.border is not None:
            axis, edges, _ = self.border
            size = self.width() if axis == 'x' else self.height()
            value = (pos.x() if axis == 'x' else pos.y()) / max(size, 1)
            if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
                snap = min(SNAPS, key=lambda s: abs(s - value))
                if abs(snap - value) < 0.04:
                    value = snap
            self.move_edges(axis, edges, value)
            return
        hit = self.border_at(pos)
        self.setCursor(Qt.CursorShape.SplitHCursor if hit and hit[0] == 'x'
                       else Qt.CursorShape.SplitVCursor if hit
                       else Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, e):
        if self.split_mode:
            if e.button() == Qt.MouseButton.LeftButton:
                self.finish_split()
            else:
                self.cancel_gesture()
            return
        hit = self.border_at(e.position())
        if hit is None:
            return
        axis, c, at = hit
        if e.button() == Qt.MouseButton.RightButton:
            self.border_menu(axis, c, at, e.position())
            return
        shift = e.modifiers() & Qt.KeyboardModifier.ShiftModifier
        self.border = (axis, self.edges_on(axis, c, at, not shift), c)

    def mouseReleaseEvent(self, e):
        if self.border is not None:
            self.border = None
            self.changed.emit()

    # ---------- corners (split, join, swap, new window) ----------

    def begin_corner(self, area, corner, event):
        self.gesture = {
            'area': area, 'corner': corner,
            'start': self.mapFromGlobal(event.globalPosition().toPoint()),
            'mods': event.modifiers(), 'action': None}

    def corner_move(self, event):
        g = self.gesture
        if g is None:
            return
        pos = self.mapFromGlobal(event.globalPosition().toPoint())
        delta = pos - g['start']
        if g['action'] is None and max(abs(delta.x()),
                                       abs(delta.y())) < DRAG_START:
            return
        area = g['area']
        over = self.area_at(pos)
        overlay = self.overlay
        overlay.line = overlay.dark = overlay.mark = None
        mods = g['mods']
        if mods & Qt.KeyboardModifier.ShiftModifier:
            g['action'] = ('window',)
            overlay.mark = area.geometry()
        elif mods & Qt.KeyboardModifier.ControlModifier:
            g['action'] = ('swap', over) if over and over is not area \
                else ('none',)
            if over and over is not area:
                overlay.mark = over.geometry()
        elif over is area or over is None:
            # Split: left/right drags split vertically, up/down
            # horizontally, at the pointer
            axis = 'x' if abs(delta.x()) >= abs(delta.y()) else 'y'
            g['action'] = ('split', axis, pos)
            rect = area.geometry()
            if axis == 'x':
                overlay.line = (pos.x(), rect.top(), pos.x(), rect.bottom())
            else:
                overlay.line = (rect.left(), pos.y(), rect.right(), pos.y())
        elif self.can_join(area, over):
            g['action'] = ('join', over)
            overlay.dark = over.geometry()
        else:
            # Into the middle of a non-neighbour: replace it
            g['action'] = ('replace', over)
            overlay.mark = over.geometry()
        overlay.show()
        overlay.raise_()
        overlay.update()

    def corner_release(self, event):
        g = self.gesture
        self.overlay.clear()
        self.gesture = None
        if not g or not g['action']:
            return
        action, area = g['action'], g['area']
        if action[0] == 'split':
            self.split(area, action[1], action[2], new_side=g['corner'])
        elif action[0] == 'join':
            self.join(area, action[1])
        elif action[0] == 'swap':
            self.swap(area, action[1])
        elif action[0] == 'window':
            self.to_window(area)
        elif action[0] == 'replace':
            self.replace(area, action[1])

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and (self.gesture
                                                 or self.split_mode):
            self.cancel_gesture()
            return
        if event.key() == Qt.Key.Key_Tab and self.split_mode:
            mode = self.split_mode
            mode['axis'] = 'y' if mode['axis'] == 'x' else 'x'
            self.split_preview(self.mapFromGlobal(QtGui.QCursor.pos()))
            return
        super().keyPressEvent(event)

    # ---------- operations ----------

    def split(self, area, axis, pos, new_side=None):
        """Split an area at a point (px). The new, empty area goes on the
        side of the corner the drag started from."""
        r = area.rect_
        size = self.width() if axis == 'x' else self.height()
        f = (pos.x() if axis == 'x' else pos.y()) / max(size, 1)
        lo, hi = (0, 2) if axis == 'x' else (1, 3)
        margin = MIN_SIZE / max(size, 1)
        if not r[lo] + margin <= f <= r[hi] - margin:
            self.notify('not enough room to split there')
            return None
        new_rect = list(r)
        high_side = (new_side in (1, 3)) if axis == 'x' \
            else (new_side in (2, 3))
        if new_side is None:
            high_side = True
        if high_side:
            new_rect[lo] = f
            r[hi] = f
        else:
            new_rect[hi] = f
            r[lo] = f
        new = self.add_area(new_rect)
        self.relayout()
        self.changed.emit()
        return new

    def neighbour_side(self, a, b):
        """How b touches a along a full shared edge: 'left', 'right', 'up',
        'down', or None."""
        ra, rb = a.rect_, b.rect_
        if near(ra[1], rb[1]) and near(ra[3], rb[3]):
            if near(ra[2], rb[0]):
                return 'right'
            if near(ra[0], rb[2]):
                return 'left'
        if near(ra[0], rb[0]) and near(ra[2], rb[2]):
            if near(ra[3], rb[1]):
                return 'down'
            if near(ra[1], rb[3]):
                return 'up'
        return None

    def can_join(self, a, b):
        return a is not b and self.neighbour_side(a, b) is not None

    def neighbour(self, area, side):
        for other in self.areas:
            if other is not area and self.neighbour_side(area, other) == side:
                return other
        return None

    def join(self, keep, absorb):
        """`keep` grows over `absorb`, whose board is closed (sub boards
        stay in the layers menu)."""
        if not self.can_join(keep, absorb):
            self.notify('areas join only when they share a whole edge')
            return
        if absorb.is_main():
            # The main board always has an area; swap so it survives
            self.swap(keep, absorb)
        r, o = keep.rect_, absorb.rect_
        keep.rect_ = [min(r[0], o[0]), min(r[1], o[1]),
                      max(r[2], o[2]), max(r[3], o[3])]
        self.remove_area(absorb)
        self.relayout()
        self.changed.emit()

    def remove_area(self, area):
        if self.maximized is area:
            self.toggle_maximize(area)
        self.close_content(area)
        self.areas.remove(area)
        area.setParent(None)
        area.deleteLater()

    def close_content(self, area):
        content = area.content
        if hasattr(content, 'release'):
            content.release()   # caches a sub board's layout
        area.content = None

    def swap(self, a, b):
        ca, cb = a.content, b.content
        for widget in (ca, cb):
            widget.setParent(None)
        a.content = b.content = None
        a.set_content(cb)
        b.set_content(ca)
        self.changed.emit()

    def replace(self, source, target):
        """Show the source area's board in the target area instead, and
        give the source area's space to a neighbour (Blender's docking)."""
        if target.is_main():
            self.swap(source, target)
            return
        content = source.content
        source.content = None
        content.setParent(None)
        self.close_content(target)
        target.set_content(content)
        source.set_content(EmptyArea(source))
        self.close_area(source)

    def close_area(self, area):
        """Close an area by joining it into a neighbour."""
        if len(self.areas) == 1:
            return
        if area.is_main():
            other = next(a for a in self.areas if a is not area)
            self.swap(area, other)
            area = other
        for side in ('left', 'right', 'up', 'down'):
            other = self.neighbour(area, side)
            if other is not None:
                self.join(other, area)
                return
        # No full-edge neighbour: leave it, but empty
        self.close_content(area)
        area.set_content(EmptyArea(area))

    def to_window(self, area):
        """Duplicate Area into New Window: a sub board moves to a window
        of its own (there's one main board view, so it stays)."""
        content = area.content
        board = getattr(content, 'board', None)
        if board is None:
            self.notify('only sub boards can go in their own window')
            return
        manager = self.main_view.subboards
        self.close_area_keeping(area)
        manager.pop_out(board)

    def close_area_keeping(self, area):
        """Close an area whose board is moving elsewhere."""
        content = area.content
        if hasattr(content, 'release'):
            content.release()
        area.content = None
        area.set_content(EmptyArea(area))
        self.close_area(area)

    def toggle_maximize(self, area=None):
        if self.maximized is not None:
            self.maximized = None
            self.focus_mode = False
            for a in self.areas:
                a.layout_children()
        elif area is not None:
            self.maximized = area
        self.relayout()
        for a in self.areas:
            a.header.update()

    def toggle_focus(self, area):
        if self.focus_mode:
            self.toggle_maximize()
            return
        if self.maximized is None:
            self.maximized = area
        self.focus_mode = True
        self.relayout()

    # ---------- showing boards ----------

    def show_board(self, board, near_area=None):
        """Show a sub board in an area: where it already is, else in a
        new area split off the right of the main board's area."""
        area = self.area_of(board)
        if area is not None:
            if self.maximized is not None and self.maximized is not area:
                self.toggle_maximize()
            return area
        empty = next((a for a in self.areas
                      if isinstance(a.content, EmptyArea)), None)
        if empty is None:
            base = near_area or self.main_area()
            rect = base.pixel_rect()
            empty = self.split(base, 'x', QtCore.QPointF(
                rect.center().x(), rect.center().y()))
            if empty is None:   # too small: reuse the last sub board area
                empty = next((a for a in reversed(self.areas)
                              if not a.is_main()), None)
                if empty is None:
                    return None
                self.close_content(empty)
        from beeref.rboard.subboard_window import DockedBoard
        empty.set_content(DockedBoard(self.main_view.subboards, board, empty))
        if self.maximized is not None:
            self.toggle_maximize()
        self.changed.emit()
        return empty

    def main_area(self):
        return next(a for a in self.areas if a.is_main())

    # ---------- menus ----------

    def board_menu(self, area):
        """Which board an area shows (Blender's editor type menu)."""
        manager = self.main_view.subboards
        entries = [('label', 'show in this area')]
        main_area = self.main_area()
        entries.append(('item', self.main_view_title(),
                        lambda: self.swap(area, main_area)
                        if area is not main_area else None,
                        {'icon': 'image', 'checked': area.is_main()}))
        for board in manager.tree():
            shown = self.area_of(board)
            entries.append((
                'item', board.title,
                lambda b=board: self.put_board(area, b),
                {'indent': board.depth() + 1,
                 'checked': shown is area,
                 'hint': 'in another area' if shown and shown is not area
                 else ('window' if board.window else '')}))
        entries += [('sep',),
                    ('action', 'new_subboard', 'new sub board…'),
                    ('sep',), ('label', 'area')]
        entries += self.area_entries(area)
        menu = OverlayMenu(self, entries, min_width=240)
        self.menu_host.show(menu, area.mapTo(self, QtCore.QPoint(
            6, area.header.height())))

    def main_view_title(self):
        import os
        filename = self.main_view.filename
        return os.path.basename(filename) if filename else 'main board'

    def put_board(self, area, board):
        """Show a board in this area (moving it from wherever it is)."""
        current = self.area_of(board)
        if current is area:
            return
        if current is not None:
            self.swap(current, area)
            return
        if board.window is not None:  # in a window: bring it in
            board.window.close()
        if area.is_main():
            new = self.split(area, 'x', QtCore.QPointF(
                area.pixel_rect().center()))
            if new is None:
                return
            area = new
        self.close_content(area)
        from beeref.rboard.subboard_window import DockedBoard
        area.set_content(DockedBoard(self.main_view.subboards, board, area))
        self.changed.emit()

    def area_entries(self, area):
        maximized = self.maximized is not None
        return [
            ('item', 'back to previous' if maximized
             else 'toggle maximize area',
             lambda: self.toggle_maximize(area), {'kbd': 'Ctrl+Space'}),
            ('item', 'focus mode', lambda: self.toggle_focus(area),
             {'kbd': 'Ctrl+Alt+Space'}),
            ('item', 'vertical split',
             lambda: self.start_split(area, 'x')),
            ('item', 'horizontal split',
             lambda: self.start_split(area, 'y')),
            ('item', 'duplicate area into new window',
             lambda: self.to_window(area),
             {'enabled': hasattr(area.content, 'board')}),
            ('item', 'close area', lambda: self.close_area(area),
             {'enabled': len(self.areas) > 1}),
        ]

    def border_menu(self, axis, c, at, pos):
        """Area options for a border (Blender: right-click a border)."""
        lo, hi = (0, 2) if axis == 'x' else (1, 3)
        point = QtCore.QPointF(pos)
        before = after = None
        for area in self.areas:
            r = area.rect_
            span = (r[1], r[3]) if axis == 'x' else (r[0], r[2])
            if not span[0] - EPS <= at <= span[1] + EPS:
                continue
            if near(r[hi], c):
                before = area
            elif near(r[lo], c):
                after = area
        first, second = ('left', 'right') if axis == 'x' else ('up', 'down')
        entries = [('label', 'area options'),
                   ('item', 'vertical split',
                    lambda: self.start_split(None, 'x')),
                   ('item', 'horizontal split',
                    lambda: self.start_split(None, 'y'))]
        if before and after:
            entries += [
                ('item', f'join {second}', lambda: self.join(before, after),
                 {'enabled': self.can_join(before, after)}),
                ('item', f'join {first}', lambda: self.join(after, before),
                 {'enabled': self.can_join(before, after)}),
                ('item', 'swap areas', lambda: self.swap(before, after)),
            ]
        menu = OverlayMenu(self, entries, min_width=200)
        self.menu_host.show(menu, point.toPoint())

    def area_menu(self, area, global_pos):
        menu = OverlayMenu(self, [('label', 'area')]
                           + self.area_entries(area), min_width=220)
        self.menu_host.show(menu, self.mapFromGlobal(global_pos.toPoint()))

    # ---------- interactive split (from the menus) ----------

    def start_split(self, area, axis):
        """Show a split line that follows the pointer; click to split the
        area under it, Tab switches direction, Esc cancels."""
        self.split_mode = {'axis': axis}
        self.setFocus()
        self.grabMouse()
        self.grabKeyboard()
        self.split_preview(self.mapFromGlobal(QtGui.QCursor.pos()))

    def split_preview(self, pos):
        pos = QtCore.QPointF(pos)
        area = self.area_at(pos.toPoint())
        self.overlay.line = None
        if area is not None:
            rect = area.geometry()
            if self.split_mode['axis'] == 'x':
                self.overlay.line = (pos.x(), rect.top(), pos.x(),
                                     rect.bottom())
            else:
                self.overlay.line = (rect.left(), pos.y(), rect.right(),
                                     pos.y())
        self.split_mode['area'] = area
        self.split_mode['pos'] = pos
        self.overlay.show()
        self.overlay.raise_()
        self.overlay.update()

    def finish_split(self):
        mode = self.split_mode
        self.release_split_grab()
        if mode and mode.get('area') is not None:
            self.split(mode['area'], mode['axis'], mode['pos'])

    def release_split_grab(self):
        self.releaseMouse()
        self.releaseKeyboard()
        self.split_mode = None
        self.overlay.clear()

    def cancel_gesture(self):
        if self.split_mode:
            self.release_split_grab()
        self.gesture = None
        self.overlay.clear()

    # ---------- saving ----------

    def snapshot(self, kept):
        """The layout for the board file: rects and what each shows
        ('main', an index into the kept boards, or None)."""
        out = []
        for area in self.areas:
            board = getattr(area.content, 'board', None)
            if area.is_main():
                shows = 'main'
            elif board is not None and board in kept:
                shows = kept.index(board)
            else:
                shows = None
            out.append({'rect': [round(v, 5) for v in area.rect_],
                        'shows': shows})
        return out

    def restore(self, layout, kept):
        """Rebuild areas from a snapshot (after kept boards are back)."""
        if not layout or not any(a.get('shows') == 'main' for a in layout):
            return
        for area in list(self.areas):
            if not area.is_main():
                self.remove_area(area)
        main_area = self.main_area()
        from beeref.rboard.subboard_window import DockedBoard
        for entry in layout:
            rect = [float(v) for v in entry['rect']]
            shows = entry.get('shows')
            if shows == 'main':
                main_area.rect_ = rect
                continue
            area = self.add_area(rect)
            if isinstance(shows, int) and 0 <= shows < len(kept) \
                    and kept[shows] is not None:
                area.set_content(DockedBoard(self.main_view.subboards,
                                             kept[shows], area))
        self.relayout()
