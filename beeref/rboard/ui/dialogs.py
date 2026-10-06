# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Small Softclub dialogs: notes and tags."""

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from beeref.rboard.ui.theme import tm, ui_font


def heading(text):
    label = QtWidgets.QLabel(text)
    label.setFont(ui_font(18, 'light'))
    return label


def caption(text):
    label = QtWidgets.QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(f'color: {tm().hex("ink-muted")}; font-size: 11px;')
    return label


def button_row(*buttons):
    row = QtWidgets.QHBoxLayout()
    row.setSpacing(8)
    for b in buttons:
        if b is None:
            row.addStretch()
        else:
            row.addWidget(b)
    return row


def primary(text):
    b = QtWidgets.QPushButton(text)
    b.setProperty('primary', True)
    b.setDefault(True)
    return b


class NoteDialog(QtWidgets.QDialog):
    """Write or edit an image's note. result_text is None on cancel and
    '' when the note was removed."""

    def __init__(self, parent, text='', count=1):
        super().__init__(parent)
        self.setWindowTitle('note')
        self.result_text = None
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(heading('note'))
        if count > 1:
            layout.addWidget(caption(f'for {count} images'))
        self.edit = QtWidgets.QPlainTextEdit(text)
        self.edit.setPlaceholderText('write a note for this image')
        self.edit.setMinimumSize(360, 140)
        layout.addWidget(self.edit)
        save = primary('save note')
        cancel = QtWidgets.QPushButton('cancel')
        remove = QtWidgets.QPushButton('remove note')
        remove.setVisible(bool(text))
        save.clicked.connect(self.on_save)
        cancel.clicked.connect(self.reject)
        remove.clicked.connect(self.on_remove)
        layout.addLayout(button_row(remove, None, cancel, save))
        QtGui.QShortcut(QtGui.QKeySequence('Ctrl+Return'), self, self.on_save)
        self.edit.setFocus()
        self.edit.moveCursor(QtGui.QTextCursor.MoveOperation.End)

    def on_save(self):
        self.result_text = self.edit.toPlainText().strip()
        self.accept()

    def on_remove(self):
        self.result_text = ''
        self.accept()


class TagField(QtWidgets.QLineEdit):
    """Inline field for adding a tag, with completion of existing tags."""

    submitted = QtCore.pyqtSignal(str)

    def __init__(self, existing):
        super().__init__()
        self.setPlaceholderText('new tag')
        completer = QtWidgets.QCompleter(existing, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setCompleter(completer)
        self.returnPressed.connect(self._submit)

    def _submit(self):
        tag = ' '.join(self.text().strip().lower().split())
        if tag:
            self.submitted.emit(tag)
