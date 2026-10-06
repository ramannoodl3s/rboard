# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Installing plugins: the one-click AI features install, plugin zips,
and the plugins page in settings."""

import logging
import os
import tempfile

from PyQt6 import QtWidgets

from beeref import fileio, widgets
from beeref.rboard import plugins, semantic


logger = logging.getLogger(__name__)

PLUGIN_SHARE = 10   # % of the AI install's progress bar for the plugin


def _run_ai_install(window, worker):
    """Worker: the AI plugin (unless it's here already), then both
    models."""
    worker.begin_processing.emit(100)
    try:
        if plugins.ensure(plugins.AI_ID, window) is None:
            existing = plugins.get(plugins.AI_ID)
            if existing and existing.error:
                raise plugins.PluginError(existing.error)
            path = os.path.join(tempfile.gettempdir(), 'R-Board-AI.zip')
            plugins.download(
                plugins.ai_url(), path,
                on_progress=lambda d, t: worker.progress.emit(
                    int(d * PLUGIN_SHARE / t) if t else 0),
                is_canceled=lambda: worker.canceled)
            plugin, restart = plugins.install_zip(path)
            os.remove(path)
            if restart:
                raise plugins.PluginError(
                    'restart R Board to finish installing')
            plugin = plugins.load(plugin, window)
            if plugin.error:
                raise plugins.PluginError(plugin.error)
        todo = [p for p in semantic.PARTS
                if not semantic.models_installed(p)]
        total = sum(semantic.part_size(p) for p in todo) or 1
        done = 0
        for part in todo:
            semantic.download(
                part,
                on_progress=lambda d, t, before=done: worker.progress.emit(
                    PLUGIN_SHARE + int((before + d) * (100 - PLUGIN_SHARE)
                                       / total)),
                is_canceled=lambda: worker.canceled)
            done += semantic.part_size(part)
    except Exception as e:
        logger.exception('AI install failed')
        worker.finished.emit('', [str(e)])
        return
    worker.finished.emit('', [])


def install_ai(view, then=None, ask=True):
    """Install the AI features (plugin and models) in one go, then run
    `then`."""
    if semantic.ready():
        if then:
            then()
        return
    if ask:
        size = sum(semantic.part_size(p) for p in semantic.PARTS
                   if not semantic.models_installed(p)) / 1e6
        if plugins.ensure(plugins.AI_ID) is None:
            size += 20
        answer = QtWidgets.QMessageBox.question(
            view, 'AI features',
            'this needs R Board\'s AI features: a one-time download of '
            f'about {size:.0f} MB (the AI plugin from R Board\'s GitHub '
            'page and the CLIP image model from huggingface.co).\n\n'
            'they give images kind, mood, style and subject tags, and '
            'power search by meaning, group by content and tag '
            'suggestions. everything runs on this computer; nothing is '
            'uploaded.\n\ninstall them now?')
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
    worker = fileio.ThreadedIO(_run_ai_install, view.window())

    def finished(filename, errors):
        if errors:
            if 'canceled' not in errors[0]:
                QtWidgets.QMessageBox.warning(
                    view, 'AI features',
                    f"couldn't install the AI features: {errors[0]}. "
                    'check your connection and try again.')
            return
        if then:
            then()

    worker.finished.connect(finished)
    view.ai_install_worker = worker
    view.ai_install_progress = widgets.BeeProgressDialog(
        'installing AI features…', worker=worker, parent=view)
    worker.start()


def remove_ai(view):
    answer = QtWidgets.QMessageBox.question(
        view, 'remove AI features',
        'remove the AI features and their models? images that were '
        'already read keep their tags; new ones need the AI features '
        'again.')
    if answer != QtWidgets.QMessageBox.StandardButton.Yes:
        return False
    semantic.remove_models()
    plugin = plugins.get(plugins.AI_ID)
    if plugin and not plugin.builtin and plugins.remove(plugins.AI_ID):
        QtWidgets.QMessageBox.information(
            view, 'remove AI features',
            'the models are gone; the plugin goes when R Board restarts.')
    return True


def install_from_file(view):
    """Pick a plugin zip and install it."""
    path, _ = QtWidgets.QFileDialog.getOpenFileName(
        view, 'install plugin', '', 'R Board plugins (*.zip)')
    if not path:
        return False
    try:
        plugin, restart = plugins.install_zip(path)
    except Exception as e:
        QtWidgets.QMessageBox.warning(
            view, 'install plugin', f"couldn't install that plugin: {e}")
        return False
    if restart:
        message = (f'{plugin.name} {plugin.version} is ready; it starts '
                   'when R Board restarts.')
    else:
        plugin = plugins.load(plugin, view.window())
        message = (f"{plugin.name} installed but couldn't start: "
                   f'{plugin.error}' if plugin.error
                   else f'{plugin.name} {plugin.version} is installed.')
    QtWidgets.QMessageBox.information(view, 'install plugin', message)
    return True


def menu_entries(view):
    """Plugin actions for the softclub menus."""
    return [('item', label, lambda cb=callback: cb(view.rb_main()))
            for plugin, label, callback in plugins.actions]


def fill_menu(view, menu):
    """The menu bar's plugins menu, rebuilt each time it opens."""
    menu.clear()
    for plugin, label, callback in plugins.actions:
        menu.addAction(label).triggered.connect(
            lambda _, cb=callback: cb(view.rb_main()))
    if plugins.actions:
        menu.addSeparator()
    if not semantic.ready():
        menu.addAction('Get AI Features…').triggered.connect(
            lambda: install_ai(view))
    menu.addAction('Install Plugin from File…').triggered.connect(
        lambda: install_from_file(view))
    menu.addAction('Plugins…').triggered.connect(
        lambda: view.on_action_settings(page='plugins'))


class PluginsPage(QtWidgets.QWidget):
    """Settings page: AI features and other plugins."""

    def __init__(self, view, settings):
        super().__init__()
        from beeref.rboard.ui.settings_dialog import (
            FieldRow, section_label, setting_check)
        from beeref.rboard.ui.dialogs import caption
        self.view = view
        self.FieldRow = FieldRow
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(section_label('AI features'))
        layout.addWidget(caption(
            'kind, mood, style and subject tags, search by meaning, group '
            'by content and tag suggestions. a one-time install: the AI '
            'plugin and a small image model (OpenAI CLIP) that runs on '
            'this computer. nothing is uploaded.'))
        self.ai_status = QtWidgets.QLabel()
        self.ai_button = QtWidgets.QPushButton()
        self.ai_button.clicked.connect(self.toggle_ai)
        row = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.ai_status, 1)
        h.addWidget(self.ai_button)
        layout.addWidget(FieldRow('AI features', row))
        layout.addWidget(setting_check(
            settings, 'Content/auto_index',
            'read new images automatically once AI features are installed'))

        layout.addWidget(section_label('plugins'))
        self.list_box = QtWidgets.QVBoxLayout()
        self.list_box.setSpacing(6)
        layout.addLayout(self.list_box)
        install = QtWidgets.QPushButton('install plugin from file…')
        install.clicked.connect(
            lambda: install_from_file(self.view) and self.refresh())
        layout.addWidget(install)
        layout.addStretch()
        self.refresh()

    def refresh(self):
        ready = semantic.ready()
        plugin = plugins.get(plugins.AI_ID)
        if ready:
            self.ai_status.setText(
                f'installed · version {plugin.version}' if plugin
                else 'installed')
        elif plugin and plugin.error:
            self.ai_status.setText(plugin.error)
        else:
            self.ai_status.setText('not installed')
        self.ai_button.setText('remove' if ready else 'install')

        while self.list_box.count():
            widget = self.list_box.takeAt(0).widget()
            if widget:
                widget.deleteLater()
        others = [p for p in plugins.all_plugins() if p.id != plugins.AI_ID]
        if not others:
            self.list_box.addWidget(QtWidgets.QLabel('none installed'))
        for p in others:
            status = p.error or ('running' if p.loaded
                                 else 'starts after a restart')
            label = QtWidgets.QLabel(f'{p.version} · {status}')
            label.setWordWrap(True)
            remove = QtWidgets.QPushButton('remove')
            remove.setEnabled(not p.builtin)
            remove.clicked.connect(lambda _, p=p: self.remove(p))
            row = QtWidgets.QWidget()
            h = QtWidgets.QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(label, 1)
            h.addWidget(remove)
            self.list_box.addWidget(self.FieldRow(p.name, row))

    def toggle_ai(self):
        if semantic.ready():
            remove_ai(self)
            self.refresh()
        else:
            install_ai(self.view, then=self.refresh, ask=False)

    def remove(self, plugin):
        answer = QtWidgets.QMessageBox.question(
            self, 'remove plugin', f'remove {plugin.name}?')
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        later = plugins.remove(plugin.id)
        if later:
            QtWidgets.QMessageBox.information(
                self, 'remove plugin',
                f'{plugin.name} goes when R Board restarts.')
        self.refresh()
