# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Images held at about the resolution they're shown at.

Each distinct image is a Source: its original file data (compressed,
also what's saved, so saving never re-encodes) plus decoded copies
("levels") of different widths:

- a base copy, always in memory, which the image tools use. Images up
  to the preset's size are kept whole; bigger ones are shrunk harder the
  bigger they are (with a floor so the tools keep enough detail);
- halved copies of the base, for drawing zoomed out;
- sharper steps (a quarter, half and full width), decoded in the
  background once the image is drawn bigger on screen than its copy.
  They share a memory budget; the least recently drawn go first.

Decoding is pure QImage work, so it runs on worker threads; levels are
only added or dropped on the GUI thread.
"""

import hashlib
import logging
import math
import os
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager

from PyQt6 import QtCore, QtGui


logger = logging.getLogger(__name__)

PRESETS = {
    # base: megapixels kept whole; floor: least megapixels a shrunk base
    # keeps; step: an image steps up when drawn this many times bigger
    # than its copy; budget: MB for the sharper steps
    'performance': {'base': 0.5, 'floor': 0.25, 'step': 1.5,
                    'budget': 1024},
    'balanced': {'base': 1.0, 'floor': 0.35, 'step': 1.0, 'budget': 2048},
    'quality': {'base': 2.0, 'floor': 0.5, 'step': 0.75, 'budget': 4096},
    # everything at full resolution
    'full': {'base': math.inf, 'floor': 0.0, 'step': 1.0, 'budget': 4096},
}
DEFAULT_PRESET = 'balanced'
MIP_LEVELS = 3        # halved copies of the base for zoomed-out drawing
MIN_MIP_WIDTH = 48
KEEP_RECENT = 2.0     # seconds a drawn step is safe from eviction
THREADS = max(1, (os.cpu_count() or 2) - 1)

_preset = None
_exact = 0            # >0 while exporting: draw the exact resolution


def preset():
    global _preset
    if _preset is None:
        from beeref.config import BeeSettings
        name = BeeSettings().valueOrDefault('Items/image_quality')
        _preset = PRESETS.get(name, PRESETS[DEFAULT_PRESET])
    return _preset


def reload_preset():
    global _preset
    _preset = None
    store().evict()


def base_megapixels(mp, p=None):
    """How many megapixels an image of `mp` keeps in its base copy."""
    p = preset() if p is None else p
    if mp <= p['base']:
        return mp
    return min(mp, max(p['floor'], p['base'] * math.sqrt(p['base'] / mp)))


@contextmanager
def exact():
    """Draw images at the exact resolution they need (for exports)."""
    global _exact
    _exact += 1
    try:
        yield
    finally:
        _exact -= 1


# ---------- decoding (any thread) ----------

# Raster images are decoded with Pillow, which lets go of Python's GIL
# while it works, so threads really decode in parallel (Qt's decoders
# called from PyQt hold it), and it can decode JPEGs straight at a
# fraction of their size. Qt decodes what Pillow can't (SVG and rarer
# formats). QImageReader isn't used: on a QBuffer made in Python it calls
# back into Python for every read, which deadlocks between threads.

# Decodes in flight are held to this many pixels in total (one bigger
# image may always go alone), so a board of big images doesn't need
# gigabytes of scratch memory at once
SCRATCH_PIXELS = 48_000_000
_scratch = threading.Condition()
_in_flight = 0


@contextmanager
def _maybe_big(pixels):
    global _in_flight
    with _scratch:
        _scratch.wait_for(
            lambda: _in_flight == 0
            or _in_flight + pixels <= SCRATCH_PIXELS)
        _in_flight += pixels
    try:
        yield
    finally:
        with _scratch:
            _in_flight -= pixels
            _scratch.notify_all()
PIL_FORMATS = {'JPEG': 'jpg', 'PNG': 'png', 'GIF': 'gif', 'WEBP': 'webp'}


def _fast_format(img):
    fmt = (QtGui.QImage.Format.Format_ARGB32_Premultiplied
           if img.hasAlphaChannel() else QtGui.QImage.Format.Format_RGB32)
    return img if img.format() == fmt else img.convertToFormat(fmt)


def _pil_open(data):
    """(Pillow image, format name) or None if Pillow can't read it."""
    import io
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
    except Exception:
        return None
    return im, PIL_FORMATS.get(im.format)


def _pil_ready(im, width=None):
    """Decode (at about `width` for JPEGs), orient, and make RGB(A)."""
    from PIL import Image, ImageOps
    if width and im.format == 'JPEG':
        turned = im.getexif().get(0x0112, 1) in (5, 6, 7, 8)
        w, h = (im.height, im.width) if turned else im.size
        need = (width, max(1, round(h * width / w)))
        im.draft('RGB', need[::-1] if turned else need)
    im.load()
    im = ImageOps.exif_transpose(im)
    alpha = im.mode in ('RGBA', 'LA', 'PA', 'RGBa') or (
        im.mode == 'P' and 'transparency' in im.info)
    if im.mode.startswith('I') or im.mode == 'F':
        im = im.convert('F').point(lambda v: v / 256).convert('L')
    mode = 'RGBA' if alpha else 'RGB'
    return (im if im.mode == mode else im.convert(mode)), alpha, Image


def _to_qimage(im, alpha):
    """Pillow RGB(A) image -> QImage in the format Qt draws fastest."""
    if alpha:
        raw = im.tobytes('raw', 'BGRa')
        fmt = QtGui.QImage.Format.Format_ARGB32_Premultiplied
    else:
        raw = im.convert('RGBA').tobytes('raw', 'BGRA')
        fmt = QtGui.QImage.Format.Format_RGB32
    w, h = im.size
    return QtGui.QImage(raw, w, h, 4 * w, fmt).copy()


def _pil_levels(im, alpha, Image, base_width):
    """Base copy and halved copies, scaled by Pillow."""
    if im.width > base_width:
        im = im.resize((base_width, max(1, round(
            im.height * base_width / im.width))), Image.LANCZOS,
            reducing_gap=3.0)
    levels = {im.width: _to_qimage(im, alpha)}
    for _ in range(MIP_LEVELS):
        width = im.width // 2
        if width < MIN_MIP_WIDTH:
            break
        im = im.reduce(2)
        levels[im.width] = _to_qimage(im, alpha)
    return levels


def _qt_decode(data, width=None):
    img = QtGui.QImage.fromData(data)
    if img.isNull():
        return img
    if width and width < img.width():
        img = _halved(img, width)
    return _fast_format(img)


def decode(data, width=None):
    """Decode image data (EXIF orientation applied), scaled down to
    `width` (None: full size). Any thread."""
    opened = _pil_open(data)
    if opened is None or opened[1] is None:
        return _qt_decode(data, width)
    im = opened[0]
    with _maybe_big(im.width * im.height):
        try:
            im, alpha, Image = _pil_ready(im, width)
            if width and width < im.width:
                im = im.resize(
                    (width, max(1, round(im.height * width / im.width))),
                    Image.LANCZOS, reducing_gap=3.0)
            return _to_qimage(im, alpha)
        except Exception:
            logger.exception('Decoding failed')
    return _qt_decode(data, width)


def _halved(img, width):
    return img.scaledToWidth(
        width, QtCore.Qt.TransformationMode.SmoothTransformation)


def _base_and_mips(full_or_scaled, base_width):
    levels = {}
    base = full_or_scaled
    if base.width() > base_width:
        base = _fast_format(_halved(base, base_width))
    levels[base.width()] = base
    img = base
    for _ in range(MIP_LEVELS):
        width = img.width() // 2
        if width < MIN_MIP_WIDTH:
            break
        img = _halved(img, width)
        levels[img.width()] = img
    return levels


def _base_width(width, height):
    if width < 1 or height < 1:
        return width
    mp = width * height / 1e6
    return max(1, round(width * math.sqrt(base_megapixels(mp) / mp)))


# ---------- sources ----------

class Source:
    """One distinct image."""

    def __init__(self, data=None, fmt=None, width=0, height=0, levels=None,
                 pixels=None):
        self.data = data          # original file bytes, or None
        self.fmt = fmt            # file format of `data` ('jpg', 'png', …)
        self.width = width        # full size, after EXIF orientation
        self.height = height
        self.levels = levels or {}   # width -> QImage
        self.pinned = set(self.levels)   # never evicted
        self.pixels = pixels      # full QImage when there's no file data
        self.pending = set()
        self.gray = {}            # width -> grayscale QImage
        self.items = []           # weak refs of items showing it

    # -- creating --

    @classmethod
    def from_bytes(cls, data):
        """Decode the base copy (any thread). A null Source if the data
        isn't an image."""
        data = bytes(data)
        opened = _pil_open(data)
        if opened is None or opened[1] is None:
            # SVG and formats Pillow doesn't do here: keep Qt's pixels
            # (saved as png or jpg, as BeeRef does)
            return cls.from_image(_qt_decode(data))
        im, fmt = opened
        try:
            # The full size comes from the header; JPEGs decode straight
            # at about the base size
            turned = im.format == 'JPEG' and \
                im.getexif().get(0x0112, 1) in (5, 6, 7, 8)
            width, height = (im.height, im.width) if turned else im.size
            base_width = _base_width(width, height)
            # JPEGs decode near the base size; others need a full decode
            scratch = base_width ** 2 if fmt == 'jpg' else width * height
            with _maybe_big(scratch):
                im, alpha, Image = _pil_ready(im, base_width)
                if im.width < base_width:
                    # A JPEG decoded smaller than its header said (rare)
                    base_width = im.width
                levels = _pil_levels(im, alpha, Image, base_width)
        except Exception:
            logger.exception('Decoding failed')
            return cls.from_image(_qt_decode(data))
        return cls(data, fmt, width, height, levels)

    @classmethod
    def from_image(cls, img):
        """A Source from pixels with no file behind them (pasted images,
        BeeRef API)."""
        if img is None or img.isNull():
            return cls()
        img = _fast_format(img)
        base_width = _base_width(img.width(), img.height())
        levels = _base_and_mips(img, base_width)
        source = cls(None, None, img.width(), img.height(), levels,
                     pixels=img)
        return source

    # -- facts --

    def is_null(self):
        return self.width < 1 or self.height < 1

    @property
    def base_width(self):
        return max(self.pinned) if self.pinned else self.width

    def ratio(self, width):
        return width / self.width if self.width else 1

    def step_widths(self):
        """The sharper steps above the base: a quarter, half and full."""
        base = self.base_width
        return [w for w in (self.width // 4, self.width // 2, self.width)
                if w > base * 1.15] or [self.width]

    def loaded(self, width):
        return width in self.levels or (
            width == self.width and self.pixels is not None)

    def level(self, width):
        if width == self.width and self.pixels is not None:
            return self.pixels
        return self.levels.get(width)

    # -- choosing what to draw --

    def wanted_width(self, scale):
        """The smallest copy that's sharp enough at `scale` device px per
        image px."""
        p = preset()
        need = self.width * scale / p['step']
        for width in sorted(set(self.levels) | set(self.step_widths())):
            if width >= need:
                return width
        return self.width

    def best_loaded(self, wanted):
        """The loaded copy closest to `wanted`, preferring sharper."""
        widths = sorted(self.levels)
        if self.pixels is not None:
            widths.append(self.width)
        bigger = [w for w in widths if w >= wanted]
        width = bigger[0] if bigger else widths[-1]
        return width, self.level(width)

    def full_image(self):
        """Full resolution, decoded now if needed (any thread)."""
        if self.pixels is not None:
            return self.pixels
        img = self.levels.get(self.width)
        if img is not None:
            return img
        if self.data is None:
            return QtGui.QImage()
        return decode(self.data)

    def image_at_least(self, width):
        """A copy at least `width` wide (or full), decoded now if needed;
        not kept (any thread)."""
        loaded = [w for w in self.levels if w >= width]
        if loaded:
            return self.levels[min(loaded)]
        if self.pixels is not None or self.data is None:
            return self.full_image()
        return decode(self.data, min(width, self.width))

    def gray_level(self, width, img, canvas):
        """Grayscale version of a copy (GUI thread). Transparent parts
        get the canvas colour (see BeePixmapItem.grayscale)."""
        cached = self.gray.get(width)
        if cached is None or cached[0] != canvas.rgb():
            out = QtGui.QImage(img.size(), QtGui.QImage.Format.Format_RGB32)
            out.fill(canvas)
            painter = QtGui.QPainter(out)
            painter.drawImage(0, 0, img)
            painter.end()
            cached = (canvas.rgb(), out.convertToFormat(
                QtGui.QImage.Format.Format_Grayscale8))
            self.gray[width] = cached
        return cached[1]

    # -- saving --

    def file_data(self):
        """(bytes, format) to save: the original data when there is."""
        if self.data is not None:
            return self.data, self.fmt
        return None, None

# ---------- the store ----------

class _Signals(QtCore.QObject):
    decoded = QtCore.pyqtSignal(object, int, object)


class Store:
    """Background decoding of sharper steps, and their memory budget."""

    def __init__(self):
        self.signals = _Signals()
        self.signals.decoded.connect(self._on_decoded)
        self.pool = ThreadPoolExecutor(THREADS, 'rboard-image')
        self.steps = OrderedDict()   # (id(source), width) -> (source, t)
        self.used = 0

    def request(self, source, width):
        """Decode a sharper step in the background; items showing the
        source repaint when it's ready."""
        if source.loaded(width) or width in source.pending \
                or source.data is None:
            return
        source.pending.add(width)
        data = source.data

        def work():
            try:
                img = decode(data, width if width < source.width else None)
            except Exception:
                logger.exception('Decoding failed')
                img = QtGui.QImage()
            self.signals.decoded.emit(source, width, img)

        self.pool.submit(work)

    def _on_decoded(self, source, width, img):
        source.pending.discard(width)
        if img.isNull() or width in source.levels:
            return
        # Keyed by the requested width, which is what drawing asks for
        source.levels[width] = img
        self.steps[(id(source), width)] = (source, time.monotonic())
        self.used += img.sizeInBytes()
        self.evict()
        for ref in list(source.items):
            item = ref()
            if item is not None:
                try:
                    item.update()
                except RuntimeError:
                    pass

    def touch(self, source, width):
        key = (id(source), width)
        if key in self.steps:
            self.steps[key] = (source, time.monotonic())
            self.steps.move_to_end(key)

    def evict(self):
        p = preset()
        budget = p['budget'] * (1 << 20)
        now = time.monotonic()
        for key in list(self.steps):
            if self.used <= budget:
                break
            source, used_at = self.steps[key]
            if now - used_at < KEEP_RECENT:
                continue
            self.drop(source, key[1])

    def drop(self, source, width):
        img = source.levels.pop(width, None)
        source.gray.pop(width, None)
        if self.steps.pop((id(source), width), None) and img is not None:
            self.used -= img.sizeInBytes()

_store = None


def store():
    global _store
    if _store is None:
        _store = Store()
    return _store


# ---------- loading many ----------

def digest(data):
    return hashlib.blake2b(data, digest_size=16).digest()


def decode_many(datas, on_progress=None, is_canceled=lambda: False):
    """Sources for many images' data, decoded in parallel; identical data
    gives the same Source. Returns a list aligned with `datas` (None for
    data that isn't an image)."""
    keys = [digest(d) if d is not None else None for d in datas]
    unique = {}
    for key, data in zip(keys, datas):
        if key is not None and key not in unique:
            unique[key] = data
    results = {}
    done = 0
    with ThreadPoolExecutor(THREADS + 1) as pool:
        futures = {pool.submit(Source.from_bytes, data): key
                   for key, data in unique.items()}
        for future in as_completed(futures):
            key = futures[future]
            try:
                source = future.result()
            except Exception:
                logger.exception('Decoding failed')
                source = None
            results[key] = source if source and not source.is_null() \
                else None
            done += 1
            if on_progress:
                on_progress(done, len(unique))
            if is_canceled():
                for f in futures:
                    f.cancel()
                break
    return [results.get(key) for key in keys]
