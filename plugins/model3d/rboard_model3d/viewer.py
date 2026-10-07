# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""The 3D viewport and its window.

Controls follow Blender's defaults and only work while the viewer has
focus: middle-drag orbits, Shift+middle pans, Ctrl+middle or the wheel
zooms, numpad 1/3/7 (Ctrl: opposite) 2/4/6/8 9 5 . and Home, ` for the
view menu. Ctrl+right-drag turns the lights or environment.

Posing works like Blender's pose mode: click bones (Shift adds, A all,
Alt+A none), G moves, R rotates (R again: trackball), X/Y/Z lock to an
axis (again: the bone's own), type a number, click or Enter confirms,
right-click or Esc cancels. Alt+G / Alt+R clear, Alt+B shows or hides
bones, Ctrl+Z / Ctrl+Shift+Z undo and redo."""

import copy
import math
import re

import numpy as np
from PyQt6 import QtCore, QtGui, QtOpenGLWidgets, QtWidgets
from PyQt6.QtCore import Qt

from . import env as envlib
from .model import (decompose, lens_to_fov, orthographic, perspective,
                    quat_axis_angle, quat_mul, quat_normalize)
from .render import Look, Renderer

PICK_PX = 12
GIZMO_PX = 70
AXES = np.eye(3)
AXIS_COLORS = ('#e8505b', '#7bc043', '#4a90e2')
SIDE_NAMES = [(r'\.L$', '.R'), (r'\.R$', '.L'), (r'_L$', '_R'),
              (r'_R$', '_L'), (r'\.l$', '.r'), (r'\.r$', '.l'),
              (r'_l$', '_r'), (r'_r$', '_l'), (r'Left', 'Right'),
              (r'Right', 'Left'), (r'left', 'right'), (r'right', 'left'),
              (r'^l_', 'r_'), (r'^r_', 'l_'), (r'^L_', 'R_'), (r'^R_', 'L_')]


def conj(q):
    return np.array([-q[0], -q[1], -q[2], q[3]])


def rot_part(m):
    return decompose(m)[1]


def mirror_name(name):
    for pattern, swap in SIDE_NAMES:
        if re.search(pattern, name):
            return re.sub(pattern, swap, name, count=1)
    return None


# ---------- camera ----------

class Camera:
    """Turntable camera around a target, as Blender's viewport."""

    def __init__(self):
        self.target = np.zeros(3)
        self.dist = 5.0
        self.yaw = math.radians(30)
        self.pitch = math.radians(15)
        self.lens = 50.0
        self.ortho = False
        self.auto_ortho = False     # switched to ortho by an axis view
        self.view_name = ''

    def rotation(self):
        cy, sy = math.cos(self.yaw), math.sin(self.yaw)
        cp, sp = math.cos(-self.pitch), math.sin(-self.pitch)
        ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
        rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])
        return ry @ rx

    def eye(self):
        return self.target + self.rotation() @ np.array([0, 0, self.dist])

    def view(self):
        m = np.eye(4)
        m[:3, :3] = self.rotation()
        m[:3, 3] = self.eye()
        return np.linalg.inv(m)

    @property
    def fov(self):
        return lens_to_fov(self.lens)

    def proj(self, aspect, extent=1.0):
        near = max(self.dist * 0.002, 1e-4)
        far = self.dist * 20 + extent * 10
        if self.ortho:
            height = 2 * self.dist * math.tan(self.fov / 2)
            return orthographic(height, aspect, -far, far)
        return perspective(self.fov, aspect, near, far)

    def units_per_px(self, depth, height_px):
        d = self.dist if self.ortho else depth
        return 2 * d * math.tan(self.fov / 2) / max(height_px, 1)

    def state(self):
        return {'target': self.target.tolist(), 'dist': self.dist,
                'yaw': self.yaw, 'pitch': self.pitch, 'lens': self.lens,
                'ortho': self.ortho}

    def restore(self, s):
        self.target = np.array(s.get('target', [0, 0, 0]), float)
        self.dist = float(s.get('dist', self.dist))
        self.yaw = float(s.get('yaw', self.yaw))
        self.pitch = float(s.get('pitch', self.pitch))
        self.lens = float(s.get('lens', self.lens))
        self.ortho = bool(s.get('ortho', False))


VIEWS = {   # Blender numpad: name, yaw, pitch
    'front': ('Front', 0.0, 0.0), 'back': ('Back', math.pi, 0.0),
    'right': ('Right', math.pi / 2, 0.0), 'left': ('Left', -math.pi / 2, 0.0),
    'top': ('Top', 0.0, math.pi / 2), 'bottom': ('Bottom', 0.0, -math.pi / 2),
}


# ---------- the viewport ----------

class Viewport(QtOpenGLWidgets.QOpenGLWidget):
    changed = QtCore.pyqtSignal()        # anything shown changed
    pose_changed = QtCore.pyqtSignal()
    status = QtCore.pyqtSignal(str)

    def __init__(self, model, environment=None, emulate_3button=False,
                 parent=None):
        super().__init__(parent)
        fmt = QtGui.QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QtGui.QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        fmt.setDepthBufferSize(24)
        fmt.setSamples(4)
        self.setFormat(fmt)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(320, 240)
        self.model = model
        self.environment = environment or envlib.studio()
        self.emulate_3button = emulate_3button
        self.camera = Camera()
        self.look = Look()
        self.pose = {}                 # node index -> (move, quat)
        self.selected = []             # node indices, last = active
        self.show_bones = model.rigged
        self.gizmo = 'off'             # off, move, rotate
        self.ctx = None
        self.renderer = None
        self.drag = None
        self.modal = None              # active G / R
        self.undo = []
        self.redo = []
        self._globals = None
        self.gl_error = None
        self.frame_all()

    # -- GL --

    def initializeGL(self):
        try:
            import moderngl
            self.ctx = moderngl.create_context()
            self.renderer = Renderer(self.ctx)
            self.renderer.set_model(self.model)
            self.renderer.set_env(self.environment)
            self.gl_error = None
        except Exception as e:   # no OpenGL 3.3
            self.gl_error = str(e)
            self.ctx = self.renderer = None

    def paintGL(self):
        if self.renderer is None:
            p = QtGui.QPainter(self)
            p.fillRect(self.rect(), QtGui.QColor('#202022'))
            p.setPen(QtGui.QColor('#ddd'))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "3D needs OpenGL 3.3, which isn't available here."
                       f'\n{self.gl_error or ""}')
            p.end()
            return
        ratio = self.devicePixelRatioF()
        w, h = int(self.width() * ratio), int(self.height() * ratio)
        fbo = self.ctx.detect_framebuffer(self.defaultFramebufferObject())
        g = self.globals()
        self.renderer.render(fbo, (w, h), self.camera.view(),
                             self.camera.proj(w / max(h, 1), self.extent),
                             self.camera.eye(), g,
                             self.model.skin_matrices(g), self.look,
                             self.bounds)
        self.renderer.hand_back()
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        self.paint_overlays(p)
        p.end()

    # -- model state --

    def globals(self):
        if self._globals is None:
            self._globals = self.model.globals(self.pose)
        return self._globals

    def set_pose(self, pose, record=False):
        if record:
            self.push_undo()
        self.pose = pose
        self._globals = None
        self.pose_changed.emit()
        self.update()

    def push_undo(self):
        self.undo.append(copy.deepcopy(self.pose))
        self.undo = self.undo[-100:]
        self.redo.clear()

    def frame_all(self, nodes=None):
        lo, hi = self.model.bounds()
        self.bounds = (lo, hi)
        self.extent = float(np.linalg.norm(hi - lo)) or 1.0
        if nodes:
            g = self.globals()
            pts = np.array([g[n][:3, 3] for n in nodes])
            lo, hi = pts.min(0), pts.max(0)
            size = max(float(np.linalg.norm(hi - lo)), self.extent * 0.15)
        else:
            size = self.extent
        self.camera.target = (lo + hi) / 2
        self.camera.dist = size / 2 / math.tan(self.camera.fov / 2) * 1.15
        self.update()

    # -- projection helpers --

    def view_proj(self):
        w, h = self.width(), self.height()
        return self.camera.proj(w / max(h, 1), self.extent) @ \
            self.camera.view()

    def project(self, points):
        """World points -> (screen xy in widget px, depth, in front)."""
        pts = np.atleast_2d(np.asarray(points, float))
        clip = np.c_[pts, np.ones(len(pts))] @ self.view_proj().T
        w = clip[:, 3:4]
        ok = (w[:, 0] > 1e-9) if not self.camera.ortho else \
            np.ones(len(pts), bool)
        ndc = clip[:, :3] / np.where(np.abs(w) > 1e-9, w, 1e-9)
        x = (ndc[:, 0] * 0.5 + 0.5) * self.width()
        y = (1 - (ndc[:, 1] * 0.5 + 0.5)) * self.height()
        view_pts = np.c_[pts, np.ones(len(pts))] @ self.camera.view().T
        return np.c_[x, y], -view_pts[:, 2], ok

    # -- bones --

    def segments(self):
        return self.model.bone_segments(self.globals())

    def bone_at(self, pos):
        best, best_d = None, PICK_PX
        p = np.array([pos.x(), pos.y()], float)
        for j, head, tail in self.segments():
            (a, b), _, ok = self.project([head, tail])
            if not ok.all():
                continue
            ab = b - a
            t = np.clip(np.dot(p - a, ab) / max(np.dot(ab, ab), 1e-9), 0, 1)
            d = np.linalg.norm(p - (a + t * ab))
            if d < best_d:
                best, best_d = j, d
        return best

    # -- drawing on top --

    def paint_overlays(self, p):
        self.paint_hud(p)
        if self.show_bones and self.model.joints:
            self.paint_bones(p)
        if self.gizmo != 'off' and self.selected and not self.modal:
            self.paint_gizmo(p)

    def paint_hud(self, p):
        name = self.camera.view_name or 'User'
        kind = 'Orthographic' if self.camera.ortho else 'Perspective'
        p.setPen(QtGui.QColor(220, 220, 220, 200))
        font = p.font()
        font.setPixelSize(13)
        p.setFont(font)
        p.drawText(12, 22, f'{name} {kind}')
        if self.modal:
            p.drawText(12, self.height() - 14, self.modal_text())

    def paint_bones(self, p):
        g = self.globals()
        active = self.selected[-1] if self.selected else None
        for j, head, tail in self.segments():
            axis = tail - head
            length = np.linalg.norm(axis)
            if length < 1e-9:
                continue
            rot = g[j][:3, :3]
            u = rot[:, 0] / (np.linalg.norm(rot[:, 0]) or 1)
            v = rot[:, 2] / (np.linalg.norm(rot[:, 2]) or 1)
            mid = head + axis * 0.15
            r = length * 0.1
            ring = [mid + u * r, mid + v * r, mid - u * r, mid - v * r]
            pts, _, ok = self.project([head, tail] + ring)
            if not ok.all():
                continue
            qp = [QtCore.QPointF(*xy) for xy in pts]
            if j == active:
                line, fill = QtGui.QColor('#ffd17a'), QtGui.QColor(
                    255, 190, 90, 110)
            elif j in self.selected:
                line, fill = QtGui.QColor('#7ab8ff'), QtGui.QColor(
                    90, 150, 255, 90)
            else:
                line, fill = QtGui.QColor(30, 30, 30, 220), QtGui.QColor(
                    200, 200, 200, 70)
            p.setPen(QtGui.QPen(line, 1.4))
            p.setBrush(fill)
            for k in range(4):
                a, b = qp[2 + k], qp[2 + (k + 1) % 4]
                p.drawPolygon(QtGui.QPolygonF([qp[0], a, b]))
                p.drawPolygon(QtGui.QPolygonF([qp[1], a, b]))

    def gizmo_center(self):
        return self.globals()[self.selected[-1]][:3, 3]

    def gizmo_world_len(self):
        center = self.gizmo_center()
        _, depth, _ = self.project([center])
        return self.camera.units_per_px(depth[0], self.height()) * GIZMO_PX

    def gizmo_shapes(self):
        """[(axis index, [screen points])] for the gizmo's handles."""
        c = self.gizmo_center()
        length = self.gizmo_world_len()
        out = []
        for i in range(3):
            if self.gizmo == 'move':
                pts, _, _ = self.project([c, c + AXES[i] * length])
            else:
                a, b = AXES[(i + 1) % 3], AXES[(i + 2) % 3]
                t = np.linspace(0, 2 * math.pi, 65)
                ring = c + length * (np.cos(t)[:, None] * a +
                                     np.sin(t)[:, None] * b)
                pts, _, _ = self.project(ring)
            out.append((i, pts))
        return out

    def paint_gizmo(self, p):
        for i, pts in self.gizmo_shapes():
            p.setPen(QtGui.QPen(QtGui.QColor(AXIS_COLORS[i]), 2.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline(QtGui.QPolygonF(
                [QtCore.QPointF(*xy) for xy in pts]))
            if self.gizmo == 'move':
                p.setBrush(QtGui.QColor(AXIS_COLORS[i]))
                p.drawEllipse(QtCore.QPointF(*pts[-1]), 5, 5)

    def gizmo_hit(self, pos):
        p = np.array([pos.x(), pos.y()], float)
        best, best_d = None, PICK_PX
        for i, pts in self.gizmo_shapes():
            for a, b in zip(pts[:-1], pts[1:]):
                ab = b - a
                t = np.clip(np.dot(p - a, ab) / max(np.dot(ab, ab), 1e-9),
                            0, 1)
                d = np.linalg.norm(p - (a + t * ab))
                if d < best_d:
                    best, best_d = i, d
        return best

    # -- mouse --

    def _button(self, e):
        """Which camera action a press means: orbit, pan, zoom, light."""
        b, mods = e.button(), e.modifiers()
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        middle = b == Qt.MouseButton.MiddleButton or (
            self.emulate_3button and alt and b == Qt.MouseButton.LeftButton)
        if middle:
            return 'pan' if shift else 'zoom' if ctrl else 'orbit'
        if b == Qt.MouseButton.RightButton and ctrl:
            return 'light'
        return None

    def mousePressEvent(self, e):
        self.setFocus()
        pos = e.position()
        if self.modal:
            if e.button() == Qt.MouseButton.LeftButton:
                self.confirm_modal()
            elif e.button() == Qt.MouseButton.RightButton:
                self.cancel_modal()
            return
        action = self._button(e)
        if action:
            self.drag = (action, pos)
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self.gizmo != 'off' and self.selected:
            axis = self.gizmo_hit(pos)
            if axis is not None:
                self.start_modal('G' if self.gizmo == 'move' else 'R', pos,
                                 axis=(axis, 'global'), by_drag=True)
                return
        if not (self.show_bones and self.model.joints):
            return
        bone = self.bone_at(pos)
        shift = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if bone is None:
            if not shift:
                self.selected = []
        elif shift:
            if bone in self.selected and self.selected[-1] == bone:
                self.selected.remove(bone)
            else:
                if bone in self.selected:
                    self.selected.remove(bone)
                self.selected.append(bone)
        else:
            self.selected = [bone]
        self.changed.emit()
        self.update()

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self.modal:
            self.update_modal(pos, e.modifiers())
            return
        if not self.drag:
            return
        action, last = self.drag
        dx, dy = pos.x() - last.x(), pos.y() - last.y()
        self.drag = (action, pos)
        cam = self.camera
        if action == 'orbit':
            cam.yaw -= dx * 0.008
            cam.pitch = max(-math.pi / 2, min(math.pi / 2,
                                              cam.pitch + dy * 0.008))
            if cam.auto_ortho:
                cam.ortho = cam.auto_ortho = False
            cam.view_name = ''
        elif action == 'pan':
            rot = cam.rotation()
            scale = cam.units_per_px(cam.dist, self.height())
            cam.target = cam.target - rot[:, 0] * dx * scale + \
                rot[:, 1] * dy * scale
        elif action == 'zoom':
            cam.dist *= math.exp(dy * 0.01)
        elif action == 'light':
            self.look.light_yaw += dx * 0.01
        self.changed.emit()
        self.update()

    def mouseReleaseEvent(self, e):
        if self.modal and self.modal.get('by_drag') and \
                e.button() == Qt.MouseButton.LeftButton:
            self.confirm_modal()
            return
        self.drag = None

    def wheelEvent(self, e):
        steps = e.angleDelta().y() / 120
        self.camera.dist *= 0.88 ** steps
        self.changed.emit()
        self.update()

    # -- keys (only while the viewer has focus) --

    def keyPressEvent(self, e):
        key, mods = e.key(), e.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        pad = bool(mods & Qt.KeyboardModifier.KeypadModifier)
        if self.modal:
            self.modal_key(e)
            return
        if pad and key in (Qt.Key.Key_1, Qt.Key.Key_3, Qt.Key.Key_7):
            name = {Qt.Key.Key_1: ('front', 'back'),
                    Qt.Key.Key_3: ('right', 'left'),
                    Qt.Key.Key_7: ('top', 'bottom')}[key][1 if ctrl else 0]
            self.set_view(name)
        elif pad and key in (Qt.Key.Key_2, Qt.Key.Key_4, Qt.Key.Key_6,
                             Qt.Key.Key_8):
            step = math.radians(15)
            if key == Qt.Key.Key_4:
                self.camera.yaw -= step
            elif key == Qt.Key.Key_6:
                self.camera.yaw += step
            elif key == Qt.Key.Key_8:
                self.camera.pitch = min(math.pi / 2, self.camera.pitch + step)
            else:
                self.camera.pitch = max(-math.pi / 2,
                                        self.camera.pitch - step)
            self.camera.view_name = ''
        elif pad and key == Qt.Key.Key_9:
            self.camera.yaw += math.pi
            self.camera.pitch = -self.camera.pitch
            self.camera.view_name = {'Front': 'Back', 'Back': 'Front',
                                     'Right': 'Left', 'Left': 'Right',
                                     'Top': 'Bottom', 'Bottom': 'Top'}.get(
                self.camera.view_name, '')
        elif pad and key == Qt.Key.Key_5:
            self.camera.ortho = not self.camera.ortho
            self.camera.auto_ortho = False
        elif key == Qt.Key.Key_Home:
            self.frame_all()
        elif pad and key in (Qt.Key.Key_Period, Qt.Key.Key_Comma,
                             Qt.Key.Key_Delete):
            self.frame_all(self.selected or None)
        elif key in (Qt.Key.Key_QuoteLeft, Qt.Key.Key_AsciiTilde):
            self.view_menu()
        elif key == Qt.Key.Key_Z and ctrl:
            self.undo_redo(redo=shift)
        elif key == Qt.Key.Key_B and alt:
            self.show_bones = not self.show_bones
            self.changed.emit()
        elif not self.model.joints:
            super().keyPressEvent(e)
            return
        elif key == Qt.Key.Key_A and alt:
            self.selected = []
            self.changed.emit()
        elif key == Qt.Key.Key_A and not ctrl:
            self.selected = list(self.model.joints)
            self.changed.emit()
        elif key == Qt.Key.Key_G and alt:
            self.clear_selected(move=True)
        elif key == Qt.Key.Key_R and alt:
            self.clear_selected(rotate=True)
        elif key in (Qt.Key.Key_G, Qt.Key.Key_R) and self.selected:
            self.start_modal('G' if key == Qt.Key.Key_G else 'R',
                             self.mapFromGlobal(QtGui.QCursor.pos()).toPointF())
        else:
            super().keyPressEvent(e)
            return
        self.update()

    def set_view(self, name):
        label, yaw, pitch = VIEWS[name]
        cam = self.camera
        cam.yaw, cam.pitch, cam.view_name = yaw, pitch, label
        if not cam.ortho:
            cam.ortho = cam.auto_ortho = True
        self.changed.emit()
        self.update()

    def view_menu(self):
        menu = QtWidgets.QMenu(self)
        for key, label in (('front', 'Front  (Numpad 1)'),
                           ('back', 'Back  (Ctrl+Numpad 1)'),
                           ('right', 'Right  (Numpad 3)'),
                           ('left', 'Left  (Ctrl+Numpad 3)'),
                           ('top', 'Top  (Numpad 7)'),
                           ('bottom', 'Bottom  (Ctrl+Numpad 7)')):
            menu.addAction(label, lambda k=key: self.set_view(k))
        menu.addSeparator()
        menu.addAction('Frame all  (Home)', self.frame_all)
        menu.exec(QtGui.QCursor.pos())

    def undo_redo(self, redo=False):
        source, target = (self.redo, self.undo) if redo else \
            (self.undo, self.redo)
        if not source:
            return
        target.append(copy.deepcopy(self.pose))
        self.set_pose(source.pop())

    def clear_selected(self, move=False, rotate=False):
        targets = self.selected or list(self.model.joints)
        self.push_undo()
        pose = copy.deepcopy(self.pose)
        for j in targets:
            if j not in pose:
                continue
            t, q = pose[j]
            pose[j] = (np.zeros(3) if move else t,
                       np.array([0, 0, 0, 1.0]) if rotate else q)
        self.set_pose(pose)

    # -- G / R --

    def start_modal(self, kind, pos, axis=None, by_drag=False):
        if not self.selected:
            return
        g = self.globals()
        centers = [g[j][:3, 3] for j in self.selected]
        center = np.mean(centers, axis=0)
        (cxy,), (depth,), _ = self.project([center])
        self.modal = {'kind': kind, 'start': np.array([pos.x(), pos.y()]),
                      'pos': np.array([pos.x(), pos.y()]),
                      'center': center, 'center_xy': cxy, 'depth': depth,
                      'pose': copy.deepcopy(self.pose), 'axis': axis,
                      'typed': '', 'trackball': False, 'by_drag': by_drag}
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.update_modal(pos, Qt.KeyboardModifier.NoModifier)

    def modal_axis_vector(self, j):
        """The constraint axis for bone j in world space, or None."""
        axis = self.modal['axis']
        if axis is None:
            return None
        i, space = axis
        if space == 'global':
            return AXES[i]
        m = self.model.globals(self.modal['pose'])[j][:3, :3]
        v = m[:, i]
        return v / (np.linalg.norm(v) or 1)

    def modal_text(self):
        m = self.modal
        what = {'G': 'move', 'R': 'trackball' if m['trackball'] else
                'rotate'}[m['kind']]
        axis = ''
        if m['axis']:
            axis = f" · {'XYZ'[m['axis'][0]]} {m['axis'][1]}"
        typed = f" · {m['typed']}" if m['typed'] else ''
        return (f'{what}{axis}{typed}   ·   click or Enter confirms, '
                'right-click or Esc cancels, X/Y/Z lock')

    def modal_key(self, e):
        m = self.modal
        key = e.key()
        if key in (Qt.Key.Key_Escape,):
            self.cancel_modal()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.confirm_modal()
        elif key in (Qt.Key.Key_X, Qt.Key.Key_Y, Qt.Key.Key_Z):
            i = {Qt.Key.Key_X: 0, Qt.Key.Key_Y: 1, Qt.Key.Key_Z: 2}[key]
            if m['axis'] is None or m['axis'][0] != i:
                m['axis'] = (i, 'global')
            elif m['axis'][1] == 'global':
                m['axis'] = (i, 'local')
            else:
                m['axis'] = None
            m['trackball'] = False
        elif key == Qt.Key.Key_R and m['kind'] == 'R':
            m['trackball'] = not m['trackball']
            m['axis'] = None
        elif key == Qt.Key.Key_Backspace:
            m['typed'] = m['typed'][:-1]
        elif e.text() and e.text() in '0123456789.-':
            m['typed'] += e.text()
        self.update_modal(QtCore.QPointF(*m['pos']), e.modifiers())

    def typed_value(self):
        try:
            return float(self.modal['typed'])
        except ValueError:
            return None

    def update_modal(self, pos, mods):
        m = self.modal
        m['pos'] = np.array([pos.x(), pos.y()])
        delta = m['pos'] - m['start']
        start_pose = m['pose']
        g0 = self.model.globals(start_pose)
        pose = copy.deepcopy(start_pose)
        cam = self.camera
        rot = cam.rotation()
        right, up, toward = rot[:, 0], rot[:, 1], rot[:, 2]
        typed = self.typed_value()
        for j in self.selected:
            move, q = pose.get(j, (np.zeros(3), np.array([0, 0, 0, 1.0])))
            node = self.model.nodes[j]
            parent = g0[node.parent] if node.parent >= 0 else np.eye(4)
            frame = parent @ node.rest()        # bone rest space -> world
            if m['kind'] == 'G':
                axis = self.modal_axis_vector(j)
                scale = cam.units_per_px(m['depth'], self.height())
                world = (delta[0] * right - delta[1] * up) * scale
                if axis is not None:
                    if typed is not None:
                        world = axis * typed
                    else:
                        # Follow the mouse along the axis as drawn
                        (a, b), _, _ = self.project([m['center'],
                                                     m['center'] + axis])
                        sa = b - a
                        px = np.linalg.norm(sa)
                        amount = (np.dot(delta, sa / px) / px) if px > 1e-6 \
                            else 0.0
                        world = axis * amount
                elif typed is not None:
                    world = right * typed
                local = np.linalg.solve(frame[:3, :3], world)
                pose[j] = (np.asarray(move) + local, q)
            else:
                if m['trackball']:
                    a = quat_mul(quat_axis_angle(up, delta[0] * 0.01),
                                 quat_axis_angle(right, delta[1] * 0.01))
                else:
                    c = m['center_xy']
                    v0, v1 = m['start'] - c, m['pos'] - c
                    angle = math.atan2(v1[1], v1[0]) - math.atan2(v0[1], v0[0])
                    axis = self.modal_axis_vector(j)
                    if axis is None:
                        axis = toward
                    sign = 1 if np.dot(axis, toward) >= 0 else -1
                    angle = -angle * sign
                    if typed is not None:
                        angle = math.radians(typed)
                    a = quat_axis_angle(axis, angle)
                b = rot_part(frame)
                q_new = quat_mul(quat_mul(quat_mul(conj(b), a), b), q)
                pose[j] = (move, quat_normalize(q_new))
        self.pose = pose
        self._globals = None
        self.status.emit(self.modal_text())
        self.update()

    def confirm_modal(self):
        before = self.modal['pose']
        self.modal = None
        self.unsetCursor()
        self.undo.append(before)
        self.redo.clear()
        self.pose_changed.emit()
        self.status.emit('')
        self.update()

    def cancel_modal(self):
        self.pose = self.modal['pose']
        self.modal = None
        self._globals = None
        self.unsetCursor()
        self.status.emit('')
        self.update()

    # -- mirror --

    def mirror_pose(self):
        """Copy each selected bone's pose to the bone on the other side
        (all bones when none are selected), flipped across X."""
        names = {self.model.nodes[j].name: j for j in self.model.joints}
        targets = self.selected or list(self.model.joints)
        pose = copy.deepcopy(self.pose)
        done = 0
        for j in targets:
            other = mirror_name(self.model.nodes[j].name)
            k = names.get(other)
            if k is None:
                continue
            t, q = self.pose.get(j, (np.zeros(3), np.array([0, 0, 0, 1.0])))
            pose[k] = (np.array([-t[0], t[1], t[2]]),
                       np.array([q[0], -q[1], -q[2], q[3]]))
            done += 1
        if done:
            self.set_pose(pose, record=True)
        return done

    # -- state for cards --

    def pose_by_name(self):
        return {self.model.nodes[j].name: [list(map(float, t)),
                                           list(map(float, q))]
                for j, (t, q) in self.pose.items()}

    def pose_from_names(self, named):
        index = {n.name: i for i, n in enumerate(self.model.nodes)}
        return {index[name]: (np.array(t, float), np.array(q, float))
                for name, (t, q) in (named or {}).items() if name in index}

    def state(self):
        return {'camera': self.camera.state(),
                'pose': self.pose_by_name(),
                'look': {k: getattr(self.look, k) for k in (
                    'shading', 'wire', 'grid', 'shadow', 'lighting',
                    'light_yaw', 'strength', 'exposure', 'show_env')}}

    def restore(self, state):
        if not state:
            return
        self.camera.restore(state.get('camera', {}))
        for k, v in state.get('look', {}).items():
            if hasattr(self.look, k):
                setattr(self.look, k, v)
        self.pose = self.pose_from_names(state.get('pose'))
        self._globals = None
        self.update()

    # -- images --

    def render_image(self, long_side=2048, transparent=True):
        """The current view as a QImage, `long_side` px on its longer
        side, with the same framing."""
        if self.renderer is None:
            return None
        self.makeCurrent()
        try:
            aspect = self.width() / max(self.height(), 1)
            if aspect >= 1:
                w, h = long_side, max(1, round(long_side / aspect))
            else:
                w, h = max(1, round(long_side * aspect)), long_side
            look = copy.copy(self.look)
            look.transparent = transparent
            g = self.globals()
            raw = self.renderer.snapshot(
                (w, h), self.camera.view(),
                self.camera.proj(w / h, self.extent), self.camera.eye(), g,
                self.model.skin_matrices(g), look, self.bounds)
        finally:
            self.doneCurrent()
        return QtGui.QImage(raw, w, h, 4 * w,
                            QtGui.QImage.Format.Format_RGBA8888).copy()

    def set_environment(self, environment):
        self.environment = environment
        if self.renderer is not None:
            self.makeCurrent()
            self.renderer.set_env(environment)
            self.doneCurrent()
        self.update()

    def clone(self, parent=None):
        """A second live view of the same model and state (for the
        overlay, which has its own window and GL context)."""
        other = Viewport(self.model, self.environment, self.emulate_3button,
                         parent)
        other.camera.restore(self.camera.state())
        other.look = copy.copy(self.look)
        other.pose = copy.deepcopy(self.pose)
        other.show_bones = False
        return other


# ---------- the window ----------

class ViewerWindow(QtWidgets.QWidget):
    """A model's viewer: the viewport with its toolbar."""

    def __init__(self, model, path, actions, state=None, settings=None,
                 parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.model = model
        self.path = path
        self.actions = actions   # callbacks: add_to_board, overlay, ...
        self.settings = settings
        self.env_path = ''
        self.poses = dict((state or {}).get('poses', {}))
        self.setWindowTitle(f'{model.name} · 3D')
        self.resize(1200, 820)
        emulate = bool(settings and str(settings.value(
            'Plugins/model3d/emulate_3button', 'false')).lower() == 'true')
        self.view = Viewport(model, emulate_3button=emulate)
        self.view.restore(state or {})
        if state and state.get('env_path'):
            self.load_env(state['env_path'], quiet=True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.toolbar())
        layout.addWidget(self.view, 1)
        self.status = QtWidgets.QLabel()
        self.status.setContentsMargins(10, 4, 10, 4)
        layout.addWidget(self.status)
        self.view.status.connect(self.show_status)
        self.view.changed.connect(self.sync)
        self.view.pose_changed.connect(self.sync)
        self.show_status('')
        self.sync()

    # -- toolbar --

    def toolbar(self):
        bar = QtWidgets.QWidget()
        rows = QtWidgets.QVBoxLayout(bar)
        rows.setContentsMargins(8, 6, 8, 6)
        rows.setSpacing(4)
        top = QtWidgets.QHBoxLayout()
        low = QtWidgets.QHBoxLayout()
        rows.addLayout(top)
        rows.addLayout(low)

        def combo(items, value, apply):
            c = QtWidgets.QComboBox()
            for label, data in items:
                c.addItem(label, data)
            c.setCurrentIndex(max(0, [d for _, d in items].index(value)
                                  if value in [d for _, d in items] else 0))
            c.currentIndexChanged.connect(lambda: apply(c.currentData()))
            return c

        def check(label, value, apply, tip=''):
            b = QtWidgets.QCheckBox(label)
            b.setChecked(value)
            b.setToolTip(tip)
            b.toggled.connect(apply)
            return b

        look = self.view.look
        top.addWidget(QtWidgets.QLabel('shading'))
        self.shading = combo([('clay', 'clay'), ('textured', 'textured'),
                              ('flat', 'flat'), ('silhouette', 'silhouette')],
                             look.shading, lambda v: self.set_look(shading=v))
        top.addWidget(self.shading)
        self.wire = check('wireframe', look.wire,
                          lambda v: self.set_look(wire=v))
        top.addWidget(self.wire)
        top.addSpacing(12)
        top.addWidget(QtWidgets.QLabel('light'))
        self.lighting = combo([('key light', 'key'), ('2-point', '2-point'),
                               ('3-point', '3-point'),
                               ('environment', 'environment')],
                              look.lighting,
                              lambda v: self.set_look(lighting=v))
        top.addWidget(self.lighting)
        env = QtWidgets.QPushButton('environment…')
        env.setToolTip('an .hdr, .jpg or .png panorama (shrunk to 2048 px)')
        env.clicked.connect(self.pick_env)
        top.addWidget(env)
        studio = QtWidgets.QPushButton('studio')
        studio.setToolTip('the built-in studio environment')
        studio.clicked.connect(lambda: self.set_env(envlib.studio(), ''))
        top.addWidget(studio)
        self.show_env = check('show it', look.show_env,
                              lambda v: self.set_look(show_env=v),
                              'show the environment behind the model')
        top.addWidget(self.show_env)
        top.addWidget(QtWidgets.QLabel('strength'))
        self.strength = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        self.strength.setRange(10, 300)
        self.strength.setValue(int(look.strength * 100))
        self.strength.setFixedWidth(110)
        self.strength.valueChanged.connect(
            lambda v: self.set_look(strength=v / 100))
        top.addWidget(self.strength)
        top.addStretch()

        low.addWidget(QtWidgets.QLabel('lens'))
        self.lens = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        self.lens.setRange(18, 135)
        self.lens.setValue(int(self.view.camera.lens))
        self.lens.setFixedWidth(120)
        self.lens_label = QtWidgets.QLabel()
        self.lens.valueChanged.connect(self.set_lens)
        low.addWidget(self.lens)
        low.addWidget(self.lens_label)
        self.grid = check('grid', look.grid, lambda v: self.set_look(grid=v))
        low.addWidget(self.grid)
        self.shadow = check('shadow', look.shadow,
                            lambda v: self.set_look(shadow=v))
        low.addWidget(self.shadow)
        if self.model.rigged:
            low.addSpacing(12)
            self.bones = check('bones (Alt+B)', self.view.show_bones,
                               self.set_bones)
            low.addWidget(self.bones)
            low.addWidget(QtWidgets.QLabel('gizmo'))
            self.gizmo = combo([('off', 'off'), ('move', 'move'),
                                ('rotate', 'rotate')], 'off', self.set_gizmo)
            low.addWidget(self.gizmo)
            mirror = QtWidgets.QPushButton('mirror pose')
            mirror.setToolTip('copy the selected bones (or all) to the other '
                              'side')
            mirror.clicked.connect(self.mirror)
            low.addWidget(mirror)
            self.pose_box = QtWidgets.QComboBox()
            self.pose_box.setMinimumWidth(120)
            self.pose_box.activated.connect(self.apply_named_pose)
            low.addWidget(self.pose_box)
            save_pose = QtWidgets.QPushButton('save pose…')
            save_pose.clicked.connect(self.save_pose)
            low.addWidget(save_pose)
            self.fill_poses()
        low.addStretch()
        for label, name, tip in (
                ('add view to board', 'add_to_board',
                 'a card of this view on the board'),
                ('export image', 'export', 'save this view as a PNG (F12)'),
                ('copy image', 'copy', 'copy this view (Ctrl+Shift+C)'),
                ('overlay', 'overlay',
                 'float this live view over other apps')):
            b = QtWidgets.QPushButton(label)
            b.setToolTip(tip)
            b.clicked.connect(lambda _, n=name: self.run(n))
            low.addWidget(b)
        return bar

    def run(self, name):
        callback = self.actions.get(name)
        if callback:
            callback(self)

    def set_look(self, **values):
        for k, v in values.items():
            setattr(self.view.look, k, v)
        self.view.update()

    def set_lens(self, mm):
        self.view.camera.lens = float(mm)
        self.lens_label.setText(f'{mm} mm')
        self.view.update()

    def set_bones(self, on):
        self.view.show_bones = on
        self.view.update()

    def set_gizmo(self, mode):
        self.view.gizmo = mode
        self.view.update()

    def sync(self):
        """Toolbar follows changes made with keys in the viewport."""
        if hasattr(self, 'bones'):
            self.bones.blockSignals(True)
            self.bones.setChecked(self.view.show_bones)
            self.bones.blockSignals(False)
        self.lens_label.setText(f'{int(self.view.camera.lens)} mm')

    def show_status(self, text):
        if not text:
            m = self.model
            text = f'{m.triangles:,} triangles'
            if m.joints:
                n = len(self.view.selected)
                text += (f' · {len(m.joints)} bones · click bones, G move, '
                         f'R rotate, A all, Alt+A none')
                if n:
                    text += f' · {n} selected'
            text += ' · middle-drag orbits, Shift pans, wheel zooms, ` views'
        self.status.setText(text)

    # -- environment --

    def pick_env(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, 'environment', '',
            'Environments (*.hdr *.jpg *.jpeg *.png)')
        if path:
            self.load_env(path)

    def load_env(self, path, quiet=False):
        try:
            environment = envlib.load(path)
        except Exception as e:
            if not quiet:
                QtWidgets.QMessageBox.warning(
                    self, 'environment', f"couldn't read that image: {e}")
            return
        self.set_env(environment, path)

    def set_env(self, environment, path):
        self.env_path = path
        self.view.set_environment(environment)
        if self.view.look.lighting != 'environment':
            index = self.lighting.findData('environment')
            self.lighting.setCurrentIndex(index)

    # -- poses --

    def fill_poses(self):
        self.pose_box.clear()
        self.pose_box.addItem('poses…', None)
        self.pose_box.addItem('rest pose', '')
        for name in sorted(self.poses):
            self.pose_box.addItem(name, name)

    def save_pose(self):
        name, ok = QtWidgets.QInputDialog.getText(self, 'save pose',
                                                  'name for this pose:')
        if ok and name.strip():
            self.poses[name.strip()] = self.view.pose_by_name()
            self.fill_poses()

    def apply_named_pose(self, index):
        name = self.pose_box.itemData(index)
        self.pose_box.setCurrentIndex(0)
        if name is None:
            return
        pose = {} if name == '' else self.view.pose_from_names(
            self.poses.get(name))
        self.view.set_pose(pose, record=True)

    def mirror(self):
        if not self.view.mirror_pose():
            self.show_status('no left/right bone names to mirror '
                             '(.L/.R, _l/_r, Left/Right)')

    # -- keys that belong to the window's actions --

    def keyPressEvent(self, e):
        mods = e.modifiers()
        if e.key() == Qt.Key.Key_F12:
            self.run('export')
            return
        if e.key() == Qt.Key.Key_C and \
                mods & Qt.KeyboardModifier.ControlModifier and \
                mods & Qt.KeyboardModifier.ShiftModifier:
            self.run('copy')
            return
        super().keyPressEvent(e)

    def state(self):
        out = self.view.state()
        out['env_path'] = self.env_path
        out['poses'] = self.poses
        return out
