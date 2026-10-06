# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Per-image color statistics shared by sorting, palettes, find-by-color
and the duplicate finder.

Every image is reduced to a small thumbnail once; all statistics are
computed from that, so analysing a board of hundreds of images takes
seconds. Colors are clustered and compared in CIELAB, where distances
roughly match perceived differences.
"""

import math

import numpy as np
from PyQt6 import QtGui
from PyQt6.QtCore import Qt


ANALYSIS_VERSION = 2   # 2: adds the 8-colour breakdown ('palette')
THUMB_SIZE = 64      # longest side of the analysis thumbnail
SAMPLE_SIZE = 16     # side of the stored pixel sample (16x16 = 256 colors)
NEUTRAL_CHROMA = 12  # below this LCh chroma a color counts as gray


# ---------- conversions ----------

def qimage_to_rgb(img):
    """QImage -> (H, W, 3) uint8 array, plus an (H, W) alpha array."""
    img = img.convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
    w, h = img.width(), img.height()
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    arr = np.frombuffer(ptr, np.uint8).reshape(h, img.bytesPerLine())
    arr = arr[:, :w * 4].reshape(h, w, 4).copy()
    return arr[..., :3], arr[..., 3]


def rgb_to_lab(rgb):
    """sRGB uint8 array (..., 3) -> CIELAB float array (..., 3), D65."""
    c = np.asarray(rgb, np.float64) / 255
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    m = np.array([[0.4124, 0.3576, 0.1805],
                  [0.2126, 0.7152, 0.0722],
                  [0.0193, 0.1192, 0.9505]])
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16,
                     500 * (f[..., 0] - f[..., 1]),
                     200 * (f[..., 1] - f[..., 2])], axis=-1)


def lab_to_rgb(lab):
    lab = np.asarray(lab, np.float64)
    fy = (lab[..., 0] + 16) / 116
    f = np.stack([fy + lab[..., 1] / 500, fy, fy - lab[..., 2] / 200], -1)
    xyz = np.where(f ** 3 > 0.008856, f ** 3, (f - 16 / 116) / 7.787)
    xyz *= np.array([0.95047, 1.0, 1.08883])
    m = np.array([[3.2406, -1.5372, -0.4986],
                  [-0.9689, 1.8758, 0.0415],
                  [0.0557, -0.2040, 1.0570]])
    c = xyz @ m.T
    c = np.where(c > 0.0031308, 1.055 * np.abs(c) ** (1 / 2.4) - 0.055,
                 12.92 * c)
    return np.clip(np.round(c * 255), 0, 255).astype(np.uint8)


def to_hex(rgb):
    return '#{:02x}{:02x}{:02x}'.format(*(int(v) for v in rgb))


def from_hex(value):
    value = value.lstrip('#')
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


# ---------- clustering ----------

def kmeans(points, k, iterations=12, seed=0):
    """Small k-means with k-means++ seeding. Returns (centers, counts)."""
    points = np.asarray(points, np.float64)
    k = min(k, len(points))
    rng = np.random.default_rng(seed)
    centers = [points[rng.integers(len(points))]]
    for _ in range(1, k):
        d = np.min([((points - c) ** 2).sum(1) for c in centers], axis=0)
        if d.sum() == 0:
            break
        centers.append(points[rng.choice(len(points), p=d / d.sum())])
    centers = np.array(centers)
    for _ in range(iterations):
        labels = ((points[:, None] - centers[None]) ** 2).sum(2).argmin(1)
        new = np.array([points[labels == i].mean(0) if (labels == i).any()
                        else centers[i] for i in range(len(centers))])
        if np.allclose(new, centers):
            break
        centers = new
    labels = ((points[:, None] - centers[None]) ** 2).sum(2).argmin(1)
    counts = np.bincount(labels, minlength=len(centers))
    return centers, counts


# ---------- per-image analysis ----------

def thumbnail_for(image):
    """Downscale the visible part of an image (see
    BeePixmapItem.visible_image)."""
    pm = image
    if max(pm.width(), pm.height()) > 4 * THUMB_SIZE:
        pm = pm.scaled(4 * THUMB_SIZE, 4 * THUMB_SIZE,
                       Qt.AspectRatioMode.KeepAspectRatio,
                       Qt.TransformationMode.FastTransformation)
    pm = pm.scaled(THUMB_SIZE, THUMB_SIZE,
                   Qt.AspectRatioMode.KeepAspectRatio,
                   Qt.TransformationMode.SmoothTransformation)
    return pm


def _dhash(img):
    """64-bit difference hash: robust to resizing and recompression."""
    small = img.scaled(9, 8, Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
    rgb, _ = qimage_to_rgb(small)
    gray = rgb.astype(np.float64) @ np.array([0.299, 0.587, 0.114])
    bits = (gray[:, 1:] > gray[:, :-1]).flatten()
    return int(''.join('1' if b else '0' for b in bits), 2)


def analyze(thumb, grayscale=False):
    """Statistics for one image thumbnail (QImage), as a JSON-able dict."""
    rgb, alpha = qimage_to_rgb(thumb)
    opaque = rgb[alpha > 128]
    if len(opaque) == 0:
        opaque = rgb.reshape(-1, 3)
    if grayscale:
        g = np.round(opaque @ np.array([0.299, 0.587, 0.114]))
        opaque = np.repeat(g[:, None], 3, 1).astype(np.uint8)

    lab = rgb_to_lab(opaque)
    average = lab_to_rgb(lab.mean(0))

    centers, counts = kmeans(lab, 5)
    share = counts / counts.sum()
    chroma = np.hypot(centers[:, 1], centers[:, 2])
    colorful = (chroma > 20) & (centers[:, 0] > 10) & (centers[:, 0] < 97)
    # The dominant color is the biggest colorful cluster if it covers a
    # meaningful part of the image; otherwise simply the biggest cluster.
    if colorful.any() and share[colorful].max() >= 0.06:
        idx = np.flatnonzero(colorful)[share[colorful].argmax()]
    else:
        idx = share.argmax()
    dominant = lab_to_rgb(centers[idx])

    sample = thumb.scaled(SAMPLE_SIZE, SAMPLE_SIZE,
                          Qt.AspectRatioMode.IgnoreAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
    s_rgb, s_alpha = qimage_to_rgb(sample)
    s_rgb = s_rgb[s_alpha > 128]
    if grayscale:
        g = np.round(s_rgb @ np.array([0.299, 0.587, 0.114]))
        s_rgb = np.repeat(g[:, None], 3, 1).astype(np.uint8)

    return {
        'v': ANALYSIS_VERSION,
        # The image's 8 main colours by how much of it each covers; shared
        # by colour tags, colour sorting and the palette
        'palette': [[h, round(share, 4)]
                    for h, share in _palette_from(opaque, 8)],
        'vivid': vivid_hues(lab),
        'average': to_hex(average),
        'dominant': to_hex(dominant),
        'sample': s_rgb.tobytes().hex(),
        'dhash': f'{_dhash(thumb):016x}',
    }


def vivid_hues(lab):
    """Share of the image in strong colour, per 5-degree hue band (for
    accent colours too small to win a palette slot)."""
    chroma = np.hypot(lab[:, 1], lab[:, 2])
    vivid = chroma >= ACCENT_CHROMA
    if not vivid.any():
        return {}
    hue = (np.degrees(np.arctan2(lab[vivid, 2], lab[vivid, 1])) % 360)
    bands = np.bincount((hue // 5).astype(int), minlength=72)
    return {str(i): round(n / len(lab), 4)
            for i, n in enumerate(bands) if n}


def sample_pixels(stats):
    """The stored pixel sample as an (N, 3) uint8 array."""
    return np.frombuffer(bytes.fromhex(stats['sample']),
                         np.uint8).reshape(-1, 3)


# ---------- uses ----------

def sort_key(hex_color, mode):
    """Sort key for 'hue', 'lightness' or 'saturation' ordering."""
    L, a, b = rgb_to_lab(from_hex(hex_color))
    chroma = math.hypot(a, b)
    if mode == 'lightness':
        return (-L,)
    if mode == 'saturation':
        return (-chroma, -L)
    # hue: a rainbow of colorful images first (24 hue bands starting at
    # red, light to dark inside a band), then neutrals from light to dark
    if chroma < NEUTRAL_CHROMA:
        return (1, 0, -L)
    hue = (math.degrees(math.atan2(b, a)) - 20) % 360
    return (0, int(hue // 15), -L)


def _palette_from(pixels, count):
    """[(hex, share)] from (N, 3) uint8 pixels, most prominent first."""
    if len(pixels) > 60000:
        pixels = pixels[np.random.default_rng(0).choice(
            len(pixels), 60000, replace=False)]
    centers, counts = kmeans(rgb_to_lab(pixels), count, iterations=20)
    order = np.argsort(-counts)
    total = max(int(counts.sum()), 1)
    return [(to_hex(lab_to_rgb(centers[i])), float(counts[i]) / total)
            for i in order if counts[i]]


def hamming(hash_a, hash_b):
    return bin(int(hash_a, 16) ^ int(hash_b, 16)).count('1')


# ---------- naming colours ----------

NAMING_CHROMA = 18   # below this, a colour reads as white, grey or black
ACCENT_CHROMA = 35   # a small area this colourful is an accent


def lch(hex_color):
    L, a, b = rgb_to_lab(from_hex(hex_color))
    return L, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360


def breakdown(palette, families):
    """{colour name: share of the image} from a palette, merging clusters
    with the same name. Near-greys are named by lightness. `families`
    maps a chromatic hex colour to its hue name."""
    out = {}
    for hex_, share in palette:
        L, chroma, _ = lch(hex_)
        if chroma < NAMING_CHROMA:
            name = 'white' if L >= 82 else ('black' if L < 22 else 'grey')
        else:
            name = families(hex_)
        out[name] = out.get(name, 0) + share
    return out
