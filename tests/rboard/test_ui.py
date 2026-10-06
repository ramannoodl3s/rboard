from unittest.mock import patch

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

from beeref.fileio.sql import SQLiteIO
from beeref.items import BeePixmapItem
from beeref.rboard import attributes, links, pen, subboards
from beeref.rboard.subboards import SUBBOARD_DISABLED
from beeref.rboard.ui import icons, theme as T
from beeref.rboard.ui.menu import SectionLabel, OverlayMenu, clean_label
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
    assert board.state == 'closed'
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
    menu = OverlayMenu(sv, sv.rb_tag_entries(item))
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
    menu = view.menu_host.menus[0]
    labels = [r.label for r in menu.rows]
    assert labels[0] == 'tags'
    assert 'add note…' in labels and 'delete' in labels
    assert item.isSelected()
    # One tags list: main tags, your tags, then the rest
    menu.open_submenu(menu.rows[0])
    tags = menu.child
    sections = [w.text for w in tags.body.findChildren(SectionLabel)]
    assert sections == ['main', 'your tags', 'found']
    assert [r.label for r in tags.rows][:2] == ['red', 'mid']
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


# ---------- links between images ----------

def test_links_draw_undo_and_tree(view):
    a, b, c, d = add_images(view, [('#e02020', 60, 40)] * 4)
    view.rb_add_link(a, b)
    view.rb_add_link(b, c)
    assert links.edges(view.rb_images()) == [(a, b), (b, c)]
    assert links.tree(c, view.rb_images()) == [c, b, a]
    assert links.levels([a, b, c]) == [[a], [b], [c]]
    # Linking back the other way replaces the old direction
    view.rb_add_link(c, b)
    assert (c, b) in links.edges(view.rb_images())
    assert (b, c) not in links.edges(view.rb_images())
    view.undo_stack.undo()
    assert (b, c) in links.edges(view.rb_images())
    # A copy of an image doesn't inherit its links
    copy = a.create_copy()
    assert 'uid' not in copy.meta and 'links' not in copy.meta


def test_link_arrow_hit_and_menu(view):
    a, b = add_images(view, [('#e02020', 60, 40), ('#2040d0', 60, 40)])
    view.on_action_fit_scene()
    view.rb_add_link(a, b)
    (_, _, start, end), = view.rb_link_lines()
    middle = (start + end) / 2
    assert view.rb_link_at(middle.toPoint()) == (a, b)
    view.rb_context_menu(middle.toPoint())
    labels = [r.label for r in view.menu_host.menus[0].rows]
    assert 'remove link' in labels and 'reverse direction' in labels


def test_link_by_dragging_the_handle(view):
    a, b = add_images(view, [('#e02020', 60, 40), ('#2040d0', 60, 40)])
    view.on_action_fit_scene()
    view.link_hover = a
    handle = view.rb_handle_center(a)
    target = view.rb_viewport_rect(b).center()

    def event(kind, pos):
        types = {'press': QtCore.QEvent.Type.MouseButtonPress,
                 'move': QtCore.QEvent.Type.MouseMove,
                 'release': QtCore.QEvent.Type.MouseButtonRelease}
        return QtGui.QMouseEvent(
            types[kind], pos, view.viewport().mapToGlobal(pos),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier)

    assert view.rb_link_event(event('press', handle), 'press')
    assert view.rb_link_event(event('move', target), 'move')
    assert view.rb_link_event(event('release', target), 'release')
    assert links.edges(view.rb_images()) == [(a, b)]


def test_link_tree_subboard(view):
    a, b, c, lone = add_images(view, [('#e02020', 60, 40)] * 4)
    view.rb_add_link(a, b)
    view.rb_add_link(a, c)
    view.rb_open_link_tree(b)
    board = view.subboards.boards[-1]
    assert set(board.sources) == {a, b, c}
    assert board.rows == [[a], [b, c]]
    sv = board.window.view
    copies = {i.link_source: i for i in sv.rb_images()}
    # Arrows show in the sub board too (links follow the images)
    assert len(sv.rb_link_lines()) == 2
    assert copies[a].pos().y() < copies[b].pos().y()
    menu = OverlayMenu(sv, sv.rb_image_menu(copies[a]))
    labels = [r.label for r in menu.rows]
    assert 'open link tree' in labels
    board.window.close()


# ---------- board files, font, size ----------

def test_brd_keeps_board_data(view, tmp_path):
    a, b = add_images(view, [('#e02020', 60, 40), ('#2040d0', 60, 40)])
    view.rb_add_link(a, b)
    view.rb_add_tag([a], 'mine')
    view.scale(2, 2)
    path = str(tmp_path / 'board.brd')
    view.scene.board_data = view.rb_board_data()
    SQLiteIO(path, view.scene, create_new=True).write()
    import sqlite3
    con = sqlite3.connect(path)
    assert con.execute('PRAGMA application_id').fetchone()[0] == 0x52425244
    con.close()
    view.scene.clear()
    SQLiteIO(path, view.scene, readonly=True).read()
    view.scene.add_queued_items()
    data = view.scene.loaded_board_data
    assert data['tags'] == ['mine']
    assert abs(data['view']['scale'] - view.get_scale()) < 1e-6
    images = view.rb_images()
    assert len(links.edges(images)) == 1
    view.setTransform(QtGui.QTransform())
    assert view.rb_restore_view(data)
    assert abs(view.get_scale() - data['view']['scale']) < 1e-6


def test_saving_a_bee_board_writes_brd_next_to_it(view, tmp_path):
    add_images(view, [('#e02020', 60, 40)])
    view.filename = str(tmp_path / 'old.bee')
    with patch.object(view, 'do_save') as do_save:
        view.on_action_save()
    do_save.assert_called_once_with(str(tmp_path / 'old.brd'),
                                    create_new=True)


def test_interface_scale_and_font(settings, qapp, tmp_path):
    import os
    settings.setValue('Appearance/ui_scale', 200)
    with patch.dict(os.environ, {}, clear=False) as env:
        env.pop('QT_SCALE_FACTOR', None)
        with patch.object(T, 'system_scale', return_value=1.0):
            T.apply_interface_scale(settings)
            assert env['QT_SCALE_FACTOR'] == '2.000'
        env.pop('QT_SCALE_FACTOR')
        with patch.object(T, 'system_scale', return_value=2.0):
            T.apply_interface_scale(settings)  # Windows already scales
            assert 'QT_SCALE_FACTOR' not in env
    font_file = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'),
                             'Fonts', 'arial.ttf')
    if not os.path.isfile(font_file):
        pytest.skip('no font file to add')
    with patch.object(T, 'fonts_dir', return_value=str(tmp_path)):
        family, copied = T.add_font_file(font_file)
    assert family == 'Arial' and os.path.isfile(copied)
    settings.setValue('Appearance/font_file', copied)
    T.load_custom_font()
    assert T.ui_font(12).family() == 'Arial'
    settings.setValue('Appearance/font_file', '')
    T.load_custom_font()
    assert T._custom['family'] is None


# ---------- sub board queries, keeping boards ----------

def test_query_include_and_exclude(view):
    red, red2, blue = add_images(view, [
        ('#e02020', 60, 40), ('#e02020', 40, 60), ('#2040d0', 60, 40)])
    view.rb_analyze(view.rb_images())
    view.rb_add_tag([red, blue], 'mine')
    images = view.rb_images()
    rule = {'include': ['mine'], 'exclude': ['blue'], 'mode': 'all'}
    assert subboards.query_matches(rule, images) == [red]
    rule = {'include': ['red', 'mine'], 'exclude': [], 'mode': 'any'}
    assert subboards.query_matches(rule, images) == [red, red2, blue]
    rule = {'include': [], 'exclude': ['portrait'], 'mode': 'all'}
    assert subboards.query_matches(rule, images) == [red, blue]
    # Unknown words without the content model match nothing
    rule = {'include': ['nighttime'], 'exclude': [], 'mode': 'all'}
    assert subboards.query_matches(rule, images, by_meaning=False) == []


def test_new_subboard_dialog(view):
    add_images(view, [('#e02020', 60, 40), ('#2040d0', 60, 40)])
    from beeref.rboard.ui.subboard_dialog import SubBoardDialog
    view.rb_analyze(view.rb_images())
    dialog = SubBoardDialog(view, view.rb_images(), by_meaning=False)
    dialog.include.setText('red, ')
    dialog.update_count()
    assert dialog.count.text() == '1 image match'
    assert dialog.title() == 'red'
    dialog.exclude.setText('red')
    dialog.update_count()
    assert not dialog.ok.isEnabled()


def test_kept_boards_and_trees_come_back(view, tmp_path):
    a, b, c = add_images(view, [('#e02020', 60, 40), ('#e02020', 60, 40),
                                ('#2040d0', 60, 40)])
    view.rb_analyze(view.rb_images())
    view.rb_add_link(a, c)
    query = view.subboards.open_query(
        'red', {'include': ['red'], 'exclude': [], 'mode': 'all'},
        view.rb_images())
    view.rb_keep_board(query, True)
    assert not view.undo_stack.isClean()
    view.rb_open_link_tree(a)
    scratch = view.subboards.open_attribute('color:blue', 'blue',
                                            view.rb_images())
    for board in list(view.subboards.boards):
        if board.window:  # a small window reuses areas
            board.window.close()
    data = view.subboards.snapshot()
    assert [d['title'] for d in data] == ['red', 'links · 0.png']
    assert scratch not in [d['title'] for d in data]
    # Reload: kept boards come back closed, with their layouts
    view.subboards.clear()
    view.subboards.restore(data, view.rb_images())
    boards = view.subboards.boards
    assert [b.title for b in boards] == ['red', 'links · 0.png']
    assert boards[0].saved and boards[0].sources == [a, b]
    assert boards[1].is_tree and set(boards[1].sources) == {a, c}
    view.subboards.show(boards[0])
    assert len(boards[0].window.view.rb_images()) == 2
    boards[0].window.close()
    # Discarding closed boards leaves kept ones alone
    view.subboards.discard_cached()
    assert len(view.subboards.boards) == 2


def test_layers_menu_lists_boards(view):
    add_images(view, [('#e02020', 60, 40)])
    view.rb_analyze(view.rb_images())
    view.subboards.open_query('all', {'include': [], 'exclude': [],
                                      'mode': 'all'}, view.rb_images())
    labels = [r.label for r in OverlayMenu(view, view.rb_menu_layers()).rows]
    assert 'new sub board…' in labels and 'all' in labels
    board = view.subboards.boards[0]
    sub = [r.label for r in OverlayMenu(
        view, view.rb_board_entries(board)).rows]
    assert sub[:3] == ['show', 'pop out to a window',
                       'keep in this board file']
    board.window.close()


# ---------- areas (Blender-style window splits) ----------

def test_subboard_docks_in_an_area_and_pops_out(view, main_window):
    main_window.resize(1600, 900)
    screen = main_window.screen
    screen.resize(1600, 900)
    add_images(view, [('#e02020', 60, 40), ('#2040d0', 60, 40)])
    board = open_board(view)
    assert board.state == 'area' and len(screen.areas) == 2
    area = screen.area_of(board)
    assert area.rect_[0] > 0.4 and screen.main_area().rect_[2] == area.rect_[0]
    view.subboards.pop_out(board)
    assert board.state == 'window' and len(screen.areas) == 1
    view.subboards.dock(board)
    assert board.state == 'area' and len(screen.areas) == 2
    board.window.close()
    assert board.state == 'closed' and len(screen.areas) == 1


def test_area_split_join_swap_resize(view, main_window):
    screen = main_window.screen
    screen.resize(1600, 900)
    main = screen.main_area()
    new = screen.split(main, 'y', QtCore.QPointF(800, 600), new_side=3)
    assert main.rect_ == [0, 0, 1, 600 / 900] and new.rect_[1] == 600 / 900
    assert screen.neighbour_side(main, new) == 'down'
    # Resize the border, with Ctrl-style snapping done by the caller
    edges = screen.edges_on('y', main.rect_[3], 0.5)
    screen.move_edges('y', edges, 0.5)
    assert main.rect_[3] == 0.5 == new.rect_[1]
    screen.swap(main, new)
    assert new.is_main() and not main.is_main()
    screen.join(new, main)
    assert len(screen.areas) == 1 and screen.areas[0].rect_ == [0, 0, 1, 1]
    assert screen.areas[0].is_main()


def test_area_maximize_and_layout_saved(view, main_window):
    screen = main_window.screen
    screen.resize(1600, 900)
    add_images(view, [('#e02020', 60, 40)])
    view.rb_analyze(view.rb_images())
    board = view.subboards.open_query(
        'red', {'include': ['red'], 'exclude': [], 'mode': 'all'},
        view.rb_images())
    view.rb_keep_board(board, True)
    area = screen.area_of(board)
    screen.toggle_maximize(area)
    assert not screen.main_area().isVisible()
    screen.toggle_maximize()
    layout = screen.snapshot(view.subboards.kept_boards())
    assert sorted(str(a['shows']) for a in layout) == ['0', 'main']
    data = view.subboards.snapshot()
    view.subboards.clear()
    assert len(screen.areas) == 1
    view.subboards.restore(data, view.rb_images())
    screen.restore(layout, view.subboards.restored)
    assert len(screen.areas) == 2
    assert view.subboards.boards[0].state == 'area'


def test_export_selection_only_has_the_selection(view, tmp_path):
    a, b, c = add_images(view, [('#e02020', 60, 40), ('#2040d0', 60, 40),
                                ('#20a040', 60, 40)])
    from beeref.fileio.export import SceneToPixmapExporter
    exporter = SceneToPixmapExporter(view.scene, items=[a, c])
    exporter.size = exporter.default_size
    path = str(tmp_path / 'sel.png')
    exporter.export(path)
    img = QtGui.QImage(path)
    # a and c with the gap between them, but no blue from b
    assert img.width() > 400
    colors = {img.pixelColor(x, img.height() // 2).name()
              for x in range(0, img.width(), 5)}
    assert '#2040d0' not in colors and '#e02020' in colors
    assert b.isVisible()
