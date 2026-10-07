# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""3D models: view, light, pose and overlay .obj, .fbx and .glb files.

A model shows on the board as a card: a rendered image whose data links
to the model file on disk (relative to the board when it's near it) and
remembers the camera, light, shading and pose. Double-click a card to
open the model as it was; "add view to board" makes more cards."""

import logging
import os

from PyQt6 import QtCore, QtGui, QtWidgets

from . import loaders

logger = logging.getLogger(__name__)

api = None
_windows = set()        # open viewer windows (kept alive)
_models = {}            # (path, mtime) -> Model, the last few loaded
KEEP_MODELS = 3
EXPORT_SIZES = (1024, 2048, 3072, 4096)


# ---------- paths ----------

def board_dir(view):
    main = view.rb_main()
    return os.path.dirname(main.filename) if main.filename else ''


def link_data(view, path):
    path = os.path.abspath(path)
    data = {'path': path, 'rel': ''}
    folder = board_dir(view)
    if folder:
        try:
            rel = os.path.relpath(path, folder)
            if not rel.startswith('..' + os.sep + '..' + os.sep + '..'):
                data['rel'] = rel
        except ValueError:   # another drive
            pass
    return data


def resolve(view, data):
    """The model file for a card, or None if it's gone."""
    folder = board_dir(view)
    if data.get('rel') and folder:
        path = os.path.normpath(os.path.join(folder, data['rel']))
        if os.path.isfile(path):
            return path
    path = data.get('path', '')
    return path if path and os.path.isfile(path) else None


def is_card(item):
    return isinstance(getattr(item, 'meta', None), dict) and \
        'model3d' in item.meta


# ---------- loading ----------

def load_then(view, path, then):
    """Load a model in the background (or from the cache), then call
    then(model)."""
    try:
        loaders.check_size(path)
    except loaders.LoadError as e:
        api.notify(view, str(e))
        return
    key = (os.path.abspath(path), os.path.getmtime(path))
    if key in _models:
        then(_models[key])
        return

    def work(progress, canceled):
        return loaders.load(path, progress)

    def done(model, error):
        if error is not None:
            QtWidgets.QMessageBox.warning(
                view, '3D model', str(error) if isinstance(
                    error, loaders.LoadError) else
                f'could not read the model: {error}')
            return
        _models[key] = model
        while len(_models) > KEEP_MODELS:
            _models.pop(next(iter(_models)))
        then(model)

    api.run_in_background(view, f'opening {os.path.basename(path)}…', work,
                          done)


def open_viewer(view, model, path, state=None, first_card=False):
    from .viewer import ViewerWindow
    window = ViewerWindow(
        model, path,
        {'add_to_board': lambda w: add_card(view, w),
         'export': export_image, 'copy': copy_image,
         'overlay': lambda w: overlay(view, w)},
        state=state, settings=view.settings)
    _windows.add(window)
    window.destroyed.connect(lambda *_: _windows.discard(window))
    window.show()
    window.raise_()
    window.activateWindow()
    window.view.setFocus()
    if first_card:
        # Once OpenGL is up, the model gets its first card on the board
        QtCore.QTimer.singleShot(400, lambda: add_card(view, window))
    return window


# ---------- importing ----------

def import_model(view, paths=None):
    if not paths:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            view, '3D model', '',
            '3D models (*.obj *.fbx *.glb *.gltf)')
        if not path:
            return
        paths = [path]
    for path in paths[:4]:
        load_then(view, path, lambda model, p=path: open_viewer(
            view, model, p, first_card=True))


def is_model_file(text):
    return text.lower().endswith(loaders.EXTENSIONS) and \
        os.path.isfile(text)


# ---------- cards ----------

def add_card(view, window):
    image = window.view.render_image(2048, transparent=True)
    if image is None:
        api.notify(view, "the view couldn't be drawn (no OpenGL)")
        return
    model = window.model
    tags = ['3d model'] + (['rigged'] if model.rigged else [])
    meta = {'model3d': dict(link_data(view, window.path),
                            state=window.state()),
            'tags': tags}
    added = api.add_images(view, [(image, f'{model.name}.png', meta)])
    if added:
        api.notify(view, f'added a view of {model.name} to the board')


def open_card(view, item):
    data = item.meta.get('model3d', {})
    path = resolve(view, data)
    if path is None:
        path = relink(view, item, data)
        if path is None:
            return
    load_then(view, path, lambda model: open_viewer(
        view, model, path, state=data.get('state')))


def relink(view, item, data):
    """Ask where a moved model went; every card of it follows."""
    answer = QtWidgets.QMessageBox.question(
        view, '3D model',
        f"model file not found:\n{data.get('path', '')}\n\nlocate it?",
        QtWidgets.QMessageBox.StandardButton.Yes |
        QtWidgets.QMessageBox.StandardButton.Cancel)
    if answer != QtWidgets.QMessageBox.StandardButton.Yes:
        return None
    path, _ = QtWidgets.QFileDialog.getOpenFileName(
        view, 'locate the model', os.path.dirname(data.get('path', '')),
        '3D models (*.obj *.fbx *.glb *.gltf)')
    if not path:
        return None
    old = data.get('path')
    main = view.rb_main()
    cards = [i for i in main.rb_images() if is_card(i) and
             i.meta['model3d'].get('path') == old] or \
        [getattr(item, 'link_source', None) or item]
    link = link_data(view, path)
    values = [dict(c.meta['model3d'], **link) for c in cards]
    api.set_image_data(main, cards, 'model3d', values, 'Relink 3D model')
    return path


def paint_badge(painter, rect):
    """A small cube on a dark disc: this card opens a 3D model."""
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    painter.setPen(QtCore.Qt.PenStyle.NoPen)
    painter.setBrush(QtGui.QColor(20, 20, 24, 190))
    painter.drawEllipse(rect)
    c = rect.center()
    s = rect.width() * 0.26
    top = [QtCore.QPointF(c.x(), c.y() - s),
           QtCore.QPointF(c.x() + s * 0.9, c.y() - s * 0.5),
           QtCore.QPointF(c.x(), c.y()),
           QtCore.QPointF(c.x() - s * 0.9, c.y() - s * 0.5)]
    pen = QtGui.QPen(QtGui.QColor(240, 240, 240), rect.width() * 0.07)
    pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    painter.drawPolygon(QtGui.QPolygonF(top))
    painter.drawLine(top[3], QtCore.QPointF(top[3].x(), top[3].y() + s))
    painter.drawLine(top[1], QtCore.QPointF(top[1].x(), top[1].y() + s))
    painter.drawLine(top[2], QtCore.QPointF(c.x(), c.y() + s))
    painter.drawLine(QtCore.QPointF(top[3].x(), top[3].y() + s),
                     QtCore.QPointF(c.x(), c.y() + s))
    painter.drawLine(QtCore.QPointF(top[1].x(), top[1].y() + s),
                     QtCore.QPointF(c.x(), c.y() + s))


# ---------- images out ----------

def export_image(window):
    dialog = QtWidgets.QDialog(window)
    dialog.setWindowTitle('export image')
    form = QtWidgets.QFormLayout(dialog)
    size = QtWidgets.QComboBox()
    for px in EXPORT_SIZES:
        size.addItem(f'{px} px', px)
    size.setCurrentIndex(1)
    form.addRow('long side', size)
    transparent = QtWidgets.QCheckBox('transparent background')
    transparent.setChecked(True)
    form.addRow('', transparent)
    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.StandardButton.Save |
        QtWidgets.QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    if not dialog.exec():
        return
    path, _ = QtWidgets.QFileDialog.getSaveFileName(
        window, 'export image', f'{window.model.name}.png', 'PNG (*.png)')
    if not path:
        return
    if not path.lower().endswith('.png'):
        path += '.png'
    image = window.view.render_image(size.currentData(),
                                     transparent.isChecked())
    if image is None or not image.save(path, 'PNG'):
        QtWidgets.QMessageBox.warning(window, 'export image',
                                      "couldn't save the image")
        return
    window.show_status(f'saved {os.path.basename(path)}')


def copy_image(window):
    image = window.view.render_image(2048, transparent=False)
    if image is not None:
        QtWidgets.QApplication.clipboard().setImage(image)
        window.show_status('copied the view')


def overlay(view, window):
    live = window.view.clone()
    api.open_overlay(view, live, window.model.name)


# ---------- registering ----------

def register(plugin_api):
    global api
    api = plugin_api
    api.add_action('3D model…', import_model)
    api.add_drop_handler(is_model_file, import_model)
    api.add_open_handler(is_card, open_card)
    api.add_badge(is_card, paint_badge)
    api.add_setting('emulate_3button', 'emulate 3-button mouse', 'check',
                    'Alt + left-drag orbits, for laptops and pens (as in '
                    'Blender)')
