# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Arranging images by how alike they are.

Each image gets a feature vector: what it shows (the AI plugin's image
vectors) or, without the plugin, its colours. t-SNE puts alike images
near each other in 2D; that becomes a map (images where t-SNE put them,
pushed apart so none overlap) or a grid (rows of the map, sorted)."""

import math

import numpy as np

from beeref.rboard import analysis


# ---------- features ----------

def colour_features(stats):
    """A 64-bin Lab colour histogram from an image's analysis sample."""
    raw = bytes.fromhex(stats.get('sample', ''))
    rgb = np.frombuffer(raw, np.uint8).reshape(-1, 3) if raw else \
        np.array([analysis.from_hex(stats.get('average', '#808080'))],
                 np.uint8)
    # Clipped, or strong colours fall outside the bins and are dropped
    lab = np.clip(analysis.rgb_to_lab(rgb), [0, -80, -80], [100, 80, 80])
    hist, _ = np.histogramdd(
        lab, bins=(4, 4, 4), range=((0, 100), (-80, 80), (-80, 80)))
    hist = hist.ravel() / max(hist.sum(), 1)
    return np.sqrt(hist)   # Hellinger: big bins don't drown small ones


def normalise(vectors):
    x = np.asarray(vectors, np.float64)
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    return x / np.where(norms > 0, norms, 1)


# ---------- reducing to 2D ----------

def pca(x, dims):
    x = x - x.mean(0)
    dims = min(dims, *x.shape)
    u, s, _ = np.linalg.svd(x, full_matrices=False)
    return u[:, :dims] * s[:dims]


def _affinities(x, perplexity):
    """Symmetric t-SNE input affinities, each row's spread found by
    bisection so its perplexity matches."""
    n = len(x)
    sq = (x ** 2).sum(1)
    d = np.maximum(sq[:, None] + sq[None] - 2 * x @ x.T, 0)
    scale = np.median(d[~np.eye(n, dtype=bool)])
    d = d / scale if scale > 0 else d   # identical images: all zero
    np.fill_diagonal(d, np.inf)
    finite = np.where(np.isfinite(d), d, 0)
    target = math.log(perplexity)
    lo = np.zeros(n)
    hi = np.full(n, np.inf)
    beta = np.ones(n)
    for _ in range(60):
        p = np.exp(-d * beta[:, None])
        total = np.maximum(p.sum(1), 1e-300)
        dp = (finite * p).sum(1)
        entropy = np.log(total) + beta * dp / total
        high = entropy > target       # too spread out: sharpen
        lo = np.where(high, beta, lo)
        hi = np.where(high, hi, beta)
        beta = np.where(np.isinf(hi), beta * 2, (lo + hi) / 2)
    p = p / total[:, None]
    p = (p + p.T) / (2 * n)
    return np.maximum(p, 1e-12)


def tsne(x, perplexity=30, iters=500, seed=0):
    """Exact t-SNE (van der Maaten 2008) in numpy. Fine up to a few
    thousand images."""
    n = len(x)
    if n < 5:
        out = pca(x, 2)
        return np.pad(out, ((0, 0), (0, 2 - out.shape[1])))
    if x.shape[1] > 50:
        x = pca(x, 50)
    p = _affinities(x, min(perplexity, (n - 1) / 3))
    rng = np.random.default_rng(seed)
    y = rng.normal(0, 1e-4, (n, 2))
    step = np.zeros_like(y)
    gains = np.ones_like(y)
    rate = max(n / 12 / 4, 50)
    for it in range(iters):
        exaggerate = 12 if it < 100 else 1
        sq = (y ** 2).sum(1)
        num = 1 / (1 + np.maximum(sq[:, None] + sq[None] - 2 * y @ y.T, 0))
        np.fill_diagonal(num, 0)
        q = np.maximum(num / num.sum(), 1e-12)
        pq = (exaggerate * p - q) * num
        grad = 4 * (np.diag(pq.sum(1)) - pq) @ y
        momentum = 0.5 if it < 250 else 0.8
        same = np.sign(grad) == np.sign(step)
        gains = np.maximum(np.where(same, gains * 0.8, gains + 0.2), 0.01)
        step = momentum * step - rate * gains * grad
        y = y + step
        y -= y.mean(0)
    return y


# ---------- layouts (placements as in layouts.py) ----------

def _scaled_sizes(sizes):
    """Factors giving every image the median area."""
    area = float(np.median([w * h for w, h in sizes]))
    return [math.sqrt(area / max(w * h, 1e-9)) for w, h in sizes]


def map_layout(sizes, points, gap, spread=1.5, passes=300):
    """Images where the points say, all at about the same size, then
    pushed apart until none overlap."""
    factors = _scaled_sizes(sizes)
    w = np.array([s[0] * f for s, f in zip(sizes, factors)]) + gap
    h = np.array([s[1] * f for s, f in zip(sizes, factors)]) + gap
    pts = np.asarray(points, np.float64)
    pts = pts - pts.min(0)
    extent = max(pts.max(), 1e-9)
    side = math.sqrt(len(sizes) * float(np.median(w * h))) * spread
    c = pts / extent * side
    n = len(c)
    for _ in range(passes):
        dx = c[:, None, 0] - c[None, :, 0]
        dy = c[:, None, 1] - c[None, :, 1]
        ox = (w[:, None] + w[None]) / 2 - np.abs(dx)
        oy = (h[:, None] + h[None]) / 2 - np.abs(dy)
        hit = (ox > 0) & (oy > 0)
        np.fill_diagonal(hit, False)
        if not hit.any():
            break
        # Push each overlapping pair apart along the shallower overlap
        along_x = hit & (ox <= oy)
        along_y = hit & (ox > oy)
        tie = np.arange(n)[:, None] < np.arange(n)[None]
        sx = np.where(dx == 0, np.where(tie, -1.0, 1.0), np.sign(dx))
        sy = np.where(dy == 0, np.where(tie, -1.0, 1.0), np.sign(dy))
        c[:, 0] += (np.where(along_x, ox * sx, 0) / 2).sum(1) * 0.6
        c[:, 1] += (np.where(along_y, oy * sy, 0) / 2).sum(1) * 0.6
    top_left = c - np.stack([w, h], 1) / 2
    top_left -= top_left.min(0)
    return [(x + gap / 2, y + gap / 2, f)
            for (x, y), f in zip(top_left, factors)]


def grid_order(points):
    """Reading order for layouts.grid that keeps the map's
    neighbourhoods: the map is stretched over the grid's cells and each
    point takes the nearest free cell, closest pairs first."""
    pts = np.asarray(points, np.float64)
    n = len(pts)
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    span = np.maximum(np.ptp(pts, 0), 1e-12)
    pts = (pts - pts.min(0)) / span * [cols - 1, max(rows - 1, 0)]
    cells = np.array([(i % cols, i // cols) for i in range(n)], np.float64)
    dist = ((pts[:, None] - cells[None]) ** 2).sum(-1)
    taken_p = np.zeros(n, bool)
    taken_c = np.zeros(n, bool)
    cell_of = np.empty(n, np.int64)
    for flat in np.argsort(dist, axis=None, kind='stable'):
        p, c = divmod(int(flat), n)
        if taken_p[p] or taken_c[c]:
            continue
        cell_of[p] = c
        taken_p[p] = taken_c[c] = True
        if taken_p.all():
            break
    return [int(p) for p in np.argsort(cell_of)]
