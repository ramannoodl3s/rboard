# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Source finder: right-click an image, "find original…".

SauceNAO (https://saucenao.com) finds art across Pixiv, ArtStation,
DeviantArt, Danbooru, Twitter and more; it needs a free API key, pasted on
the plugins page. Google Lens and Yandex open in the browser as well:
with the image's web link when it has one, else with the image copied to
paste in.

"use this" sets the image's source link and adds the artist as a tag (and
to the sub board's description, if you like). Only the standard library
is used, so the plugin is tiny."""

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid

from PyQt6 import QtCore, QtGui, QtWidgets

logger = logging.getLogger(__name__)

SAUCENAO = 'https://saucenao.com/search.php'
KEY_PAGE = 'https://saucenao.com/user.php?page=search-api'
UPLOAD_SIDE = 1200       # px, longest side sent to SauceNAO
WEAK = 60                # % similarity below which a match is doubtful
ARTIST_FIELDS = ('member_name', 'author_name', 'creator', 'artist',
                 'user_name', 'twitter_user_handle', 'pawoo_user_username',
                 'company')

api = None
_cache = {}              # id(source) -> results, for this session


class SearchError(Exception):
    pass


# ---------- SauceNAO ----------

def _multipart(fields, file_field, file_name, file_data):
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; '
                     f'name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; '
        f'name="{file_field}"; filename="{file_name}"\r\n'
        'Content-Type: image/jpeg\r\n\r\n'.encode()
        + file_data + b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode())
    return b''.join(parts), f'multipart/form-data; boundary={boundary}'


def search(jpeg, key, timeout=30):
    """Results for an image (JPEG bytes), best first. Raises SearchError
    with a message for people."""
    body, ctype = _multipart(
        {'output_type': 2, 'numres': 8, 'db': 999, 'api_key': key},
        'file', 'image.jpg', jpeg)
    request = urllib.request.Request(
        SAUCENAO, data=body,
        headers={'Content-Type': ctype, 'User-Agent': 'R Board'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise SearchError('SauceNAO says too many searches for now; '
                              'wait half a minute (or until tomorrow if '
                              'the daily limit is used up)')
        if e.code == 403:
            raise SearchError("SauceNAO didn't accept the API key; check it "
                              'on the plugins page')
        raise SearchError(f'SauceNAO answered with an error ({e.code})')
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SearchError(f"couldn't reach SauceNAO: {e}")
    except ValueError:
        raise SearchError('SauceNAO sent something unreadable')
    return parse(payload)


def parse(payload):
    header = payload.get('header', {})
    status = header.get('status', 0)
    if status and status < 0:
        raise SearchError(header.get('message') or
                          "SauceNAO couldn't search that image")
    out = []
    for result in payload.get('results') or []:
        head, data = result.get('header', {}), result.get('data', {})
        try:
            similarity = float(head.get('similarity', 0))
        except (TypeError, ValueError):
            similarity = 0.0
        urls = [u for u in data.get('ext_urls') or []
                if isinstance(u, str) and u.startswith('http')]
        source = data.get('source')
        if isinstance(source, str) and source.startswith('http') and \
                source not in urls:
            urls.append(source)
        out.append({
            'similarity': similarity,
            'thumbnail': head.get('thumbnail', ''),
            'site': site_name(head.get('index_name', '')),
            'title': str(data.get('title') or data.get('material') or
                         data.get('eng_name') or ''),
            'artist': artist_of(data),
            'urls': urls,
        })
    return sorted(out, key=lambda r: -r['similarity'])


def site_name(index_name):
    """'Index #5: Pixiv Images - 1234_p0.jpg' -> 'Pixiv Images'."""
    name = re.sub(r'^Index #\d+:\s*', '', index_name)
    return re.sub(r'\s+-\s+\S+$', '', name).strip()


def artist_of(data):
    for field in ARTIST_FIELDS:
        value = data.get(field)
        if isinstance(value, list):
            value = ', '.join(str(v) for v in value if v)
        if value:
            return str(value).strip()
    return ''


# ---------- the image ----------

def jpeg_of(item):
    img = item.visible_image(800)
    if max(img.width(), img.height()) > UPLOAD_SIDE:
        img = img.scaled(UPLOAD_SIDE, UPLOAD_SIDE,
                         QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                         QtCore.Qt.TransformationMode.SmoothTransformation)
    data = QtCore.QByteArray()
    buffer = QtCore.QBuffer(data)
    buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    img.convertToFormat(QtGui.QImage.Format.Format_RGB32).save(
        buffer, 'JPG', 88)
    return bytes(data)


def web_link(item):
    url = item.meta.get('source_url') or ''
    if not url and item.filename and item.filename.startswith('http'):
        url = item.filename
    return url if url.startswith('http') else ''


def search_in_browser(view, item, engine):
    link = web_link(item)
    if link:
        quoted = urllib.parse.quote(link, safe='')
        url = (f'https://lens.google.com/uploadbyurl?url={quoted}'
               if engine == 'lens' else
               f'https://yandex.com/images/search?rpt=imageview&url={quoted}')
        api.notify(view, 'searching with the image\'s web link')
    else:
        QtWidgets.QApplication.clipboard().setImage(item.visible_image(800))
        url = ('https://images.google.com/' if engine == 'lens'
               else 'https://yandex.com/images/')
        api.notify(view, 'image copied: paste it into the search with '
                         'Ctrl+V (or the camera icon)')
    QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))


# ---------- results ----------

class Thumbs(QtCore.QThread):
    loaded = QtCore.pyqtSignal(int, bytes)

    def __init__(self, urls):
        super().__init__()
        self.urls = urls

    def run(self):
        for i, url in enumerate(self.urls):
            if not url:
                continue
            try:
                request = urllib.request.Request(
                    url, headers={'User-Agent': 'R Board'})
                with urllib.request.urlopen(request, timeout=10) as r:
                    self.loaded.emit(i, r.read(2_000_000))
            except Exception:
                pass


class ResultsDialog(QtWidgets.QDialog):
    def __init__(self, view, items, results, message=''):
        super().__init__(view)
        self.view = view
        self.items = items
        self.setWindowTitle('find original')
        self.setMinimumWidth(620)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(10)
        if message:
            note = QtWidgets.QLabel(message)
            note.setWordWrap(True)
            note.setOpenExternalLinks(True)
            layout.addWidget(note)
        self.thumbs = []
        if results:
            box = QtWidgets.QWidget()
            rows = QtWidgets.QVBoxLayout(box)
            rows.setSpacing(8)
            for result in results:
                rows.addWidget(self.row(result))
            rows.addStretch()
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(box)
            scroll.setMinimumHeight(360)
            layout.addWidget(scroll, 1)
            self.loader = Thumbs([r['thumbnail'] for r in results])
            self.loader.loaded.connect(self.set_thumb)
            self.loader.start()
        elif not message:
            layout.addWidget(QtWidgets.QLabel('no matches on SauceNAO.'))
        self.describe = None
        if getattr(view, 'is_subboard', False):
            self.describe = QtWidgets.QCheckBox(
                f'also add the artist to “{view.board.title}”’s description')
            layout.addWidget(self.describe)
        buttons = QtWidgets.QHBoxLayout()
        for label, engine in (('search Google Lens', 'lens'),
                              ('search Yandex', 'yandex')):
            b = QtWidgets.QPushButton(label)
            b.clicked.connect(lambda _, e=engine: search_in_browser(
                view, items[0], e))
            buttons.addWidget(b)
        buttons.addStretch()
        close = QtWidgets.QPushButton('close')
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def row(self, result):
        frame = QtWidgets.QFrame()
        frame.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        h = QtWidgets.QHBoxLayout(frame)
        thumb = QtWidgets.QLabel()
        thumb.setFixedSize(96, 96)
        thumb.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.thumbs.append(thumb)
        h.addWidget(thumb)
        weak = result['similarity'] < WEAK
        lines = [f"<b>{result['similarity']:.0f}%</b> · "
                 f"{_esc(result['site'])}"
                 + (' · <i>weak match</i>' if weak else '')]
        if result['title'] or result['artist']:
            lines.append(_esc(result['title'])
                         + (f" · by <b>{_esc(result['artist'])}</b>"
                            if result['artist'] else ''))
        for url in result['urls'][:2]:
            lines.append(f'<a href="{_esc(url)}">{_esc(url)}</a>')
        text = QtWidgets.QLabel('<br>'.join(lines))
        text.setOpenExternalLinks(True)
        text.setWordWrap(True)
        text.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextBrowserInteraction)
        h.addWidget(text, 1)
        use = QtWidgets.QPushButton('use this')
        use.setEnabled(bool(result['urls'] or result['artist']))
        use.clicked.connect(lambda: self.use(result))
        h.addWidget(use)
        return frame

    def set_thumb(self, index, data):
        img = QtGui.QImage.fromData(data)
        if not img.isNull() and index < len(self.thumbs):
            self.thumbs[index].setPixmap(QtGui.QPixmap.fromImage(img.scaled(
                96, 96, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation)))

    def use(self, result):
        use_result(self.view, self.items, result,
                   self.describe is not None and self.describe.isChecked())
        self.accept()


def _esc(text):
    import html
    return html.escape(str(text))


def use_result(view, items, result, describe=False):
    """Source link and artist onto the images (undoable)."""
    targets = [getattr(i, 'link_source', None) or i for i in items]
    main = view.rb_main()
    url = result['urls'][0] if result['urls'] else ''
    if url:
        api.set_image_data(main, targets, 'source_url', [url] * len(targets),
                           'Set source link')
    artist = result['artist']
    if artist:
        api.set_image_data(main, targets, 'artist', [artist] * len(targets),
                           'Set artist')
        main.rb_add_tag(targets, artist)
    if describe and artist and getattr(view, 'is_subboard', False):
        from beeref.rboard.subboards import describe as set_description
        board = view.board
        line = f'{artist} · {url}' if url else artist
        if line not in board.description:
            text = (board.description + '\n' + line).strip()
            set_description(view.rb_manager(), board, text)
    api.notify(view, 'source set' + (f' · by {artist}' if artist else ''))


# ---------- the action ----------

def find_original(view, items):
    item = items[0]
    key = str(api.setting('saucenao_key', '')).strip()
    if not key:
        ResultsDialog(view, items, [], (
            'add a free SauceNAO API key on the plugins page (settings → '
            f'plugins) to search art sites. get one at <a href="{KEY_PAGE}">'
            'saucenao.com</a>. or search in the browser:')).exec()
        return
    cache_key = id(item.source)
    if cache_key in _cache:
        ResultsDialog(view, items, _cache[cache_key]).exec()
        return
    jpeg = jpeg_of(item)

    def work(progress, canceled):
        progress(0.2)
        return search(jpeg, key)

    def done(results, error):
        if error is not None:
            message = str(error) if isinstance(error, SearchError) \
                else f'the search failed: {error}'
            ResultsDialog(view, items, [], message + '. try the browser:')\
                .exec()
            return
        _cache[cache_key] = results
        ResultsDialog(view, items, results).exec()

    api.run_in_background(view, 'searching SauceNAO…', work, done)


def register(plugin_api):
    global api
    api = plugin_api
    api.add_image_action('find original…', find_original)
    api.add_setting(
        'saucenao_key', 'SauceNAO API key', 'secret',
        'free from saucenao.com (account → api). about 100 searches a day')
