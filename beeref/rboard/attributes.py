# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Image attributes and tags: the facts the image menu shows and that
sub boards are built from.

Every attribute is a (key, label) pair; images sharing a key form a sub
board. Keys look like 'color:orange', 'shape:square', 'tag:type'.
"""

import math
import os
from collections import OrderedDict
from urllib.parse import urlparse

from beeref.rboard import analysis

SQUARE_TOLERANCE = 0.03   # |aspect - 1| below this counts as square
COVER_TOLERANCE = 0.02    # album covers are square within 2%
MIN_COVER_SIDE = 200      # px; tiny squares are icons, not covers
SIMILAR_DISTANCE = 10     # image-hash bits for "visually similar"

HUE_FAMILIES = [  # (name, CIELAB hue where it starts), measured
    ('pink', 0), ('red', 20), ('orange', 48), ('yellow', 85),
    ('green', 120), ('teal', 180), ('blue', 235), ('purple', 305),
    ('pink', 340),
]
FAMILY_DOTS = {
    'red': '#c4564a', 'orange': '#d0874f', 'yellow': '#d6b85a',
    'green': '#6f9a5b', 'teal': '#4f9a92', 'blue': '#5a7fc0',
    'purple': '#8a6bb8', 'pink': '#c87094', 'neutral': '#9a9a9a',
    'white': '#ececec', 'grey': '#8c8c8c', 'black': '#1e1e1e',
}
COLOR_TAG_SHARE = 0.15    # a colour names an image when it covers this much
ACCENT_SHARE = 0.01       # smallest area an accent colour can have


def hue_family(hex_color):
    """The hue name of a colour, however faint."""
    L, a, b = analysis.rgb_to_lab(analysis.from_hex(hex_color))
    hue = math.degrees(math.atan2(b, a)) % 360
    name = HUE_FAMILIES[0][0]
    for family, start in HUE_FAMILIES:
        if hue >= start:
            name = family
    return name


def band_family(band):
    """Hue name for a 5-degree hue band (0 = 0-5 degrees)."""
    hue = band * 5 + 2.5
    name = HUE_FAMILIES[0][0]
    for family, start in HUE_FAMILIES:
        if hue >= start:
            name = family
    return name


def color_tags(stats):
    """(main colour names, accent name or None) for an image: colours
    that cover a good part of it, by area, and a small but strong colour
    if there is one (the blue lights on a dark photo)."""
    palette = stats.get('palette')
    if not palette:
        return [color_family(stats['dominant'])], None
    shares = analysis.breakdown(palette, hue_family)
    ranked = sorted(shares.items(), key=lambda kv: -kv[1])
    main = [name for name, share in ranked
            if share >= COLOR_TAG_SHARE][:3] or [ranked[0][0]]
    # Accent: the hue family with the most strongly coloured pixels,
    # if it isn't one of the main colours already
    vivid = {}
    for band, share in stats.get('vivid', {}).items():
        name = band_family(int(band))
        vivid[name] = vivid.get(name, 0) + share
    accent = None
    for name, share in sorted(vivid.items(), key=lambda kv: -kv[1]):
        if share >= ACCENT_SHARE and name not in main:
            accent = name
            break
    return main, accent


def color_family(hex_color):
    L, a, b = analysis.rgb_to_lab(analysis.from_hex(hex_color))
    if math.hypot(a, b) < analysis.NEUTRAL_CHROMA:
        return 'neutral'
    hue = math.degrees(math.atan2(b, a)) % 360
    name = HUE_FAMILIES[0][0]
    for family, start in HUE_FAMILIES:
        if hue >= start:
            name = family
    return name


def tone(hex_color):
    L = analysis.rgb_to_lab(analysis.from_hex(hex_color))[0]
    return 'light' if L >= 70 else ('dark' if L < 35 else 'mid')


def aspect(item):
    return item.crop.width() / max(item.crop.height(), 1)


def shape(item):
    a = aspect(item)
    if abs(a - 1) < SQUARE_TOLERANCE:
        return 'square'
    return 'landscape' if a > 1 else 'portrait'


def likely_album_cover(item):
    """Square, big enough, and either has text or hasn't been read yet.

    A guess, not recognition: plenty of square images aren't covers.
    """
    if abs(aspect(item) - 1) >= COVER_TOLERANCE:
        return False
    if min(item.crop.width(), item.crop.height()) < MIN_COVER_SIDE:
        return False
    text = item.meta.get('ocr_text')
    return text is None or bool(text.strip())


def channel_name(url):
    slug = urlparse(url).path.rstrip('/').split('/')[-1]
    return slug.replace('-', ' ')


def snippet(text, length=24):
    text = ' '.join(text.split())
    return text if len(text) <= length else text[:length - 1] + '…'


def tags_of(item):
    return list(item.meta.get('tags', []))


def attributes(item):
    """Ordered attribute list for one image: (key, label, dot, kind).

    kind is 'auto' for computed facts, 'tag' for user tags.
    Needs item.meta['analysis'] (see RBoardMixin.rb_analyze).
    """
    stats = item.meta.get('analysis', {})
    out = []
    if stats:
        main, accent = color_tags(stats)
        for name in main:
            out.append((f'color:{name}', name, FAMILY_DOTS[name], 'auto'))
        if accent:
            out.append((f'accent:{accent}', f'accent · {accent}',
                        FAMILY_DOTS[accent], 'auto'))
        t = tone(stats['average'])
        out.append((f'tone:{t}', t, stats['average'], 'auto'))
    from beeref.rboard import semantic
    model = semantic.entries(item)
    if model:
        out.extend(model)
    out.append((f'shape:{shape(item)}', shape(item), None, 'auto'))
    if model is None and likely_album_cover(item):
        # Without the content model, fall back to a shape-based guess
        out.append(('cover:likely', 'likely album cover', None, 'auto'))
    meta = item.meta
    if meta.get('arena_channel'):
        out.append((f'channel:{meta["arena_channel"]}',
                    f'channel · {channel_name(meta["arena_channel"])}',
                    None, 'auto'))
    if meta.get('pureref_board'):
        out.append((f'board:{meta["pureref_board"]}',
                    f'from {meta["pureref_board"]}', None, 'auto'))
    filename = getattr(item, 'filename', None)
    if (filename and not filename.startswith('http')
            and not meta.get('arena_key') and os.path.dirname(filename)):
        folder = os.path.dirname(filename)
        out.append((f'folder:{folder}',
                    f'folder · {os.path.basename(folder) or folder}',
                    None, 'auto'))
    text = meta.get('ocr_text')
    if text and text.strip():
        out.append(('text:yes', f'has text · “{snippet(text)}”', None, 'auto'))
    if meta.get('note'):
        out.append(('note:yes', 'has note', None, 'auto'))
    if meta.get('marks'):
        out.append(('marks:yes', 'has pen marks', None, 'auto'))
    for tag in tags_of(item):
        out.append((f'tag:{tag}', tag, None, 'tag'))
    return out


MAIN = ('color', 'accent', 'tone', 'kind', 'mood', 'style')
HINTS = {'color': 'colour', 'accent': 'colour', 'tone': 'tone', 'kind': 'kind', 'mood': 'mood',
         'style': 'style', 'looks': 'subject', 'shape': 'shape',
         'cover': 'guess'}


def grouped(item):
    """The image's tags in menu order: main ones (colour, tone, kind, mood,
    style), your own tags, then the rest of what was found."""
    main, tags, auto = [], [], []
    for entry in attributes(item):
        prefix = entry[0].split(':')[0]
        if entry[3] == 'tag':
            tags.append(entry)
        elif prefix in MAIN:
            main.append(entry)
        else:
            auto.append(entry)
    main.sort(key=lambda e: MAIN.index(e[0].split(':')[0]))
    return main, tags, auto


def search_words(item):
    """Tag names that search should find the image by."""
    return ' '.join(label for key, label, *_ in attributes(item)
                    if key.split(':')[0] in MAIN + ('looks',))


def keys_of(item):
    return {key for key, *_ in attributes(item)}


def similar_to(item, candidates):
    """Images that look like `item`, incl. itself: by the content model
    when it has seen them, else by image hash + colour."""
    from beeref.rboard import semantic
    by_content = semantic.similar(item, candidates)
    if by_content is not None:
        return by_content
    stats = item.meta.get('analysis')
    if not stats:
        return [item]
    h = int(stats['dhash'], 16)
    lab = analysis.rgb_to_lab(analysis.from_hex(stats['average']))
    out = []
    for other in candidates:
        s = other.meta.get('analysis')
        if not s:
            continue
        if (bin(h ^ int(s['dhash'], 16)).count('1') <= SIMILAR_DISTANCE
                and math.dist(lab, analysis.rgb_to_lab(
                    analysis.from_hex(s['average']))) < 14):
            out.append(other)
    return out


def matching(key, candidates, anchor=None):
    """Images among candidates that have attribute `key`."""
    if key == 'similar':
        return similar_to(anchor, candidates)
    return [c for c in candidates if key in keys_of(c)]


def counts(candidates):
    """key -> number of images with it."""
    result = OrderedDict()
    for item in candidates:
        for key in keys_of(item):
            result[key] = result.get(key, 0) + 1
    return result


def all_tags(candidates):
    seen = []
    for item in candidates:
        for tag in tags_of(item):
            if tag not in seen:
                seen.append(tag)
    return sorted(seen)
