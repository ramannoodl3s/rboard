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

Closing a window caches its layout. Sub boards last for the session,
except saved ones and link trees: those are kept in the board file
(.brd) with their layouts and come back when it's opened.

A sub board is made from one tag, a link tree, or a query: tags its
images must have (all, or any) and tags they mustn't have. A query term
that isn't a tag on the board is matched by meaning with the content
model ("nighttime").
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
    'insert_text', 'paste', 'import_pureref',
}

_ids = itertools.count(1)


def linked_copy(source):
    """A lightweight copy of a main-board image for a sub board."""
    item = BeePixmapItem(source.source, source.filename)  # shared pixels
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
        self.rule = None          # query: {'include', 'exclude', 'mode'}
        self.saved = False        # kept in the board file
        self.description = ''     # shown above the board; links work
        self.window = None

    @property
    def state(self):
        """'area', 'window' or 'closed'."""
        if self.window is None:
            return 'closed'
        return 'area' if hasattr(self.window, 'release') else 'window'

    @property
    def is_tree(self):
        return self.key.startswith('links:')

    @property
    def kept(self):
        """Whether it's saved with the board (trees always are)."""
        return self.saved or self.is_tree

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

    def open_list(self, title, sources, parent=None):
        """A sub board of these images, in this order."""
        board = SubBoard(title, 'list:' + title, list(sources), parent)
        self.boards.append(board)
        self.show(board)
        return board

    def open_query(self, title, rule, candidates, parent=None):
        """A sub board of the images matching a query (see
        `query_matches`)."""
        board = SubBoard(title, 'query:' + title, query_matches(
            rule, candidates), parent)
        board.rule = rule
        self.boards.append(board)
        self.show(board)
        return board

    # -- keeping boards in the board file --

    def kept_boards(self):
        return [b for b in self.tree() if b.kept]

    def snapshot(self):
        """The saved boards and trees, as data for the .brd file."""
        from beeref.rboard import links
        kept = self.kept_boards()
        out = []
        for board in kept:
            if board.window:  # remember the open layout too
                board.headers = board.window.header_snapshot()
                board.layout = board.window.layout_snapshot()
            entry = {
                'title': board.title, 'key': board.key,
                'saved': board.saved, 'rule': board.rule,
                'sources': [links.uid(s) for s in self.live_sources(board)],
                'description': board.description,
                'parent': kept.index(board.parent)
                if board.parent in kept else None,
            }
            if board.layout:
                entry['layout'] = [[links.uid(src), x, y, sc, z]
                                   for src, x, y, sc, z in board.layout
                                   if src.scene() is self.main_view.scene]
                entry['headers'] = [list(h) for h in board.headers]
            if board.rows:
                entry['rows'] = [[links.uid(s) for s in row]
                                 for row in board.rows]
            if board.sections:
                entry['sections'] = [[t, [links.uid(s) for s in srcs]]
                                     for t, srcs in board.sections]
            out.append(entry)
        return out

    def restore(self, entries, images):
        """Bring back saved boards and trees (closed, ready to open)."""
        from beeref.rboard import links
        index = links.by_uid(images)

        def items(uids):
            return [index[u] for u in uids if u in index]

        made = []
        self.restored = made
        for entry in entries or []:
            try:
                parent = made[entry['parent']] \
                    if entry.get('parent') is not None else None
                board = SubBoard(entry['title'], entry['key'],
                                 items(entry['sources']), parent)
                board.saved = bool(entry.get('saved'))
                board.description = entry.get('description') or ''
                board.rule = entry.get('rule')
                if board.rule:  # queries pick up new matching images
                    board.sources = query_matches(board.rule, images)
                if entry.get('layout'):
                    board.layout = [(index[u], x, y, sc, z)
                                    for u, x, y, sc, z in entry['layout']
                                    if u in index]
                    board.headers = [tuple(h) for h in
                                     entry.get('headers', [])]
                if entry.get('rows'):
                    board.rows = [items(r) for r in entry['rows']]
                if entry.get('sections'):
                    board.sections = [(t, items(u))
                                      for t, u in entry['sections']]
            except (KeyError, TypeError, ValueError, IndexError):
                logger.exception('Skipping a saved sub board')
                made.append(None)
                continue
            made.append(board)
            if board.sources:
                self.boards.append(board)
        self.changed.emit()

    def add(self, board):
        if board not in self.boards:
            self.boards.append(board)
            self.changed.emit()

    def set_saved(self, board, saved):
        board.saved = saved
        self.changed.emit()

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
        """Bring a board up: where it already is, else in an area of the
        main window (or a window of its own when there are no areas)."""
        if board.window:
            board.window.focus()
            return
        screen = getattr(self.main_view, 'rb_screen', None)
        if screen is not None and screen.show_board(board) is not None:
            return
        self.pop_out(board)

    def pop_out(self, board):
        """Show a board in a window of its own."""
        from beeref.rboard.subboard_window import SubBoardWindow
        if board.window is not None:
            board.window.close()
        board.window = SubBoardWindow(self, board)
        board.window.show()
        self.changed.emit()

    def dock(self, board):
        """Move a board from its window into an area of the main
        window."""
        if board.window is not None:
            board.window.close()
        self.show(board)

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
        for board in [b for b in self.boards
                      if not b.window and not b.kept]:
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

    def candidates(self, board):
        """The images a board picks from: its parent board's, or the
        main board's."""
        if board.parent is None:
            return self.main_view.rb_images()
        return self.live_sources(board.parent)

    def refresh_views(self):
        """Repaint every open sub board (after linked data changed)."""
        for board in self.boards:
            if board.window:
                board.window.view.scene.update()
        self.main_view.scene.update()


def describe(manager, board, text):
    """Set a board's description (undoable, so the board file shows it's
    changed)."""
    old = board.description

    def apply(value):
        board.description = value
        if board.window is not None:
            board.window.refresh_description()

    manager.main_view.undo_stack.push(ManagerChange(
        'Describe sub board', lambda: apply(text), lambda: apply(old)))


def board_rule(board):
    """The tags a board includes and leaves out: its query, or the one
    tag (colour, shape, folder…) it was opened for. None for lists, link
    trees and similar images."""
    if board.rule is not None:
        return board.rule
    if ':' in board.key and not board.key.startswith(
            ('links:', 'list:', 'query:')):
        return {'include': [board.key], 'exclude': [], 'mode': 'all'}
    return None


def term_label(term):
    """'color:orange' -> 'orange'; plain tags stay as they are."""
    return term.split(':', 1)[1] if ':' in term else term


def rule_title(rule):
    joiner = ' + ' if rule.get('mode', 'all') == 'all' else ' or '
    title = joiner.join(map(term_label, rule['include'])) or 'everything'
    if rule['exclude']:
        title += ' − ' + ', '.join(map(term_label, rule['exclude']))
    return title


RULE_FIELDS = ('rule', 'key', 'title', 'sources', 'sections', 'layout',
               'headers')


def change_rule(manager, board, rule):
    """Give a board new tags to include and leave out: it fills again
    with the images matching them (undoable). A board named after its
    tags is renamed to match."""
    if board.window is not None:
        board.layout = board.window.layout_snapshot()
        board.headers = board.window.header_snapshot()
    before = {f: getattr(board, f) for f in RULE_FIELDS}
    old = board_rule(board)
    after = dict(before, rule=rule, key=f'query:{board.id}',
                 sources=query_matches(rule, manager.candidates(board)),
                 sections=None, layout=None, headers=[])
    if old is not None and board.title in (rule_title(old), board.key):
        after['title'] = rule_title(rule)

    def apply(state):
        for field, value in state.items():
            setattr(board, field, value)
        if board.window is not None:
            board.window.repopulate()
        manager.changed.emit()

    manager.main_view.undo_stack.push(ManagerChange(
        'Change sub board tags', lambda: apply(after), lambda: apply(before)))
    return len(after['sources'])


class ManagerChange(QtGui.QUndoCommand):
    """An undoable change to the sub boards kept in the board file, so
    keeping or removing one marks the board as changed."""

    def __init__(self, text, do, undo):
        super().__init__(text)
        self.do = do
        self.undo_ = undo

    def redo(self):
        self.do()

    def undo(self):
        self.undo_()


def term_index(images):
    """{tag name (lower case): set of attribute keys} over images."""
    out = {}
    for item in images:
        for key, label, *_ in attributes.attributes(item):
            out.setdefault(label.lower(), set()).add(key)
            out.setdefault(key.lower(), set()).add(key)
    return out


def term_matches(term, images, index=None, by_meaning=True):
    """Images having a tag called `term`; terms that aren't tags on the
    board are matched by meaning, when the content model can."""
    term = ' '.join(term.lower().split())
    index = term_index(images) if index is None else index
    keys = index.get(term)
    if keys:
        return [i for i in images if attributes.keys_of(i) & keys]
    if not by_meaning:
        return []
    from beeref.rboard import semantic
    if not semantic.installed('text') or not any(
            semantic.vector(i) is not None for i in images):
        return []
    try:
        return semantic.matches_label(term, images)
    except Exception:
        logger.exception('Matching by meaning failed')
        return []


def query_matches(rule, images, by_meaning=True):
    """Images with all (or any, mode 'any') of rule['include'] and none of
    rule['exclude']. No include terms means every image."""
    index = term_index(images)
    include = [t for t in rule.get('include', []) if t.strip()]
    exclude = [t for t in rule.get('exclude', []) if t.strip()]
    if include:
        sets = [set(map(id, term_matches(t, images, index, by_meaning)))
                for t in include]
        keep = (set.union(*sets) if rule.get('mode') == 'any'
                else set.intersection(*sets))
    else:
        keep = set(map(id, images))
    for term in exclude:
        keep -= set(map(id, term_matches(term, images, index, by_meaning)))
    return [i for i in images if id(i) in keep]


def initial_placements(items, scene, gap):
    """Justified rows for a fresh sub board."""
    sizes = []
    for item in items:
        rect = scene.itemsBoundingRect(items=[item])
        sizes.append((rect.width(), rect.height()))
    return layouts.justified(sizes, gap)
