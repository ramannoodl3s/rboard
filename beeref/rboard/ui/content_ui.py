# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Content understanding in the app: the AI features install, indexing images
(in the background once the model is installed), grouping by content,
searching by meaning and custom-tag suggestions."""

import logging
from statistics import median

import numpy as np
from PyQt6 import QtCore, QtWidgets
from PyQt6.QtCore import Qt

from beeref import commands, fileio, widgets
from beeref.items import BeeTextItem
from beeref.rboard import analysis, layouts, semantic
from beeref.rboard.ui.dialogs import button_row, caption, heading, primary


logger = logging.getLogger(__name__)

BATCH = 16


class ContentWorker(fileio.ThreadedIO):
    """Runs the image model off the GUI thread. Image data is prepared on
    the GUI thread a batch at a time through a blocking signal."""

    need_batch = QtCore.pyqtSignal(int)
    batch_done = QtCore.pyqtSignal(int)


def _run_index(count, worker):
    errors = []
    worker.begin_processing.emit(count)
    batches = (count + BATCH - 1) // BATCH
    for b in range(batches):
        if worker.canceled:
            break
        worker.batch = None
        worker.need_batch.emit(b)  # blocks until the GUI thread is done
        if worker.batch is not None and len(worker.batch):
            try:
                worker.vectors[b] = semantic.Clip.embed_images(worker.batch)
            except Exception as e:
                logger.exception('Content indexing failed')
                errors.append(str(e))
                break
            worker.batch_done.emit(b)
        worker.progress.emit(min((b + 1) * BATCH, count))
    worker.finished.emit('', errors)


class GroupDialog(QtWidgets.QDialog):
    """Choose how many content groups; names preview live."""

    def __init__(self, parent, vecs, extra_labels=()):
        super().__init__(parent)
        self.vecs = vecs
        self.extra_labels = extra_labels
        self.setWindowTitle('group by content')
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(heading('group by content'))
        layout.addWidget(caption(f'{len(vecs)} images, grouped by what they '
                                 'show. groups are sorted by colour inside.'))
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel('fewer'))
        self.slider = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        top = max(2, min(20, len(vecs)))
        self.slider.setRange(2, top)
        self.slider.setValue(min(top, semantic.default_group_count(
            len(vecs))))
        row.addWidget(self.slider, 1)
        row.addWidget(QtWidgets.QLabel('more'))
        layout.addLayout(row)
        self.preview = caption('')
        self.preview.setMinimumWidth(420)
        layout.addWidget(self.preview)
        self.labels = QtWidgets.QCheckBox('label each group')
        self.labels.setChecked(True)
        layout.addWidget(self.labels)
        ok = primary('group')
        cancel = QtWidgets.QPushButton('cancel')
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        layout.addLayout(button_row(None, cancel, ok))
        self.slider.valueChanged.connect(self.update_preview)
        self.update_preview()

    def update_preview(self):
        k = self.slider.value()
        self.assign, centers = semantic.group(self.vecs, k)
        self.names = semantic.name_groups(centers)
        sizes = [(int((self.assign == g).sum()), self.names[g])
                 for g in range(len(centers))]
        self.preview.setText(' · '.join(
            f'{name} {n}' for n, name in sorted(sizes, reverse=True) if n))


class ContentMixin:
    """Mixed into BeeGraphicsView."""

    # ---------- models ----------

    def rb_ensure_model(self, part, then):
        """Run `then` once the AI features are installed, offering the
        one-time install first if needed."""
        from beeref.rboard.ui.plugins_ui import install_ai
        if semantic.installed(part):
            then()
        else:
            install_ai(self, then)

    # ---------- indexing ----------

    def rb_content_unread(self, items=None):
        items = self.rb_images() if items is None else items
        return [i for i in items if semantic.vector(i) is None]

    def rb_index_content(self, items, then=None, modal=True):
        """Compute embeddings for images that don't have one."""
        if self.is_subboard:
            # Sub board images share their metadata with the main board
            items = [getattr(i, 'link_source', i) for i in items]
            return self.rb_main().rb_index_content(items, then, modal)
        todo = self.rb_content_unread(items)
        if not todo:
            if then:
                then()
            return
        if self.content_running():
            if modal:
                self.rb_notify('still reading image content, '
                               'one moment')
            return
        self.rb_ensure_model('vision',
                             lambda: self._start_index(todo, then, modal))

    def content_running(self):
        worker = getattr(self, 'content_worker', None)
        return worker is not None and worker.isRunning()

    def _start_index(self, todo, then, modal):
        worker = ContentWorker(_run_index, len(todo))
        worker.vectors = {}
        batches = {}

        def prepare(b):
            chunk = todo[b * BATCH:(b + 1) * BATCH]
            arrays, owners = [], []
            for item in chunk:
                try:
                    if item.scene() is not self.scene:
                        continue
                    img = semantic.model_input_image(
                        item.visible_image(semantic.SIZE))
                except RuntimeError:
                    continue  # deleted meanwhile
                if img is not None:
                    arrays.append(semantic.to_array(img, item.grayscale))
                    owners.append(item)
            batches[b] = owners
            worker.batch = np.stack(arrays) if arrays else None

        def done(b):
            for item, vec in zip(batches.pop(b, []), worker.vectors.pop(b)):
                try:
                    if item.scene() is self.scene:
                        semantic.store(item, vec)
                except RuntimeError:
                    pass

        def progress(n):
            self._content_progress = (n, len(todo))
            self.rb_update_status()

        def finished(filename, errors):
            self._content_progress = None
            self.rb_update_status()
            if errors:
                QtWidgets.QMessageBox.warning(
                    self, 'image content', errors[0])
            elif then and not worker.canceled:
                then()

        worker.need_batch.connect(
            prepare, Qt.ConnectionType.BlockingQueuedConnection)
        worker.batch_done.connect(done)
        worker.progress.connect(progress)
        worker.finished.connect(finished)
        self.content_worker = worker
        if modal:
            self.progress = widgets.BeeProgressDialog(
                'reading image content…', worker=worker, parent=self)
        worker.start()

    def rb_index_in_background(self):
        """Index new images quietly when the model is already installed."""
        if (self.is_subboard or not semantic.installed('vision')
                or not self.settings.valueOrDefault('Content/auto_index')
                or self.content_running() or not self.rb_content_unread()):
            return
        self.rb_index_content(self.rb_images(), modal=False)

    def rb_refresh_profile(self):
        """Update the board's norm that moods and styles are judged
        against, when the set of read images changed."""
        indexed, vecs = semantic.matrix(self.rb_images())
        signature = (id(self.scene), len(indexed))
        if signature != getattr(self, '_profile_signature', None):
            self._profile_signature = signature
            semantic.set_profile(vecs)

    def rb_after_images_added(self):
        QtCore.QTimer.singleShot(500, self.rb_index_in_background)

    def on_action_index_content(self):
        todo = self.rb_content_unread()
        if not todo:
            self.rb_notify('all images have been read already')
            return
        self.rb_index_content(self.rb_images(), lambda: self.rb_notify(
            f'read the content of {len(todo)} image(s)'))

    # ---------- grouping ----------

    def on_action_group_content(self):
        self.cancel_active_modes()
        view, how = self.rb_selection_target()
        if view is not self:
            return view.on_action_group_content()
        items = self.rb_selected(images_only=True)
        if len(items) < 2:
            self.rb_notify('add some images first')
            return
        self.rb_index_content(items, lambda: self._group_dialog(items))

    def _group_dialog(self, items):
        indexed, vecs = semantic.matrix(items)
        if len(indexed) < 2:
            return
        dialog = GroupDialog(self, vecs)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        self.rb_arrange_groups(indexed, dialog.assign, dialog.names,
                               dialog.labels.isChecked())

    def rb_arrange_groups(self, items, assign, names, add_labels):
        """Lay groups out as blocks of justified rows, biggest first, each
        sorted by colour, optionally with a label above each block."""
        stats = self.rb_analyze(items)
        if stats is None:
            return
        groups = {}
        for item, g, s in zip(items, assign, stats):
            groups.setdefault(int(g), []).append((item, s))
        order = sorted(groups, key=lambda g: -len(groups[g]))
        rects = {i: self.scene.itemsBoundingRect(items=[i]) for i in items}
        total = sum(r.width() * r.height() for r in rects.values())
        heights = [r.height() for r in rects.values()]
        gap = self.rb_gap(items)
        width = np.sqrt(total) * 1.8
        row_h = median(heights)
        origin = self.scene.itemsBoundingRect(items=items).topLeft()
        label_h = row_h * 0.6 if add_labels else 0

        placed_items, positions, factors, labels = [], [], [], []
        y = origin.y()
        for g in order:
            members = sorted(groups[g], key=lambda p: analysis.sort_key(
                p[1]['dominant'], 'hue'))
            block = [m for m, _ in members]
            sizes = [(rects[m].width(), rects[m].height()) for m in block]
            placements = layouts.justified(sizes, gap, target=width,
                                           height=row_h)
            if add_labels:
                labels.append((f'{names[g]} · {len(block)}',
                               QtCore.QPointF(origin.x(), y)))
                y += label_h * 1.6
            for m, (x, py, f) in zip(block, placements):
                placed_items.append(m)
                positions.append(QtCore.QPointF(origin.x() + x, y + py))
                factors.append(f)
            _, block_h = layouts.bounds(sizes, placements)
            y += block_h + gap * 6

        self.undo_stack.beginMacro('Group by content')
        self.undo_stack.push(commands.ArrangeScaleItems(
            self.scene, placed_items, positions, factors))
        if labels:
            text_items = []
            for text, pos in labels:
                item = BeeTextItem(text)
                item.setScale(label_h / max(item.boundingRect().height(), 1))
                item.setPos(pos)
                text_items.append(item)
            self.undo_stack.push(commands.InsertItems(self.scene,
                                                      text_items))
            self.scene.clearSelection()
        self.undo_stack.endMacro()
        self.on_action_fit_scene()
        self.rb_notify(f'grouped into {len(order)} groups')

    # ---------- searching by meaning ----------

    def rb_semantic_search(self, query):
        """Images that look like the query, or None when unavailable."""
        if len(query) < 3 or not semantic.installed('text'):
            return None
        images = self.rb_images()
        if not any(semantic.vector(i) is not None for i in images):
            return None
        try:
            return semantic.matches_label(query, images)
        except Exception:
            logger.exception('Search by meaning failed')
            return None

    def rb_enable_meaning_search(self):
        def ready():
            self.rb_index_content(self.rb_images(), self._rerun_search)
        self.rb_ensure_model('text', ready)

    def _rerun_search(self):
        if getattr(self, 'search_bar', None) and self.search_bar.isVisible():
            self.search_bar.refresh_meaning(self.rb_meaning_status())
            self.rb_search(self.search_bar.field.text())

    def rb_meaning_status(self):
        """'' when search by meaning is ready, else a button label."""
        if not semantic.installed('text'):
            return 'search by meaning…'
        if self.rb_content_unread():
            return 'read image content…'
        return ''
