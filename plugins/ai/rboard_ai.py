# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""R Board's AI features plugin: runs the CLIP image and text models
with ONNX Runtime. R Board itself does everything else (downloading the
models, storing vectors, tags, search); this is the part that needs the
big libraries, so it's installed once on its own.

The release zip bundles onnxruntime and tokenizers in `lib`; from a
source checkout they come from the virtualenv.
"""

import os
import threading

import numpy as np


class Engine:
    """Lazily loaded ONNX sessions, shared by the whole app."""

    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        self._vision = self._text = self._tokenizer = None
        self._text_cache = {}

    @staticmethod
    def check():
        """Raises if the libraries are missing (without importing them,
        which would slow R Board's start)."""
        from importlib.util import find_spec
        for name in ('onnxruntime', 'tokenizers'):
            if find_spec(name) is None:
                raise ImportError(f'{name} is missing')

    @staticmethod
    def _session(path):
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = max(1, (os.cpu_count() or 2) - 1)
        return ort.InferenceSession(path, options,
                                    providers=['CPUExecutionProvider'])

    def vision(self, model_path):
        with self._lock:
            if self._vision is None:
                self._vision = self._session(model_path)
            return self._vision

    def text(self, model_path, tokenizer_path):
        with self._lock:
            if self._text is None:
                from tokenizers import Tokenizer
                self._tokenizer = Tokenizer.from_file(tokenizer_path)
                self._text = self._session(model_path)
            return self._text, self._tokenizer

    def embed_images(self, model_path, arrays, batch=16):
        """(N, 3, 224, 224) float32 -> (N, 512) raw vectors."""
        session = self.vision(model_path)
        out = [session.run(None, {'pixel_values': arrays[i:i + batch]})[0]
               for i in range(0, len(arrays), batch)]
        return np.concatenate(out)

    def embed_text(self, model_path, tokenizer_path, text):
        """Raw vector for one text."""
        key = text
        if key not in self._text_cache:
            session, tokenizer = self.text(model_path, tokenizer_path)
            ids = tokenizer.encode(text).ids[:77]
            self._text_cache[key] = session.run(
                None, {'input_ids': np.array([ids], np.int64)})[0][0]
        return self._text_cache[key]


def register(api):
    engine = Engine()
    engine.check()
    api.provide('ai', engine)
