# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Source links for images added from a folder.

A folder can hold a `links.txt` next to its images (the Are.na Grabber
writes one): a line per image, the file name and its source link
separated by a tab. Lines starting with # are comments; a
`# channel: <url>` line names where the whole folder came from.
"""

import os

from PyQt6 import QtGui

LINKS_FILE = 'links.txt'
_cache = {}


def read_links(folder):
    """{file name: source url} and the channel url (or None) for a
    folder, cached by the file's modification time."""
    path = os.path.join(folder, LINKS_FILE)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}, None
    cached = _cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1], cached[2]
    links, channel = {}, None
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.rstrip('\n')
            if line.startswith('#'):
                if line[1:].strip().lower().startswith('channel:'):
                    channel = line.split(':', 1)[1].strip()
                continue
            name, sep, url = line.partition('\t')
            if sep and url.strip():
                links[name.strip()] = url.strip()
    _cache[path] = (mtime, links, channel)
    return links, channel


def apply(item, filename):
    """Give an image added from a file its source link, if its folder
    has one for it."""
    if not filename or filename.startswith('http'):
        return
    links, channel = read_links(os.path.dirname(filename))
    url = links.get(os.path.basename(filename))
    if url:
        item.meta['source_url'] = url
        if channel:
            item.meta['arena_channel'] = channel


def images_in(folder):
    """Image files directly in a folder, sorted by name."""
    formats = {bytes(f).decode().lower()
               for f in QtGui.QImageReader.supportedImageFormats()}
    out = []
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if os.path.isfile(path) and \
                os.path.splitext(name)[1][1:].lower() in formats:
            out.append(path)
    return out
