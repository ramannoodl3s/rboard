from unittest.mock import patch

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

from beeref.fileio.sql import SQLiteIO
from beeref.items import BeePixmapItem
from beeref.rboard import attributes, pen
from beeref.rboard.subboards import SUBBOARD_DISABLED
from beeref.rboard.ui import icons, theme as T
from beeref.rboard.ui.menu import OverlayMenu, clean_label
from beeref.rboard.ui.theme import tm


def solid(color, w=40, h=30):
    img = QtGui.QImage(w, h, QtGui.QImage.Format.Format_RGB32)
    img.fill(QtGui.QColor(color))
    return img


def add_images(view, specs):
    items = []
    for i, (color, w, h) in enumerate(specs):
        item = BeePixmapItem(solid(color, w, h), f'/pics/{i}.png')
        item.setPos(i * 400, 0)
        view.scene.addItem(item)
        items.append(item)
    return items


@pytest.fixture(autouse=True)
def default_theme():
    tm().preview(T.PRESETS['carbon'])
    yield
    tm().preview(T.PRESETS['carbon'])


# ---------- theme ----------

def test_presets_have_concrete_colours():
    for theme in T.PRESETS.values():
        for name, value in theme['colors'].items():
            assert QtGui.QColor(value).isValid(), (theme['id'], name)


@pytest.mark.parametrize('base', [
    {'canvas': '#3b1f4a', 'surface': '#2a1536', 'ink': '#f5e6ff',
     'accent': '#ff7ac6'},
    {'canvas': '#f4f1e8', 'surface': '#fbf9f2', 'ink': '#1d1d1d',
     'accent': '#3060c0'},
])
def test_derived_themes_meet_contrast_rules(base):
    c = T.derive(base)
    grounds = ('canvas', 'surface', 'surface-raised', 'surface-sunken')
    assert min(T.contrast(c['ink-muted'], c[g]) for g in grounds) >= 4.5
    assert min(T.contrast(c['control-border'], c[g]) for g in grounds) >= 3


def test_custom_theme_saved_and_applied(settings):
    stored = {'id': 'custom:pink', 'name': 'pink',
              'base': {'canvas': '#3b1f4a', 'surface': '#2a1536',
                       'ink': '#f5e6ff', 'accent': '#ff7ac6'},
              'overrides': {'accent-soft': '#552244'}}
    tm().save_custom_theme(stored)
    tm().set_theme('custom:pink')
    assert tm().hex('canvas') == '#3b1f4a'
    assert tm().hex('accent-soft') == '#552244'
    assert settings.value('Appearance/theme') == 'custom:pink'
    tm().delete_custom_theme('custom:pink')
    assert tm().theme['id'] == T.DEFAULT_THEME


def test_stylesheet_parses(qapp):
    messages = []
    old = QtCore.qInstallMessageHandler(lambda t, c, m: messages.append(m))
    try:
        w = QtWidgets.QWidget()
        w.setStyleSheet(T.stylesheet(T.PRESETS['pictogram']['colors']))
        w.ensurePolished()
    finally:
        QtCore.qInstallMessageHandler(old)
    assert not [m for m in messages if 'parse' in m]


def test_every_icon_renders(qapp):
    for name in list(icons.LINE) + list(icons.GLYPHS):
        pm = icons.pixmap(name, '#ffffff')
        assert not pm.isNull()
        img = pm.toImage()
        assert any(img.pixelColor(x, y).alpha() for x in range(16)
                   for y in range(16)), name


def test_clean_label():
    assert clean_label('Fit &Scene') == 'fit scene'
    assert clean_label('From &Are.na...') == 'from Are.na…'


# ---------- menus and home bar ----------

def test_menu_builds_rows_and_runs_callback(view, qtbot):
    calls = []
    menu = OverlayMenu(view, [
        ('label', 'section'), ('item', 'do it', lambda: calls.append(1)),
        ('sep',), ('action', 'select_all', 'select all'),
        ('submenu', 'more', lambda: [('item', 'inner', None)])])
    assert [r.label for r in menu.rows] == ['do it', 'select all', 'more']
    view.menu_host.show(menu, QtCore.QPoint(10, 10))
    menu.activate(menu.rows[0])
    qtbot.waitUntil(lambda: calls == [1])
    assert not view.menu_host.is_open()


def test_bar_arrange_applies_to_all_when_nothing_selected(view):
    add_images(view, [('#ff0000', 40, 30)] * 3)
    menu = OverlayMenu(view, view.rb_menu_arrange())
    row = next(r for r in menu.rows if r.label.startswith('justified'))
    assert row.enabled and row.label.endswith('(all)')
    row.callback()
    assert view.undo_stack.undoText() == 'Arrange items'


def test_home_bar_buttons(view):
    labels = [b.spec['label'] for b in view.home_bar.buttons]
    assert labels == ['undo', 'redo', 'file', 'add', 'arrange', 'image',
                      'find', 'pen', 'notes and tags', 'layers', 'view',
                      'settings']


def test_home_bar_fades_and_pins(view, qtbot):
    bar = view.home_bar
    with patch.object(bar, 'underMouse', return_value=False):
        bar.fade_out()
        qtbot.waitUntil(lambda: not bar.isVisible())
        bar.fade_in()
        qtbot.waitUntil(lambda: bar.isVisible())
        bar.pin(True)
        bar.fade_out()
        assert bar.shown
        bar.pin(False)


def test_every_bar_menu_builds(view):
    add_images(view, [('#ff0000', 40, 30)])
    for button in view.home_bar.buttons:
        if 'menu' in button.spec:
            menu = OverlayMenu(view, button.spec['menu']())
            assert menu.rows, button.spec['label']


# ---------- attributes ----------

@pytest.mark.parametrize('color,family', [
    ('#e02020', 'red'), ('#f08020', 'orange'), ('#f0e040', 'yellow'),
    ('#30a040', 'green'), ('#20a0a0', 'teal'), ('#2040d0', 'blue'),
    ('#7040c0', 'purple'), ('#f080b0', 'pink'), ('#808080', 'neutral')])
def test_color_family(color, family):
    assert attributes.color_family(color) == family


def test_attributes_and_album_cover(view):
    square, wide = add_images(view, [('#e02020', 600, 600),
                                     ('#2040d0', 800, 400)])
    view.rb_analyze([square, wide])
    keys = attributes.keys_of(square)
    assert {'color:red', 'shape:square', 'cover:likely'} <= keys
    assert 'cover:likely' not in attributes.keys_of(wide)
    square.meta['ocr_text'] = ''  # read, and no text found
    assert 'cover:likely' not in attributes.keys_of(square)
    square.meta['tags'] = ['type']
    assert attributes.matching('tag:type', [square, wide]) == [square]
    assert attributes.counts([square, wide])['folder:/pics'] == 2


# ---------- sub boards ----------

def open_board(view, key='folder:/pics', label='all'):
    images = view.rb_images()
    view.rb_analyze(images)
    return view.subboards.open_attribute(key, label, images)


def test_subboard_links_content_not_layout(view, qtbot):
    a, b = add_images(view, [('#e02020', 60, 40), ('#2040d0', 60, 40)])
    board = open_board(view)
    sv = board.window.view
    linked = {i.link_source: i for i in sv.rb_images()}
    assert set(linked) == {a, b}
    # Same pixel data, same metadata dict
    assert linked[a].pixmap().cacheKey() == a.pixmap().cacheKey()
    assert linked[a].meta is a.meta
    sv.rb_meta_change([linked[a]], 'note', ['hello'], 'note')
    assert a.meta['note'] == 'hello'
    assert view.undo_stack.undoText() == 'note'
    before = a.pos()
    linked[a].setPos(linked[a].pos() + QtCore.QPointF(500, 0))
    assert a.pos() == before
    board.window.close()


def test_subboard_cache_and_discard(view, qtbot):
    add_images(view, [('#e02020', 60, 40), ('#2040d0', 60, 40)])
    board = open_board(view)
    item = board.window.view.rb_images()[0]
    item.setPos(1234, 567)
    board.window.close()
    assert board.state == 'cached'
    view.subboards.show(board)
    restored = [i for i in board.window.view.rb_images()
                if i.link_source is item.link_source][0]
    assert (restored.pos().x(), restored.pos().y()) == (1234, 567)
    view.subboards.discard(board)
    assert view.subboards.boards == []


def test_subboards_cleared_with_main_board(view):
    add_images(view, [('#e02020', 60, 40)])
    open_board(view)
    view.clear_scene()
    assert view.subboards.boards == []


def test_subboard_actions_restricted(view):
    add_images(view, [('#e02020', 60, 40)])
    board = open_board(view)
    sv = board.window.view
    for action_id in SUBBOARD_DISABLED:
        assert not sv.bee_qactions[action_id].isEnabled(), action_id
    # The shared registry still points at the main board's actions
    from beeref.actions.actions import actions
    assert actions['select_all'].qaction is view.bee_qactions['select_all']
    board.window.close()


def test_nested_subboard_from_image_menu(view):
    red_image, _, _ = add_images(view, [
        ('#e02020', 60, 40), ('#e02020', 60, 40), ('#2040d0', 60, 40)])
    board = open_board(view)
    sv = board.window.view
    item = next(i for i in sv.rb_images() if i.link_source is red_image)
    menu = OverlayMenu(sv, sv.rb_image_menu(item))
    red = next(r for r in menu.rows if r.label == 'red')
    assert red.count == 2
    red.callback()
    child = view.subboards.boards[-1]
    assert child.parent is board and len(child.sources) == 2
    view.subboards.discard(board)
    assert view.subboards.boards == []


# ---------- right-click ----------

def test_right_click_menus(view):
    item, = add_images(view, [('#e02020', 200, 150)])
    view.on_action_fit_scene()
    centre = view.mapFromScene(item.sceneBoundingRect().center())
    view.rb_context_menu(centre)
    labels = [r.label for r in view.menu_host.menus[0].rows]
    assert 'red' in labels and 'add note…' in labels and 'delete' in labels
    assert item.isSelected()
    view.menu_host.close_all()
    view.rb_context_menu(QtCore.QPoint(2, 2))
    labels = [r.label for r in view.menu_host.menus[0].rows]
    assert labels == ['paste', 'add images…', 'add text', 'select all',
                      'fit board']


# ---------- notes, tags, pen ----------

def test_tags_and_notes_searchable(view):
    a, b = add_images(view, [('#e02020', 60, 40), ('#2040d0', 60, 40)])
    view.rb_add_tag([a, b], 'cover')
    view.rb_meta_change([a], 'note', ['blue headers'], 'note')
    view.on_action_find_text()
    view.rb_search('headers')
    assert view.search_matches == [a]
    view.rb_search('cover')
    assert set(view.search_matches) == {a, b}
    view.rb_remove_tag([b], 'cover')
    assert b.meta['tags'] == []


def test_note_callout_paints(view):
    a, = add_images(view, [('#e02020', 200, 150)])
    a.meta['note'] = 'a note'
    view.note_hover_item = a
    view.on_action_fit_scene()
    view.viewport().grab()  # runs drawForeground without errors


def test_pen_marks_attach_to_images(view):
    img, = add_images(view, [('#ffffff', 200, 150)])
    img.setScale(2)
    view.settings.setValue('Pen/color', '#d24b3c')
    r = view.scene.itemsBoundingRect(items=[img])
    pts = [r.topLeft() + QtCore.QPointF(20 + i * 10, 40) for i in range(10)]
    view._pen_commit(pts, 'free')
    mark, = img.meta['marks']
    assert mark['color'] == '#d24b3c'
    assert mark['points'][0] == pytest.approx([10, 20])  # local coords
    # Eraser removes it
    view._pen_erase_at(img.mapToScene(QtCore.QPointF(*mark['points'][3])))
    assert img.meta['marks'] == []


def test_standalone_stroke_saves(view, tmpfile):
    view._pen_commit([QtCore.QPointF(5000, 5000),
                      QtCore.QPointF(5100, 5050)], 'arrow')
    stroke, = [i for i in view.scene.items_for_save()
               if isinstance(i, pen.StrokeItem)]
    SQLiteIO(tmpfile, view.scene, create_new=True).write()
    view.scene.clear()
    SQLiteIO(tmpfile, view.scene, readonly=True).read()
    view.scene.add_queued_items()
    loaded, = [i for i in view.scene.items_for_save()
               if isinstance(i, pen.StrokeItem)]
    assert loaded.mark['kind'] == 'arrow'


def test_mark_paths():
    for kind in ('free', 'circle', 'arrow'):
        path = pen.mark_path({'kind': kind, 'points': [[0, 0], [10, 10]],
                              'color': '#000', 'width': 2})
        assert not path.isEmpty()


# ---------- settings ----------

def test_settings_dialog_switches_theme(view):
    from beeref.rboard.ui.settings_dialog import SettingsDialog
    with patch.object(SettingsDialog, 'show'):
        dialog = SettingsDialog(view)
    page = dialog.pages.widget(0).widget()
    card = next(c for c in page.cards if c.theme['id'] == 'pictogram')
    card.click()
    assert tm().theme['id'] == 'pictogram'
    dialog.close()
