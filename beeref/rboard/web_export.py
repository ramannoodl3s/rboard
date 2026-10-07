# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""A board as one web page: a single .html file with the images inside,
to send to anyone. Pan and zoom like the board; click an image for a
full view with its tags, note and source link.

The page is kept under a size limit (20 MB by default): every image gets
the same sharpness relative to how big it is on the board, and that
sharpness is lowered until the WebP-encoded images fit."""

import base64
import html
import io
import json
import logging
import math
import os

from beeref.fileio.export import ExporterBase

logger = logging.getLogger(__name__)

LIMITS_MB = (5, 10, 20, 50)
DEFAULT_LIMIT_MB = 20
QUALITY = 80
MIN_QUALITY = 55
MAX_SIDE = 3000         # px, longest side of any image in the page
MIN_SIDE = 48
BYTES_PER_PIXEL = 0.12  # first guess for WebP at QUALITY
RESERVE = 300_000       # bytes for the page itself (text, script)


# ---------- gathering (main thread) ----------

def _matrix(item):
    """CSS matrix() placing the image's visible (cropped) part."""
    from PyQt6 import QtGui
    crop = item.crop
    t = QtGui.QTransform.fromTranslate(crop.x(), crop.y()) \
        * item.sceneTransform()
    return [t.m11(), t.m12(), t.m21(), t.m22(), t.dx(), t.dy()]


def _image_entry(item):
    from beeref.rboard import attributes
    data, _ = item.source.file_data()
    if data is None:   # pasted or made in the app: no original file
        data = bytes(item.pixmap_to_bytes()[0])
    crop = item.crop
    scale = math.hypot(*_matrix(item)[:2])
    source_url = item.meta.get('source_url') or (
        item.filename if item.filename and item.filename.startswith('http')
        else '')
    tags = [label for key, label, *_ in attributes.attributes(item)
            if ':' in key and not key.startswith('folder:')]
    return {
        'data': data,
        'crop': (crop.x(), crop.y(), crop.width(), crop.height()),
        'size': (item.source.width, item.source.height),
        'shown': (crop.width() * scale, crop.height() * scale),
        'info': {
            'kind': 'image',
            'm': [round(v, 4) for v in _matrix(item)],
            'w': round(crop.width(), 2), 'h': round(crop.height(), 2),
            'z': item.zValue(),
            'opacity': round(item.opacity(), 3),
            'gray': bool(item.grayscale),
            'name': os.path.basename(item.filename) if item.filename
            else '',
            'note': item.meta.get('note', ''),
            'tags': tags[:40],
            'source': source_url,
        },
    }


def _text_entry(item):
    from PyQt6 import QtGui
    t = item.sceneTransform()
    font = item.font()
    return {'kind': 'text',
            'm': [round(v, 4) for v in (t.m11(), t.m12(), t.m21(), t.m22(),
                                        t.dx(), t.dy())],
            'z': item.zValue(),
            'text': item.toPlainText(),
            'size': font.pointSizeF() * 96 / 72 if font.pointSizeF() > 0
            else font.pixelSize(),
            'color': QtGui.QColor(item.defaultTextColor()).name()}


def gather(view, title, description='', rule=None):
    """Everything the page needs from a board view, read on the main
    thread (the encoding happens elsewhere)."""
    from beeref.rboard.ui.theme import tm
    images, texts = [], []
    for item in view.scene.items_for_save():
        if getattr(item, 'is_image', False):
            if not item.source.is_null():
                images.append(_image_entry(item))
        elif item.TYPE == 'text':
            texts.append(_text_entry(item))
    return {'title': title, 'description': description, 'rule': rule,
            'images': images, 'texts': texts,
            'canvas': tm().hex('canvas'), 'ink': tm().hex('ink'),
            'accent': tm().hex('accent')}


# ---------- encoding (any thread) ----------

def encode(entry, long_side, quality):
    """The visible part of an image as WebP bytes, at most `long_side`
    px on its longest side."""
    from PIL import Image
    from beeref.rboard.imagestore import (
        _maybe_big, _pil_open, _pil_ready)
    full_w, full_h = entry['size']
    cx, cy, cw, ch = entry['crop']
    factor = min(1.0, long_side / max(cw, ch, 1))
    opened = _pil_open(entry['data'])
    if opened is not None and opened[1] is not None:
        with _maybe_big(opened[0].width * opened[0].height * factor ** 2):
            im, _, _ = _pil_ready(opened[0],
                                          max(1, round(full_w * factor)))
    else:
        # Formats only Qt reads (as the board itself falls back to)
        from PyQt6 import QtGui
        img = QtGui.QImage.fromData(entry['data'])
        if img.isNull():
            return None
        img = img.convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
        im = Image.frombytes('RGBA', (img.width(), img.height()),
                             img.constBits().asstring(img.sizeInBytes()),
                             'raw', 'RGBA', img.bytesPerLine())
    # A JPEG may have been decoded smaller; crop in its own pixels
    sx, sy = im.width / max(full_w, 1), im.height / max(full_h, 1)
    im = im.crop((round(cx * sx), round(cy * sy),
                  round((cx + cw) * sx), round((cy + ch) * sy)))
    target = (max(1, round(cw * factor)), max(1, round(ch * factor)))
    if im.size != target:
        im = im.resize(target, Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, 'WEBP', quality=quality, method=4)
    return out.getvalue()


def encode_all(entries, sides, quality, progress=None,
               canceled=lambda: False):
    """encode() for every image, in parallel (Pillow lets go of the
    GIL), keeping the order. None when canceled."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    out = [None] * len(entries)
    workers = max(1, min(8, (os.cpu_count() or 2) - 1))
    with ThreadPoolExecutor(workers) as pool:
        jobs = {pool.submit(encode, e, side, quality): i
                for i, (e, side) in enumerate(zip(entries, sides))}
        for done, job in enumerate(as_completed(jobs), 1):
            if canceled():
                for other in jobs:
                    other.cancel()
                return None
            out[jobs[job]] = job.result()
            if progress:
                progress(done)
    return out


def plan_sides(entries, density):
    """Longest side in px for each image at this density (px per board
    unit), never more than the image has or MAX_SIDE."""
    sides = []
    for e in entries:
        shown = max(e['shown'])
        has = max(e['crop'][2], e['crop'][3])
        sides.append(int(max(MIN_SIDE, min(shown * density, has, MAX_SIDE))))
    return sides


def first_density(entries, budget):
    area = sum(e['shown'][0] * e['shown'][1] for e in entries) or 1
    return math.sqrt(budget / BYTES_PER_PIXEL / area)


def fit(entries, limit_bytes, progress=None, canceled=lambda: False):
    """[(webp bytes)] for every image, together under limit_bytes (as
    base64 in the page). Lowers sharpness first, then quality."""
    budget = (limit_bytes - RESERVE) * 3 / 4   # base64 grows data by 4/3
    density = first_density(entries, budget)
    quality = QUALITY
    best = None
    for attempt in range(6):
        sides = plan_sides(entries, density)
        blobs = encode_all(entries, sides, quality,
                           lambda done: progress and progress(attempt, done),
                           canceled)
        if blobs is None:
            return None
        total = sum(len(b) for b in blobs if b)
        logger.debug(f'Web page try {attempt}: density {density:.4f}, '
                     f'quality {quality}, {total / 1e6:.1f} MB')
        if total <= budget:
            best = blobs
            capped = all(s >= min(max(e['crop'][2], e['crop'][3]), MAX_SIDE)
                         for e, s in zip(entries, sides))
            if total > budget * 0.7 or capped or attempt >= 2:
                return blobs
            density *= math.sqrt(budget / total) * 0.95   # room to spare
            continue
        if best is not None:
            return best   # the bigger try didn't fit: keep the last one
        if attempt >= 2 and quality > MIN_QUALITY:
            quality = max(MIN_QUALITY, quality - 15)   # sharpness first
        else:
            density *= math.sqrt(budget / total) * 0.93
    return blobs


# ---------- the page ----------

def page(board, blobs):
    images = []
    for entry, blob in zip(board['images'], blobs):
        if blob is None:   # unreadable: left out
            continue
        info = dict(entry['info'])
        info['src'] = 'data:image/webp;base64,' + \
            base64.b64encode(blob).decode('ascii')
        images.append(info)
    items = sorted(images + board['texts'], key=lambda i: i['z'])
    data = json.dumps({'items': items, 'rule': board['rule']},
                      separators=(',', ':')).replace('</', '<\\/')
    from beeref.rboard.subboard_window import linked_html
    return TEMPLATE.format(
        title=html.escape(board['title']),
        description=linked_html(board['description']),
        canvas=board['canvas'], ink=board['ink'], accent=board['accent'],
        data=data)


class WebPageExporter(ExporterBase):
    """For BeeGraphicsView's export worker: gather first (main thread),
    then export() encodes and writes on the worker thread."""

    def __init__(self, board, limit_mb=DEFAULT_LIMIT_MB):
        self.board = board
        self.limit = limit_mb * 1_000_000 if limit_mb else None

    def export(self, filename, worker=None):
        entries = self.board['images']
        n = max(len(entries), 1)
        self.emit_begin_processing(worker, n)

        def progress(attempt, done):
            self.emit_progress(worker, done)

        def canceled():
            return bool(worker and worker.canceled)

        try:
            if self.limit is None:
                blobs = encode_all(entries, [MAX_SIDE] * len(entries), 90,
                                   lambda done: progress(0, done), canceled)
            else:
                blobs = fit(entries, self.limit, progress, canceled)
            if blobs is None:
                self.emit_finished(worker, filename, [])
                return
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(page(self.board, blobs))
        except Exception as e:
            logger.exception('Web page export failed')
            self.handle_export_error(filename, e, worker)
            return
        self.emit_finished(worker, filename, [])


TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ --canvas: {canvas}; --ink: {ink}; --accent: {accent}; }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; height: 100%; overflow: hidden;
  background: var(--canvas); color: var(--ink);
  font: 15px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }}
#head {{ position: fixed; top: 0; left: 0; right: 0; z-index: 5;
  padding: 12px 16px; background: color-mix(in srgb, var(--canvas) 85%, black);
  border-bottom: 1px solid color-mix(in srgb, var(--ink) 15%, transparent); }}
#head h1 {{ margin: 0; font-size: 18px; font-weight: 500; }}
#head p {{ margin: 4px 0 0; opacity: .8; }}
#head .tags span {{ display: inline-block; margin: 6px 6px 0 0;
  padding: 1px 9px; border-radius: 10px; font-size: 13px;
  background: color-mix(in srgb, var(--accent) 30%, transparent); }}
#head .tags b {{ font-weight: 400; opacity: .7; margin-right: 4px; }}
a {{ color: var(--accent); }}
#stage {{ position: absolute; inset: 0; cursor: grab; touch-action: none; }}
#stage.drag {{ cursor: grabbing; }}
#board {{ position: absolute; left: 0; top: 0; transform-origin: 0 0; }}
#board > * {{ position: absolute; left: 0; top: 0; transform-origin: 0 0; }}
#board img {{ display: block; cursor: zoom-in; user-select: none;
  -webkit-user-drag: none; }}
#board .text {{ white-space: pre; }}
#hint {{ position: fixed; right: 12px; bottom: 10px; opacity: .55;
  font-size: 12px; pointer-events: none; }}
#full {{ position: fixed; inset: 0; z-index: 10; display: none;
  background: rgba(0,0,0,.88); color: #eee; }}
#full.open {{ display: flex; flex-direction: column; }}
#full .pic {{ flex: 1; min-height: 0; display: flex; align-items: center;
  justify-content: center; padding: 16px; }}
#full img {{ max-width: 100%; max-height: 100%; object-fit: contain; }}
#full .about {{ padding: 10px 18px 16px; max-height: 35vh; overflow: auto; }}
#full .about .tags span {{ display: inline-block; margin: 4px 6px 0 0;
  padding: 1px 9px; border-radius: 10px; background: rgba(255,255,255,.12);
  font-size: 13px; }}
#full .close {{ position: absolute; top: 10px; right: 14px; font-size: 26px;
  background: none; border: 0; color: #eee; cursor: pointer; }}
</style>
</head>
<body>
<div id="stage"><div id="board"></div></div>
<div id="head"><h1>{title}</h1><p>{description}</p><div class="tags"></div></div>
<div id="hint">drag to move · scroll to zoom · click an image</div>
<div id="full"><button class="close" title="close">×</button>
  <div class="pic"><img alt=""></div><div class="about"></div></div>
<script id="data" type="application/json">{data}</script>
<script>
(function () {{
  var data = JSON.parse(document.getElementById('data').textContent);
  var board = document.getElementById('board');
  var stage = document.getElementById('stage');
  var head = document.getElementById('head');
  var full = document.getElementById('full');
  function esc(s) {{ var d = document.createElement('div');
    d.textContent = s; return d.innerHTML; }}
  function chips(list, label) {{
    if (!list || !list.length) return '';
    return (label ? '<b>' + esc(label) + '</b>' : '') +
      list.map(function (t) {{ return '<span>' + esc(t) + '</span>'; }}).join('');
  }}
  if (data.rule) {{
    var label = function (t) {{ return t.indexOf(':') < 0 ? t : t.split(':')[1]; }};
    head.querySelector('.tags').innerHTML =
      chips(data.rule.include.map(label), 'include') + ' ' +
      chips(data.rule.exclude.map(label), 'leave out');
  }}
  if (!head.querySelector('p').textContent.trim()) head.querySelector('p').remove();
  var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  data.items.forEach(function (it) {{
    var el;
    if (it.kind === 'image') {{
      el = document.createElement('img');
      el.src = it.src; el.width = it.w; el.height = it.h;
      el.style.width = it.w + 'px'; el.style.height = it.h + 'px';
      if (it.gray) el.style.filter = 'grayscale(1)';
      if (it.opacity < 1) el.style.opacity = it.opacity;
      if (it.note) el.title = it.note;
      el.addEventListener('click', function () {{ if (!moved) open(it); }});
      var m = it.m, pts = [[0, 0], [it.w, 0], [0, it.h], [it.w, it.h]];
      pts.forEach(function (p) {{
        var x = m[0] * p[0] + m[2] * p[1] + m[4];
        var y = m[1] * p[0] + m[3] * p[1] + m[5];
        minX = Math.min(minX, x); maxX = Math.max(maxX, x);
        minY = Math.min(minY, y); maxY = Math.max(maxY, y);
      }});
    }} else {{
      el = document.createElement('div');
      el.className = 'text'; el.textContent = it.text;
      el.style.fontSize = it.size + 'px'; el.style.color = it.color;
      minX = Math.min(minX, it.m[4]); minY = Math.min(minY, it.m[5]);
    }}
    el.style.transform = 'matrix(' + it.m.join(',') + ')';
    board.appendChild(el);
  }});
  if (!isFinite(minX)) {{ minX = minY = 0; maxX = maxY = 1; }}
  var view = {{ x: 0, y: 0, s: 1 }};
  function apply() {{
    board.style.transform = 'translate(' + view.x + 'px,' + view.y +
      'px) scale(' + view.s + ')';
  }}
  function fitAll() {{
    var top = head.offsetHeight + 16, pad = 24;
    var w = innerWidth - 2 * pad, h = innerHeight - top - pad;
    view.s = Math.min(w / (maxX - minX), h / (maxY - minY));
    view.x = pad + (w - (maxX - minX) * view.s) / 2 - minX * view.s;
    view.y = top + (h - (maxY - minY) * view.s) / 2 - minY * view.s;
    apply();
  }}
  fitAll();
  addEventListener('resize', fitAll);
  stage.addEventListener('wheel', function (e) {{
    e.preventDefault();
    var f = Math.exp(-e.deltaY * (e.deltaMode ? 0.05 : 0.0015));
    view.x = e.clientX - (e.clientX - view.x) * f;
    view.y = e.clientY - (e.clientY - view.y) * f;
    view.s *= f; apply();
  }}, {{ passive: false }});
  var pointers = {{}}, last = null, moved = false, pinch = 0;
  stage.addEventListener('pointerdown', function (e) {{
    pointers[e.pointerId] = [e.clientX, e.clientY];
    last = [e.clientX, e.clientY]; moved = false; pinch = 0;
    stage.classList.add('drag');
  }});
  addEventListener('pointermove', function (e) {{
    if (!(e.pointerId in pointers)) return;
    pointers[e.pointerId] = [e.clientX, e.clientY];
    var ids = Object.keys(pointers);
    if (ids.length === 2) {{
      var a = pointers[ids[0]], b = pointers[ids[1]];
      var d = Math.hypot(a[0] - b[0], a[1] - b[1]);
      var cx = (a[0] + b[0]) / 2, cy = (a[1] + b[1]) / 2;
      if (pinch) {{
        var f = d / pinch;
        view.x = cx - (cx - view.x) * f; view.y = cy - (cy - view.y) * f;
        view.s *= f; apply();
      }}
      pinch = d; moved = true; return;
    }}
    var dx = e.clientX - last[0], dy = e.clientY - last[1];
    if (Math.abs(dx) + Math.abs(dy) > 3) moved = true;
    view.x += dx; view.y += dy; last = [e.clientX, e.clientY]; apply();
  }});
  function up(e) {{ delete pointers[e.pointerId];
    if (!Object.keys(pointers).length) stage.classList.remove('drag'); }}
  addEventListener('pointerup', up); addEventListener('pointercancel', up);
  stage.addEventListener('dblclick', fitAll);
  function open(it) {{
    full.querySelector('img').src = it.src;
    full.querySelector('img').style.filter = it.gray ? 'grayscale(1)' : '';
    var parts = [];
    if (it.name) parts.push('<b>' + esc(it.name) + '</b>');
    if (it.note) parts.push('<div>' + esc(it.note) + '</div>');
    if (/^https?:\/\//i.test(it.source)) parts.push('<div><a href="' + encodeURI(it.source) +
      '" target="_blank" rel="noopener">' + esc(it.source) + '</a></div>');
    if (it.tags.length) parts.push('<div class="tags">' + chips(it.tags) + '</div>');
    full.querySelector('.about').innerHTML = parts.join('');
    full.classList.add('open');
  }}
  function shut() {{ full.classList.remove('open'); }}
  full.querySelector('.close').addEventListener('click', shut);
  full.addEventListener('click', function (e) {{ if (e.target === full ||
    e.target.classList.contains('pic')) shut(); }});
  addEventListener('keydown', function (e) {{ if (e.key === 'Escape') shut(); }});
}})();
</script>
</body>
</html>
'''
