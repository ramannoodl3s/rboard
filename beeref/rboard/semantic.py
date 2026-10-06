# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Content understanding with a small local CLIP model.

OpenAI's CLIP (ViT-B/32, MIT licence) as 8-bit ONNX files from
huggingface.co/Xenova/clip-vit-base-patch32, run with ONNX Runtime on the
CPU. The image half (89 MB) and text half (64 MB) are downloaded
separately, on first use; the text half is only needed for searching
with words and for matching custom tags by name.

Each image is turned into a 512-number embedding once and cached in the
board file. Tags come in groups:

- kind (album cover, poster, photo of a product…): the label that wins
  the probability among the kind labels.
- mood and style: judged against the rest of the board (how much more
  "calm" an image is than the board's typical image), since on a board
  where everything is from one scene every image looks equally "retro".
- subjects (interior, car, flowers…): labels that win enough of the
  probability among all subjects. Custom tags are matched by this same
  rule, competing with the subject labels.
"""

import base64
import logging
import os
import threading
import urllib.request

import numpy as np
from PyQt6 import QtGui
from PyQt6.QtCore import Qt


logger = logging.getLogger(__name__)

MODEL_NAME = 'clip-vit-base-patch32'
BASE_URL = 'https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main/'
PARTS = {
    'vision': [('onnx/vision_model_quantized.onnx', 89117001)],
    'text': [('onnx/text_model_quantized.onnx', 64504507),
             ('tokenizer.json', 2224119)],
}
PART_NAMES = {'vision': 'image model', 'text': 'text model'}
EMBED_VERSION = 1
SIZE = 224
MEAN = np.array([0.48145466, 0.4578275, 0.40821073], np.float32)
STD = np.array([0.26862954, 0.26130258, 0.27577711], np.float32)
LOGIT_SCALE = 100.0          # CLIP's learned temperature
LOOKS_LIKE_PROB = 0.15       # a label "wins" with this share of probability
SUBJECT_PROB = 0.07          # ...or this much among the top 3 subjects
KIND_PROB = 0.30             # share a kind needs to be named
STANDOUT = 0.6               # mood/style: std devs above the board's norm
MIN_PROFILE = 12             # images needed to judge against the board
SIMILAR_COSINE = 0.82        # image-to-image similarity for "similar"
SUGGEST_MAX = 60             # most suggestions shown for a custom tag
SUGGEST_STRICTNESS = 0.25    # share of the examples' own pull (measured)

# What an image is: (tag, prompt)
KINDS = [
    ('album cover', 'an album cover'), ('poster', 'a poster'),
    ('flyer', 'a flyer'), ('advert', 'an advertisement'),
    ('magazine page', 'a magazine page'), ('book cover', 'a book cover'),
    ('packaging', 'product packaging'), ('product shot', 'a product photo'),
    ('fashion photo', 'a fashion photo'), ('portrait', 'a portrait photo'),
    ('street photo', 'a street photo'),
    ('landscape photo', 'a landscape photo'),
    ('interior photo', 'an interior photo'),
    ('architecture photo', 'an architecture photo'),
    ('snapshot', 'a snapshot'), ('film still', 'a film still'),
    ('screenshot', 'a screenshot'), ('interface', 'a user interface'),
    ('illustration', 'an illustration'), ('painting', 'a painting'),
    ('drawing', 'a drawing'), ('3D render', 'a 3D render'),
    ('logo', 'a logo'), ('type design', 'a typographic design'),
    ('pattern', 'a pattern'), ('collage', 'a collage'),
    ('diagram', 'a diagram'), ('comic', 'a comic'),
    ('still life', 'a still life photo'),
]
MOODS = [
    'calm', 'dreamy', 'melancholic', 'playful', 'mysterious', 'eerie',
    'romantic', 'luxurious', 'gritty', 'cozy', 'cold', 'warm', 'clinical',
    'chaotic', 'serene', 'dramatic', 'soft', 'bold', 'joyful', 'lonely',
    'tense', 'sensual', 'nostalgic', 'futuristic',
]
STYLES = [
    'minimalist', 'brutalist', 'cyberpunk', 'vaporwave', 'art deco',
    'mid-century modern', 'grunge', 'psychedelic', 'corporate',
    'Swiss graphic design', 'Frutiger Aero', 'rave', 'Bauhaus', 'kawaii',
    'gothic', 'punk', 'streetwear', 'luxury fashion', 'editorial', 'lo-fi',
    'glossy', 'industrial', 'organic', 'maximalist', 'surreal', 'pop art',
    'techwear', 'Y2K', 'retro-futuristic', 'hand-made', 'clean modern',
]
# What's in an image
LABELS = [
    'CD', 'vinyl record', 'brochure', 'catalogue page', 'postcard',
    'business card', 'booklet', 'book page', 'newspaper', 'bottle',
    'perfume', 'cosmetics', 'shoes', 'sneakers', 'bag', 'jewelry', 'watch',
    'glasses', 'clothing', 'runway show', 'face close-up',
    'group of people', 'crowd', 'hands', 'body', 'child', 'living room',
    'bedroom', 'kitchen', 'bathroom', 'office', 'shop interior',
    'restaurant', 'exhibition', 'stage', 'building', 'skyscraper', 'house',
    'architecture detail', 'staircase', 'street', 'city at night',
    'bridge', 'train', 'subway', 'airport', 'airplane', 'car',
    'car interior', 'motorcycle', 'bicycle', 'boat', 'mountains', 'desert',
    'beach', 'ocean', 'underwater', 'sky', 'clouds', 'sunset', 'forest',
    'flowers', 'plants', 'garden', 'snow', 'rain', 'animal', 'dog', 'cat',
    'bird', 'horse', 'insect', 'fish', 'food', 'drink', 'fruit',
    'furniture', 'chair', 'lamp', 'lighting', 'table', 'computer', 'phone',
    'camera', 'headphones', 'electronics', 'website', 'video game',
    'icons', 'lettering', 'handwriting', 'signage', 'neon sign',
    'graffiti', 'map', 'chart', 'technical drawing', 'blueprint', 'sketch',
    'watercolor', 'anime', 'cartoon character', 'abstract shapes',
    'geometric pattern', 'texture', 'gradient', 'noise', 'grid', 'stripes',
    'dots', 'chrome', 'glass', 'metal', 'plastic', 'paper', 'fabric',
    'wood', 'concrete', 'stone', 'water', 'fire', 'smoke', 'light',
    'shadows', 'reflections', 'black and white photo', 'film photo',
    'sculpture', 'installation art', 'toy', 'robot', 'space', 'planet',
    'moon', 'concert', 'sports', 'dance', 'tickets', 'stickers', 'menu',
]
TEMPLATES = ['a photo of {}.', '{}', 'an image of {}.']
MUSIC_FORMATS = {'CD', 'vinyl record', 'booklet'}  # implied by album cover
FACET_TEMPLATES = {
    'kind': ['a photo of {}.', 'an image of {}.', '{}'],
    'mood': ['a {} image.', 'an image with a {} mood.', 'a {} atmosphere.'],
    'style': ['{} style.', 'an image in {} style.', 'a {} aesthetic.'],
}
FACET_NAMES = {'kind': 'kind', 'mood': 'mood', 'style': 'style',
               'looks': 'subject'}
VOCAB_FILE = os.path.join(os.path.dirname(__file__), 'clip_vocab.npz')


class SemanticError(Exception):
    pass


# ---------- files ----------

def model_dir():
    from beeref.config import BeeSettings
    base = os.path.dirname(BeeSettings().fileName())
    return os.path.join(base, 'models', MODEL_NAME)


def part_size(part):
    return sum(size for _, size in PARTS[part])


def installed(part):
    base = model_dir()
    return all(os.path.isfile(os.path.join(base, f))
               and os.path.getsize(os.path.join(base, f)) == size
               for f, size in PARTS[part])


def download(part, on_progress=None, is_canceled=lambda: False):
    """Fetch a model part, verifying each file's size. Raises on failure
    or cancel; partial files never replace complete ones."""
    base = model_dir()
    total = part_size(part)
    done = 0
    for name, size in PARTS[part]:
        target = os.path.join(base, name)
        if os.path.isfile(target) and os.path.getsize(target) == size:
            done += size
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        tmp = target + '.part'
        request = urllib.request.Request(
            BASE_URL + name, headers={'User-Agent': 'R Board'})
        with urllib.request.urlopen(request, timeout=60) as response, \
                open(tmp, 'wb') as out:
            while True:
                if is_canceled():
                    out.close()
                    os.remove(tmp)
                    raise SemanticError('Download canceled')
                chunk = response.read(1 << 18)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if on_progress:
                    on_progress(done, total)
        if os.path.getsize(tmp) != size:
            os.remove(tmp)
            raise SemanticError(f'{name} downloaded incompletely; try again')
        os.replace(tmp, target)


def remove_models():
    import shutil
    shutil.rmtree(model_dir(), ignore_errors=True)
    Clip.reset()


# ---------- model ----------

class Clip:
    """Lazily loaded ONNX sessions, shared by the whole app."""

    _lock = threading.Lock()
    _vision = None
    _text = None
    _tokenizer = None
    _text_cache = {}

    @classmethod
    def reset(cls):
        with cls._lock:
            cls._vision = cls._text = cls._tokenizer = None
            cls._text_cache = {}

    @classmethod
    def _session(cls, path):
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = max(1, (os.cpu_count() or 2) - 1)
        return ort.InferenceSession(path, options,
                                    providers=['CPUExecutionProvider'])

    @classmethod
    def vision(cls):
        with cls._lock:
            if cls._vision is None:
                if not installed('vision'):
                    raise SemanticError('The image model is not installed')
                cls._vision = cls._session(os.path.join(
                    model_dir(), PARTS['vision'][0][0]))
            return cls._vision

    @classmethod
    def text(cls):
        with cls._lock:
            if cls._text is None:
                if not installed('text'):
                    raise SemanticError('The text model is not installed')
                from tokenizers import Tokenizer
                cls._tokenizer = Tokenizer.from_file(
                    os.path.join(model_dir(), 'tokenizer.json'))
                cls._text = cls._session(os.path.join(
                    model_dir(), PARTS['text'][0][0]))
            return cls._text, cls._tokenizer

    @classmethod
    def embed_images(cls, arrays, batch=16):
        """(N, 3, 224, 224) float32 -> (N, 512) unit vectors."""
        session = cls.vision()
        out = [session.run(None, {'pixel_values': arrays[i:i + batch]})[0]
               for i in range(0, len(arrays), batch)]
        return normalize(np.concatenate(out))

    @classmethod
    def embed_texts(cls, texts, templates=None):
        """Unit vectors for texts, each averaged over a few phrasings."""
        session, tokenizer = cls.text()
        templates = tuple(templates or TEMPLATES)
        result = []
        for text in texts:
            key = (templates, text)
            if key not in cls._text_cache:
                vecs = []
                for template in templates:
                    ids = tokenizer.encode(template.format(text)).ids[:77]
                    vecs.append(session.run(None, {'input_ids': np.array(
                        [ids], np.int64)})[0][0])
                cls._text_cache[key] = normalize(
                    normalize(np.array(vecs)).mean(0))
            result.append(cls._text_cache[key])
        return np.array(result, np.float32)


def normalize(x):
    x = np.asarray(x, np.float32)
    return x / np.maximum(np.linalg.norm(x, axis=-1, keepdims=True), 1e-8)


# ---------- images ----------

def model_input_image(pixmap, crop):
    """The visible part of an image, resized so the short side is 224 px
    and centre-cropped to 224 x 224. GUI thread (pixmaps)."""
    pm = pixmap.copy(crop.toRect())
    if pm.isNull() or pm.width() < 1 or pm.height() < 1:
        return None
    scale = SIZE / min(pm.width(), pm.height())
    w = max(SIZE, round(pm.width() * scale))
    h = max(SIZE, round(pm.height() * scale))
    if max(pm.width(), pm.height()) > 4 * max(w, h):
        pm = pm.scaled(2 * w, 2 * h, Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.FastTransformation)
    img = pm.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation).toImage()
    return img.copy((w - SIZE) // 2, (h - SIZE) // 2, SIZE, SIZE)


def to_array(img, grayscale=False):
    """224x224 QImage -> normalised (3, 224, 224) float32."""
    img = img.convertToFormat(QtGui.QImage.Format.Format_RGB888)
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    a = np.frombuffer(ptr, np.uint8).reshape(SIZE, img.bytesPerLine())
    a = a[:, :SIZE * 3].reshape(SIZE, SIZE, 3).astype(np.float32) / 255
    if grayscale:
        a = np.repeat((a @ np.array([0.299, 0.587, 0.114],
                                    np.float32))[..., None], 3, 2)
    return ((a - MEAN) / STD).transpose(2, 0, 1)


# ---------- cached embeddings ----------

def cache_key(item):
    c = item.crop
    return [round(c.x()), round(c.y()), round(c.width()), round(c.height()),
            bool(item.grayscale), EMBED_VERSION]


def store(item, vector):
    data = base64.b64encode(np.asarray(vector, np.float16).tobytes())
    item.meta['clip'] = {'key': cache_key(item), 'v': data.decode('ascii')}


def vector(item):
    """The item's embedding, or None if it hasn't been computed (or the
    crop changed since)."""
    entry = item.meta.get('clip')
    if not entry or entry.get('key') != cache_key(item):
        return None
    cached = getattr(item, '_clip_vec', None)
    if cached is not None and cached[0] is entry:
        return cached[1]
    vec = np.frombuffer(base64.b64decode(entry['v']),
                        np.float16).astype(np.float32)
    item._clip_vec = (entry, vec)
    return vec


def matrix(items):
    """(indexed items, (N, 512) embeddings) for items that have one."""
    pairs = [(i, vector(i)) for i in items]
    pairs = [(i, v) for i, v in pairs if v is not None]
    if not pairs:
        return [], np.zeros((0, 512), np.float32)
    return [i for i, _ in pairs], np.stack([v for _, v in pairs])


# ---------- labels ----------

_vocab = None
_facets = {}


def _facet_prompts(name):
    if name == 'kind':
        return [k for k, _ in KINDS], [p for _, p in KINDS]
    labels = MOODS if name == 'mood' else STYLES
    return list(labels), list(labels)


def vocabulary():
    """Subject labels and their (L, 512) text embeddings, shipped with
    the app so tagging needs only the image model."""
    global _vocab
    if _vocab is None:
        if os.path.isfile(VOCAB_FILE):
            data = np.load(VOCAB_FILE)
            labels = [str(x) for x in data['labels']]
            if labels == LABELS:
                _vocab = (labels, data['embeddings'].astype(np.float32))
        if _vocab is None:
            _vocab = (list(LABELS), Clip.embed_texts(LABELS))
    return _vocab


def facet(name):
    """(labels, embeddings) for 'kind', 'mood' or 'style'."""
    if name not in _facets:
        labels, prompts = _facet_prompts(name)
        if os.path.isfile(VOCAB_FILE):
            data = np.load(VOCAB_FILE)
            if f'{name}_labels' in data and [
                    str(x) for x in data[f'{name}_labels']] == labels:
                _facets[name] = (labels, data[f'{name}_embeddings'].astype(
                    np.float32))
        if name not in _facets:
            _facets[name] = (labels, Clip.embed_texts(
                prompts, FACET_TEMPLATES[name]))
    return _facets[name]


def naming_vocabulary():
    """Kinds and subjects together, for naming groups."""
    kinds, kemb = facet('kind')
    labels, emb = vocabulary()
    return kinds + labels, np.concatenate([kemb, emb])


def build_vocab_file():
    """Developer helper: precompute the vocabulary embeddings."""
    arrays = {'labels': np.array(LABELS),
              'embeddings': Clip.embed_texts(LABELS).astype(np.float16)}
    for name in ('kind', 'mood', 'style'):
        labels, prompts = _facet_prompts(name)
        arrays[f'{name}_labels'] = np.array(labels)
        arrays[f'{name}_embeddings'] = Clip.embed_texts(
            prompts, FACET_TEMPLATES[name]).astype(np.float16)
    np.savez_compressed(VOCAB_FILE, **arrays)
    global _vocab
    _vocab = None
    _facets.clear()


# ---------- the board's norm (for mood and style) ----------

_profile = {'version': 0, 'stats': None}


def set_profile(vecs):
    """Remember how the board's images score on each mood and style, so
    an image's mood is what sets it apart from the rest of the board."""
    stats = None
    if len(vecs) >= MIN_PROFILE:
        stats = {}
        for name in ('mood', 'style'):
            sims = vecs @ facet(name)[1].T
            stats[name] = (sims.mean(0), sims.std(0) + 1e-6)
    _profile['stats'] = stats
    _profile['version'] += 1


def label_matrix(extra_labels=(), extra_vectors=None):
    """All label names and their text embeddings: the vocabulary plus any
    custom tags (whose embeddings need the text model)."""
    labels, emb = vocabulary()
    extra = [t for t in extra_labels if t not in labels]
    if extra:
        vecs = (extra_vectors if extra_vectors is not None
                else Clip.embed_texts(extra))
        labels = labels + extra
        emb = np.concatenate([emb, vecs])
    return labels, emb


def probabilities(image_vectors, label_vectors):
    """Softmax over labels per image (CLIP zero-shot)."""
    logits = LOGIT_SCALE * image_vectors @ label_vectors.T
    logits -= logits.max(1, keepdims=True)
    p = np.exp(logits)
    return p / p.sum(1, keepdims=True)


def looks_like(prob_row, labels, top=3):
    """Labels an image looks like: winners with enough probability."""
    order = np.argsort(-prob_row)
    out = []
    for idx in order[:top]:
        # A clear share of the probability, or a top place with a
        # reasonable share
        if prob_row[idx] >= SUBJECT_PROB:
            out.append(labels[idx])
    return out


def standout(vec, name):
    """The mood or style that sets an image apart from the board, or
    None. Small boards fall back to the plain zero-shot winner."""
    labels, emb = facet(name)
    sims = emb @ vec
    stats = (_profile['stats'] or {}).get(name)
    if stats is not None:
        z = (sims - stats[0]) / stats[1]
        j = int(z.argmax())
        return labels[j] if z[j] >= STANDOUT else None
    p = probabilities(vec[None], emb)[0]
    j = int(p.argmax())
    return labels[j] if p[j] >= 0.25 else None


def kind_of(vec):
    labels, emb = facet('kind')
    p = probabilities(vec[None], emb)[0]
    j = int(p.argmax())
    return labels[j] if p[j] >= KIND_PROB else None


def entries(item):
    """What the model says about one image, as attribute entries
    (key, label, dot, kind), or None if the image isn't indexed. Uses the
    shipped vocabulary only, so it works without the text model."""
    vec = vector(item)
    if vec is None:
        return None
    entry = item.meta['clip']
    cached = getattr(item, '_clip_entries', None)
    if cached is not None and cached[0] is entry and \
            cached[1] == _profile['version']:
        return cached[2]
    out = []
    kind = kind_of(vec)
    if kind:
        out.append((f'kind:{kind}', kind, None, 'auto'))
    for name in ('mood', 'style'):
        label = standout(vec, name)
        if label:
            out.append((f'{name}:{label}', label, None, 'auto'))
    for label in subjects_of(vec, kind):
        out.append((f'looks:{label}', label, None, 'auto'))
    item._clip_entries = (entry, _profile['version'], out)
    return out


def subjects_of(vec, kind=None):
    """What's in the image. Subjects compete with the kinds, so a scan of
    a magazine isn't also called 'newspaper' just for being print."""
    labels, emb = naming_vocabulary()
    probs = probabilities(vec[None], emb)[0]
    n_kinds = len(KINDS)
    order = [j for j in np.argsort(-probs)[:5] if j >= n_kinds]
    found = [labels[j] for j in order if probs[j] >= SUBJECT_PROB][:3]
    if kind == 'album cover':
        found = [f for f in found if f not in MUSIC_FORMATS]
    return found


def matches_label(label, items, extra_labels=()):
    """Images that look like `label` (built-in or custom tag name) by the
    shared zero-shot rule."""
    indexed, vecs = matrix(items)
    if not indexed:
        return []
    labels, emb = label_matrix(
        [t for t in extra_labels if t] + ([label] if label not in
                                          extra_labels else []))
    probs = probabilities(vecs, emb)
    col = labels.index(label)
    return [item for item, row in zip(indexed, probs)
            if label in looks_like(row, labels) or row[col] >= LOOKS_LIKE_PROB]


def similar(anchor, items):
    """Images that look like the anchor, most similar first."""
    v = vector(anchor)
    indexed, vecs = matrix(items)
    if v is None or not indexed:
        return None
    sims = vecs @ v
    order = np.argsort(-sims)
    return [indexed[i] for i in order if sims[i] >= SIMILAR_COSINE]


def suggest_for_tag(tag, items, tagged, use_text):
    """Untagged images that probably belong under a custom tag.

    The same zero-shot rule as built-in labels (needs the text model),
    plus learning from the images you've tagged: an image is suggested
    when it's clearly closer to your examples than to the board's typical
    image (measured against the examples themselves, so it adapts to
    boards where everything looks alike).
    """
    candidates = [i for i in items if i not in tagged]
    found = []
    if use_text:
        found = matches_label(tag, candidates)
    ex_items, ex_vecs = matrix(tagged)
    all_items, all_vecs = matrix(items)
    cand_items, cand_vecs = matrix(candidates)
    if ex_items and cand_items:
        proto = normalize(ex_vecs.mean(0))
        board = normalize(all_vecs.mean(0))
        ex_contrast = ex_vecs @ proto - ex_vecs @ board
        cutoff = max(0.0, SUGGEST_STRICTNESS * float(np.median(ex_contrast)))
        contrast = cand_vecs @ proto - cand_vecs @ board
        ranked = sorted(zip(cand_items, contrast), key=lambda p: -p[1])
        for item, c in ranked[:SUGGEST_MAX]:
            if c > cutoff and item not in found:
                found.append(item)
    return found


# ---------- grouping ----------

def group(vecs, k, seed=0):
    """Spherical k-means: (labels per image, centres)."""
    from beeref.rboard.analysis import kmeans
    k = max(1, min(k, len(vecs)))
    centers, _ = kmeans(vecs, k, iterations=25, seed=seed)
    centers = normalize(centers)
    assign = (vecs @ centers.T).argmax(1)
    return assign, centers


def name_groups(centers, extra_labels=()):
    """A distinct label name for each group centre."""
    labels, emb = naming_vocabulary()
    extra = [t for t in extra_labels if t not in labels]
    if extra:
        labels = labels + extra
        emb = np.concatenate([emb, Clip.embed_texts(extra)])
    probs = probabilities(centers, emb)
    names, used = [], set()
    for row in probs:
        for idx in np.argsort(-row):
            if labels[idx] not in used:
                used.add(labels[idx])
                names.append(labels[idx])
                break
    return names


def default_group_count(n):
    return int(min(12, max(2, round(np.sqrt(n / 2)))))
