# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Sort by colour. Everything is worked out from each image's 8-colour
breakdown (the same one colour tags use), by area, so a small bright
detail doesn't decide what colour an image is (except in "accent
colour" sorting, where that's the point).

Sorting near a colour targets a range, not one exact colour: a colour
family (red, orange, ... or grey) and how light it is, measured as the
share of the image in that range.
"""

import numpy as np
from PyQt6 import QtGui, QtWidgets
from PyQt6.QtCore import Qt

from beeref.rboard import analysis
from beeref.rboard.attributes import ACCENT_SHARE
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


FAMILIES = ['red', 'orange', 'yellow', 'green', 'teal', 'blue',
            'purple', 'pink', 'grey']
FAMILY_LABELS = {'orange': 'orange (dark = brown)',
                 'grey': 'grey (white to black)'}
TIERS = [('any', 'any lightness'), ('light', 'light'),
         ('medium', 'medium'), ('dark', 'dark')]
LIGHT_L, DARK_L = 70, 35      # same bounds as the tone tags


def colour_range(L, chroma, hue):
    """(family, tier) a colour falls in."""
    from beeref.rboard.attributes import HUE_FAMILIES
    if chroma < analysis.NAMING_CHROMA:
        family = 'grey'
    else:
        family = HUE_FAMILIES[0][0]
        for name, start in HUE_FAMILIES:
            if hue >= start:
                family = name
    tier = 'light' if L >= LIGHT_L else ('dark' if L < DARK_L
                                          else 'medium')
    return family, tier


def coverage(m, family, tier='any'):
    """Share of the image whose colours fall in the range."""
    total = 0.0
    for lab, share in zip(m['labs'], m['shares']):
        L = float(lab[0])
        chroma = float(np.hypot(lab[1], lab[2]))
        hue = float(np.degrees(np.arctan2(lab[2], lab[1]))) % 360
        f, t = colour_range(L, chroma, hue)
        if f == family and tier in ('any', t):
            total += float(share)
    return total


# mode: (label, what decides which images take part)
MODES = {
    'overall': ('overall colour (by area)',
                'leave out mostly grey images'),
    'accent': ('accent colour (small and strong)',
               'only images with an accent colour'),
    'lightness': ('lightness, light to dark', None),
    'colourful': ('colourfulness, most first', None),
    'warmth': ('warm to cool', None),
    'near': ('near a colour', None),
}


class ColorSortDialog(QtWidgets.QDialog):

    def __init__(self, view, images):
        super().__init__(view)
        self.view = view
        self.images = images
        self.measures = [measures(i.meta['analysis']) for i in images]
        self.setWindowTitle('sort by colour')
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        layout.addWidget(heading('sort by colour'))
        layout.addWidget(caption(
            f'{len(images)} images. the ones that don’t take part '
            'stay where they are.'))

        form = QtWidgets.QFormLayout()
        form.setSpacing(8)
        self.form = form
        self.mode = QtWidgets.QComboBox()
        for key, (label, _) in MODES.items():
            self.mode.addItem(label, key)
        form.addRow('sort by', self.mode)

        self.only = QtWidgets.QCheckBox()
        self.only.setChecked(True)
        form.addRow('', self.only)

        # Near a colour: a family and a lightness, not one exact colour
        from beeref.rboard.attributes import FAMILY_DOTS
        self.family = QtWidgets.QComboBox()
        for name in FAMILIES:
            pm = QtGui.QPixmap(14, 14)
            pm.fill(QtGui.QColor(FAMILY_DOTS[name]))
            self.family.addItem(QtGui.QIcon(pm),
                                FAMILY_LABELS.get(name, name), name)
        self.family.setCurrentIndex(FAMILIES.index('blue'))
        self.tier = QtWidgets.QComboBox()
        for key, label in TIERS:
            self.tier.addItem(label, key)
        pick = QtWidgets.QPushButton('eyedropper…')
        pick.setToolTip('pick a colour (from anywhere on screen) to set '
                        'the family and lightness')
        pick.clicked.connect(self.pick_color)
        colour_row = QtWidgets.QHBoxLayout()
        colour_row.addWidget(self.family, 1)
        colour_row.addWidget(self.tier)
        colour_row.addWidget(pick)
        self.colour_row = QtWidgets.QWidget()
        self.colour_row.setLayout(colour_row)
        colour_row.setContentsMargins(0, 0, 0, 0)
        form.addRow('colour', self.colour_row)
        self.slider = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(1, 100)
        self.slider.setValue(10)
        self.slider_value = QtWidgets.QLabel()
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.slider, 1)
        row.addWidget(self.slider_value)
        self.slider_row = QtWidgets.QWidget()
        self.slider_row.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        form.addRow('covers at least', self.slider_row)

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
        self.setMinimumWidth(520)

        self.mode.currentIndexChanged.connect(self.on_mode)
        for signal in (self.only.toggled, self.slider.valueChanged,
                       self.family.currentIndexChanged,
                       self.tier.currentIndexChanged):
            signal.connect(self.update_count)
        self.on_mode()

    # -- controls --

    def key(self):
        return self.mode.currentData()

    def show_row(self, widget, visible):
        widget.setVisible(visible)
        label = self.form.labelForField(widget)
        if label is not None:
            label.setVisible(visible)

    def on_mode(self):
        only = MODES[self.key()][1]
        self.only.setText(only or '')
        self.show_row(self.only, only is not None)
        near = self.key() == 'near'
        self.show_row(self.colour_row, near)
        self.show_row(self.slider_row, near)
        self.update_count()

    def pick_color(self):
        color = QtWidgets.QColorDialog.getColor(
            QtGui.QColor('#2a5fd0'), self, 'pick a colour')
        if not color.isValid():
            return
        L, chroma, hue = analysis.lch(color.name())
        family, tier = colour_range(L, chroma, hue)
        self.family.setCurrentIndex(FAMILIES.index(family))
        self.tier.setCurrentIndex([k for k, _ in TIERS].index(tier))

    def target(self):
        return self.family.currentData(), self.tier.currentData()

    # -- results --

    def passes(self, m):
        key = self.key()
        if key == 'near':
            return coverage(m, *self.target()) * 100 >= self.slider.value()
        if key == 'accent':
            return not self.only.isChecked() or (
                m['accent_hue'] is not None
                and m['accent_share'] >= ACCENT_SHARE)
        if key == 'overall':
            return not self.only.isChecked() or m['main'] is not None
        return True

    def sort_key(self, m):
        key = self.key()
        if key == 'overall':
            if m['main'] is None:
                return (1, -m['lightness'])
            L, chroma, hue = analysis.lch(m['main'])
            return (0, int(rainbow(hue) // 15), -L)
        if key == 'accent':
            if m['accent_hue'] is None:
                return (1, -m['lightness'])
            return (0, rainbow(m['accent_hue']), -m['accent_share'])
        if key == 'lightness':
            return (-m['lightness'],)
        if key == 'colourful':
            return (-m['colourful'],)
        if key == 'warmth':
            return (-m['warmth'],)
        return (-coverage(m, *self.target()),)

    def result_images(self):
        chosen = [(i, m) for i, m in zip(self.images, self.measures)
                  if self.passes(m)]
        chosen.sort(key=lambda p: self.sort_key(p[1]),
                    reverse=self.reverse.isChecked())
        return [i for i, _ in chosen]

    def to_subboard(self):
        return self.output.currentData() == 'subboard'

    def title(self):
        if self.key() == 'near':
            family, tier = self.target()
            return 'sorted by ' + (family if tier == 'any'
                                   else f'{tier} {family}')
        label = MODES[self.key()][0].split(' (')[0].split(',')[0]
        return f'sorted by {label}'

    def update_count(self):
        self.slider_value.setText(f'{self.slider.value()}% of the image')
        n = len(self.result_images())
        self.count.setText(f'{n} of {len(self.images)} images take part')
        self.ok.setEnabled(n > 0)
