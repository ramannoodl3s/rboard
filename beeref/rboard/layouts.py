# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Layout algorithms. Pure geometry: they take item sizes in order and
return, per item, a top-left position and a scale factor. Positions are
relative to (0, 0); callers move the result where they want it.
"""

import math
from statistics import median


def reading_order(rects):
    """Indices of rects (x, y, w, h) in reading order: top-to-bottom rows,
    left-to-right within a row. Keeps an existing sort (e.g. by color)
    when re-laying out a board."""
    rows, row, row_bottom = [], [], None
    for i in sorted(range(len(rects)), key=lambda i: rects[i][1]):
        x, y, w, h = rects[i]
        # An item starts a new row once it no longer overlaps vertically
        # with every item of the current row
        if row and y >= row_bottom:
            rows.append(row)
            row, row_bottom = [], None
        row.append(i)
        row_bottom = y + h if row_bottom is None else min(row_bottom, y + h)
    if row:
        rows.append(row)
    return [i for r in rows for i in sorted(r, key=lambda i: rects[i][0])]


def flow(sizes, gap):
    """Rows of unscaled items, in order, wrapping at a roughly 16:10 width."""
    area = sum(w * h for w, h in sizes)
    row_width = max(max(w for w, _ in sizes), math.sqrt(area) * 1.6)
    out, x, y, row_h = [], 0, 0, 0
    for w, h in sizes:
        if x > 0 and x + w > row_width:
            x, y, row_h = 0, y + row_h + gap, 0
        out.append((x, y, 1.0))
        x += w + gap
        row_h = max(row_h, h)
    return out


def justified(sizes, gap, target=None, height=None):
    """Rows of equal height that all end at the same right edge
    (like Are.na or Google Photos). The last row is not stretched.
    `target` sets the row width and `height` the row height, so several
    blocks can share one look."""
    height = height or median(h for _, h in sizes)
    widths = [w * height / h for w, h in sizes]
    total = sum(widths) * height
    target = max(max(widths), target or math.sqrt(total) * 1.6)

    rows, row = [], []
    for i, w in enumerate(widths):
        row.append(i)
        if sum(widths[j] for j in row) + gap * (len(row) - 1) >= target:
            rows.append(row)
            row = []
    last = row

    out = [None] * len(sizes)
    y = 0
    for row in rows + ([last] if last else []):
        natural = sum(widths[j] for j in row)
        gaps = gap * (len(row) - 1)
        fit = (target - gaps) / natural if row is not last else 1.0
        x = 0
        for j in row:
            factor = height / sizes[j][1] * fit
            out[j] = (x, y, factor)
            x += widths[j] * fit + gap
        y += height * fit + gap
    return out


def masonry(sizes, gap):
    """Equal-width columns; each item goes into the currently shortest one."""
    width = median(w for w, _ in sizes)
    heights = [h * width / w for w, h in sizes]
    cols = max(1, min(len(sizes), round(
        math.sqrt(len(sizes) * median(heights) / width * 1.6))))
    col_y = [0.0] * cols
    out = []
    for (w, h), ht in zip(sizes, heights):
        c = col_y.index(min(col_y))
        out.append((c * (width + gap), col_y[c], width / w))
        col_y[c] += ht + gap
    return out


def grid(sizes, gap):
    """Uniform cells; every item is scaled to fit its cell and centred."""
    cell = math.sqrt(median(w * h for w, h in sizes))
    cols = math.ceil(math.sqrt(len(sizes)))
    out = []
    for i, (w, h) in enumerate(sizes):
        factor = cell / max(w, h)
        col, row = i % cols, i // cols
        out.append((col * (cell + gap) + (cell - w * factor) / 2,
                    row * (cell + gap) + (cell - h * factor) / 2,
                    factor))
    return out


LAYOUTS = {
    'flow': flow,
    'justified': justified,
    'masonry': masonry,
    'grid': grid,
}


def bounds(sizes, placements):
    """Width and height of a layout result."""
    right = max(x + w * f for (w, h), (x, y, f) in zip(sizes, placements))
    bottom = max(y + h * f for (w, h), (x, y, f) in zip(sizes, placements))
    return right, bottom
