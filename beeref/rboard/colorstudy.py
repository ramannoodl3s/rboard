# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Colour study: an image reduced to 8 flat regions, to see its big
shapes and which colours or values dominate them.

The image is shrunk, its colours are grouped into 8 clusters in CIELAB
(where distances match what we see), and a few passes of a majority
filter merge specks into the regions around them, a bit like a cutout
filter. Value mode clusters by lightness alone and paints each region in
the grey of its true lightness (CIELAB L*), not a black/white threshold.
"""

import numpy as np
from PyQt6 import QtGui
from PyQt6.QtCore import Qt

from beeref.rboard import analysis

LEVELS = 8
WORK_SIDE = 240     # long side of the working image (px)
FILTER_RADIUS = 2   # majority filter window: (2r + 1) squared
FILTER_PASSES = 3
SAMPLE = 20000      # pixels used to find the clusters


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


def majority(labels, k, radius=FILTER_RADIUS, passes=FILTER_PASSES):
    """Each pixel takes the most common label around it."""
    for _ in range(passes):
        onehot = (labels[..., None] == np.arange(k)).astype(np.float32)
        labels = _box_sum(onehot, radius).argmax(-1)
    return labels


def _clusters(features, k, seed=0):
    flat = features.reshape(-1, features.shape[-1])
    if len(flat) > SAMPLE:
        flat = flat[np.random.default_rng(seed).choice(
            len(flat), SAMPLE, replace=False)]
    centers, _ = analysis.kmeans(flat, k, iterations=15, seed=seed)
    dist = ((features[..., None, :] - centers) ** 2).sum(-1)
    return dist.argmin(-1), len(centers)


def study(img, grayscale=False):
    """{'value': (QImage, levels), 'color': (QImage, levels)} for a QImage.
    levels: [(hex, share, L*)], value levels dark to light, colour levels
    most prominent first."""
    small = img.scaled(WORK_SIDE, WORK_SIDE,
                       Qt.AspectRatioMode.KeepAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
    rgb, alpha = analysis.qimage_to_rgb(small)
    if grayscale:
        g = np.round(rgb @ np.array([0.299, 0.587, 0.114]))
        rgb = np.repeat(g[..., None], 3, -1).astype(np.uint8)
    lab = analysis.rgb_to_lab(rgb)
    # A light blur first, so texture doesn't splinter the regions
    lab = _box_sum(lab, 1) / 9.0
    out = {}
    for mode in ('value', 'color'):
        features = lab[..., :1] if mode == 'value' else lab
        labels, k = _clusters(features, LEVELS)
        labels = majority(labels, k)
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
        levels, colors = [], np.zeros((k, 3), np.uint8)
        for i in range(k):
            mask = labels == i
            if not mask.any():
                continue
            mean = lab[mask].mean(0)
            if mode == 'value':
                mean = np.array([mean[0], 0.0, 0.0])
            colors[i] = analysis.lab_to_rgb(mean)
            levels.append((i, analysis.to_hex(colors[i]),
                           float(mask.sum()) / total, float(mean[0])))
        if mode == 'value':
            levels.sort(key=lambda lv: lv[3])
        else:
            levels.sort(key=lambda lv: -lv[2])
        pixels = colors[labels]
        rgba = np.dstack([pixels, alpha]).astype(np.uint8)
        h, w = labels.shape
        image = QtGui.QImage(rgba.tobytes(), w, h, w * 4,
                             QtGui.QImage.Format.Format_RGBA8888).copy()
        out[mode] = (image, [(hx, share, L) for _, hx, share, L in levels])
    return out
