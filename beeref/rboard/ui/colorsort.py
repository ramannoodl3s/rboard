# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Sort by colour: one dialog with the kinds of sort and a threshold to
cherry-pick which images take part. Everything is worked out from each
image's 8-colour breakdown (the same one colour tags use), by area, so
a small bright detail doesn't decide what colour an image is (except in
"accent colour" sorting, where that's the point)."""

import numpy as np
from PyQt6 import QtGui, QtWidgets
from PyQt6.QtCore import Qt

from beeref.rboard import analysis
from beeref.rboard.ui.dialogs import button_row, caption, heading, primary


def _lab(hex_):
    return analysis.rgb_to_lab(analysis.from_hex(hex_))


def measures(stats):
    """Numbers to sort and filter one image by."""
    palette = stats.get('palette') or [[stats['average'], 1.0]]
    labs = np.array([_lab(h) for h, _ in palette])
    shares = np.array([s for _, s in palette])
    shares = shares / max(shares.sum(), 1e-9)
    chroma = np.hypot(labs[:, 1], labs[:, 2])
    colourful = [(s, h) for (h, _), s, c in zip(palette, shares, chroma)
                 if c >= analysis.NAMING_CHROMA]
    main = max(colourful)[1] if colourful else None
    vivid = stats.get('vivid', {})
    accent_band = max(vivid, key=vivid.get) if vivid else None
    return {
        'main': main,
        'lightness': float((labs[:, 0] * shares).sum()),
        'colourful': float((chroma * shares).sum()),
        'warmth': float(((labs[:, 2] + 0.5 * labs[:, 1]) * shares).sum()),
        'accent_hue': (int(accent_band) * 5 + 2.5) if vivid else None,
        'accent_share': float(sum(vivid.values())),
        'labs': labs, 'shares': shares,
    }


def rainbow(hue):
    """Sort position of a hue, starting at red."""
    return (hue - 20) % 360


def coverage(m, target_lab, tolerance=25):
    near = np.linalg.norm(m['labs'] - target_lab, axis=1) < tolerance
    return float(m['shares'][near].sum())


# mode: (label, filter label, filter range, filter default)
MODES = {
    'overall': ('overall colour (by area)', 'at least this colourful',
                (0, 60), 10),
    'accent': ('accent colour (small and strong)', 'accent covers at least',
               (0, 30), 1),
    'lightness': ('lightness, light to dark', 'at least this colourful',
                  (0, 60), 0),
    'colourful': ('colourfulness, most first', 'at least this colourful',
                  (0, 60), 0),
    'warmth': ('warm to cool', 'at least this colourful', (0, 60), 0),
    'near': ('closeness to a colour', 'the colour covers at least',
             (0, 100), 10),
}


class ColorSortDialog(QtWidgets.QDialog):

    def __init__(self, view, images):
        super().__init__(view)
        self.view = view
        self.images = images
        self.measures = [measures(i.meta['analysis']) for i in images]
        self.target = QtGui.QColor('#2a5fd0')
        self.setWindowTitle('sort by colour')
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        layout.addWidget(heading('sort by colour'))
        layout.addWidget(caption(
            f'{len(images)} images. only the ones that pass the slider are '
            'sorted; the rest stay where they are.'))

        form = QtWidgets.QFormLayout()
        form.setSpacing(8)
        self.mode = QtWidgets.QComboBox()
        for key, (label, *_) in MODES.items():
            self.mode.addItem(label, key)
        form.addRow('sort by', self.mode)
        self.color_button = QtWidgets.QPushButton()
        self.color_button.clicked.connect(self.pick_color)
        form.addRow('colour', self.color_button)
        self.filter_label = QtWidgets.QLabel()
        self.slider = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        self.slider_value = QtWidgets.QLabel()
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.slider, 1)
        row.addWidget(self.slider_value)
        form.addRow(self.filter_label, row)
        self.reverse = QtWidgets.QCheckBox('reverse the order')
        form.addRow('', self.reverse)
        self.output = QtWidgets.QComboBox()
        self.output.addItem('arrange them on the board', 'board')
        self.output.addItem('open them as a sub board', 'subboard')
        form.addRow('then', self.output)
        layout.addLayout(form)
        self.count = caption('')
        layout.addWidget(self.count)

        self.ok = primary('sort')
        cancel = QtWidgets.QPushButton('cancel')
        self.ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        layout.addLayout(button_row(None, cancel, self.ok))
        self.setMinimumWidth(480)

        self.mode.currentIndexChanged.connect(self.on_mode)
        self.slider.valueChanged.connect(self.update_count)
        self.on_mode()

    # -- controls --

    def key(self):
        return self.mode.currentData()

    def on_mode(self):
        _, label, (low, high), default = MODES[self.key()]
        self.filter_label.setText(label)
        self.slider.blockSignals(True)
        self.slider.setRange(low, high)
        self.slider.setValue(default)
        self.slider.blockSignals(False)
        near = self.key() == 'near'
        self.color_button.setVisible(near)
        self.form_label(self.color_button).setVisible(near)
        self.refresh_color_button()
        self.update_count()

    def form_label(self, widget):
        form = self.layout().itemAt(2).layout()
        return form.labelForField(widget)

    def refresh_color_button(self):
        hex_ = self.target.name()
        ink = '#111111' if self.target.lightnessF() > 0.55 else '#f2f2f2'
        self.color_button.setText(hex_)
        self.color_button.setStyleSheet(
            f'QPushButton {{ background: {hex_}; color: {ink}; }}')

    def pick_color(self):
        color = QtWidgets.QColorDialog.getColor(self.target, self,
                                                'pick a colour')
        if color.isValid():
            self.target = color
            self.refresh_color_button()
            self.update_count()

    # -- results --

    def passes(self, m):
        value = self.slider.value()
        key = self.key()
        if key == 'accent':
            return m['accent_hue'] is not None and \
                m['accent_share'] * 100 >= value
        if key == 'near':
            return coverage(m, self.target_lab()) * 100 >= max(value, 1)
        if key == 'overall' and m['main'] is None:
            return value == 0
        return m['colourful'] >= value

    def target_lab(self):
        c = self.target
        return analysis.rgb_to_lab((c.red(), c.green(), c.blue()))

    def sort_key(self, m):
        key = self.key()
        if key == 'overall':
            if m['main'] is None:
                return (1, -m['lightness'])
            L, chroma, hue = analysis.lch(m['main'])
            return (0, int(rainbow(hue) // 15), -L)
        if key == 'accent':
            return (0, rainbow(m['accent_hue']), -m['accent_share'])
        if key == 'lightness':
            return (-m['lightness'],)
        if key == 'colourful':
            return (-m['colourful'],)
        if key == 'warmth':
            return (-m['warmth'],)
        return (-coverage(m, self.target_lab()),)

    def result_images(self):
        chosen = [(i, m) for i, m in zip(self.images, self.measures)
                  if self.passes(m)]
        chosen.sort(key=lambda p: self.sort_key(p[1]),
                    reverse=self.reverse.isChecked())
        return [i for i, _ in chosen]

    def to_subboard(self):
        return self.output.currentData() == 'subboard'

    def title(self):
        label = MODES[self.key()][0].split(' (')[0].split(',')[0]
        if self.key() == 'near':
            label = f'near {self.target.name()}'
        return f'sorted by {label}'

    def update_count(self):
        value = self.slider.value()
        unit = '%' if self.key() in ('accent', 'near') else ''
        self.slider_value.setText(f'{value}{unit}')
        n = len(self.result_images())
        self.count.setText(f'{n} of {len(self.images)} images pass')
        self.ok.setEnabled(n > 0)
