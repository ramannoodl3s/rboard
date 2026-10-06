import os
import random
import sqlite3
import struct
from unittest.mock import patch

import numpy as np
import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

from beeref import commands
from beeref.fileio.sql import SQLiteIO
from beeref.items import BeePixmapItem, BeeTextItem
from beeref.rboard import analysis, layouts, ocr, pureref
from beeref.rboard.palette_item import BeePaletteItem


def solid(color, w=40, h=30, patch_color=None, patch_frac=0.0):
    """A QImage filled with `color`, optionally with a square patch."""
    img = QtGui.QImage(w, h, QtGui.QImage.Format.Format_RGB32)
    img.fill(QtGui.QColor(color))
    if patch_color:
        painter = QtGui.QPainter(img)
        side = int((w * h * patch_frac) ** 0.5)
        painter.fillRect(0, 0, side, side, QtGui.QColor(patch_color))
        painter.end()
    return img


def stats_for(img):
    pm = QtGui.QPixmap.fromImage(img)
    thumb = analysis.thumbnail_for(pm, QtCore.QRectF(pm.rect()))
    return analysis.analyze(thumb)


# ---------- analysis ----------

def test_lab_roundtrip():
    rgb = np.array([[255, 0, 0], [0, 128, 255], [30, 30, 30]], np.uint8)
    assert (analysis.lab_to_rgb(analysis.rgb_to_lab(rgb)) == rgb).all()


def test_average_and_dominant_color(qapp):
    stats = stats_for(solid('#808080', 100, 100, '#ff8000', 0.25))
    # The average is a muddy mix; the dominant color is the orange patch
    avg = analysis.rgb_to_lab(analysis.from_hex(stats['average']))
    assert np.hypot(avg[1], avg[2]) < 40
    r, g, b = analysis.from_hex(stats['dominant'])
    assert r > 200 and 100 < g < 160 and b < 60


def test_dominant_falls_back_to_biggest_cluster_for_gray(qapp):
    stats = stats_for(solid('#777777'))
    assert stats['dominant'] == '#777777'


def test_sort_key_orders_rainbow_then_neutrals():
    colors = ['#808080', '#0000ff', '#ff0000', '#ffff00', '#00ff00']
    ordered = sorted(colors, key=lambda c: analysis.sort_key(c, 'hue'))
    assert ordered == ['#ff0000', '#ffff00', '#00ff00', '#0000ff', '#808080']


def test_palette_returns_requested_colors(qapp):
    stats = [stats_for(solid(c)) for c in ('#ff0000', '#00ff00', '#0000ff')]
    colors = analysis.palette(stats, 3)
    assert sorted(h for h, _ in colors) == ['#0000ff', '#00ff00', '#ff0000']
    assert abs(sum(share for _, share in colors) - 1) < 1e-6


def test_image_palette_sorted_by_prominence(qapp):
    img = solid('#2040d0', 100, 100, '#e02020', 0.2)
    colors = analysis.image_palette(analysis.thumbnail_for(
        QtGui.QPixmap.fromImage(img), QtCore.QRectF(0, 0, 100, 100)), 2)
    assert analysis.from_hex(colors[0][0])[2] > 180   # the blue first
    assert colors[0][1] > colors[1][1]


def test_dhash_matches_resized_copy(qapp):
    img = QtGui.QImage(os.path.join(
        os.path.dirname(__file__), '..', 'assets', 'test3x3.png'))
    big = img.scaled(300, 300)
    other = solid('#123456', 300, 300, '#fedcba', 0.3)
    a, b, c = stats_for(big), stats_for(big.scaled(90, 90)), stats_for(other)
    assert analysis.hamming(a['dhash'], b['dhash']) <= 2
    assert analysis.hamming(a['dhash'], c['dhash']) > 5


def test_posterize_levels(qapp):
    img = QtGui.QImage(256, 1, QtGui.QImage.Format.Format_RGB32)
    for x in range(256):
        img.setPixelColor(x, 0, QtGui.QColor(x, x, x))
    out = analysis.posterize(img, 4)
    values = {out.pixelColor(x, 0).red() for x in range(256)}
    assert values == {0, 85, 170, 255}


# ---------- layouts ----------

@pytest.mark.parametrize('name', sorted(layouts.LAYOUTS))
def test_layouts_do_not_overlap(name):
    random.seed(3)
    sizes = [(random.randint(50, 400), random.randint(50, 400))
             for _ in range(30)]
    placements = layouts.LAYOUTS[name](sizes, 5)
    rects = [(x, y, x + w * f, y + h * f)
             for (w, h), (x, y, f) in zip(sizes, placements)]
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            assert not (a[0] < b[2] - 1e-6 and b[0] < a[2] - 1e-6
                        and a[1] < b[3] - 1e-6 and b[1] < a[3] - 1e-6)


def test_justified_rows_share_right_edge():
    sizes = [(100 + 37 * i % 300, 80 + 53 * i % 200) for i in range(25)]
    placements = layouts.justified(sizes, 4)
    edges = {}
    for (w, h), (x, y, f) in zip(sizes, placements):
        edges[round(y, 3)] = max(edges.get(round(y, 3), 0), x + w * f)
    full_rows = sorted(edges.values())[1:]  # the last row isn't stretched
    assert max(full_rows) - min(full_rows) < 1e-6


@pytest.mark.parametrize('name', ['flow', 'justified', 'grid'])
def test_reading_order_survives_relayout(name):
    sizes = [(100 + 37 * i % 300, 80 + 53 * i % 200) for i in range(20)]
    placements = layouts.LAYOUTS[name](sizes, 4)
    rects = [(x, y, w * f, h * f)
             for (w, h), (x, y, f) in zip(sizes, placements)]
    assert layouts.reading_order(rects) == list(range(20))


# ---------- folders with links.txt ----------

def test_links_txt_gives_source_links(view, tmp_path):
    from beeref.rboard import sidecar
    solid('#336699').save(str(tmp_path / 'a.png'))
    solid('#993366').save(str(tmp_path / 'b.png'))
    (tmp_path / 'links.txt').write_text(
        '# channel: https://www.are.na/x/chan\n'
        'a.png\thttps://www.are.na/block/1\n', encoding='utf-8')
    assert sidecar.images_in(str(tmp_path)) == [
        str(tmp_path / 'a.png'), str(tmp_path / 'b.png')]
    item = BeePixmapItem(solid('#336699'), str(tmp_path / 'a.png'))
    sidecar.apply(item, str(tmp_path / 'a.png'))
    assert item.meta['source_url'] == 'https://www.are.na/block/1'
    assert item.meta['arena_channel'] == 'https://www.are.na/x/chan'
    other = BeePixmapItem(solid('#993366'), str(tmp_path / 'b.png'))
    sidecar.apply(other, str(tmp_path / 'b.png'))
    assert 'source_url' not in other.meta


# ---------- PureRef ----------

def _qstring(s):
    b = s.encode('utf-16-be')
    return struct.pack('>I', len(b)) + b


def _variant(type_id, payload, name=None):
    head = struct.pack('>IB', type_id, 0)
    if name:
        n = name.encode() + b'\0'
        head += struct.pack('>I', len(n)) + n
    return (head + payload).decode('latin1')


def _matrix(m):
    return _variant(80, struct.pack('>9d', *m))


def _rect_path(w, h):
    pts = [(0, -w / 2, -h / 2), (1, w / 2, -h / 2), (1, w / 2, h / 2),
           (1, -w / 2, h / 2), (1, -w / 2, -h / 2)]
    payload = struct.pack('>I', len(pts)) + b''.join(
        struct.pack('>idd', *p) for p in pts) + struct.pack('>ii', 0, 0)
    return _variant(1024, payload, 'QPainterPath')


def make_pur(path, png, w, h, item_matrix):
    db = sqlite3.connect(':memory:')
    db.executescript('''
    CREATE TABLE images (id INTEGER PRIMARY KEY, source_type INTEGER,
      origin TEXT, source TEXT, format TEXT, checksum TEXT, data BLOB,
      width INTEGER, height INTEGER);
    CREATE TABLE items (parent INTEGER, id INTEGER PRIMARY KEY, name TEXT,
      transform BLOB, sort_order BLOB, z REAL, opacity REAL,
      locked INTEGER, comment INTEGER);
    CREATE TABLE items_images (image INTEGER, playback_speed REAL,
      id INTEGER PRIMARY KEY, playback_state INTEGER, image_transform BLOB,
      image_bounds BLOB, playback_frame INTEGER, flags INTEGER);
    CREATE TABLE items_notes (text_color TEXT, id INTEGER PRIMARY KEY,
      fixed_size TEXT, background_color TEXT, text TEXT, style INTEGER);
    ''')
    db.execute("INSERT INTO images VALUES (0, 1, '', '', 'PNG', '', ?, ?, ?)",
               (png, w, h))
    db.execute('INSERT INTO items VALUES (-1, 0, ?, ?, NULL, 1, 1, 0, NULL)',
               ('pic', _matrix(item_matrix)))
    db.execute('INSERT INTO items_images VALUES (0, 1, 0, 0, ?, ?, 0, 1)',
               (_matrix([1, 0, 0, 0, 1, 0, -w / 2, -h / 2, 1]),
                _rect_path(w, h)))
    db.execute('INSERT INTO items VALUES (-1, 1, ?, ?, NULL, 2, 1, 0, NULL)',
               ('note', _matrix([1, 0, 0, 0, 1, 0, 0, -50, 1])))
    db.execute('INSERT INTO items_notes VALUES (NULL, 1, NULL, NULL, ?, 0)',
               ('<html><body style="font-size:22.0px">'
                '<p>Hello &amp; welcome</p></body></html>',))
    db.commit()
    data = db.serialize()
    header = (_qstring('2.1') + struct.pack('>IQ', 0, len(data))
              + _qstring('2.1.3') + _qstring('0' * 32)
              + struct.pack('>I', 0))
    tail = struct.pack('>I', 0) + data[len(header):] + data[:len(header)]
    with open(path, 'wb') as f:
        f.write(_qstring('2.1') + struct.pack('>IQ', 0, len(data))
                + _qstring('2.1.3') + _qstring('0' * 32) + tail)


def test_pureref_read_and_decompose(tmpdir, imgdata3x3):
    path = os.path.join(tmpdir, 'board.pur')
    # scale 2, rotated 90 degrees, centre at (100, 50)
    make_pur(path, imgdata3x3, 3, 3, [0, 2, 0, -2, 0, 0, 100, 50, 1])
    entries = pureref.read(path)
    image = next(e for e in entries if e['type'] == 'image')
    note = next(e for e in entries if e['type'] == 'text')
    assert image['crop'] == (0, 0, 3, 3)
    assert note['text'] == 'Hello & welcome'
    x, y, scale, rotation, flip = pureref.decompose(image['transform'])
    assert scale == pytest.approx(2)
    assert rotation == pytest.approx(90)
    assert flip == 1
    # pixel (1.5, 1.5) is the image centre and must land at (100, 50)
    item = BeePixmapItem(QtGui.QImage(3, 3, QtGui.QImage.Format.Format_RGB32))
    item.setScale(scale)
    item.setRotation(rotation)
    item.setPos(x, y)
    centre = item.mapToScene(QtCore.QPointF(1.5, 1.5))
    assert (centre.x(), centre.y()) == pytest.approx((100, 50))


def test_pureref_rejects_old_format(tmpdir):
    path = os.path.join(tmpdir, 'old.pur')
    with open(path, 'wb') as f:
        f.write(_qstring('1.10') + b'\0' * 64)
    with pytest.raises(pureref.PureRefError, match='PureRef 1.10'):
        pureref.read(path)


def test_import_pureref_into_view(view, qtbot, tmpdir, imgdata3x3):
    path = os.path.join(tmpdir, 'board.pur')
    make_pur(path, imgdata3x3, 3, 3, [1, 0, 0, 0, 1, 0, 10, 10, 1])
    view.rb_import_pureref(path)
    qtbot.waitUntil(lambda: len(list(view.scene.items_for_save())) == 2)
    kinds = sorted(type(i).__name__ for i in view.scene.items_for_save())
    assert kinds == ['BeePixmapItem', 'BeeTextItem']
    view.undo_stack.undo()
    assert list(view.scene.items_for_save()) == []


# ---------- saving ----------

def test_palette_and_meta_survive_save(view, tmpfile, imgfilename3x3):
    palette = BeePaletteItem(['#ff0000', '#00ff00'])
    view.scene.addItem(palette)
    image = BeePixmapItem(QtGui.QImage(imgfilename3x3), 'x.png')
    image.meta = {'ocr_text': 'hello', 'source_url': 'https://are.na/block/1'}
    view.scene.addItem(image)
    SQLiteIO(tmpfile, view.scene, create_new=True).write()

    view.scene.clear()
    SQLiteIO(tmpfile, view.scene, readonly=True).read()
    view.scene.add_queued_items()
    items = list(view.scene.items_for_save())
    loaded_palette = next(i for i in items if isinstance(i, BeePaletteItem))
    loaded_image = next(i for i in items if isinstance(i, BeePixmapItem))
    assert loaded_palette.colors == ['#ff0000', '#00ff00']
    assert loaded_image.meta['ocr_text'] == 'hello'
    assert loaded_image.meta['source_url'] == 'https://are.na/block/1'


def test_palette_copy_and_sample(view):
    palette = BeePaletteItem(['#ff0000', '#00ff00'])
    view.scene.addItem(palette)
    clipboard = QtWidgets.QApplication.clipboard()
    palette.copy_to_clipboard(clipboard)
    assert clipboard.text() == '#ff0000 #00ff00'
    color = palette.sample_color_at(QtCore.QPointF(150, 50))
    assert color.name() == '#00ff00'


# ---------- view actions ----------

def add_images(view, colors):
    items = []
    for i, c in enumerate(colors):
        item = BeePixmapItem(solid(c), f'{i}.png')
        item.setPos(i * 50, 0)
        view.scene.addItem(item)
        item.setSelected(True)
        items.append(item)
    return items


def test_arrange_by_color_is_undoable(view):
    items = add_images(view, ['#0000ff', '#808080', '#ff0000', '#00ff00'])
    before = [i.pos() for i in items]
    view.on_action_arrange_color_dominant()
    order = sorted(items, key=lambda i: (i.pos().y(), i.pos().x()))
    assert [i.filename for i in order] == ['2.png', '3.png', '0.png', '1.png']
    view.undo_stack.undo()
    assert [i.pos() for i in items] == before


@pytest.mark.parametrize('action', ['justified', 'masonry', 'grid'])
def test_layout_actions_undo(view, action):
    items = add_images(view, ['#111111'] * 5)
    items[0].setScale(2)
    before = [(i.pos(), i.scale()) for i in items]
    getattr(view, f'on_action_arrange_{action}')()
    view.undo_stack.undo()
    assert [(i.pos(), i.scale()) for i in items] == before


def test_view_palette_is_kept_with_the_image(view):
    a, b = add_images(view, ['#ff0000', '#0000ff'])
    view.settings.setValue('Items/palette_size', 2)
    colors = view.rb_palette([a])
    assert colors[0][0] == '#ff0000'
    assert a.meta['palette']['colors'] == [list(c) for c in colors]
    # Shift+P shows the palette in a menu instead of adding an item
    a.setSelected(True)
    view.on_action_generate_palette()
    rows = [r.label for r in view.menu_host.menus[0].rows]
    assert '#ff0000' in rows and 'copy all hex codes' in rows
    assert not [i for i in view.scene.items_for_save()
                if isinstance(i, BeePaletteItem)]


def test_select_duplicates_keeps_largest(view):
    big = BeePixmapItem(solid('#000000', 80, 60, '#ffffff', 0.3), 'big')
    small = BeePixmapItem(big.pixmap().toImage().scaled(40, 30), 'small')
    other = BeePixmapItem(solid('#ff0000', 80, 60, '#00ff00', 0.5), 'other')
    for item in (big, small, other):
        view.scene.addItem(item)
    view.on_action_select_duplicates()
    assert view.scene.selectedItems(user_only=True) == [small]


def test_search_matches_ocr_text_and_notes(view):
    a, b = add_images(view, ['#ffffff', '#000000'])
    a.meta['ocr_text'] = 'Silver Lining'
    note = BeeTextItem('silver paint')
    view.scene.addItem(note)
    view.on_action_find_text()
    view.rb_search('silver')
    assert set(view.scene.selectedItems(user_only=True)) == {a, note}
    view.rb_search('lining silver')
    assert view.scene.selectedItems(user_only=True) == [a]


def test_value_study_toggle(view):
    item, = add_images(view, ['#336699'])
    view.on_action_value_study(True)
    assert view.scene.value_study_levels == 4
    pm = item.value_study_pixmap(4)
    assert not pm.isNull()
    view.on_action_value_study(False)
    assert view.scene.value_study_levels == 0


def test_set_item_meta_undo(view):
    item, = add_images(view, ['#336699'])
    view.undo_stack.push(commands.SetItemMeta([item], 'ocr_text', ['hi']))
    assert item.meta['ocr_text'] == 'hi'
    view.undo_stack.undo()
    assert 'ocr_text' not in item.meta


def test_find_by_color_selects_matches(view):
    red, blue = add_images(view, ['#ff0000', '#0000ff'])
    view.scene.clearSelection()

    def fake_exec(dialog):
        dialog.button.set_color(QtGui.QColor('#fe0101'))
        return QtWidgets.QDialog.DialogCode.Accepted

    with patch('beeref.rboard.widgets.FindColorDialog.exec', fake_exec):
        view.on_action_find_by_color()
    assert view.scene.selectedItems(user_only=True) == [red]


TEXT_ASSET = os.path.join(
    os.path.dirname(__file__), '..', 'assets', 'text_mood_board.png')


@pytest.mark.skipif(not ocr.is_available(), reason='Windows OCR not available')
def test_ocr_reads_text():
    with open(TEXT_ASSET, 'rb') as f:
        assert ocr.recognize(f.read()) == 'MOOD BOARD'


@pytest.mark.skipif(not ocr.is_available(), reason='Windows OCR not available')
def test_extract_text_action(view, qtbot):
    item = BeePixmapItem(QtGui.QImage(TEXT_ASSET))
    view.scene.addItem(item)
    item.setSelected(True)
    view.on_action_extract_text()
    qtbot.waitUntil(lambda: 'ocr_text' in item.meta, timeout=20000)
    assert item.meta['ocr_text'] == 'MOOD BOARD'
    assert QtWidgets.QApplication.clipboard().text() == 'MOOD BOARD'
    view.undo_stack.undo()
    assert 'ocr_text' not in item.meta


def test_queued_items_keep_metadata(view):
    # Imports set metadata before the item is queued for adding
    item = BeePixmapItem(solid('#336699'), 'a.png')
    item.meta['arena_key'] = '1/original_x.jpg'
    view.scene.add_item_later({'item': item, 'type': 'pixmap'})
    view.scene.add_queued_items()
    assert item.meta['arena_key'] == '1/original_x.jpg'
