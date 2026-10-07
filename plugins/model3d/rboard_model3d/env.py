# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Environment lighting: an HDRI (.hdr) or a panorama (.jpg/.png), or a
built-in studio, as an equirectangular image.

Big images are brought down to 2048 x 1024. Light from all around is
precomputed as 9 spherical harmonics (diffuse), plus a small blurred copy
for soft reflections, so drawing stays cheap."""

import math
import os

import numpy as np

MAX_W, MAX_H = 2048, 1024
BLUR_W, BLUR_H = 128, 64
EXTENSIONS = ('.hdr', '.jpg', '.jpeg', '.png')


class Environment:
    def __init__(self, image, name=''):
        self.image = np.ascontiguousarray(fit(image), np.float32)
        self.name = name
        self.sh = irradiance_sh(self.image)
        self.blurred = blur(resize(self.image, BLUR_W, BLUR_H), passes=3)


# ---------- reading ----------

def read_hdr(path):
    """A Radiance .hdr (RGBE) as linear float RGB."""
    with open(path, 'rb') as f:
        data = f.read()
    end = data.find(b'\n\n')
    if not data.startswith(b'#?') or end < 0:
        raise ValueError('not a Radiance .hdr file')
    pos = end + 2
    line_end = data.index(b'\n', pos)
    size = data[pos:line_end].decode('ascii').split()
    pos = line_end + 1
    m = dict(zip(size[0::2], size[1::2]))
    h, w = int(m.get('-Y', m.get('+Y', 0))), int(m.get('+X', m.get('-X', 0)))
    if not w or not h:
        raise ValueError('unknown .hdr layout')
    out = np.empty((h, w, 4), np.uint8)
    for y in range(h):
        if w < 8 or w > 0x7FFF or data[pos] != 2 or data[pos + 1] != 2:
            # Flat (not run-length) scanlines: the rest is plain RGBE
            flat = np.frombuffer(data, np.uint8, (h - y) * w * 4, pos)
            out[y:] = flat.reshape(h - y, w, 4)
            break
        pos += 4
        for c in range(4):
            row = bytearray()
            while len(row) < w:
                count = data[pos]
                pos += 1
                if count > 128:
                    row += bytes((data[pos],)) * (count - 128)
                    pos += 1
                else:
                    row += data[pos:pos + count]
                    pos += count
            out[y, :, c] = np.frombuffer(bytes(row[:w]), np.uint8)
    e = out[..., 3].astype(np.int32)
    scale = np.where(e > 0, np.ldexp(1.0, e - 136), 0.0)
    return (out[..., :3] * scale[..., None]).astype(np.float32)


def read_ldr(path):
    """A panorama image as linear float RGB (brightness 0..1)."""
    from PyQt6 import QtGui
    img = QtGui.QImage(path)
    if img.isNull():
        raise ValueError('could not read the image')
    if img.width() > MAX_W * 2:
        img = img.scaledToWidth(MAX_W * 2)
    img = img.convertToFormat(QtGui.QImage.Format.Format_RGB888)
    arr = np.frombuffer(img.constBits().asstring(img.sizeInBytes()),
                        np.uint8).reshape(img.height(), img.bytesPerLine())
    arr = arr[:, :img.width() * 3].reshape(img.height(), img.width(), 3)
    c = arr.astype(np.float32) / 255
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def load(path):
    ext = os.path.splitext(path)[1].lower()
    if ext not in EXTENSIONS:
        raise ValueError('use an .hdr, .jpg or .png environment')
    image = read_hdr(path) if ext == '.hdr' else read_ldr(path)
    return Environment(image, os.path.basename(path))


# ---------- resizing ----------

def resize(img, w, h):
    """Area-average down to w x h (any factor), nearest up."""
    ih, iw, _ = img.shape
    ys = np.minimum((np.arange(h + 1) * ih / h).astype(int), ih)
    xs = np.minimum((np.arange(w + 1) * iw / w).astype(int), iw)
    # Sum over row bands then column bands with cumulative sums
    cy = np.concatenate([np.zeros((1, iw, 3)), np.cumsum(img, 0)], 0)
    rows = cy[np.maximum(ys[1:], ys[:-1] + 1).clip(max=ih)] - cy[ys[:-1]]
    ny = (np.maximum(ys[1:], ys[:-1] + 1).clip(max=ih) - ys[:-1])
    rows = rows / np.maximum(ny, 1)[:, None, None]
    cx = np.concatenate([np.zeros((h, 1, 3)), np.cumsum(rows, 1)], 1)
    hi = np.maximum(xs[1:], xs[:-1] + 1).clip(max=iw)
    cols = cx[:, hi] - cx[:, xs[:-1]]
    return (cols / np.maximum(hi - xs[:-1], 1)[None, :, None]).astype(
        np.float32)


def fit(img):
    """At most 2048 x 1024, keeping 2:1."""
    h, w, _ = img.shape
    if w <= MAX_W and h <= MAX_H:
        return img
    return resize(img, MAX_W, MAX_H)


def blur(img, passes=2):
    """Box blur that wraps around horizontally (it's a panorama)."""
    out = img.astype(np.float32)
    for _ in range(passes):
        out = (np.roll(out, 1, 1) + out + np.roll(out, -1, 1)) / 3
        pad = np.concatenate([out[:1], out, out[-1:]], 0)
        out = (pad[:-2] + pad[1:-1] + pad[2:]) / 3
    return out


# ---------- light from all around ----------

def directions(w, h):
    """Unit direction per pixel of an equirect image, and solid angles.
    u = 0.5 + atan2(x, -z) / 2pi, v = acos(y) / pi (as the shader)."""
    v = (np.arange(h) + 0.5) / h
    u = (np.arange(w) + 0.5) / w
    theta = v * math.pi                 # from +Y down
    phi = (u - 0.5) * 2 * math.pi
    st, ct = np.sin(theta)[:, None], np.cos(theta)[:, None]
    x = st * np.sin(phi)[None, :]
    y = np.broadcast_to(ct, (h, w))
    z = -st * np.cos(phi)[None, :]
    area = (2 * math.pi / w) * (math.pi / h) * np.broadcast_to(st, (h, w))
    return np.stack([x, y, z], -1), area


def sh_basis(d):
    x, y, z = d[..., 0], d[..., 1], d[..., 2]
    return np.stack([
        0.282095 * np.ones_like(x),
        0.488603 * y, 0.488603 * z, 0.488603 * x,
        1.092548 * x * y, 1.092548 * y * z,
        0.315392 * (3 * z * z - 1),
        1.092548 * x * z, 0.546274 * (x * x - y * y)], -1)


# Cosine-lobe convolution per SH band (Ramamoorthi & Hanrahan 2001)
BAND = np.array([math.pi] + [2 * math.pi / 3] * 3 + [math.pi / 4] * 5)


def irradiance_sh(img):
    """9 RGB coefficients of the light falling on a surface facing each
    way; the shader evaluates them with the same basis."""
    small = resize(img, 128, 64)
    d, area = directions(128, 64)
    basis = sh_basis(d)
    coeffs = np.einsum('hwk,hwc,hw->kc', basis, small, area)
    return (coeffs * BAND[:, None] / math.pi).astype(np.float32)


def evaluate_sh(sh, normal):
    return sh_basis(np.asarray(normal, np.float64)) @ sh


# ---------- built-in studio ----------

def studio(w=512, h=256):
    """A soft studio: light grey above fading to a darker floor, with a
    big softbox front-left and a smaller one behind-right."""
    d, _ = directions(w, h)
    y = d[..., 1]
    base = np.where(y > 0, 0.35 + 0.35 * y, 0.18 + 0.1 * (1 + y))
    img = np.repeat(base[..., None], 3, -1).astype(np.float32)

    def box(direction, size, power, tint=(1, 1, 1)):
        direction = np.asarray(direction, float)
        direction /= np.linalg.norm(direction)
        c = np.clip((d @ direction - math.cos(size)) /
                    (1 - math.cos(size)), 0, 1)
        return (c ** 2)[..., None] * power * np.asarray(tint, np.float32)

    img += box((-1, 0.8, 1), 0.5, 6.0)
    img += box((1, 0.5, -1), 0.3, 3.0, (1.0, 0.97, 0.92))
    img += box((0, 1, 0), 0.6, 1.5)
    return Environment(img, 'studio')

