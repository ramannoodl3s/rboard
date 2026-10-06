# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""The 'new sub board' dialog: tags to include and tags to leave out."""

from PyQt6 import QtCore, QtWidgets
from PyQt6.QtCore import Qt

from beeref.rboard import subboards
from beeref.rboard.ui.dialogs import button_row, caption, heading, primary


def split_terms(text):
    return [' '.join(t.split()) for t in text.split(',') if t.strip()]


class TermsField(QtWidgets.QLineEdit):
    """Comma-separated tags, completing the one being typed."""

    def __init__(self, names, placeholder):
        super().__init__()
        self.setPlaceholderText(placeholder)
        self.completer_ = QtWidgets.QCompleter(sorted(names), self)
        self.completer_.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer_.setFilterMode(Qt.MatchFlag.MatchContains)
        self.completer_.setWidget(self)
        self.completer_.activated.connect(self.insert_completion)
        self.textEdited.connect(self.update_completion)

    def current_term(self):
        return self.text()[:self.cursorPosition()].split(',')[-1].strip()

    def update_completion(self):
        term = self.current_term()
        if not term:
            self.completer_.popup().hide()
            return
        self.completer_.setCompletionPrefix(term)
        self.completer_.complete()

    def insert_completion(self, name):
        head = self.text()[:self.cursorPosition()]
        tail = self.text()[self.cursorPosition():]
        before = head.rsplit(',', 1)[0] + ', ' if ',' in head else ''
        self.setText(f'{before}{name}, {tail.lstrip(", ")}'.rstrip())
        self.setCursorPosition(len(before) + len(name) + 2)

    def keyPressEvent(self, event):
        popup = self.completer_.popup()
        if popup.isVisible() and event.key() in (
                Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
            index = popup.currentIndex()
            if index.isValid():
                self.insert_completion(index.data())
            popup.hide()
            return
        super().keyPressEvent(event)


class SubBoardDialog(QtWidgets.QDialog):
    """Pick tags to include (all or any) and to leave out. Words that
    aren't tags are matched by meaning when the content model can."""

    def __init__(self, parent, images, by_meaning):
        super().__init__(parent)
        self.images = images
        self.by_meaning = by_meaning
        self.setWindowTitle('new sub board')
        names = {label.lower() for label in subboards.term_index(images)
                 if ':' not in label}
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        layout.addWidget(heading('new sub board'))
        layout.addWidget(caption(
            'images with these tags, without those. separate tags with '
            'commas.' + (' words that aren\'t tags are matched by what the '
                         'images show.' if by_meaning else '')))

        form = QtWidgets.QFormLayout()
        form.setSpacing(8)
        self.name = QtWidgets.QLineEdit()
        self.name.setPlaceholderText('named after the tags')
        form.addRow('name', self.name)
        self.include = TermsField(names, 'e.g. yellow, nighttime')
        form.addRow('include', self.include)
        self.mode = QtWidgets.QComboBox()
        self.mode.addItem('images with all of these', 'all')
        self.mode.addItem('images with any of these', 'any')
        form.addRow('', self.mode)
        self.exclude = TermsField(names, 'e.g. blue')
        form.addRow('leave out', self.exclude)
        layout.addLayout(form)
        self.save = QtWidgets.QCheckBox('keep it in this board file')
        layout.addWidget(self.save)
        self.count = caption('')
        layout.addWidget(self.count)

        self.ok = primary('create')
        cancel = QtWidgets.QPushButton('cancel')
        self.ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        layout.addLayout(button_row(None, cancel, self.ok))
        self.setMinimumWidth(460)

        self.timer = QtCore.QTimer(self, singleShot=True, interval=350)
        self.timer.timeout.connect(self.update_count)
        for field in (self.include, self.exclude):
            field.textChanged.connect(self.timer.start)
        self.mode.currentIndexChanged.connect(self.timer.start)
        self.update_count()

    def rule(self):
        return {'include': split_terms(self.include.text()),
                'exclude': split_terms(self.exclude.text()),
                'mode': self.mode.currentData()}

    def title(self):
        if self.name.text().strip():
            return self.name.text().strip()
        rule = self.rule()
        joiner = ' + ' if rule['mode'] == 'all' else ' or '
        title = joiner.join(rule['include']) or 'everything'
        if rule['exclude']:
            title += ' − ' + ', '.join(rule['exclude'])
        return title

    def matches(self):
        return subboards.query_matches(self.rule(), self.images,
                                       by_meaning=self.by_meaning)

    def update_count(self):
        n = len(self.matches())
        self.count.setText(f'{n} image{"" if n == 1 else "s"} match')
        self.ok.setEnabled(n > 0)
