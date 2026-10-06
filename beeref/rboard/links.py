# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Links between images: flowchart arrows from one image to another.

A link belongs to the images, like notes and tags: it's kept in the
source image's metadata as the target's id, so it shows on every board
that has both ends. A "tree" is everything connected by links.
"""

import math
import uuid

from PyQt6 import QtCore


def uid(item):
    """The image's stable id, made on first use."""
    if 'uid' not in item.meta:
        item.meta['uid'] = uuid.uuid4().hex[:12]
    return item.meta['uid']


def targets(item):
    return list(item.meta.get('links', []))


def by_uid(items):
    return {i.meta['uid']: i for i in items if 'uid' in i.meta}


def edges(items):
    """(source, target) pairs among these images."""
    index = by_uid(items)
    out = []
    for item in items:
        for target in targets(item):
            other = index.get(target)
            if other is not None and other is not item:
                out.append((item, other))
    return out


def linked(item, items):
    """Images directly linked to or from `item` (outgoing first)."""
    outgoing = [b for a, b in edges(items) if a is item]
    incoming = [a for a, b in edges(items) if b is item]
    return outgoing, incoming


def tree(item, items):
    """Every image connected to `item` by links, in either direction."""
    neighbours = {}
    for a, b in edges(items):
        neighbours.setdefault(a, []).append(b)
        neighbours.setdefault(b, []).append(a)
    seen = [item]
    queue = [item]
    while queue:
        current = queue.pop(0)
        for other in neighbours.get(current, []):
            if other not in seen:
                seen.append(other)
                queue.append(other)
    return seen


def levels(members):
    """Rows for a flowchart layout: images nothing links to come first,
    then each image one row below the furthest image linking to it."""
    pairs = edges(members)
    incoming = {m: [] for m in members}
    outgoing = {m: [] for m in members}
    for a, b in pairs:
        outgoing[a].append(b)
        incoming[b].append(a)
    roots = [m for m in members if not incoming[m]] or members[:1]
    depth = {m: 0 for m in roots}
    queue = list(roots)
    steps = 0
    while queue and steps < len(members) ** 2 + 10:  # cycles stop here
        steps += 1
        current = queue.pop(0)
        for nxt in outgoing[current]:
            d = depth[current] + 1
            if nxt not in depth or (d > depth[nxt] and d < len(members)):
                depth[nxt] = d
                queue.append(nxt)
    for m in members:
        depth.setdefault(m, 0)
    rows = {}
    for m in members:
        rows.setdefault(depth[m], []).append(m)
    return [rows[d] for d in sorted(rows)]


def border_point(rect, toward):
    """Where the line from rect's centre to `toward` leaves the rect."""
    c = rect.center()
    dx, dy = toward.x() - c.x(), toward.y() - c.y()
    if dx == 0 and dy == 0:
        return QtCore.QPointF(c)
    sx = rect.width() / 2 / abs(dx) if dx else math.inf
    sy = rect.height() / 2 / abs(dy) if dy else math.inf
    s = min(sx, sy)
    return QtCore.QPointF(c.x() + dx * s, c.y() + dy * s)


def arrow_line(rect_a, rect_b, gap=0.0):
    """The arrow between two image rects, from border to border, or None
    when they overlap."""
    if rect_a.intersects(rect_b):
        return None
    start = border_point(rect_a, rect_b.center())
    end = border_point(rect_b, rect_a.center())
    length = math.dist((start.x(), start.y()), (end.x(), end.y()))
    if length <= 2 * gap + 1:
        return None
    ux, uy = (end.x() - start.x()) / length, (end.y() - start.y()) / length
    return (QtCore.QPointF(start.x() + ux * gap, start.y() + uy * gap),
            QtCore.QPointF(end.x() - ux * gap, end.y() - uy * gap))


def distance_to_segment(p, a, b):
    ax, ay, bx, by = a.x(), a.y(), b.x(), b.y()
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    t = 0 if length2 == 0 else max(0, min(1, ((p.x() - ax) * dx
                                              + (p.y() - ay) * dy) / length2))
    return math.hypot(p.x() - (ax + t * dx), p.y() - (ay + t * dy))
