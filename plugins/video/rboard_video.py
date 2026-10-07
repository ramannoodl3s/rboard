# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Video frames: scrub through a video and put frames on the board.

Opens video files (or drop one on the board) and links: YouTube and the
other sites yt-dlp knows, or a direct link to a video file. Links are
downloaded once, video only, at up to 1080p, into the plugin's folder
(the last few are kept).

Decoding is PyAV (FFmpeg); downloading is yt-dlp. Both are bundled in the
plugin's lib folder."""

import logging
import os
import re
import threading

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

logger = logging.getLogger(__name__)

VIDEO_EXTS = ('.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v', '.wmv',
              '.flv', '.mpg', '.mpeg', '.ts')
LINK = re.compile(r'^https?://(www\.|m\.)?(youtube\.com/(watch|shorts|live)|'
                  r'youtu\.be/|vimeo\.com/|twitter\.com/|x\.com/|'
                  r'tiktok\.com/|instagram\.com/(p|reel)/)', re.I)
FORMAT = ('bv*[height<=1080][vcodec^=avc1]/bv*[height<=1080]/'
          'b[height<=1080]/bv*/b')
KEEP_DOWNLOADS = 5
STRIP = 12               # thumbnails along the video
THUMB_H = 72
FRAME_QUALITY = 92       # JPEG quality of grabbed frames

api = None


# ---------- helpers ----------

def is_video(text):
    """A dropped path or link this plugin opens."""
    t = text.strip()
    if t.lower().startswith('http'):
        path = t.split('?', 1)[0].lower()
        return bool(LINK.match(t)) or path.endswith(VIDEO_EXTS)
    return t.lower().endswith(VIDEO_EXTS) and os.path.isfile(t)


def clock(seconds):
    seconds = max(0.0, seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(int(m), 60)
    return (f'{h}:{m:02d}:{s:04.1f}' if h else f'{m:02d}:{s:04.1f}')


def link_at(url, seconds):
    """A link that opens the video at this time (YouTube style t=)."""
    if not url or 'youtu' not in url:
        return url
    url = re.sub(r'([?&])t=\d+s?&?', r'\1', url).rstrip('?&')
    return f"{url}{'&' if '?' in url else '?'}t={int(seconds)}s"


def to_qimage(frame, height=None):
    """A PyAV frame as a QImage (scaled to `height` px when given)."""
    if height:
        width = max(2, round(frame.width * height / frame.height))
        frame = frame.reformat(width=width, height=height, format='rgb24')
    arr = frame.to_ndarray(format='rgb24')
    h, w, _ = arr.shape
    return QtGui.QImage(arr.data, w, h, 3 * w,
                        QtGui.QImage.Format.Format_RGB888).copy()


def jpeg_bytes(img):
    data = QtCore.QByteArray()
    buffer = QtCore.QBuffer(data)
    buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    img.save(buffer, 'JPG', FRAME_QUALITY)
    return bytes(data)


# ---------- reading ----------

class Reader:
    """Frames from one video file. Use from one thread at a time."""

    def __init__(self, path):
        import av
        self.path = path
        self.container = av.open(path)
        if not self.container.streams.video:
            raise ValueError('no video in that file')
        self.stream = self.container.streams.video[0]
        self.stream.thread_type = 'AUTO'
        base = self.stream.time_base
        if self.stream.duration:
            self.duration = float(self.stream.duration * base)
        elif self.container.duration:
            self.duration = self.container.duration / 1_000_000
        else:
            self.duration = 0.0
        rate = self.stream.average_rate or self.stream.guessed_rate
        self.fps = float(rate) if rate else 30.0
        self.start = float(self.stream.start_time * base) \
            if self.stream.start_time else 0.0
        self.last = None

    def frame_at(self, seconds):
        """The frame showing at `seconds` (from the start): (frame,
        its time)."""
        seconds = min(max(0.0, seconds), max(self.duration - 0.5 / self.fps,
                                             0.0))
        target = self.start + seconds
        base = self.stream.time_base
        self.container.seek(int(target / base), stream=self.stream,
                            backward=True, any_frame=False)
        best = None
        for frame in self.container.decode(self.stream):
            if frame.time is None:
                continue
            if frame.time > target + 0.5 / self.fps and best is not None:
                break
            best = frame
            if frame.time >= target - 0.5 / self.fps:
                break
        if best is None:
            raise ValueError('no frame there')
        self.last = best
        return best, best.time - self.start

    def next_frame(self):
        """The frame after the last one returned."""
        for frame in self.container.decode(self.stream):
            if frame.time is not None:
                self.last = frame
                return frame, frame.time - self.start
        return self.frame_at(self.duration)

    def close(self):
        self.container.close()


class FrameWorker(QtCore.QThread):
    """Decodes on its own thread. Previews: only the newest request counts
    (scrubbing stays smooth). Grabs and thumbnails queue up."""

    preview = QtCore.pyqtSignal(object, float)          # QImage, seconds
    thumb = QtCore.pyqtSignal(int, float, object)       # index, s, QImage
    grabbed = QtCore.pyqtSignal(float, bytes, object)   # s, jpeg, thumb
    failed = QtCore.pyqtSignal(str)

    def __init__(self, path):
        super().__init__()
        self.path = path
        self.lock = threading.Condition()
        self.want = None          # ('at', s), ('next', None), ('by', s)
        self.jobs = []            # ('grab', s) and ('thumb', i, s)
        self.stopping = False

    def request(self, kind, value):
        with self.lock:
            self.want = (kind, value)
            self.lock.notify()

    def queue(self, *job):
        with self.lock:
            self.jobs.append(job)
            self.lock.notify()

    def clear_jobs(self):
        with self.lock:
            self.jobs = []

    def stop(self):
        with self.lock:
            self.stopping = True
            self.lock.notify()
        self.wait(3000)

    def run(self):
        try:
            reader = Reader(self.path)
        except Exception as e:
            self.failed.emit(f"couldn't open the video: {e}")
            return
        self.reader = reader
        while True:
            with self.lock:
                while not (self.stopping or self.want or self.jobs):
                    self.lock.wait()
                if self.stopping:
                    break
                want, self.want = self.want, None
                job = None if want else self.jobs.pop(0)
            try:
                if want:
                    kind, value = want
                    if kind == 'at':
                        frame, t = reader.frame_at(value)
                    elif kind == 'next' and reader.last is not None:
                        frame, t = reader.next_frame()
                    else:   # 'by': seconds from the frame showing
                        here = (reader.last.time - reader.start
                                if reader.last is not None else 0)
                        frame, t = reader.frame_at(here + (value or 0))
                    self.preview.emit(to_qimage(frame), t)
                elif job[0] == 'thumb':
                    frame, t = reader.frame_at(job[2])
                    self.thumb.emit(job[1], t, to_qimage(frame, THUMB_H))
                elif job[0] == 'grab':
                    frame, t = reader.frame_at(job[1])
                    img = to_qimage(frame)
                    self.grabbed.emit(t, jpeg_bytes(img), img.scaledToHeight(
                        THUMB_H, Qt.TransformationMode.SmoothTransformation))
            except Exception as e:
                logger.exception('Decoding failed')
                self.failed.emit(f'couldn\'t read that part: {e}')
        reader.close()


# ---------- downloading ----------

def downloads_dir():
    path = os.path.join(api.data_dir(), 'downloads')
    os.makedirs(path, exist_ok=True)
    return path


def tidy_downloads(keep=KEEP_DOWNLOADS):
    folder = downloads_dir()
    files = sorted((os.path.join(folder, f) for f in os.listdir(folder)),
                   key=os.path.getmtime, reverse=True)
    for path in files[keep:]:
        try:
            os.remove(path)
        except OSError:
            pass


def download(url, progress, canceled):
    """(file path, title, page link) for a video link, downloaded once."""
    import yt_dlp

    def hook(d):
        if canceled():
            raise yt_dlp.utils.DownloadCancelled()
        if d.get('status') == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate')
            if total:
                progress(d.get('downloaded_bytes', 0) / total)

    options = {
        'format': FORMAT,
        'outtmpl': os.path.join(downloads_dir(), '%(id)s.%(ext)s'),
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'noprogress': True,
        'progress_hooks': [hook],
        'overwrites': False,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        path = info.get('filepath') or ydl.prepare_filename(info)
        if not os.path.isfile(path):
            # The requested downloads report their own file paths
            for entry in info.get('requested_downloads') or []:
                if os.path.isfile(entry.get('filepath', '')):
                    path = entry['filepath']
                    break
    os.utime(path)
    tidy_downloads()
    return path, info.get('title') or 'video', \
        info.get('webpage_url') or url


# ---------- the dialog ----------

class Preview(QtWidgets.QLabel):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(560, 315)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                           QtWidgets.QSizePolicy.Policy.Expanding)
        self.setStyleSheet('background: #111; color: #999;')
        self.setText('open a video file, or paste a link above')
        self.image = None

    def set_image(self, img):
        self.image = img
        self.refresh()

    def refresh(self):
        if self.image is not None:
            self.setPixmap(QtGui.QPixmap.fromImage(self.image.scaled(
                self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh()


class VideoDialog(QtWidgets.QDialog):
    def __init__(self, view, start=None):
        super().__init__(view)
        self.view = view
        self.worker = None
        self.reader_info = None
        self.title = ''
        self.page_link = ''
        self.local_path = ''
        self.position = 0.0
        self.frames = []        # (seconds, jpeg bytes)
        self.setWindowTitle('video frames')
        self.resize(980, 760)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(8)

        top = QtWidgets.QHBoxLayout()
        open_file = QtWidgets.QPushButton('open file…')
        open_file.clicked.connect(self.pick_file)
        top.addWidget(open_file)
        self.link = QtWidgets.QLineEdit()
        self.link.setPlaceholderText('or paste a YouTube or video link')
        self.link.returnPressed.connect(self.load_link)
        top.addWidget(self.link, 1)
        load = QtWidgets.QPushButton('load')
        load.clicked.connect(self.load_link)
        top.addWidget(load)
        layout.addLayout(top)

        self.preview = Preview()
        layout.addWidget(self.preview, 1)

        scrub = QtWidgets.QHBoxLayout()
        self.slider = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        self.slider.setEnabled(False)
        self.slider.valueChanged.connect(self.on_slide)
        scrub.addWidget(self.slider, 1)
        self.time = QtWidgets.QLabel('00:00.0 / 00:00.0')
        scrub.addWidget(self.time)
        layout.addLayout(scrub)

        self.strip = QtWidgets.QListWidget()
        self.strip.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
        self.strip.setFlow(QtWidgets.QListView.Flow.LeftToRight)
        self.strip.setWrapping(False)
        self.strip.setIconSize(QtCore.QSize(THUMB_H * 16 // 9, THUMB_H))
        self.strip.setFixedHeight(THUMB_H + 34)
        self.strip.itemClicked.connect(
            lambda it: self.seek(it.data(Qt.ItemDataRole.UserRole)))
        layout.addWidget(self.strip)

        controls = QtWidgets.QHBoxLayout()
        for text, tip, step in (('◀ frame', '← (Shift+← one second)', -1),
                                ('frame ▶', '→ (Shift+→ one second)', 1)):
            b = QtWidgets.QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _, s=step: self.step_frame(s))
            controls.addWidget(b)
        grab = QtWidgets.QPushButton('grab this frame (G)')
        grab.clicked.connect(self.grab_here)
        controls.addWidget(grab)
        controls.addSpacing(24)
        controls.addWidget(QtWidgets.QLabel('every'))
        self.every = QtWidgets.QDoubleSpinBox()
        self.every.setRange(0.2, 600)
        self.every.setValue(5)
        self.every.setSuffix(' s')
        controls.addWidget(self.every)
        every = QtWidgets.QPushButton('grab')
        every.clicked.connect(self.grab_every)
        controls.addWidget(every)
        controls.addSpacing(12)
        self.count = QtWidgets.QSpinBox()
        self.count.setRange(2, 200)
        self.count.setValue(12)
        controls.addWidget(self.count)
        evenly = QtWidgets.QPushButton('evenly spaced')
        evenly.clicked.connect(self.grab_evenly)
        controls.addWidget(evenly)
        controls.addStretch()
        layout.addLayout(controls)

        layout.addWidget(QtWidgets.QLabel(
            'grabbed frames (Delete removes the selected)'))
        self.grabbed = QtWidgets.QListWidget()
        self.grabbed.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
        self.grabbed.setIconSize(QtCore.QSize(THUMB_H * 16 // 9, THUMB_H))
        self.grabbed.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.grabbed.setFixedHeight(THUMB_H * 2 + 50)
        layout.addWidget(self.grabbed)

        bottom = QtWidgets.QHBoxLayout()
        self.status = QtWidgets.QLabel('')
        bottom.addWidget(self.status, 1)
        self.add = QtWidgets.QPushButton('add frames to board')
        self.add.setProperty('primary', True)
        self.add.setEnabled(False)
        self.add.clicked.connect(self.add_to_board)
        bottom.addWidget(self.add)
        close = QtWidgets.QPushButton('close')
        close.clicked.connect(self.reject)
        bottom.addWidget(close)
        layout.addLayout(bottom)

        if start:
            QtCore.QTimer.singleShot(0, lambda: self.open_any(start))

    # -- opening --

    def open_any(self, text):
        if text.lower().startswith('http'):
            self.link.setText(text)
            self.load_link()
        else:
            self.open_path(text, os.path.splitext(os.path.basename(text))[0])

    def pick_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, 'open a video', '',
            'Videos (' + ' '.join('*' + e for e in VIDEO_EXTS) + ')')
        if path:
            self.open_path(path, os.path.splitext(os.path.basename(path))[0])

    def load_link(self):
        url = self.link.text().strip()
        if not url.lower().startswith('http'):
            self.status.setText('paste a link starting with http')
            return

        def done(result, error):
            if error is not None:
                QtWidgets.QMessageBox.warning(
                    self, 'video frames',
                    f"couldn't get that video: {error}")
                return
            path, title, page = result
            self.open_path(path, title, page)

        api.run_in_background(
            self, 'getting the video…',
            lambda progress, canceled: download(url, progress, canceled),
            done)

    def open_path(self, path, title, page_link=''):
        self.stop_worker()
        self.title, self.page_link, self.local_path = title, page_link, path
        self.strip.clear()
        try:
            reader = Reader(path)   # quick look for length and rate
            self.reader_info = (reader.duration, reader.fps)
            reader.close()
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self, 'video frames', f"couldn't open the video: {e}")
            return
        duration, fps = self.reader_info
        self.worker = FrameWorker(path)
        self.worker.preview.connect(self.on_preview)
        self.worker.thumb.connect(self.on_thumb)
        self.worker.grabbed.connect(self.on_grabbed)
        self.worker.failed.connect(self.status.setText)
        self.worker.start()
        self.slider.blockSignals(True)
        self.slider.setRange(0, max(1, int(duration * 1000)))
        self.slider.setValue(0)
        self.slider.blockSignals(False)
        self.slider.setEnabled(True)
        self.setWindowTitle(f'video frames · {title}')
        self.status.setText(f'{clock(duration)} · {fps:.3g} fps')
        self.seek(0)
        for i in range(STRIP):
            t = duration * (i + 0.5) / STRIP
            item = QtWidgets.QListWidgetItem(clock(t))
            item.setData(Qt.ItemDataRole.UserRole, t)
            self.strip.addItem(item)
            self.worker.queue('thumb', i, t)

    # -- moving --

    def on_slide(self, value):
        self.worker and self.worker.request('at', value / 1000)

    def seek(self, seconds):
        if self.worker:
            self.worker.request('at', seconds)

    def step_frame(self, direction):
        if self.worker:
            if direction > 0:
                self.worker.request('next', None)
            else:
                self.worker.request('by', -1.0 / self.reader_info[1])

    def step_seconds(self, seconds):
        if self.worker:
            self.worker.request('by', seconds)

    def on_preview(self, img, seconds):
        self.position = seconds
        self.preview.set_image(img)
        self.slider.blockSignals(True)
        self.slider.setValue(int(seconds * 1000))
        self.slider.blockSignals(False)
        self.time.setText(f'{clock(seconds)} / {clock(self.reader_info[0])}')

    def on_thumb(self, index, seconds, img):
        item = self.strip.item(index)
        if item is not None:
            item.setIcon(QtGui.QIcon(QtGui.QPixmap.fromImage(img)))

    # -- grabbing --

    def grab_here(self):
        if self.worker:
            self.worker.queue('grab', self.position)

    def grab_times(self, times):
        if not self.worker:
            return
        have = {round(t, 2) for t, _ in self.frames}
        for t in times:
            if round(t, 2) not in have:
                self.worker.queue('grab', t)
        self.status.setText(f'grabbing {len(times)} frames…')

    def grab_every(self):
        if self.reader_info:
            gap = self.every.value()
            n = int(self.reader_info[0] // gap) + 1
            self.grab_times([i * gap for i in range(n)])

    def grab_evenly(self):
        if self.reader_info:
            n, length = self.count.value(), self.reader_info[0]
            self.grab_times([length * (i + 0.5) / n for i in range(n)])

    def on_grabbed(self, seconds, data, thumb):
        if any(abs(seconds - t) < 1e-3 for t, _ in self.frames):
            return
        self.frames.append((seconds, data))
        self.frames.sort(key=lambda f: f[0])
        item = QtWidgets.QListWidgetItem(
            QtGui.QIcon(QtGui.QPixmap.fromImage(thumb)), clock(seconds))
        item.setData(Qt.ItemDataRole.UserRole, seconds)
        self.grabbed.addItem(item)
        self.grabbed.sortItems()
        self.add.setEnabled(True)
        self.add.setText(f'add {len(self.frames)} frames to board'
                         if len(self.frames) > 1 else 'add frame to board')
        self.status.setText(f'{len(self.frames)} grabbed')

    def remove_selected(self):
        for item in self.grabbed.selectedItems():
            t = item.data(Qt.ItemDataRole.UserRole)
            self.frames = [f for f in self.frames if abs(f[0] - t) > 1e-3]
            self.grabbed.takeItem(self.grabbed.row(item))
        self.add.setEnabled(bool(self.frames))

    def add_to_board(self):
        images = []
        for seconds, data in self.frames:
            meta = {'video_time': round(seconds, 3)}
            if self.page_link:
                meta['source_url'] = link_at(self.page_link, seconds)
            else:
                meta['video_file'] = self.local_path
            images.append((data, f'{self.title} @ {clock(seconds)}', meta))
        added = api.add_images(self.view, images)
        api.notify(self.view, f'added {len(added)} frames')
        self.accept()

    # -- keys and closing --

    def keyPressEvent(self, event):
        key, shift = event.key(), bool(
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right) and \
                not self.link.hasFocus():
            sign = 1 if key == Qt.Key.Key_Right else -1
            if shift:
                self.step_seconds(sign * 1.0)
            else:
                self.step_frame(sign)
            return
        if key == Qt.Key.Key_G and not self.link.hasFocus():
            self.grab_here()
            return
        if key == Qt.Key.Key_Delete and self.grabbed.hasFocus():
            self.remove_selected()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            return   # Enter in the link field loads; don't close
        super().keyPressEvent(event)

    def stop_worker(self):
        if self.worker is not None:
            self.worker.stop()
            self.worker = None

    def done(self, result):
        self.stop_worker()
        super().done(result)


# ---------- registering ----------

def open_dialog(view, texts=None):
    dialog = VideoDialog(view, texts[0] if texts else None)
    dialog.exec()


def register(plugin_api):
    global api
    api = plugin_api
    api.add_action('grab frames from video…', open_dialog)
    api.add_drop_handler(is_video, open_dialog)
