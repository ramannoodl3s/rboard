# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Sub boards: temporary boards showing a subset of the main board.

A sub board opens in its own window with linked copies of the main
board's images. Linked copies share the original's pixel data (Qt
pixmaps are implicitly shared, so nothing is decoded or copied) and its
metadata dict, so notes, tags and pen marks show everywhere, while
arranging, sorting and removing stay local to the sub board.

Sub boards exist only in memory: closing a window caches its layout,
and everything is discarded when the main board changes or the app
closes.
"""

import itertools
import logging
import os

from PyQt6 import QtCore, QtGui

from beeref.items import BeePixmapItem
from beeref.rboard import attributes, layouts


logger = logging.getLogger(__name__)

# Actions that make no sense on a temporary board
SUBBOARD_DISABLED = {
    'new_scene', 'open', 'save', 'save_as', 'quit', 'insert_images',
    'insert_text', 'paste', 'import_arena', 'sync_arena', 'import_pureref',
}

_ids = itertools.count(1)


def linked_copy(source):
    """A lightweight copy of a main-board image for a sub board."""
    item = BeePixmapItem(QtGui.QImage(), source.filename)
    item.setPixmap(source.pixmap())   # shared pixel data, no copy
    item.crop = source.crop
    item.setOpacity(source.opacity())
    if source.grayscale:
        item.grayscale = True
    item.meta = source.meta           # same dict: notes/tags/marks follow
    item.link_source = source
    item.setRotation(source.rotation())
    if source.flip() == -1:
        item.do_flip()
    return item


class SubBoard:
    def __init__(self, title, key, sources, parent=None):
        self.id = next(_ids)
        self.title = title
        self.key = key
        self.sources = sources
        self.parent = parent      # parent SubBoard, None = main board
        self.layout = None        # cached [(source, x, y, scale, z)]
        self.headers = []         # cached [(text, x, y, scale)]
        self.sections = None      # [(title, sources)] to lay out apart
        self.rows = None          # [[sources]] for a link tree, top down
        self.window = None

    @property
    def state(self):
        return 'open' if self.window else 'cached'

    def depth(self):
        d, p = 0, self.parent
        while p:
            d, p = d + 1, p.parent
        return d


class SubBoardManager(QtCore.QObject):
    changed = QtCore.pyqtSignal()

    def __init__(self, main_view):
        super().__init__(main_view)
        self.main_view = main_view
        self.boards = []

    # -- creating --

    def open_attribute(self, key, label, candidates, parent=None,
                       anchor=None):
        """Open (or bring back) the sub board for `key` among candidates
        (main-board images)."""
        for board in self.boards:
            if board.parent is parent and board.key == key and \
                    (key != 'similar' or board.sources[:1] == [anchor]):
                self.show(board)
                return board
        sources = attributes.matching(key, candidates, anchor)
        if key == 'similar' and anchor in sources:
            # Put the image itself first
            sources.remove(anchor)
            sources.insert(0, anchor)
        sections = None
        if key.startswith('tag:'):
            suggested = self.tag_suggestions(key[4:], candidates, sources)
            if suggested:
                sections = [(f'tagged · {len(sources)}', sources),
                            (f'suggested · {len(suggested)} · right-click '
                             'to add the tag', suggested)]
                sources = sources + suggested
        board = SubBoard(label, key, sources, parent)
        board.sections = sections
        self.boards.append(board)
        self.show(board)
        return board

    def open_links(self, anchor, candidates, parent=None):
        """A sub board with every image linked to `anchor` (directly or
        through others), laid out as a flowchart."""
        from beeref.rboard import links
        key = f'links:{links.uid(anchor)}'
        members = links.tree(anchor, candidates)
        for board in self.boards:
            if board.parent is parent and board.key == key and \
                    set(map(id, board.sources)) == set(map(id, members)):
                self.show(board)
                return board
        for board in [b for b in self.boards if b.key == key
                      and b.parent is parent]:
            self.discard(board)  # the links changed since
        name = anchor.filename and os.path.basename(anchor.filename)
        board = SubBoard(f'links · {name or "image"}', key, members, parent)
        board.rows = links.levels(members)
        self.boards.append(board)
        self.show(board)
        return board

    @staticmethod
    def tag_suggestions(tag, candidates, tagged):
        """Untagged images the content model thinks fit a custom tag, by
        the same rule as built-in labels plus your tagged examples."""
        from beeref.rboard import semantic
        if not any(semantic.vector(c) is not None for c in candidates):
            return []
        try:
            return semantic.suggest_for_tag(
                tag, candidates, tagged,
                use_text=semantic.installed('text'))
        except Exception:
            logger.exception('Tag suggestions failed')
            return []

    def show(self, board):
        if board.window:
            board.window.showNormal()
            board.window.raise_()
            board.window.activateWindow()
            return
        from beeref.rboard.subboard_window import SubBoardWindow
        board.window = SubBoardWindow(self, board)
        board.window.show()
        self.changed.emit()

    # -- lifecycle --

    def live_sources(self, board):
        scene = self.main_view.scene
        return [s for s in board.sources if s.scene() is scene]

    def on_window_closed(self, board, layout):
        board.layout = layout
        board.window = None
        self.changed.emit()

    def discard(self, board):
        for child in [b for b in self.boards if b.parent is board]:
            self.discard(child)
        if board.window:
            window, board.window = board.window, None
            window.discard()
        if board in self.boards:
            self.boards.remove(board)
        self.changed.emit()

    def close_all(self):
        for board in self.boards:
            if board.window:
                board.window.close()

    def discard_cached(self):
        for board in [b for b in self.boards if not b.window]:
            if board in self.boards:
                self.discard(board)

    def clear(self):
        for board in [b for b in self.boards if b.parent is None]:
            self.discard(board)
        self.boards = []
        self.changed.emit()

    def tree(self):
        """Boards in display order (each parent followed by its children)."""
        out = []

        def walk(parent):
            for board in self.boards:
                if board.parent is parent:
                    out.append(board)
                    walk(board)
        walk(None)
        return out

    def refresh_views(self):
        """Repaint every open sub board (after linked data changed)."""
        for board in self.boards:
            if board.window:
                board.window.view.scene.update()
        self.main_view.scene.update()


def initial_placements(items, scene, gap):
    """Justified rows for a fresh sub board."""
    sizes = []
    for item in items:
        rect = scene.itemsBoundingRect(items=[item])
        sizes.append((rect.width(), rect.height()))
    return layouts.justified(sizes, gap)
