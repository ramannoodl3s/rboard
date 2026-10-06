import os
from unittest.mock import patch

import numpy as np
import pytest
from PyQt6 import QtCore, QtGui

from beeref.items import BeePixmapItem
from beeref.rboard import attributes, semantic


def unit(*values):
    v = np.zeros(512, np.float32)
    v[:len(values)] = values
    return v / np.linalg.norm(v)


def item_with(vec, w=60, h=40, tags=()):
    img = QtGui.QImage(w, h, QtGui.QImage.Format.Format_RGB32)
    img.fill(QtGui.QColor('#808080'))
    item = BeePixmapItem(img, 'x.png')
    semantic.store(item, vec)
    if tags:
        item.meta['tags'] = list(tags)
    return item


@pytest.fixture
def tiny_vocab():
    """Tiny vocabularies, each label on its own axis: kinds 'album cover'
    (axis 0) and 'poster' (3); subjects 'interior' (1) and 'car' (2);
    moods 'calm' (4) and 'tense' (5)."""
    vocab = (['interior', 'car'], np.stack([unit(0, 1), unit(0, 0, 1)]))
    axes = np.eye(512, dtype=np.float32)
    facets = {
        'kind': (['album cover', 'poster'], axes[[0, 3]]),
        'mood': (['calm', 'tense'], axes[[4, 5]]),
        'style': (['minimalist', 'punk'], axes[[6, 7]]),
    }
    with patch.object(semantic, '_vocab', vocab),             patch.dict(semantic._facets, facets, clear=True),             patch.object(semantic, 'KINDS', [('album cover', ''),
                                             ('poster', '')]):
        semantic.set_profile(np.zeros((0, 512), np.float32))
        yield vocab


def test_store_and_read_back(qapp):
    item = item_with(unit(1, 2, 3))
    assert np.allclose(semantic.vector(item), unit(1, 2, 3), atol=1e-3)
    # Cropping changes what the model would see: the cache is invalid
    item.crop = QtCore.QRectF(0, 0, 10, 10)
    assert semantic.vector(item) is None


def test_entries_and_album_cover(qapp, tiny_vocab):
    cover = item_with(unit(1, 0.05), 300, 300)
    room = item_with(unit(0, 1, 0, 0.9), 300, 300)
    assert ('kind:album cover', 'album cover', None, 'auto') in \
        semantic.entries(cover)
    entries = semantic.entries(room)
    assert ('kind:poster', 'poster', None, 'auto') in entries
    assert ('looks:interior', 'interior', None, 'auto') in entries
    # With the model's verdict, the shape-based guess is not used
    keys = attributes.keys_of(room)
    assert 'kind:album cover' not in keys and 'cover:likely' not in keys


def test_mood_is_judged_against_the_board(qapp, tiny_vocab):
    # Every image is a bit "calm"; one is much more "tense" than the rest
    usual = [item_with(unit(1, 0, 0, 0, 0.4, 0.2)) for _ in range(12)]
    odd = item_with(unit(1, 0, 0, 0, 0.4, 0.9))
    semantic.set_profile(semantic.matrix(usual + [odd])[1])
    assert ('mood:tense', 'tense', None, 'auto') in semantic.entries(odd)
    assert not [e for e in semantic.entries(usual[0])
                if e[0].startswith('mood:')]
    item = odd
    item.meta['analysis'] = {'dominant': '#2040d0', 'average': '#2040d0'}
    main, tags, auto = attributes.grouped(item)
    assert [k.split(':')[0] for k, *_ in main] == ['color', 'tone', 'kind',
                                                   'mood']


def test_unindexed_square_falls_back_to_guess(qapp):
    img = QtGui.QImage(400, 400, QtGui.QImage.Format.Format_RGB32)
    item = BeePixmapItem(img, 'x.png')
    assert 'cover:likely' in attributes.keys_of(item)


def test_similar_by_content(qapp):
    a = item_with(unit(1, 0.1))
    b = item_with(unit(1, 0.15))
    c = item_with(unit(0, 1))
    assert semantic.similar(a, [a, b, c]) == [a, b]
    assert attributes.similar_to(a, [a, b, c]) == [a, b]


def test_custom_tag_learns_from_examples(qapp, tiny_vocab):
    rooms = [item_with(unit(0.1, 1, 0.1 * i)) for i in range(3)]
    tagged = rooms[:2]
    for item in tagged:
        item.meta['tags'] = ['spaces']
    others = [item_with(unit(1, 0.1 * i)) for i in range(6)]
    found = semantic.suggest_for_tag('spaces', rooms + others, tagged,
                                     use_text=False)
    assert found == [rooms[2]]


def test_custom_tag_by_name_uses_same_rule(qapp, tiny_vocab):
    # A custom tag name competes with the built-in labels exactly like
    # they compete with each other
    red_car = item_with(unit(0, 0, 0.3, 1))
    room = item_with(unit(0, 1))
    with patch.object(semantic.Clip, 'embed_texts',
                      return_value=np.stack([unit(0, 0, 0.2, 1)])):
        assert semantic.matches_label('red car', [red_car, room]) == \
            [red_car]


def test_grouping_and_names(qapp, tiny_vocab):
    vecs = np.stack([unit(1, 0.01 * i) for i in range(5)]
                    + [unit(0.01 * i, 0, 1) for i in range(5)])
    assign, centers = semantic.group(vecs, 2)
    assert len(set(assign[:5])) == 1 and len(set(assign[5:])) == 1
    assert sorted(semantic.name_groups(centers)) == ['album cover', 'car']


def test_tag_board_has_suggestions(view, tiny_vocab):
    rooms = [item_with(unit(0.1, 1, 0.1 * i)) for i in range(3)]
    others = [item_with(unit(1, 0.1 * i)) for i in range(6)]
    for item in rooms + others:
        view.scene.addItem(item)
    view.rb_add_tag(rooms[:2], 'spaces')
    board = view.subboards.open_attribute('tag:spaces', 'spaces',
                                          view.rb_images())
    assert [len(s) for _, s in board.sections] == [2, 1]
    assert board.window.view.scene.items_for_save()
    board.window.close()


def test_group_by_content_layout_is_undoable(view, tiny_vocab):
    items = [item_with(unit(1, 0.01 * i)) for i in range(4)] + \
        [item_with(unit(0, 0, 1, 0.01 * i)) for i in range(4)]
    for i, item in enumerate(items):
        item.setPos(i * 100, 0)
        view.scene.addItem(item)
    before = [i.pos() for i in items]
    assign, centers = semantic.group(np.stack(
        [semantic.vector(i) for i in items]), 2)
    view.rb_arrange_groups(items, assign, semantic.name_groups(centers),
                           True)
    labels = [i for i in view.scene.items_for_save() if not i.is_image]
    assert sorted(t.toPlainText() for t in labels) == \
        ['album cover · 4', 'car · 4']
    view.undo_stack.undo()
    assert [i.pos() for i in items] == before
    assert not [i for i in view.scene.items_for_save() if not i.is_image]


def test_download_verifies_size(tmp_path):
    with patch.object(semantic, 'model_dir', return_value=str(tmp_path)), \
            patch.dict(semantic.PARTS, {'test': [('a.bin', 10)]}), \
            patch('urllib.request.urlopen') as urlopen:
        response = urlopen.return_value.__enter__.return_value
        response.read.side_effect = [b'12345', b'']
        with pytest.raises(semantic.SemanticError):
            semantic.download('test')
        assert not os.path.exists(tmp_path / 'a.bin')


# Tests swap the settings folder for a temporary one, so remember where
# the real downloaded model lives
REAL_DIR = semantic.model_dir()
REAL = semantic.installed('vision') and semantic.installed('text')


@pytest.mark.skipif(not REAL, reason='content model not downloaded')
@patch.object(semantic, 'model_dir', lambda: REAL_DIR)
def test_real_model_recognises_a_cd(qapp):
    # A CD-like disc: the model should call it music
    img = QtGui.QImage(300, 300, QtGui.QImage.Format.Format_RGB32)
    img.fill(QtGui.QColor('white'))
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    p.setBrush(QtGui.QColor('#c0c0c8'))
    p.drawEllipse(10, 10, 280, 280)
    p.setBrush(QtGui.QColor('white'))
    p.drawEllipse(130, 130, 40, 40)
    p.end()
    arr = semantic.to_array(img.scaled(224, 224))[None]
    vec = semantic.Clip.embed_images(arr)[0]
    assert abs(np.linalg.norm(vec) - 1) < 1e-3
    labels, emb = semantic.vocabulary()
    probs = semantic.probabilities(vec[None], emb)[0]
    assert labels[int(probs.argmax())] in ('CD', 'vinyl record')
    assert semantic.facet('mood')[1].shape == (len(semantic.MOODS), 512)


def test_shipped_vocabulary_matches_labels():
    data = np.load(semantic.VOCAB_FILE)
    assert [str(x) for x in data['labels']] == semantic.LABELS
    assert data['embeddings'].shape == (len(semantic.LABELS), 512)
    for name in ('kind', 'mood', 'style'):
        labels, _ = semantic._facet_prompts(name)
        assert [str(x) for x in data[f'{name}_labels']] == labels
