# This file is part of R Board (a fork of BeeRef), GPL-3.0-or-later.

"""Lets Claude look through the open board with tool calls (see
claude_mcp.py, the MCP server Claude runs, which forwards each call here).

R Board listens on 127.0.0.1 only, on a random port, and writes the port
plus a random token to claude-bridge.json beside the settings file; a
request without the token is dropped. Nothing runs between calls: each
request is one JSON line in, one JSON line out, handled on the GUI thread
from what the board already has in memory (tags, recognised text, notes,
colours, content embeddings, small image copies). Image pixels only go
out when Claude asks to look at specific images, as one small JPEG.
"""

import base64
import hmac
import json
import logging
import os
import secrets

from PyQt6 import QtCore, QtGui, QtNetwork

logger = logging.getLogger(__name__)

SETTING = 'Claude/enabled'
FILENAME = 'claude-bridge.json'
MAX_REQUEST = 64 * 1024
DEFAULT_LIMIT = 20
MAX_LIMIT = 100
MAX_LOOK = 16
THUMB = 256        # one image
CELL = 160         # each image of a contact sheet

_bridge = None


def enabled(settings):
    return settings.value(SETTING, True, type=bool)


def bridge_path():
    from beeref.config import BeeSettings
    return os.path.join(os.path.dirname(BeeSettings().fileName()), FILENAME)


def start(view):
    global _bridge
    if _bridge is None and enabled(view.settings):
        _bridge = Bridge(view)
        if not _bridge.listen():
            _bridge = None
    return _bridge


def stop():
    global _bridge
    if _bridge is not None:
        _bridge.close()
        _bridge = None


def set_enabled(view, on):
    view.settings.setValue(SETTING, on)
    if on:
        start(view)
    else:
        stop()


def is_running():
    return _bridge is not None


class BridgeError(Exception):
    pass


class Bridge(QtCore.QObject):

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.token = secrets.token_hex(16)
        self.server = QtNetwork.QTcpServer(self)
        self.server.newConnection.connect(self.on_connection)
        self.numbers = {}    # uid -> short number Claude uses
        self.board_key = None

    # ---------- connection ----------

    def listen(self):
        if not self.server.listen(
                QtNetwork.QHostAddress(
                    QtNetwork.QHostAddress.SpecialAddress.LocalHost), 0):
            logger.warning('Claude bridge: %s', self.server.errorString())
            return False
        path = bridge_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump({'port': self.server.serverPort(),
                           'token': self.token, 'pid': os.getpid()}, f)
        except OSError:
            logger.exception('Claude bridge: could not write %s', path)
            self.server.close()
            return False
        logger.info('Claude bridge on port %s', self.server.serverPort())
        return True

    def close(self):
        self.server.close()
        path = bridge_path()
        try:
            with open(path, encoding='utf-8') as f:
                mine = json.load(f).get('token') == self.token
            if mine:   # another R Board may have taken over the file
                os.remove(path)
        except (OSError, ValueError):
            pass
        self.deleteLater()

    def on_connection(self):
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            sock.setProperty('buffer', b'')
            sock.readyRead.connect(lambda s=sock: self.on_read(s))
            sock.disconnected.connect(sock.deleteLater)

    def on_read(self, sock):
        data = sock.property('buffer') + bytes(sock.readAll())
        if len(data) > MAX_REQUEST:
            sock.abort()
            return
        if b'\n' not in data:
            sock.setProperty('buffer', data)
            return
        line = data.split(b'\n', 1)[0]
        try:
            request = json.loads(line)
        except ValueError:
            sock.abort()
            return
        if not isinstance(request, dict) or not hmac.compare_digest(
                str(request.get('token', '')), self.token):
            sock.abort()
            return
        reply = self.handle(request.get('tool'), request.get('args') or {})
        sock.write(json.dumps(reply).encode('utf-8') + b'\n')
        sock.disconnectFromHost()

    def handle(self, tool, args):
        handler = getattr(self, f'tool_{tool}', None)
        if handler is None:
            return {'error': f'unknown tool {tool}'}
        try:
            return handler(**args)
        except BridgeError as e:
            return {'error': str(e)}
        except TypeError as e:
            return {'error': f'bad arguments: {e}'}
        except Exception as e:
            logger.exception('Claude bridge: %s failed', tool)
            return {'error': f'{tool} failed: {e}'}

    # ---------- numbering ----------

    def images(self):
        """The main board's images, numbered; renumbers on a new board."""
        from beeref.rboard import links
        view = self.view
        key = (id(view.scene), view.filename)
        if key != self.board_key:
            self.board_key = key
            self.numbers = {}
        out = {}
        for item in view.rb_images():
            uid = links.uid(item)
            if uid not in self.numbers:
                self.numbers[uid] = len(self.numbers) + 1
            out[self.numbers[uid]] = item
        return out

    def pick(self, ids, limit=MAX_LIMIT):
        if isinstance(ids, (int, str)):
            ids = [ids]
        if not ids:
            raise BridgeError('give one or more image numbers')
        images = self.images()
        items, missing = [], []
        for raw in list(ids)[:limit]:
            try:
                n = int(str(raw).lstrip('#'))
            except ValueError:
                missing.append(str(raw))
                continue
            if n in images:
                items.append((n, images[n]))
            else:
                missing.append(f'#{n}')
        if not items:
            raise BridgeError(f'no such image: {", ".join(missing)}')
        return items, missing

    def number_of(self, item):
        from beeref.rboard import links
        return self.numbers.get(links.uid(item))

    # ---------- describing ----------

    @staticmethod
    def short(text, n):
        text = ' '.join(str(text).split())
        return text if len(text) <= n else text[:n - 1] + '…'

    def line(self, n, item):
        """One compact line per image."""
        from beeref.rboard import attributes
        main, tags, auto = attributes.grouped(item)
        parts = [f'#{n}']
        facets = [e[1] for e in main if not e[0].startswith('tone:')]
        looks = [e[1] for e in auto if e[0].startswith('looks:')][:3]
        if facets or looks:
            parts.append(', '.join(facets + looks))
        if tags:
            parts.append('tags: ' + ', '.join(e[1] for e in tags))
        meta = item.meta
        if (meta.get('ocr_text') or '').strip():
            parts.append(f'text: "{self.short(meta["ocr_text"], 40)}"')
        if meta.get('note'):
            parts.append(f'note: {self.short(meta["note"], 40)}')
        name = os.path.basename(item.filename or '')
        if name and not name.startswith('http'):
            parts.append(self.short(name, 48))
        return ' | '.join(parts)

    def lines(self, pairs, offset, limit, header):
        total = len(pairs)
        page = pairs[offset:offset + limit]
        if not page:
            return {'text': f'{header}: nothing'
                    + (f' past {offset}' if offset and total else '')}
        out = [f'{header} ({offset + 1}-{offset + len(page)} of {total})']
        out += [self.line(n, item) for n, item in page]
        if offset + len(page) < total:
            out.append(f'more: offset={offset + len(page)}')
        return {'text': '\n'.join(out)}

    @staticmethod
    def page(offset, limit):
        try:
            offset = max(0, int(offset))
            limit = max(1, min(MAX_LIMIT, int(limit)))
        except (TypeError, ValueError):
            raise BridgeError('offset and limit must be numbers')
        return offset, limit

    # ---------- tools ----------

    def tool_board(self):
        from collections import Counter
        from beeref.rboard import attributes, semantic
        view = self.view
        images = self.images()
        items = list(images.values())
        name = os.path.basename(view.filename) if view.filename \
            else 'unsaved board'
        analysed = sum(1 for i in items if i.meta.get('analysis'))
        with_text = sum(1 for i in items
                        if (i.meta.get('ocr_text') or '').strip())
        embedded = sum(1 for i in items if semantic.vector(i) is not None)
        counts = Counter()
        for item in items:
            for key, label, _, kind in attributes.attributes(item):
                prefix = key.split(':')[0]
                if kind == 'tag' or prefix in attributes.MAIN \
                        or prefix == 'looks':
                    counts[label if kind != 'tag' else f'tag:{label}'] += 1
        out = [f'{name}: {len(items)} images'
               f' ({analysed} analysed, {with_text} with text,'
               f' {embedded} searchable by meaning)']
        if counts:
            out.append('top labels: ' + ', '.join(
                f'{k} {v}' for k, v in counts.most_common(40)))
        boards = view.subboards.tree()
        if boards:
            out.append('sub boards: ' + ', '.join(
                f'{b.title} ({len(b.sources)})' for b in boards[:20]))
        selected = [self.number_of(i) for i in view.rb_selected(True)]
        if selected:
            out.append('selected: ' + ', '.join(
                f'#{n}' for n in selected[:30] if n)
                + (' …' if len(selected) > 30 else ''))
        return {'text': '\n'.join(out)}

    def tool_find(self, query='', offset=0, limit=DEFAULT_LIMIT):
        offset, limit = self.page(offset, limit)
        view = self.view
        images = self.images()
        words = str(query).lower().split()
        want = [w for w in words if not w.startswith('-')]
        avoid = [w[1:] for w in words if w.startswith('-') and len(w) > 1]
        by_item = {id(item): n for n, item in images.items()}

        def text_of(item):
            return view.rb_search_text(item).lower()

        found = []
        for n, item in images.items():
            if not words:
                found.append((n, item))
                continue
            hay = text_of(item)
            if all(w in hay for w in want) and \
                    not any(w in hay for w in avoid):
                found.append((n, item))
        text_count = len(found)
        looks = None
        if want:
            looks = view.rb_semantic_search(' '.join(want))
        if looks:
            seen = {id(i) for _, i in found}
            for item in looks:
                n = by_item.get(id(item))
                if n and id(item) not in seen:
                    hay = text_of(item)
                    if not any(w in hay for w in avoid):
                        found.append((n, item))
        header = (f'{text_count} match text/tags'
                  + (f', {len(found) - text_count} look like it'
                     if looks is not None else '') if words
                  else 'all images')
        return self.lines(found, offset, limit, header)

    def tool_similar(self, id, offset=0, limit=DEFAULT_LIMIT):
        from beeref.rboard import attributes, semantic
        offset, limit = self.page(offset, limit)
        n, item = self.pick(id, 1)[0][0]
        images = self.images()
        v = semantic.vector(item)
        indexed, vecs = semantic.matrix(list(images.values()))
        if v is not None and indexed:
            # Closest first, no cutoff (the board's own rule drops
            # everything below a fixed closeness)
            order = (-(vecs @ v)).argsort()
            ranked = [indexed[i] for i in order]
        else:
            ranked = attributes.similar_to(item, list(images.values()))
        pairs = [(self.number_of(i), i) for i in ranked if i is not item]
        return self.lines([p for p in pairs if p[0]], offset, limit,
                          f'like #{n}')

    def tool_details(self, ids):
        from beeref.rboard import attributes, links
        items, missing = self.pick(ids, 20)
        out = []
        for n, item in items:
            meta = item.meta
            rows = [f'#{n}']
            if item.filename:
                rows.append(f'file: {item.filename}')
            if meta.get('source_url'):
                rows.append(f'source: {meta["source_url"]}')
            src = item.source
            rows.append(f'size: {src.width}x{src.height}')
            labels = [label for key, label, _, kind in
                      attributes.attributes(item) if kind == 'auto'
                      and not key.startswith(('text:', 'note:'))]
            if labels:
                rows.append('labels: ' + ', '.join(labels))
            if meta.get('tags'):
                rows.append('tags: ' + ', '.join(meta['tags']))
            text = (meta.get('ocr_text') or '').strip()
            if text:
                rows.append(f'text: {self.short(text, 400)}')
            if meta.get('note'):
                rows.append(f'note: {self.short(meta["note"], 400)}')
            nums = [self.numbers.get(u) for u in links.targets(item)]
            if any(nums):
                rows.append('links to: ' + ', '.join(
                    f'#{x}' for x in nums if x))
            out.append('\n'.join(rows))
        if missing:
            out.append('not found: ' + ', '.join(missing))
        return {'text': '\n\n'.join(out)}

    def tool_look(self, ids):
        items, missing = self.pick(ids, MAX_LOOK)
        if len(items) == 1:
            image = self.thumb(items[0][1], THUMB)
        else:
            image = self.sheet(items)
        buf = QtCore.QBuffer()
        buf.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
        image.save(buf, 'JPEG', 80)
        text = ', '.join(f'#{n}' for n, _ in items)
        if missing:
            text += ' (not found: ' + ', '.join(missing) + ')'
        return {'text': text, 'image': base64.b64encode(
            bytes(buf.data())).decode('ascii')}

    @staticmethod
    def thumb(item, side):
        img = item.visible_image(min_side=0)
        if img.isNull():
            img = QtGui.QImage(side, side, QtGui.QImage.Format.Format_RGB32)
            img.fill(QtGui.QColor('gray'))
        return img.scaled(
            side, side, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation)

    def sheet(self, items):
        cols = min(4, len(items))
        rows = (len(items) + cols - 1) // cols
        label_h = 20
        sheet = QtGui.QImage(cols * CELL, rows * (CELL + label_h),
                             QtGui.QImage.Format.Format_RGB32)
        sheet.fill(QtGui.QColor(30, 30, 30))
        p = QtGui.QPainter(sheet)
        font = p.font()
        font.setPixelSize(14)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QtGui.QColor('white'))
        for i, (n, item) in enumerate(items):
            x = (i % cols) * CELL
            y = (i // cols) * (CELL + label_h)
            t = self.thumb(item, CELL - 8)
            p.drawImage(x + (CELL - t.width()) // 2,
                        y + (CELL - t.height()) // 2, t)
            p.drawText(QtCore.QRect(x, y + CELL, CELL, label_h),
                       QtCore.Qt.AlignmentFlag.AlignCenter, f'#{n}')
        p.end()
        return sheet

    def tool_act(self, action, ids, text=''):
        view = self.view
        items, missing = self.pick(ids)
        found = [item for _, item in items]
        count = f'{len(found)} image{"" if len(found) == 1 else "s"}'
        text = str(text or '').strip()
        if action == 'show':
            scene = view.scene
            blocked = scene.blockSignals(True)
            try:
                scene.clearSelection()
                for item in found:
                    item.setSelected(True)
            finally:
                scene.blockSignals(blocked)
            scene.selectionChanged.emit()
            view.fit_rect(scene.itemsBoundingRect(items=found))
            done = f'selected and zoomed to {count}'
        elif action in ('tag', 'untag'):
            if not text:
                raise BridgeError('give the tag as text')
            if action == 'tag':
                view.rb_add_tag(found, text)
                done = f'tagged {count} "{text}"'
            else:
                view.rb_remove_tag(found, text)
                done = f'removed tag "{text}" from {count}'
        elif action == 'note':
            view.rb_meta_change(found, 'note', [text] * len(found),
                                'Claude: note')
            done = f'set the note on {count}'
        elif action == 'subboard':
            title = text or 'from Claude'
            view.subboards.open_list(title, found)
            done = f'opened sub board "{title}" with {count}'
        else:
            raise BridgeError(
                'action must be show, tag, untag, note or subboard')
        view.rb_notify(f'Claude {done}')
        if missing:
            done += ' (not found: ' + ', '.join(missing) + ')'
        return {'text': done}
