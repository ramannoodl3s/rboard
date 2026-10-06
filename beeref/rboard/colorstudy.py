# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Colour study: an image reduced to a few flat regions (8 unless you
pick another number), to see its big shapes and which colours or values
dominate them.

The image is worked on at a size that follows its own (half its long
side, within limits), so big images keep their detail. Its colours are
grouped into clusters in CIELAB (where distances match what we see), and
a few passes of a majority filter merge specks into the regions around
them, a bit like a cutout filter. Value mode clusters by lightness alone
and paints each region in the grey of its true lightness (CIELAB L*),
not a black/white threshold.
"""

import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PyQt6 import QtCore, QtGui
from PyQt6.QtCore import Qt

from beeref.rboard import analysis

LEVELS = 8
MIN_LEVELS, MAX_LEVELS = 2, 12
MIN_SIDE, MAX_SIDE = 240, 1600   # long side of the working image (px)
FILTER_PASSES = 3
SAMPLE = 20000      # pixels used to find the clusters
CHUNK = 250_000     # pixels labelled at a time (keeps memory small)
SECONDS_PER_UNIT = 7e-8     # see estimate(); measured on a 12-thread PC


BACKGROUND_AFTER = 1.0   # studies estimated longer run in the background
last_levels = LEVELS     # what the levels slider was last set to


def work_side(width, height):
    """Long side to work at for a visible part this big."""
    return int(min(MAX_SIDE, max(MIN_SIDE, max(width, height) // 2)))


def estimate(width, height, levels=LEVELS):
    """Rough seconds a study of a visible part this big takes."""
    side = work_side(width, height)
    scale = min(1.0, side / max(width, height, 1))
    pixels = width * height * scale * scale
    return 0.05 + pixels * (levels + 4) * SECONDS_PER_UNIT


def _box_sum(a, r):
    """Sum over a (2r+1)x(2r+1) window for each pixel (edges clamped),
    per channel, via cumulative sums."""
    p = np.pad(a, ((r + 1, r), (r + 1, r)) + ((0, 0),) * (a.ndim - 2),
               mode='edge')
    c = p.cumsum(0).cumsum(1)
    h, w = a.shape[:2]
    k = 2 * r + 1
    return (c[k:k + h, k:k + w] - c[:h, k:k + w]
            - c[k:k + h, :w] + c[:h, :w])


def majority(labels, k, radius=2, passes=FILTER_PASSES,
             progress=None):
    """Each pixel takes the most common label around it."""
    for n in range(passes):
        onehot = (labels[..., None] == np.arange(k)).astype(np.float32)
        labels = _box_sum(onehot, radius).argmax(-1)
        if progress:
            progress((n + 1) / passes)
    return labels


def _clusters(features, k, seed=0):
    flat = features.reshape(-1, features.shape[-1])
    sample = flat
    if len(flat) > SAMPLE:
        sample = flat[np.random.default_rng(seed).choice(
            len(flat), SAMPLE, replace=False)]
    centers, _ = analysis.kmeans(sample, k, iterations=15, seed=seed)
    labels = np.empty(len(flat), np.int64)
    for start in range(0, len(flat), CHUNK):
        part = flat[start:start + CHUNK]
        labels[start:start + CHUNK] = (
            (part[:, None, :] - centers) ** 2).sum(-1).argmin(-1)
    return labels.reshape(features.shape[:-1]), len(centers)


def study(img, grayscale=False, mode='color', levels=LEVELS,
          progress=None):
    """(QImage, levels) for a QImage of the visible part, in 'value' or
    'color' mode. levels: [(hex, share, L*)], value levels dark to
    light, colour levels most prominent first. progress(fraction) is
    called as it goes (from whatever thread runs it)."""
    def report(fraction):
        if progress:
            progress(fraction)

    side = work_side(img.width(), img.height())
    small = img
    if max(img.width(), img.height()) > side:
        small = img.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
    rgb, alpha = analysis.qimage_to_rgb(small)
    if grayscale:
        g = np.round(rgb @ np.array([0.299, 0.587, 0.114]))
        rgb = np.repeat(g[..., None], 3, -1).astype(np.uint8)
    lab = analysis.rgb_to_lab(rgb).astype(np.float32)
    # Bigger work sizes smooth over a proportionally bigger window, so
    # regions keep the same feel at any size
    radius = max(2, round(side / 400))
    blur = max(1, round(side / 800))
    # A light blur first, so texture doesn't splinter the regions
    lab = _box_sum(lab, blur) / float((2 * blur + 1) ** 2)
    report(0.15)
    features = lab[..., :1] if mode == 'value' else lab
    labels, k = _clusters(features, levels)
    report(0.4)
    labels = majority(labels, k, radius,
                      progress=lambda f: report(0.4 + 0.5 * f))
    total = labels.size
    # Levels the filter all but merged away join their nearest level
    counts = np.bincount(labels.ravel(), minlength=k)
    means = np.array([features[labels == i].mean(0) if counts[i]
                      else np.full(features.shape[-1], 1e9)
                      for i in range(k)])
    big = np.flatnonzero(counts >= total * 0.005)
    for i in np.flatnonzero((counts > 0) & (counts < total * 0.005)):
        nearest = big[np.argmin(((means[big] - means[i]) ** 2).sum(1))]
        labels[labels == i] = nearest
    found, colors = [], np.zeros((k, 3), np.uint8)
    for i in range(k):
        mask = labels == i
        if not mask.any():
            continue
        mean = lab[mask].mean(0)
        if mode == 'value':
            mean = np.array([mean[0], 0.0, 0.0])
        colors[i] = analysis.lab_to_rgb(mean)
        found.append((i, analysis.to_hex(colors[i]),
                      float(mask.sum()) / total, float(mean[0])))
    if mode == 'value':
        found.sort(key=lambda lv: lv[3])
    else:
        found.sort(key=lambda lv: -lv[2])
    pixels = colors[labels]
    rgba = np.dstack([pixels, alpha]).astype(np.uint8)
    h, w = labels.shape
    image = QtGui.QImage(rgba.tobytes(), w, h, w * 4,
                         QtGui.QImage.Format.Format_RGBA8888).copy()
    report(1.0)
    return image, [(hx, share, L) for _, hx, share, L in found]


class _Signals(QtCore.QObject):
    done = QtCore.pyqtSignal(object, object, object)


class Runner:
    """Studies that take a while, worked out on other threads. The image
    shows as usual until its study is ready."""

    def __init__(self):
        self.signals = _Signals()
        self.signals.done.connect(self._on_done)
        self.pool = ThreadPoolExecutor(max(1, (os.cpu_count() or 2) // 2),
                                       'rboard-study')
        self.jobs = {}    # id(item) -> (key, [progress fraction])

    def start(self, item, key, image_fn, grayscale, mode, levels):
        job = self.jobs.get(id(item))
        if job is not None and job[0] == key:
            return
        progress = [0.0]
        self.jobs[id(item)] = (key, progress)

        def work():
            try:
                result = study(image_fn(), grayscale, mode, levels,
                               progress=lambda f: progress.__setitem__(0, f))
            except Exception:
                import logging
                logging.getLogger(__name__).exception('Colour study failed')
                result = None
            self.signals.done.emit(item, key, result)

        self.pool.submit(work)

    def _on_done(self, item, key, result):
        job = self.jobs.get(id(item))
        if job is not None and job[0] == key:
            del self.jobs[id(item)]
        if result is not None:
            item.store_study(key, result)

    def progress(self, item):
        """0..1 while the item's study is being worked out, else None."""
        job = self.jobs.get(id(item))
        return job[1][0] if job else None


_runner = None


def runner():
    global _runner
    if _runner is None:
        _runner = Runner()
    return _runner
