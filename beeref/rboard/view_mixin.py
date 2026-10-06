# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""The R Board actions, mixed into the main view."""

import logging
import os

import numpy as np
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from beeref import commands, fileio, widgets
from beeref.items import BeePixmapItem, BeeTextItem
from beeref.rboard import analysis, attributes, layouts, ocr, pureref, sidecar
from beeref.rboard.palette_item import BeePaletteItem
from beeref.rboard.widgets import (
    FindColorDialog, SearchBar)


logger = logging.getLogger(__name__)

DUPLICATE_DISTANCE = 5    # max differing bits of the 64-bit image hash
DUPLICATE_COLOR_DISTANCE = 8  # max delta E between average colors
OCR_MAX_SIDE = 4000       # larger images are downscaled before OCR


def _qrect(rect):
    return (rect.x(), rect.y(), rect.width(), rect.height())


def _encode(img, fmt):
    data = QtCore.QByteArray()
    buf = QtCore.QBuffer(data)
    buf.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, fmt)
    return data.data()


class OcrWorker(fileio.ThreadedIO):
    """Runs text recognition off the GUI thread. Image data is prepared on
    the GUI thread one image at a time (pixmaps may only be touched
    there) through a blocking signal, so memory use stays flat."""

    need_image = QtCore.pyqtSignal(int)
    text_found = QtCore.pyqtSignal(int, str)


def _run_ocr(count, worker):
    errors = []
    worker.begin_processing.emit(count)
    for i in range(count):
        if worker.canceled:
            break
        worker.image_data = None
        worker.need_image.emit(i)  # blocks until the GUI thread is done
        if worker.image_data:
            try:
                worker.text_found.emit(i, ocr.recognize(worker.image_data))
            except Exception as e:
                logger.exception('Text recognition failed')
                errors.append(str(e))
        worker.progress.emit(i)
    worker.finished.emit('', errors[:1])


def _run_pureref(filename, worker):
    try:
        entries = pureref.read(filename)
    except pureref.PureRefError as e:
        worker.finished.emit(filename, [str(e)])
        return
    except Exception as e:
        logger.exception('PureRef import failed')
        worker.finished.emit(filename, [f'Could not read the board: {e}'])
        return
    worker.begin_processing.emit(len(entries))
    for i, entry in enumerate(entries):
        if entry['type'] == 'image':
            img = QtGui.QImage.fromData(entry['data'])
            entry['image'] = None if img.isNull() else img
            del entry['data']
        worker.progress.emit(i)
        if worker.canceled:
            break
    worker.pureref_entries = entries
    worker.finished.emit(filename, [])


class RBoardMixin:
    """Mixed into BeeGraphicsView."""

    # ---------- helpers ----------

    def rb_selected(self, images_only=False, all_if_empty=False):
        items = self.scene.selectedItems(user_only=True)
        if not items and all_if_empty:
            items = list(self.scene.items_for_save())
        if images_only:
            items = [i for i in items if i.is_image]
        return items

    def rb_images(self):
        return [i for i in self.scene.items_for_save() if i.is_image]

    def rb_notify(self, text):
        # One notification at a time, so messages don't stack up
        old = getattr(self, '_rb_notification', None)
        try:
            if old is not None:
                old.deleteLater()
        except RuntimeError:
            pass  # it already timed out
        self._rb_notification = widgets.BeeNotification(self, text)

    # ---------- board file (.brd) ----------

    def rb_board_data(self):
        """Board-level data kept in .brd files."""
        from beeref import constants
        center = self.mapToScene(self.get_view_center())
        return {
            'format': {'app': constants.APPNAME,
                       'version': constants.VERSION, 'brd': 1},
            'view': {'scale': self.get_scale(),
                     'center': [center.x(), center.y()]},
            'tags': attributes.all_tags(self.rb_images()),
            'subboards': self.subboards.snapshot(),
            'areas': self.rb_screen.snapshot(self.subboards.kept_boards())
            if getattr(self, 'rb_screen', None) else [],
        }

    def rb_restore_view(self, data):
        """Go back to where the board was viewed when it was saved.
        Returns False when there's nothing to restore."""
        view = (data or {}).get('view')
        if not view or not self.scene.items():
            return False
        try:
            scale = float(view['scale'])
            x, y = (float(v) for v in view['center'])
        except (KeyError, TypeError, ValueError):
            return False
        if not 1e-4 < scale < 1e4:
            return False
        self.setTransform(QtGui.QTransform.fromScale(scale, scale))
        self.recalc_scene_rect()
        self.centerOn(QtCore.QPointF(x, y))
        return True

    def rb_analyze(self, items):
        """Color statistics for image items, computed once and cached in
        the item's saved metadata."""
        def key(item):
            return [*_qrect(item.crop), bool(item.grayscale),
                    analysis.ANALYSIS_VERSION]

        todo = [i for i in items
                if i.meta.get('analysis', {}).get('key') != key(i)]
        progress = None
        if len(todo) > 20:
            progress = QtWidgets.QProgressDialog(
                'Analysing colors…', 'Cancel', 0, len(todo), self)
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setMinimumDuration(300)
        for n, item in enumerate(todo):
            if progress:
                progress.setValue(n)
                QtWidgets.QApplication.processEvents()
                if progress.wasCanceled():
                    return None
            thumb = analysis.thumbnail_for(item.pixmap(), item.crop)
            stats = analysis.analyze(thumb, grayscale=item.grayscale)
            stats['key'] = key(item)
            item.meta['analysis'] = stats
        if progress:
            progress.close()
        return [i.meta['analysis'] for i in items]

    def rb_place(self, items, placements, center=None, topleft=None):
        """Move (and scale) items to a layout result, centred on `center`
        or starting at `topleft`. Pushes one undoable command."""
        rects = [self.scene.itemsBoundingRect(items=[i]) for i in items]
        sizes = [(r.width(), r.height()) for r in rects]
        width, height = layouts.bounds(sizes, placements)
        if topleft is None:
            topleft = center - QtCore.QPointF(width / 2, height / 2)
        positions = [topleft + QtCore.QPointF(x, y)
                     for x, y, _ in placements]
        factors = [f for _, _, f in placements]
        if all(abs(f - 1) < 1e-9 for f in factors):
            cmd = commands.ArrangeItems(self.scene, items, positions)
        else:
            cmd = commands.ArrangeScaleItems(
                self.scene, items, positions, factors)
        self.undo_stack.push(cmd)

    def rb_gap(self, items):
        gap = self.settings.valueOrDefault('Items/arrange_gap')
        if gap:
            return gap
        # A small gap relative to the items, so layouts don't look cramped
        heights = sorted(self.scene.itemsBoundingRect(items=[i]).height()
                         for i in items)
        return heights[len(heights) // 2] * 0.03

    # ---------- arranging ----------

    def rb_arrange_layout(self, name):
        self.cancel_active_modes()
        items = self.rb_selected()
        if len(items) < 2:
            self.rb_notify(
                'Select the items to arrange first (Ctrl+A for all)')
            return
        rects = [_qrect(self.scene.itemsBoundingRect(items=[i]))
                 for i in items]
        order = layouts.reading_order(rects)
        items = [items[i] for i in order]
        sizes = [(rects[i][2], rects[i][3]) for i in order]
        placements = layouts.LAYOUTS[name](sizes, self.rb_gap(items))
        self.rb_place(items, placements,
                      center=self.scene.get_selection_center())

    def on_action_arrange_justified(self):
        self.rb_arrange_layout('justified')

    def on_action_arrange_masonry(self):
        self.rb_arrange_layout('masonry')

    def on_action_arrange_grid(self):
        self.rb_arrange_layout('grid')

    # ---------- colour study and sorting ----------

    def rb_set_study(self, images, mode):
        """Show the colour study ('value', 'color' or None = off) on
        images."""
        for item in images:
            item.study_mode = mode
            item.update()

    def on_action_color_study(self):
        """Cycle the selected images: value, colour, off."""
        self.cancel_active_modes()
        images = self.rb_selected(images_only=True)
        if not images:
            self.rb_notify('select images for a colour study')
            return
        modes = [None, 'value', 'color']
        current = images[0].study_mode
        mode = modes[(modes.index(current) + 1) % 3]
        self.rb_set_study(images, mode)
        self.rb_notify({None: 'colour study off', 'value': 'value study',
                        'color': 'colour study'}[mode])

    def on_action_sort_color(self):
        from beeref.rboard.ui.colorsort import ColorSortDialog
        self.cancel_active_modes()
        images = self.rb_selected(images_only=True) or self.rb_images()
        if len(images) < 2:
            self.rb_notify('add some images first')
            return
        if self.rb_analyze(images) is None:
            return
        dialog = ColorSortDialog(self, images)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        ordered = dialog.result_images()
        if not ordered:
            return
        if dialog.to_subboard():
            parent = self.board if self.is_subboard else None
            sources = [getattr(i, 'link_source', i) for i in ordered]
            self.rb_manager().open_list(dialog.title(), sources, parent)
            return
        sizes = [(r.width(), r.height()) for r in (
            self.scene.itemsBoundingRect(items=[i]) for i in ordered)]
        topleft = self.scene.itemsBoundingRect(items=ordered).topLeft()
        self.rb_place(ordered, layouts.flow(sizes, self.rb_gap(ordered)),
                      topleft=topleft)
        self.scene.clearSelection()
        for item in ordered:
            item.setSelected(True)

    # ---------- find by color / duplicates ----------

    def on_action_find_by_color(self):
        self.cancel_active_modes()
        images = self.rb_images()
        if not images:
            self.rb_notify('There are no images on the board')
            return
        stats = self.rb_analyze(images)
        if stats is None:
            return
        labs = [analysis.rgb_to_lab(analysis.sample_pixels(s))
                for s in stats]
        previous = self.scene.selectedItems(user_only=True)

        clip = QtWidgets.QApplication.clipboard().text().strip()
        initial = QtGui.QColor(clip.split()[0]) if clip else QtGui.QColor()
        if not initial.isValid():
            initial = QtGui.QColor('#c0392b')

        def select(color, tolerance, coverage):
            target = analysis.rgb_to_lab(
                (color.red(), color.green(), color.blue()))
            self.scene.clearSelection()
            count = 0
            for item, lab in zip(images, labs):
                share = (np.linalg.norm(lab - target, axis=1)
                         <= tolerance).mean()
                if share >= coverage:
                    item.setSelected(True)
                    count += 1
            return count

        dialog = FindColorDialog(self, initial, select)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            if self.scene.has_selection():
                self.on_action_fit_selection()
        else:
            self.scene.clearSelection()
            for item in previous:
                item.setSelected(True)

    def on_action_select_duplicates(self):
        self.cancel_active_modes()
        images = self.rb_images()
        stats = self.rb_analyze(images)
        if stats is None:
            return
        hashes = [int(s['dhash'], 16) for s in stats]
        aspects = [i.crop.width() / max(i.crop.height(), 1) for i in images]
        # Flat images all hash to nearly zero, so also compare color
        colors = analysis.rgb_to_lab(
            [analysis.from_hex(s['average']) for s in stats])
        group = list(range(len(images)))  # union-find

        def root(i):
            while group[i] != i:
                group[i] = group[group[i]]
                i = group[i]
            return i

        for a in range(len(images)):
            for b in range(a + 1, len(images)):
                if (bin(hashes[a] ^ hashes[b]).count('1')
                        <= DUPLICATE_DISTANCE
                        and abs(aspects[a] / aspects[b] - 1) < 0.05
                        and np.linalg.norm(colors[a] - colors[b])
                        < DUPLICATE_COLOR_DISTANCE):
                    group[root(b)] = root(a)

        groups = {}
        for i in range(len(images)):
            groups.setdefault(root(i), []).append(images[i])
        extras = []
        for members in groups.values():
            if len(members) > 1:
                # Keep the highest-resolution copy
                members.sort(key=lambda i: -i.crop.width() * i.crop.height())
                extras.extend(members[1:])

        self.scene.clearSelection()
        for item in extras:
            item.setSelected(True)
        if extras:
            self.rb_notify(
                f'Selected {len(extras)} duplicate(s), keeping the largest '
                'copy of each. Press Delete to remove them.')
        else:
            self.rb_notify('No duplicates found')

    # ---------- text recognition and search ----------

    def rb_run_ocr(self, items, on_done):
        if not ocr.is_available():
            QtWidgets.QMessageBox.warning(
                self, 'Text recognition unavailable',
                'Text recognition needs Windows 10 or 11 with at least one '
                'OCR language installed (Settings → Time & language).')
            return
        results = {}
        worker = OcrWorker(_run_ocr, len(items))

        def prepare(i):
            item = items[i]
            if item.scene() is not self.scene:
                return  # removed from the board meanwhile
            img = item.pixmap().copy(item.crop.toRect()).toImage()
            if max(img.width(), img.height()) > OCR_MAX_SIDE:
                img = img.scaled(OCR_MAX_SIDE, OCR_MAX_SIDE,
                                 Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
            worker.image_data = _encode(img, 'BMP')

        def finished(filename, errors):
            indices = [i for i in sorted(results)
                       if items[i].scene() is self.scene]
            done = [items[i] for i in indices]
            if done:
                self.undo_stack.push(commands.SetItemMeta(
                    done, 'ocr_text', [results[i] for i in indices],
                    'Read text'))
            if errors:
                QtWidgets.QMessageBox.warning(
                    self, 'Text recognition', errors[0])
            on_done(done)

        worker.need_image.connect(
            prepare, Qt.ConnectionType.BlockingQueuedConnection)
        worker.text_found.connect(lambda i, text: results.__setitem__(i, text))
        worker.finished.connect(finished)
        self.ocr_worker = worker
        self.progress = widgets.BeeProgressDialog(
            'Reading text in images…', worker=worker, parent=self)
        worker.start()

    def on_action_extract_text(self):
        self.cancel_active_modes()
        images = self.rb_selected(images_only=True)
        if not images:
            self.rb_notify('Select one or more images first')
            return

        def done(items):
            text = '\n\n'.join(i.meta['ocr_text'] for i in items
                               if i.meta.get('ocr_text'))
            if text:
                QtWidgets.QApplication.clipboard().setText(text)
                self.scene.internal_clipboard = []
                lines = text.count('\n') + 1
                self.rb_notify(f'Copied {lines} line(s) of text')
            else:
                self.rb_notify('No text found')

        self.rb_run_ocr(images, done)

    def rb_unindexed(self):
        return [i for i in self.rb_images() if 'ocr_text' not in i.meta]

    def on_action_index_text(self):
        self.cancel_active_modes()
        todo = self.rb_unindexed()
        if not todo:
            self.rb_notify('All images have been read already')
            return
        self.rb_run_ocr(todo, self.rb_after_index)

    def rb_after_index(self, items):
        found = sum(1 for i in items if i.meta.get('ocr_text'))
        self.rb_notify(f'Read {len(items)} image(s); {found} contain text')
        if getattr(self, 'search_bar', None) and self.search_bar.isVisible():
            self.search_bar.set_unindexed(len(self.rb_unindexed()))
            self.rb_search(self.search_bar.field.text())

    @staticmethod
    def rb_search_text(item):
        if isinstance(item, BeePixmapItem):
            meta = item.meta
            return ' '.join(filter(None, (
                meta.get('ocr_text'), item.filename,
                meta.get('source_url'), meta.get('note'),
                ' '.join(meta.get('tags', [])),
                attributes.search_words(item) if meta.get('analysis')
                else '')))
        if isinstance(item, BeeTextItem):
            return item.toPlainText()
        if isinstance(item, BeePaletteItem):  # from older boards
            return ' '.join(item.colors)
        return ''

    def on_action_find_text(self):
        self.cancel_active_modes()
        if not getattr(self, 'search_bar', None):
            self.search_bar = SearchBar(self)
            self.search_bar.query_changed.connect(self.rb_search)
            self.search_bar.next_requested.connect(self.rb_search_next)
            self.search_bar.index_requested.connect(self.on_action_index_text)
            self.search_bar.meaning_requested.connect(
                self.rb_enable_meaning_search)
            self.search_bar.closed.connect(self.setFocus)
        self.search_matches = []
        self.search_index = -1
        self.search_bar.open(len(self.rb_unindexed()))
        self.search_bar.refresh_meaning(self.rb_meaning_status())

    def rb_search(self, query):
        self.rb_main().rb_refresh_profile()
        words = query.lower().split()
        self.scene.clearSelection()
        self.search_matches = []
        self.search_index = -1
        if words:
            for item in self.scene.items_for_save():
                haystack = self.rb_search_text(item).lower()
                if all(w in haystack for w in words):
                    item.setSelected(True)
                    self.search_matches.append(item)
        text_count = len(self.search_matches)
        # Also images that look like the query (content model)
        looks = self.rb_semantic_search(query.strip()) if words else None
        if looks:
            for item in looks:
                if item not in self.search_matches:
                    item.setSelected(True)
                    self.search_matches.append(item)
        self.search_bar.set_count(
            text_count, query, None if looks is None
            else len(self.search_matches) - text_count)
        self.search_bar.reposition()

    def rb_search_next(self):
        if not self.search_matches:
            return
        self.search_index = (self.search_index + 1) % len(self.search_matches)
        item = self.search_matches[self.search_index]
        self.fit_rect(self.scene.itemsBoundingRect(items=[item]))

    # ---------- source links ----------

    def on_action_open_source(self):
        urls = []
        for item in self.rb_selected(images_only=True):
            url = item.meta.get('source_url')
            if not url and item.filename and item.filename.startswith('http'):
                url = item.filename
            if url and url not in urls:
                urls.append(url)
        if not urls:
            self.rb_notify('The selected images have no source link')
            return
        for url in urls[:10]:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))

    def rb_handle_drop(self, urls):
        """Dropped PureRef boards get imported and dropped folders add
        their images (with source links from a links.txt beside them).
        Returns True if the drop was handled."""
        local = [u.toLocalFile() for u in urls if u.isLocalFile()]
        if local and local[0].lower().endswith('.pur'):
            self.rb_import_pureref(os.path.normpath(local[0]))
            return True
        folders = [p for p in local if os.path.isdir(p)]
        if not folders:
            return False
        files = [p for p in local if os.path.isfile(p)]
        for folder in folders:
            files += sidecar.images_in(folder)
        if not files:
            self.rb_notify('no images in that folder')
            return True
        self.do_insert_images(
            [QtCore.QUrl.fromLocalFile(f) for f in files])
        return True

    # ---------- PureRef ----------

    def on_action_import_pureref(self):
        self.cancel_active_modes()
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            parent=self, caption='Import PureRef board',
            filter='PureRef board (*.pur)')
        if filename:
            self.rb_import_pureref(os.path.normpath(filename))

    def rb_import_pureref(self, filename):
        new_scene = not self.scene.items()
        existing = self.scene.itemsBoundingRect()
        worker = fileio.ThreadedIO(_run_pureref, filename)

        def finished(fname, errors):
            if errors:
                QtWidgets.QMessageBox.warning(
                    self, 'Import PureRef board', errors[0])
                return
            items, skipped = [], 0
            for entry in sorted(worker.pureref_entries,
                                key=lambda e: e['z']):
                x, y, scale, rotation, flip = pureref.decompose(
                    entry['transform'])
                if entry['type'] == 'image':
                    if entry['image'] is None:
                        skipped += 1
                        continue
                    item = BeePixmapItem(entry['image'], entry['name'])
                    item.crop = QtCore.QRectF(*entry['crop'])
                else:
                    item = BeeTextItem(entry['text'])
                    default_px = QtGui.QFontInfo(item.font()).pixelSize()
                    scale *= entry['font_px'] / max(default_px, 1)
                item.setScale(scale)
                item.setRotation(rotation)
                if flip == -1:
                    item.do_flip()
                item.setPos(x, y)
                items.append(item)
            if not items:
                self.rb_notify('The board has no images or notes to import')
                return
            if not existing.isNull():
                # Put the imported board to the right of what's there
                rect = self.scene.itemsBoundingRect(items=items)
                delta = QtCore.QPointF(
                    existing.right() + existing.width() * 0.05 - rect.left(),
                    existing.top() - rect.top())
                for item in items:
                    item.setPos(item.pos() + delta)
            self.undo_stack.push(commands.InsertItems(self.scene, items))
            if new_scene:
                self.on_action_fit_scene()
            else:
                self.on_action_fit_selection()
            self.rb_after_images_added()
            msg = f'Imported {len(items)} item(s)'
            if skipped:
                msg += f'; {skipped} image(s) could not be read'
            self.rb_notify(msg)

        worker.finished.connect(finished)
        self.worker = worker
        self.progress = widgets.BeeProgressDialog(
            f'Importing {os.path.basename(filename)}', worker=worker,
            parent=self)
        worker.start()
