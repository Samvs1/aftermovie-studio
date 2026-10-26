"""Looks: colour and print treatments that give a film (or one shot, or one photo) its own visual identity.

Use on a photo layer ("look": ...) or a whole shot (fx {"type": "look", "look": ...}). A look is a name or a dict:
  "bw" | {"name": "duotone", "dark": "#1d1a3b", "light": "#ffb3c7", "amount": 1.0}
Optional on any look: "amount" (0..1 mix with the original), "t" + "dur" (ramp the look in).

  bw          punchy black & white (contrast)
  duotone     two-colour gradient map (dark, light)
  tritone     three colours (shadow, mid, high)
  gradient    any number of colour stops ("colors": [...])
  cyanotype   prussian-blue sun print
  sepia       warm brown print
  riso        risograph: two fluorescent inks on paper, stippled, misregistered ("ink1", "ink2", "paper", "offset")
  xerox       photocopy: hard black toner on paper, speckle
  infrared    false-colour (Aerochrome-ish): foliage pink, skies deep
  bleach      bleach bypass: desaturated, hard contrast, silver
  chrome      teal shadows / orange highlights, saturated
  faded       lifted blacks, soft highlights, washed warm
  selective   black & white except one hue range ("hue": 0..360, "width": degrees)
  negative    colour film negative (orange mask)
  posterize   flat colour levels ("levels")
  gameboy     4 greens
  thermal     heat-camera palette
  sketch      graphite pencil drawing on paper ("paper", "lead", "blur", "strength"; "draw": 0..1 or keyframes draws
              the lines in like a hand, left to right); "color": 0..1 or keyframes
              [[t, v], ...] floods the real photo back in like watercolour blooms, from the middle out ("lines":
              how much pencil stays visible in the coloured part)
Optional on any look: "keys": [[t, amount], ...] animates the mix (e.g. a look that fades out on a downbeat).
"""
import math
from functools import lru_cache

import numpy as np
import cv2

from .common import hex2rgb

LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)


def _c(h):
    return np.array(hex2rgb(h)[:3], np.float32)


def luma(img):
    return img @ LUMA


def gradient_map(img, colors, gamma=1.0, contrast=1.0):
    l = np.clip(luma(img), 0, 1)
    if contrast != 1.0:
        l = np.clip((l - 0.5) * contrast + 0.5, 0, 1)
    if gamma != 1.0:
        l = l ** gamma
    cols = np.stack([_c(c) if isinstance(c, str) else np.asarray(c, np.float32) for c in colors])
    stops = np.linspace(0, 1, len(cols))
    idx = np.clip(l * (len(cols) - 1), 0, len(cols) - 1 - 1e-6)
    i0 = idx.astype(np.int32)
    f = (idx - i0)[..., None]
    return cols[i0] * (1 - f) + cols[i0 + 1] * f if len(stops) > 1 else np.broadcast_to(cols[0], img.shape).copy()


def _noise(h, w, seed, blur=0.0):
    n = np.random.default_rng(seed).random((h, w)).astype(np.float32)
    return cv2.GaussianBlur(n, (0, 0), blur) if blur else n


def _shift(a, dx, dy):
    M = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(a, M, (a.shape[1], a.shape[0]), borderMode=cv2.BORDER_REFLECT)


def _sat(img, s):
    g = luma(img)[..., None]
    return g + (img - g) * s


def _keyed(keys, t):
    """[[t, v], ...] -> v at t (smoothstep between keys)."""
    if t is None or t >= keys[-1][0]:
        return keys[-1][1]
    if t <= keys[0][0]:
        return keys[0][1]
    for (ta, va), (tb, vb) in zip(keys[:-1], keys[1:]):
        if t < tb:
            u = (t - ta) / max(tb - ta, 1e-4)
            return va + (vb - va) * u * u * (3 - 2 * u)
    return keys[-1][1]


@lru_cache(maxsize=16)
def _bloom_field(h, w, seed):
    """Blotchy 0..1 field for watercolour blooms: low values colour first, biased to spread from the middle out."""
    rng = np.random.default_rng(seed)
    n1 = cv2.resize(rng.random((max(2, h // 140) + 3, max(2, w // 140) + 3)).astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC)
    n2 = cv2.resize(rng.random((h // 40 + 3, w // 40 + 3)).astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    rad = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2) / 1.414
    f = 0.66 * rad + 0.26 * n1 + 0.08 * n2                    # big soft blooms, no pinholes
    return ((f - f.min()) / (np.ptp(f) + 1e-6)).astype(np.float32)


@lru_cache(maxsize=16)
def _sweep_field(h, w, seed):
    """0..1 field for a drawing hand: mostly left to right, a little top to bottom, ragged like strokes."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    n = cv2.resize(rng.random((h // 24 + 3, w // 6 + 3)).astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR)
    f = 0.72 * xx / w + 0.12 * yy / h + 0.16 * n
    return ((f - f.min()) / (np.ptp(f) + 1e-6)).astype(np.float32)


def _sketch(img, spec, S, t, seed):
    H, W = img.shape[:2]
    g = luma(img)
    inv = cv2.GaussianBlur(1 - g, (0, 0), max(1.0, spec.get("blur", 7.0) * S))
    lines = np.clip((1 - np.clip(g / np.maximum(1 - inv, 1e-3), 0, 1)) * spec.get("strength", 2.4), 0, 1)
    shade = np.clip((0.5 - g) * spec.get("shade", 0.55), 0, 1) * (0.55 + 0.6 * _noise(H, W, seed, 0.7))
    tone = np.clip(lines + shade, 0, 1)
    d = spec.get("draw", 1.0)                                 # the pencil drawing itself in: a sweep, left to right
    if isinstance(d, (list, tuple)):
        d = _keyed(d, t)
    if d < 0.999:
        tone = tone * np.clip((d * 1.3 - _sweep_field(H, W, seed + 5)) / 0.08, 0, 1)
    tone = tone[..., None]
    sk = _c(spec.get("paper", "#f3eee2")) * (1 - tone) + _c(spec.get("lead", "#3b3936")) * tone
    c = spec.get("color", 0.0)
    if isinstance(c, (list, tuple)):
        c = _keyed(c, t)
    if c <= 0.001:
        return sk
    m = np.clip((c * 1.25 - _bloom_field(H, W, seed + 11)) / 0.09, 0, 1)
    rim = (m * (1 - m) * 4)[..., None]                      # pigment pools at the edge of each bloom
    wc = img * (1 - tone * spec.get("lines", 0.28)) * (1 - 0.2 * rim)
    return sk * (1 - m[..., None]) + wc * m[..., None]


def apply(img, spec, S=1.0, t=None, seed=7):
    """img: float32 RGB 0..1 (H, W, 3). Returns a new array."""
    if not spec:
        return img
    if isinstance(spec, str):
        spec = {"name": spec}
    name = spec["name"]
    amt = spec.get("amount", 1.0)
    if t is not None and "t" in spec:
        u = (t - spec["t"]) / max(spec.get("dur", 0.3), 1e-3)
        amt *= float(np.clip(u, 0, 1)) ** 0.8
    if spec.get("keys"):
        amt *= _keyed(spec["keys"], t)
    if amt <= 0.001:
        return img
    img = np.clip(img, 0, 1).astype(np.float32)
    H, W = img.shape[:2]
    if name == "bw":
        l = luma(img)
        c = spec.get("contrast", 1.35)
        l = np.clip((l - 0.5) * c + 0.5 + spec.get("lift", 0.0), 0, 1)
        out = np.repeat(l[..., None], 3, -1)
        if spec.get("tint"):
            out = out * _c(spec["tint"])
    elif name == "duotone":
        out = gradient_map(img, [spec.get("dark", "#1d1a3b"), spec.get("light", "#ffb3c7")], contrast=spec.get("contrast", 1.15))
    elif name == "tritone":
        out = gradient_map(img, [spec.get("shadow", "#14213d"), spec.get("mid", "#e85d75"), spec.get("high", "#fdf0d5")],
                           contrast=spec.get("contrast", 1.1))
    elif name == "gradient":
        out = gradient_map(img, spec["colors"], contrast=spec.get("contrast", 1.0))
    elif name == "cyanotype":
        out = gradient_map(img, ["#06204a", "#1f4e8c", "#8fb0d6", "#eef2f6"], contrast=1.2)
        out = out * (0.96 + 0.04 * _noise(H, W, seed, 1.2))[..., None]
    elif name == "sepia":
        out = gradient_map(img, ["#2b1a0e", "#8a5a33", "#e8cfa5", "#fbf3e2"], contrast=1.1)
    elif name == "riso":
        ink1, ink2 = _c(spec.get("ink1", "#ff48b0")), _c(spec.get("ink2", "#0078bf"))
        paper = _c(spec.get("paper", "#f2ede4"))
        l = luma(img)
        warm = np.clip((img[..., 0] - img[..., 2]) * 1.1 + 0.15, 0, 1)
        d2 = np.clip(1.25 * (1 - l) - 0.18, 0, 1)                       # ink 2 carries the shadows
        d1 = np.clip(0.55 * warm + 0.55 * (1 - l) - 0.05, 0, 1)         # ink 1 carries warm tones + mids
        grain = _noise(H, W, seed + int((t or 0) * 12) % 5)
        coarse = cv2.resize(_noise(H // 3 + 1, W // 3 + 1, seed + 1), (W, H), interpolation=cv2.INTER_NEAREST)
        d1 = np.clip(d1 * (0.82 + 0.3 * coarse) + (grain - 0.5) * 0.5 - 0.04, 0, 1)
        d2 = np.clip(d2 * (0.82 + 0.3 * np.roll(coarse, 5, 1)) + (np.roll(grain, 7, 0) - 0.5) * 0.5 - 0.04, 0, 1)
        off = spec.get("offset", 3.0) * S
        d1 = _shift(d1, off, -off * 0.6)                                # misregistration
        out = paper * (1 - d1[..., None] * (1 - ink1)) * (1 - d2[..., None] * (1 - ink2))
    elif name == "xerox":
        l = cv2.GaussianBlur(luma(img), (0, 0), 0.7 * S)
        d = np.clip((spec.get("threshold", 0.55) - l) * spec.get("hardness", 4.0) + 0.5, 0, 1)
        sp = _noise(H, W, seed + int((t or 0) * 8) % 4)
        d = np.clip(d + (sp > 0.995) * 0.9 - (sp < 0.004) * 0.6, 0, 1)
        out = _c(spec.get("paper", "#efece4")) * (1 - d[..., None]) + _c(spec.get("toner", "#141414")) * d[..., None]
    elif name == "infrared":
        r, g, b = img[..., 0], img[..., 1], img[..., 2]
        out = np.stack([np.clip(0.25 * r + 0.95 * g, 0, 1), np.clip(0.65 * r + 0.1 * g + 0.15 * b, 0, 1),
                        np.clip(0.2 * r + 0.15 * g + 0.85 * b, 0, 1)], -1)
        out = np.clip(_sat(out, 1.25), 0, 1)
    elif name == "bleach":
        l = luma(img)[..., None]
        out = np.clip((img * 0.45 + l * 0.55 - 0.5) * 1.35 + 0.5, 0, 1)
    elif name == "chrome":
        l = luma(img)[..., None]
        out = img + (1 - l) ** 2 * np.array([-0.05, 0.03, 0.08], np.float32) + l ** 2 * np.array([0.08, 0.02, -0.06], np.float32)
        out = np.clip((_sat(out, 1.3) - 0.5) * 1.12 + 0.5, 0, 1)
    elif name == "faded":
        out = _sat(img, 0.72) * 0.82 + 0.12 + np.array([0.025, 0.01, -0.015], np.float32)
    elif name == "selective":
        hsv = cv2.cvtColor((np.clip(img, 0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2HSV).astype(np.float32)
        hue = spec.get("hue", 0) / 2.0
        dh = np.abs((hsv[..., 0] - hue + 90) % 180 - 90)
        keep = np.clip(1 - (dh - spec.get("width", 18) / 2) / 6, 0, 1) * np.clip(hsv[..., 1] / 255 * 3, 0, 1)
        l = np.clip((luma(img) - 0.5) * 1.2 + 0.5, 0, 1)[..., None]
        out = img * keep[..., None] + l * (1 - keep[..., None])
    elif name == "negative":
        out = np.clip((1 - img) * np.array([1.0, 0.8, 0.58], np.float32) + np.array([0.08, 0.04, 0.0], np.float32), 0, 1)
    elif name == "posterize":
        n = spec.get("levels", 4)
        out = np.round(img * (n - 1)) / (n - 1)
    elif name == "gameboy":
        n = 4
        l = np.clip((luma(img) - 0.5) * 1.2 + 0.5, 0, 1)
        q = np.clip(np.floor(l * n), 0, n - 1) / (n - 1)
        out = gradient_map(np.repeat(q[..., None], 3, -1), ["#0f380f", "#306230", "#8bac0f", "#9bbc0f"])
    elif name == "thermal":
        out = gradient_map(img, ["#05001a", "#3b0a75", "#c0164b", "#ff8c00", "#ffe94d", "#ffffff"], contrast=1.1)
    elif name == "sketch":
        out = _sketch(img, spec, S, t, seed)
    else:
        raise ValueError(f"unknown look {name!r}")
    out = np.clip(out, 0, 1).astype(np.float32)
    return out if amt >= 0.999 else img * (1 - amt) + out * amt
