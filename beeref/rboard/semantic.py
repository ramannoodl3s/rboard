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
board file. Built-in labels and custom tags are matched with the same
rule: an image "looks like" a label when that label wins enough of the
probability among all labels (the built-in vocabulary plus your tags).
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
MUSIC_PROB = 0.35            # summed share for the album-cover family
SIMILAR_COSINE = 0.82        # image-to-image similarity for "similar"
SUGGEST_MAX = 60             # most suggestions shown for a custom tag
SUGGEST_STRICTNESS = 0.25    # share of the examples' own pull (measured)

# Moodboard vocabulary. Prompts are averaged over a few phrasings.
LABELS = [
    'album cover', 'CD', 'vinyl record', 'poster', 'flyer', 'brochure',
    'catalogue page', 'postcard', 'business card', 'booklet',
    'magazine page', 'book cover', 'book page', 'newspaper', 'packaging',
    'product photo', 'bottle', 'perfume', 'cosmetics', 'shoes', 'sneakers',
    'bag', 'jewelry', 'watch', 'glasses', 'clothing', 'fashion photo',
    'runway show', 'portrait', 'face close-up', 'group of people', 'crowd',
    'hands', 'body', 'child', 'interior', 'living room', 'bedroom',
    'kitchen', 'bathroom', 'office', 'shop interior', 'restaurant',
    'exhibition', 'stage', 'building', 'skyscraper', 'house',
    'architecture detail', 'staircase', 'street', 'city at night',
    'bridge', 'train', 'subway', 'airport', 'airplane', 'car',
    'car interior', 'motorcycle', 'bicycle', 'boat', 'landscape',
    'mountains', 'desert', 'beach', 'ocean', 'underwater', 'sky', 'clouds',
    'sunset', 'forest', 'flowers', 'plants', 'garden', 'snow', 'rain',
    'animal', 'dog', 'cat', 'bird', 'horse', 'insect', 'fish', 'food',
    'drink', 'fruit', 'furniture', 'chair', 'lamp', 'lighting', 'table',
    'computer', 'phone', 'camera', 'headphones', 'electronics',
    'user interface', 'website', 'video game', 'icons', 'logo',
    'typography', 'lettering', 'handwriting', 'signage', 'neon sign',
    'graffiti', 'map', 'diagram', 'chart', 'technical drawing', 'blueprint',
    'illustration', 'drawing', 'sketch', 'painting', 'watercolor',
    'comic', 'anime', 'cartoon character', 'collage', '3D render',
    'abstract shapes', 'geometric pattern', 'pattern', 'texture',
    'gradient', 'noise', 'grid', 'stripes', 'dots', 'chrome', 'glass',
    'metal', 'plastic', 'paper', 'fabric', 'wood', 'concrete', 'stone',
    'water', 'fire', 'smoke', 'light', 'shadows', 'reflections',
    'black and white photo', 'film photo', 'screenshot',
    'sculpture', 'installation art', 'toy', 'robot', 'space', 'planet',
    'moon', 'concert', 'sports', 'dance', 'tickets', 'stickers', 'menu',
]
TEMPLATES = ['a photo of {}.', '{}', 'an image of {}.']
MUSIC_LABELS = {'album cover', 'CD', 'vinyl record'}
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
    def embed_texts(cls, texts):
        """Unit vectors for texts, each averaged over a few phrasings."""
        session, tokenizer = cls.text()
        result = []
        for text in texts:
            if text not in cls._text_cache:
                vecs = []
                for template in TEMPLATES:
                    ids = tokenizer.encode(template.format(text)).ids[:77]
                    vecs.append(session.run(None, {'input_ids': np.array(
                        [ids], np.int64)})[0][0])
                cls._text_cache[text] = normalize(
                    normalize(np.array(vecs)).mean(0))
            result.append(cls._text_cache[text])
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


def vocabulary():
    """(labels, (L, 512) text embeddings), shipped with the app so naming
    groups needs only the image model."""
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


def build_vocab_file():
    """Developer helper: precompute the vocabulary embeddings."""
    emb = Clip.embed_texts(LABELS)
    np.savez_compressed(VOCAB_FILE, labels=np.array(LABELS),
                        embeddings=emb.astype(np.float16))


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


def looks_like(prob_row, labels, top=2):
    """Labels an image looks like: winners with enough probability."""
    order = np.argsort(-prob_row)
    out = []
    for rank, idx in enumerate(order[:top]):
        # A clear share of the probability, or a near-top place with a
        # reasonable share
        if prob_row[idx] >= LOOKS_LIKE_PROB or (rank < 2 and
                                                prob_row[idx] >= 0.10):
            out.append(labels[idx])
    return out


def is_music(prob_row, labels):
    return sum(p for p, label in zip(prob_row, labels)
               if label in MUSIC_LABELS) >= MUSIC_PROB


def entries(item):
    """What the model says about one image, as attribute entries
    (key, label, dot, kind), or None if the image isn't indexed. Uses the
    shipped vocabulary only, so it works without the text model."""
    vec = vector(item)
    if vec is None:
        return None
    entry = item.meta['clip']
    cached = getattr(item, '_clip_entries', None)
    if cached is not None and cached[0] is entry:
        return cached[1]
    labels, emb = vocabulary()
    probs = probabilities(vec[None], emb)[0]
    out = []
    if is_music(probs, labels):
        out.append(('cover:album', 'album cover', None, 'auto'))
    for label in looks_like(probs, labels):
        if label in MUSIC_LABELS:
            continue
        out.append((f'looks:{label}', f'looks like · {label}', None,
                    'auto'))
    item._clip_entries = (entry, out)
    return out


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
    labels, emb = label_matrix(extra_labels) if extra_labels \
        else vocabulary()
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
