# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""The settings window: themes (presets and custom), board, tools,
imports, keyboard and mouse."""

import re

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from beeref import constants
from beeref.config import BeeSettings
from beeref.rboard.ui import theme as T
from beeref.rboard.ui.dialogs import button_row, caption, heading, primary
from beeref.rboard.ui.menu import section_font
from beeref.rboard.ui.theme import px, tm


SECTIONS = ['appearance', 'board', 'tools', 'imports', 'keyboard & mouse']


def section_label(text):
    label = QtWidgets.QLabel(text)
    label.setFont(section_font())
    label.setStyleSheet(f'color: {tm().hex("ink-muted")};')
    return label


class FieldRow(QtWidgets.QWidget):
    """'label    control' with the design's 96px label column."""

    def __init__(self, label, control, help_text=None):
        super().__init__()
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        name = QtWidgets.QLabel(label)
        name.setFixedWidth(140)
        name.setStyleSheet(f'color: {tm().hex("ink-muted")};')
        layout.addWidget(name)
        layout.addWidget(control, 1)
        if help_text:
            control.setToolTip(help_text)


# ---------- theme picker ----------

class ThemeCard(QtWidgets.QAbstractButton):
    """Theme name plus a canvas / raised surface / accent preview."""

    def __init__(self, theme):
        super().__init__()
        self.theme = theme
        self.setCheckable(True)
        self.setFixedSize(150, 76)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(theme['name'])

    def paintEvent(self, event):
        c = self.theme['colors']
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setBrush(QtGui.QColor(c['canvas']))
        border = (tm().color('accent') if self.isChecked()
                  else QtGui.QColor(c['divider']))
        p.setPen(QtGui.QPen(border, 2 if self.isChecked() else 1))
        p.drawRoundedRect(rect, px('radius-md'), px('radius-md'))
        p.setFont(section_font())
        p.setPen(QtGui.QColor(c['ink-muted']))
        p.drawText(QtCore.QRectF(12, 10, rect.width() - 20, 14),
                   Qt.AlignmentFlag.AlignLeft, self.theme['name'])
        for i, key in enumerate(('canvas', 'surface-raised', 'accent')):
            p.setPen(QtGui.QPen(QtGui.QColor(c['divider']), 1))
            p.setBrush(QtGui.QColor(c[key]))
            p.drawEllipse(QtCore.QRectF(12 + i * 24, 40, 18, 18))


class ColorButton(QtWidgets.QPushButton):
    changed = QtCore.pyqtSignal(str)

    def __init__(self, color):
        super().__init__()
        self.setFixedSize(72, 26)
        self.color = color
        self.clicked.connect(self.choose)
        self.refresh()

    def refresh(self):
        self.setText(self.color)
        ink = '#111111' if T.luminance(self.color) > 0.4 else '#f2f2f2'
        self.setStyleSheet(
            f'QPushButton {{ background: {self.color}; color: {ink}; '
            f'border: 1px solid {tm().hex("control-border")}; '
            'font-size: 10px; padding: 0; }')

    def set_color(self, color):
        self.color = color
        self.refresh()
        self.changed.emit(color)

    def choose(self):
        color = QtWidgets.QColorDialog.getColor(
            QtGui.QColor(self.color), self, 'choose colour')
        if color.isValid():
            self.set_color(color.name())


class ThemeEditor(QtWidgets.QWidget):
    """Edit a custom theme: four base colours, plus every token under
    'all colours'. Changes preview live."""

    saved = QtCore.pyqtSignal(str)
    cancelled = QtCore.pyqtSignal()

    def __init__(self, stored):
        super().__init__()
        self.stored = stored  # {'id', 'name', 'base', 'overrides'}
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(section_label('custom theme'))
        self.name = QtWidgets.QLineEdit(stored['name'])
        layout.addWidget(FieldRow('name', self.name))
        self.base_preset = QtWidgets.QComboBox()
        self.base_preset.addItem('keep current colours', None)
        for preset in T.PRESETS.values():
            self.base_preset.addItem(f'start from {preset["name"]}',
                                     preset['id'])
        self.base_preset.currentIndexChanged.connect(self.on_preset)
        layout.addWidget(FieldRow('start from', self.base_preset))

        self.base_buttons = {}
        labels = {'canvas': 'background', 'surface': 'panels',
                  'ink': 'text', 'accent': 'accent'}
        for key in T.BASE_KEYS:
            button = ColorButton(stored['base'][key])
            button.changed.connect(lambda c, k=key: self.on_base(k, c))
            self.base_buttons[key] = button
            row = QtWidgets.QWidget()
            h = QtWidgets.QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(button)
            h.addStretch()
            layout.addWidget(FieldRow(labels[key], row))

        self.advanced = QtWidgets.QCheckBox('edit all colours')
        self.advanced.toggled.connect(self.toggle_advanced)
        layout.addWidget(self.advanced)
        self.token_box = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(self.token_box)
        grid.setContentsMargins(0, 0, 0, 0)
        self.token_buttons = {}
        for i, key in enumerate(T.EDITABLE):
            button = ColorButton('#000000')
            button.changed.connect(lambda c, k=key: self.on_token(k, c))
            self.token_buttons[key] = button
            label = QtWidgets.QLabel(key.replace('-', ' '))
            label.setStyleSheet(f'color: {tm().hex("ink-muted")};')
            grid.addWidget(label, i // 2, (i % 2) * 2)
            grid.addWidget(button, i // 2, (i % 2) * 2 + 1)
        self.token_box.setVisible(False)
        layout.addWidget(self.token_box)

        self.warning = caption('')
        layout.addWidget(self.warning)
        save = primary('save theme')
        cancel = QtWidgets.QPushButton('cancel')
        save.clicked.connect(self.on_save)
        cancel.clicked.connect(self.cancelled)
        layout.addLayout(button_row(None, cancel, save))
        self.preview()

    def resolved(self):
        return tm().resolve_custom(self.stored)

    def preview(self):
        theme = self.resolved()
        for key, button in self.token_buttons.items():
            button.color = theme['colors'][key]
            button.refresh()
        c = theme['colors']
        low = T.contrast(c['ink'], c['canvas']) < 4.5 or \
            T.contrast(c['ink'], c['surface']) < 4.5
        self.warning.setText('text is hard to read on these backgrounds. '
                             'pick a lighter or darker text colour.'
                             if low else '')
        tm().preview(theme)

    def on_preset(self, index):
        preset_id = self.base_preset.itemData(index)
        if not preset_id:
            return
        colors = T.PRESETS[preset_id]['colors']
        self.stored['base'] = {k: colors[k] for k in T.BASE_KEYS}
        self.stored['overrides'] = {}
        for key, button in self.base_buttons.items():
            button.color = colors[key]
            button.refresh()
        self.preview()

    def on_base(self, key, color):
        self.stored['base'][key] = color
        # Derived colours follow the base again
        self.stored['overrides'] = {}
        self.preview()

    def on_token(self, key, color):
        self.stored.setdefault('overrides', {})[key] = color
        self.preview()

    def toggle_advanced(self, on):
        self.token_box.setVisible(on)

    def on_save(self):
        name = self.name.text().strip() or 'my theme'
        self.stored['name'] = name
        if not self.stored.get('id'):
            slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
            self.stored['id'] = f'custom:{slug or "theme"}'
        tm().save_custom_theme(self.stored)
        self.saved.emit(self.stored['id'])


class AppearancePage(QtWidgets.QWidget):

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.layout_ = QtWidgets.QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(12)
        self.layout_.addWidget(section_label('theme'))
        self.grid_host = QtWidgets.QWidget()
        self.grid = QtWidgets.QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(8)
        self.layout_.addWidget(self.grid_host)

        buttons = QtWidgets.QHBoxLayout()
        self.new_button = QtWidgets.QPushButton('new custom theme')
        self.edit_button = QtWidgets.QPushButton('edit')
        self.delete_button = QtWidgets.QPushButton('delete theme')
        self.new_button.clicked.connect(self.on_new)
        self.edit_button.clicked.connect(self.on_edit)
        self.delete_button.clicked.connect(self.on_delete)
        for b in (self.new_button, self.edit_button, self.delete_button):
            buttons.addWidget(b)
        buttons.addStretch()
        self.layout_.addLayout(buttons)

        self.editor_host = QtWidgets.QVBoxLayout()
        self.layout_.addLayout(self.editor_host)
        self.editor = None

        self.layout_.addWidget(section_label('home bar'))
        self.hide_delay = QtWidgets.QComboBox()
        for label, value in (('after 1 second', 1.0), ('after 2 seconds', 2.0),
                             ('after 4 seconds', 4.0), ('never', 0.0)):
            self.hide_delay.addItem(label, value)
        current = settings.valueOrDefault('Appearance/bar_hide_delay')
        index = self.hide_delay.findData(current)
        self.hide_delay.setCurrentIndex(index if index >= 0 else 1)
        self.hide_delay.currentIndexChanged.connect(
            lambda: settings.setValue('Appearance/bar_hide_delay',
                                      self.hide_delay.currentData()))
        self.layout_.addWidget(FieldRow('hide the bar', self.hide_delay))
        self.layout_.addStretch()
        self.populate()

    def populate(self):
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.cards = []
        current = tm().theme['id']
        for i, theme in enumerate(tm().all_themes()):
            card = ThemeCard(theme)
            card.setChecked(theme['id'] == current)
            card.clicked.connect(lambda _, t=theme: self.choose(t['id']))
            self.cards.append(card)
            self.grid.addWidget(card, i // 3, i % 3)
        custom = tm().theme.get('custom', False)
        self.edit_button.setEnabled(custom)
        self.delete_button.setEnabled(custom)

    def choose(self, theme_id):
        self.close_editor(apply_saved=False)
        tm().set_theme(theme_id)
        self.populate()

    def open_editor(self, stored):
        self.close_editor(apply_saved=False)
        self.editor = ThemeEditor(stored)
        self.editor.saved.connect(self.on_saved)
        self.editor.cancelled.connect(lambda: self.close_editor(True))
        self.editor_host.addWidget(self.editor)
        self.grid_host.setEnabled(False)

    def close_editor(self, apply_saved=True):
        if self.editor:
            self.editor.deleteLater()
            self.editor = None
            self.grid_host.setEnabled(True)
            if apply_saved:
                tm().load()  # undo the live preview
                self.populate()

    def on_new(self):
        c = tm().theme['colors']
        self.open_editor({'id': '', 'name': 'my theme',
                          'base': {k: c[k] for k in T.BASE_KEYS},
                          'overrides': {}})

    def on_edit(self):
        theme = tm().theme
        if theme.get('custom'):
            self.open_editor({'id': theme['id'], 'name': theme['name'],
                              'base': dict(theme['base']),
                              'overrides': dict(theme['overrides'])})

    def on_saved(self, theme_id):
        self.close_editor(apply_saved=False)
        tm().set_theme(theme_id)
        self.populate()

    def on_delete(self):
        theme = tm().theme
        if not theme.get('custom'):
            return
        answer = QtWidgets.QMessageBox.question(
            self, 'delete theme', f'delete the theme "{theme["name"]}"?')
        if answer == QtWidgets.QMessageBox.StandardButton.Yes:
            tm().delete_custom_theme(theme['id'])
            self.populate()


def setting_combo(settings, key, options):
    combo = QtWidgets.QComboBox()
    for label, value in options:
        combo.addItem(label, value)
    index = combo.findData(settings.valueOrDefault(key))
    combo.setCurrentIndex(max(index, 0))
    combo.currentIndexChanged.connect(
        lambda: settings.setValue(key, combo.currentData()))
    return combo


def setting_spin(settings, key, low, high, suffix=''):
    spin = QtWidgets.QSpinBox()
    spin.setRange(low, high)
    spin.setSuffix(suffix)
    spin.setValue(settings.valueOrDefault(key))
    spin.valueChanged.connect(lambda v: settings.setValue(key, v))
    return spin


def setting_check(settings, key, label):
    box = QtWidgets.QCheckBox(label)
    box.setChecked(bool(settings.valueOrDefault(key)))
    box.toggled.connect(lambda v: settings.setValue(key, v))
    return box


def page(*widgets):
    w = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(w)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    for widget in widgets:
        layout.addWidget(widget)
    layout.addStretch()
    return w


class SettingsDialog(QtWidgets.QDialog):

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.settings = BeeSettings()
        s = self.settings
        self.setWindowTitle(f'{constants.APPNAME} settings')
        self.setMinimumSize(720, 560)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(16)
        outer.addWidget(heading('settings'))
        body = QtWidgets.QHBoxLayout()
        body.setSpacing(24)
        outer.addLayout(body, 1)

        self.nav = QtWidgets.QListWidget()
        self.nav.setFixedWidth(160)
        self.nav.addItems(SECTIONS)
        self.nav.setStyleSheet(
            'QListWidget::item { height: 28px; padding-left: 8px; '
            'border-radius: 8px; } QListWidget::item:selected { '
            f'background: {tm().hex("accent-soft")}; '
            f'color: {tm().hex("ink")}; }}')
        body.addWidget(self.nav)
        self.pages = QtWidgets.QStackedWidget()
        body.addWidget(self.pages, 1)

        self.pages.addWidget(self.scrolled(AppearancePage(s)))
        self.pages.addWidget(self.scrolled(page(
            section_label('saving'),
            setting_check(s, 'Save/confirm_close_unsaved',
                          'ask before closing unsaved boards'),
            FieldRow('store images as', setting_combo(
                s, 'Items/image_storage_format',
                [('best guess', 'best'), ('always png', 'png'),
                 ('always jpg', 'jpg')]),
                'png keeps quality and transparency, jpg keeps files small'),
            section_label('arranging'),
            FieldRow('gap between images', setting_spin(
                s, 'Items/arrange_gap', 0, 200, ' px'),
                '0 picks a small gap automatically for R Board layouts'),
            FieldRow('when adding images', setting_combo(
                s, 'Items/arrange_default',
                [('arrange optimally', 'optimal'),
                 ('in a row', 'horizontal'), ('in a column', 'vertical'),
                 ('in a square', 'square')])),
            section_label('memory'),
            FieldRow('largest image', setting_spin(
                s, 'Items/image_allocation_limit', 0, 10000, ' MB'),
                'images bigger than this are refused; 0 means no limit'),
        )))
        self.pages.addWidget(self.scrolled(page(
            section_label('pen'),
            FieldRow('line width', setting_combo(
                s, 'Pen/width', [('thin', 'thin'), ('medium', 'medium'),
                                 ('thick', 'thick')])),
            section_label('notes'),
            setting_check(s, 'Appearance/show_notes',
                          'always show notes, not just on hover'),
            section_label('colour'),
            FieldRow('palette colours', setting_spin(
                s, 'Items/palette_size', 2, 24)),
            FieldRow('value study tones', setting_spin(
                s, 'Items/value_study_levels', 2, 8)),
        )))
        self.pages.addWidget(self.scrolled(page(
            section_label('Are.na'),
            FieldRow('image size', setting_combo(
                s, 'Arena/max_side',
                [('full resolution', 0), ('up to 4096 px', 4096),
                 ('up to 2048 px', 2048), ('up to 1024 px', 1024)]),
                'big channels at full resolution use a lot of memory'),
        )))
        keys = QtWidgets.QPushButton('edit keyboard & mouse controls')
        keys.clicked.connect(self.open_controls)
        folder = QtWidgets.QPushButton('open settings folder')
        folder.clicked.connect(view.on_action_open_settings_dir)
        self.pages.addWidget(self.scrolled(page(
            section_label('controls'), caption(
                'change shortcuts and what mouse buttons and the wheel do.'),
            keys, folder)))

        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)

        reset = QtWidgets.QPushButton('restore defaults')
        reset.clicked.connect(self.on_restore_defaults)
        close = primary('done')
        close.clicked.connect(self.accept)
        outer.addLayout(button_row(reset, None, close))
        self.show()

    def scrolled(self, widget):
        area = QtWidgets.QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        area.setWidget(widget)
        area.setStyleSheet('QScrollArea, QScrollArea > QWidget > QWidget '
                           '{ background: transparent; }')
        return area

    def open_controls(self):
        from beeref.widgets.controls import ControlsDialog
        ControlsDialog(self.view)

    def on_restore_defaults(self):
        answer = QtWidgets.QMessageBox.question(
            self, 'restore defaults',
            'restore all settings to their defaults? your custom themes '
            'are kept.')
        if answer == QtWidgets.QMessageBox.StandardButton.Yes:
            self.settings.restore_defaults()
            self.settings.remove('Appearance/theme')
            tm().load()
            self.accept()
            SettingsDialog(self.view)
