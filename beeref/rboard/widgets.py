# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Dialogs and overlays for R Board features."""

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt


class ColorButton(QtWidgets.QPushButton):
    color_changed = QtCore.pyqtSignal(QtGui.QColor)

    def __init__(self, color):
        super().__init__()
        self.setFixedSize(64, 28)
        self.set_color(color)
        self.clicked.connect(self.choose)

    def set_color(self, color):
        self.color = QtGui.QColor(color)
        self.setStyleSheet(
            f'background-color: {self.color.name()}; border: 1px solid #888')
        self.setToolTip(self.color.name())
        self.color_changed.emit(self.color)

    def choose(self):
        color = QtWidgets.QColorDialog.getColor(
            self.color, self, 'Find images with this color')
        if color.isValid():
            self.set_color(color)


class FindColorDialog(QtWidgets.QDialog):
    """Pick a color; images containing it are selected live."""

    def __init__(self, parent, initial_color, on_change):
        super().__init__(parent)
        self.on_change = on_change
        self.setWindowTitle('Find by Color')
        layout = QtWidgets.QFormLayout(self)

        self.button = ColorButton(initial_color)
        self.hex = QtWidgets.QLineEdit(self.button.color.name())
        self.hex.setMaximumWidth(90)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.button)
        row.addWidget(self.hex)
        row.addStretch()
        layout.addRow('Color:', row)

        self.tolerance = self._slider(4, 40, 14)
        layout.addRow('Closeness:', self.tolerance)
        self.coverage = self._slider(1, 50, 5)
        layout.addRow('Min. coverage:', self.coverage)

        self.result = QtWidgets.QLabel()
        layout.addRow(self.result)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.button(
            QtWidgets.QDialogButtonBox.StandardButton.Ok).setText('Select')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self.button.color_changed.connect(
            lambda c: self.hex.setText(c.name()))
        self.button.color_changed.connect(self.update_result)
        self.hex.editingFinished.connect(self.on_hex)
        self.update_result()

    def _slider(self, low, high, value):
        slider = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        slider.setRange(low, high)
        slider.setValue(value)
        slider.setMinimumWidth(200)
        slider.valueChanged.connect(self.update_result)
        return slider

    def on_hex(self):
        color = QtGui.QColor(self.hex.text().strip())
        if color.isValid():
            self.button.set_color(color)

    def update_result(self, *args):
        count = self.on_change(self.button.color, self.tolerance.value(),
                               self.coverage.value() / 100)
        self.result.setText(
            f'{count} matching image{"" if count == 1 else "s"} selected')


class SearchBar(QtWidgets.QFrame):
    """Floating search field at the top of the board (Ctrl+F)."""

    query_changed = QtCore.pyqtSignal(str)
    next_requested = QtCore.pyqtSignal()
    index_requested = QtCore.pyqtSignal()
    meaning_requested = QtCore.pyqtSignal()
    closed = QtCore.pyqtSignal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName('RBoardSearchBar')
        self.update_theme()
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        self.field = QtWidgets.QLineEdit()
        self.field.setPlaceholderText(
            'search text, notes, tags, links, or what images show…')
        self.field.setMinimumWidth(320)
        self.field.setClearButtonEnabled(True)
        layout.addWidget(self.field)
        self.count = QtWidgets.QLabel()
        layout.addWidget(self.count)
        self.index_button = QtWidgets.QPushButton()
        self.index_button.clicked.connect(self.index_requested)
        layout.addWidget(self.index_button)
        self.meaning_button = QtWidgets.QPushButton()
        self.meaning_button.setToolTip(
            'also find images that look like what you type')
        self.meaning_button.clicked.connect(self.meaning_requested)
        self.meaning_button.hide()
        layout.addWidget(self.meaning_button)
        close = QtWidgets.QToolButton()
        close.setText('✕')
        close.setAutoRaise(True)
        close.clicked.connect(self.close_bar)
        layout.addWidget(close)

        self.field.textChanged.connect(self.query_changed)
        self.field.returnPressed.connect(self.next_requested)
        self.field.installEventFilter(self)

    def update_theme(self):
        from beeref.rboard.ui.theme import tm
        self.setStyleSheet(
            f'#RBoardSearchBar {{ background: {tm().hex("surface-raised")};'
            f' border: 1px solid {tm().hex("divider")};'
            ' border-radius: 18px; }')

    def eventFilter(self, obj, event):
        if (event.type() == QtCore.QEvent.Type.KeyPress
                and event.key() == Qt.Key.Key_Escape):
            self.close_bar()
            return True
        return super().eventFilter(obj, event)

    def open(self, unindexed):
        self.set_unindexed(unindexed)
        self.reposition()
        self.show()
        self.raise_()
        self.field.setFocus()
        self.field.selectAll()

    def set_unindexed(self, count):
        self.index_button.setVisible(count > 0)
        self.index_button.setText(
            f'Read text in {count} image{"" if count == 1 else "s"}')

    def set_count(self, count, query, looks=None):
        if not query:
            self.count.setText('')
            return
        text = f'{count} match{"" if count == 1 else "es"}'
        if looks:
            text += f' · {looks} look like it'
        self.count.setText(text)

    def refresh_meaning(self, label):
        """label is '' when search by meaning is ready."""
        self.meaning_button.setVisible(bool(label))
        self.meaning_button.setText(label)
        self.reposition()

    def reposition(self):
        self.adjustSize()
        x = (self.parent().width() - self.width()) // 2
        self.move(max(x, 0), 10)

    def close_bar(self):
        self.hide()
        self.closed.emit()
