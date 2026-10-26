"""Time to Pretend toolkit: VHS look, VCR on-screen display, halftone, glitch transition, video clips,
VHS cassette, 7" vinyl single and die-cut stickers.

All drawing works in output pixels (callers scale design px with ctx.S), like draw.py.
"""
import math, os
from collections import OrderedDict
from functools import lru_cache

import numpy as np
import cv2

from .common import PHOTOS, hex2rgb
from . import draw as D


# ----------------------------------------------------------------- VHS look (shot fx)
def vhs(canvas, t, S, amount=1.0, band=True):
    """Chroma bleed, soft luma, scanlines, a rolling tracking band and head-switching noise at the bottom."""
    if amount <= 0:
        return
    H, W = canvas.shape[:2]
    rng = np.random.default_rng(int(t * 30) * 7 + 3)
    img = np.clip(canvas, 0, 1)
    ycc = cv2.cvtColor(img, cv2.COLOR_RGB2YCrCb)
    k = max(3, int(13 * S) | 1)
    sh = max(1, int(4 * S))
    for c in (1, 2):
        ch = cv2.blur(ycc[..., c], (k, 1))
        ycc[..., c] = np.roll(ch, sh, axis=1)
    ycc[..., 0] = cv2.blur(ycc[..., 0], (max(1, int(2 * S)) | 1, 1))
    out = cv2.cvtColor(ycc, cv2.COLOR_YCrCb2RGB)
    g = out.mean(-1, keepdims=True)
    out = g + (out - g) * 0.9
    out = out * 0.94 + 0.035
    # scanlines
    per = max(2, int(round(3 * S)))
    lines = np.ones((H, 1, 1), np.float32)
    lines[::per] = 0.9
    out = out * lines
    if band:
        # tracking band rolling slowly down the frame
        bh = int(46 * S)
        y0 = int(((t * 0.23) % 1.25 - 0.12) * H)
        ys, ye = max(0, y0), min(H, y0 + bh)
        if ye > ys:
            sub = out[ys:ye].copy()
            for r in range(ys, ye):
                dx = int(rng.normal(0, 7 * S))
                out[r] = np.roll(sub[r - ys], dx, axis=0)
            noise = rng.random((ye - ys, W)).astype(np.float32)
            out[ys:ye] += ((noise > 0.985) * 0.6)[..., None]
            out[ys:ye] *= 0.93
    # head-switching noise: the bottom lines tear sideways
    hs = int(14 * S)
    if hs > 0:
        for r in range(H - hs, H):
            out[r] = np.roll(out[r], int(18 * S * (r - (H - hs)) / hs + rng.normal(0, 3 * S)), axis=0)
        out[H - hs:] = out[H - hs:] * 0.75 + rng.random((hs, W, 1)).astype(np.float32) * 0.12
    canvas[:] = np.clip(canvas * (1 - amount) + out * amount, 0, 1)


def static(canvas, t, amount=1.0):
    """Snow: full-frame noise burst (tape between recordings)."""
    if amount <= 0:
        return
    H, W = canvas.shape[:2]
    rng = np.random.default_rng(int(t * 30) * 11 + 5)
    n = rng.random((H // 2 + 1, W // 3 + 1)).astype(np.float32)
    n = cv2.resize(n, (W, H), interpolation=cv2.INTER_NEAREST)[..., None]
    canvas[:] = canvas * (1 - amount) + n * amount


# ----------------------------------------------------------------- glitch transition
def glitch(prev_img, cur_img, u, S, seed=0):
    """Tracking-error transition: slices tear sideways, RGB splits, then settle into the new shot."""
    base = (prev_img if u < 0.5 else cur_img).copy()
    e = math.sin(math.pi * u)
    H, W = base.shape[:2]
    rng = np.random.default_rng(seed * 31 + int(u * 12))
    for _ in range(int(3 + 9 * e)):
        y = int(rng.integers(0, H))
        h = int(rng.integers(int(8 * S) + 1, int(80 * S) + 2))
        dx = int(rng.normal(0, 140 * S * e))
        base[y:y + h] = np.roll(base[y:y + h], dx, axis=1)
    sh = int(22 * S * e)
    if sh:
        base[..., 0] = np.roll(base[..., 0], sh, axis=1)
        base[..., 2] = np.roll(base[..., 2], -sh, axis=1)
    noise = rng.random((H, W, 1)).astype(np.float32)
    return np.clip(base * (1 - 0.25 * e) + noise * 0.25 * e, 0, 1)


# ----------------------------------------------------------------- halftone
def halftone(patch, cell, mode="color", ink="#141414", paper="#f4ecd8", amount=1.0, angle=15):
    """Print-dot halftone of an RGB patch. cell = dot pitch in output px."""
    if amount <= 0:
        return patch
    h, w = patch.shape[:2]
    cell = max(3.0, float(cell))
    a = math.radians(angle)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    u = (xx * math.cos(a) + yy * math.sin(a)) / cell
    v = (-xx * math.sin(a) + yy * math.cos(a)) / cell
    fu, fv = u - np.floor(u) - 0.5, v - np.floor(v) - 0.5
    d = np.sqrt(fu * fu + fv * fv)
    # cell-average colour (blur ~ one cell)
    blur = cv2.GaussianBlur(patch, (0, 0), cell * 0.45)
    lum = blur @ np.array([0.299, 0.587, 0.114], np.float32)
    dark = np.clip(1 - lum, 0, 1)
    r = 0.72 * np.sqrt(dark)
    m = np.clip((r - d) * cell * 0.9 + 0.5, 0, 1)[..., None]
    pap = np.array(hex2rgb(paper)[:3], np.float32)
    if mode == "mono":
        dots = np.array(hex2rgb(ink)[:3], np.float32)
        out = pap * (1 - m) + dots * m
    else:  # colour dots: punchy ink of the local colour
        g = blur.mean(-1, keepdims=True)
        sat = np.clip(g + (blur - g) * 1.6, 0, 1) * 0.78
        out = (pap * 0.25 + blur * 0.75) * (1 - m) * 1.04 + sat * m
    out = np.clip(out, 0, 1).astype(np.float32)
    return patch * (1 - amount) + out * amount


# ----------------------------------------------------------------- VCR on-screen display icons
def osd_icon(canvas, kind, x, y, size, color=(1, 1, 1), opacity=1.0):
    """Draw a VCR icon with a dark drop shadow. x, y = left-centre in output px."""
    s = size
    layer = np.zeros(canvas.shape[:2], np.float32)

    def poly(pts):
        cv2.fillPoly(layer, [np.array(pts, np.int32)], 1.0, cv2.LINE_AA)
    if kind == "play":
        poly([(x, y - s / 2), (x + s * 0.85, y), (x, y + s / 2)])
    elif kind == "pause":
        cv2.rectangle(layer, (int(x), int(y - s / 2)), (int(x + s * 0.3), int(y + s / 2)), 1.0, -1)
        cv2.rectangle(layer, (int(x + s * 0.52), int(y - s / 2)), (int(x + s * 0.82), int(y + s / 2)), 1.0, -1)
    elif kind == "stop":
        cv2.rectangle(layer, (int(x), int(y - s * 0.42)), (int(x + s * 0.84), int(y + s * 0.42)), 1.0, -1)
    elif kind == "rec":
        cv2.circle(layer, (int(x + s * 0.42), int(y)), int(s * 0.4), 1.0, -1, cv2.LINE_AA)
    elif kind == "eject":
        poly([(x, y + s * 0.1), (x + s * 0.42, y - s * 0.5), (x + s * 0.84, y + s * 0.1)])
        cv2.rectangle(layer, (int(x), int(y + s * 0.25)), (int(x + s * 0.84), int(y + s * 0.45)), 1.0, -1)
    elif kind == "rew":
        poly([(x + s * 0.5, y - s / 2), (x, y), (x + s * 0.5, y + s / 2)])
        poly([(x + s, y - s / 2), (x + s * 0.5, y), (x + s, y + s / 2)])
    else:
        raise ValueError(kind)
    sh = cv2.GaussianBlur(layer, (0, 0), max(1.0, s * 0.06))
    off = max(1, int(s * 0.07))
    sh = np.roll(np.roll(sh, off, 0), off, 1)
    a = sh[..., None] * 0.6 * opacity
    canvas[:] = canvas * (1 - a)
    a = layer[..., None] * opacity
    canvas[:] = canvas * (1 - a) + np.array(color, np.float32) * a


# ----------------------------------------------------------------- video clips (terrace footage)
class VideoSource:
    """Frame access for a short clip, tuned for the renderer's chunked, mostly-forward access.
    Frames are cached as uint8 (a float32 1080p frame is 25 MB; with many clips per render that ran workers out of memory)."""

    def __init__(self, name):
        self.cap = cv2.VideoCapture(os.path.join(PHOTOS, name))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
        self.n = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.pos = -1
        self.cache = OrderedDict()
        self.last = None

    def frame(self, t_src):
        i = int(np.clip(round(t_src * self.fps), 0, self.n - 1))
        if i in self.cache:
            self.cache.move_to_end(i)
            return self.cache[i].astype(np.float32) / 255
        if not (self.pos < i <= self.pos + 40):
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            self.pos = i - 1
        img = None
        while self.pos < i:
            ok, img = self.cap.read()
            if not ok:
                break
            self.pos += 1
        if img is None:                    # past a clip's last decodable frame: hold the last good one
            rgb = self.last if self.last is not None else np.zeros((480, 848, 3), np.uint8)
        else:
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            self.last = rgb
        self.cache[i] = rgb
        if len(self.cache) > 6:
            self.cache.popitem(last=False)
        return rgb.astype(np.float32) / 255

    def close(self):
        self.cap.release()
        self.cache.clear()


_videos = OrderedDict()
MAX_OPEN = 3                               # open clips per render worker (each holds a decoder + a small frame cache)


def video_frame(name, t_src):
    if name in _videos:
        _videos.move_to_end(name)
    else:
        _videos[name] = VideoSource(name)
        while len(_videos) > MAX_OPEN:
            _videos.popitem(last=False)[1].close()
    return _videos[name].frame(t_src)


# ----------------------------------------------------------------- VHS cassette prop
@lru_cache(maxsize=4)
def cassette(w):
    """Black VHS cassette seen from the front: two reel windows and a blank white label strip."""
    h = int(w * 0.56)
    body = np.zeros((h, w, 3), np.float32)
    yy = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    body[:] = 0.07 + 0.05 * (1 - yy)
    mask = np.zeros((h, w), np.float32)
    r = int(w * 0.025)
    cv2.rectangle(mask, (r, 0), (w - r, h), 1, -1)
    cv2.rectangle(mask, (0, r), (w, h - r), 1, -1)
    for c in [(r, r), (w - r, r), (r, h - r), (w - r, h - r)]:
        cv2.circle(mask, c, r, 1, -1, cv2.LINE_AA)
    # moulded ridges
    for k in range(6):
        y = int(h * (0.86 + k * 0.022))
        cv2.line(body, (int(w * 0.05), y), (int(w * 0.95), y), (0.13, 0.13, 0.14), max(1, int(w * 0.003)), cv2.LINE_AA)
    # smoked window with two reels
    wx0, wx1, wy0, wy1 = int(w * 0.24), int(w * 0.76), int(h * 0.52), int(h * 0.8)
    cv2.rectangle(body, (wx0, wy0), (wx1, wy1), (0.16, 0.15, 0.15), -1)
    for cx, rr in [(0.36, 0.105), (0.64, 0.07)]:
        c = (int(w * cx), int((wy0 + wy1) / 2))
        cv2.circle(body, c, int(w * rr), (0.24, 0.17, 0.12), -1, cv2.LINE_AA)        # wound tape
        cv2.circle(body, c, int(w * 0.04), (0.82, 0.82, 0.8), -1, cv2.LINE_AA)       # hub
        for a in range(6):
            ang = a * math.pi / 3
            cv2.line(body, c, (int(c[0] + w * 0.034 * math.cos(ang)), int(c[1] + w * 0.034 * math.sin(ang))),
                     (0.2, 0.2, 0.2), max(1, int(w * 0.006)), cv2.LINE_AA)
    cv2.rectangle(body, (wx0, wy0), (wx1, wy1), (0.3, 0.3, 0.32), max(1, int(w * 0.004)), cv2.LINE_AA)
    # blank paper label
    lx0, lx1, ly0, ly1 = int(w * 0.07), int(w * 0.93), int(h * 0.09), int(h * 0.44)
    lab = D.paper_texture(lx1 - lx0, ly1 - ly0, "#f4f0e4", seed=9)
    body[ly0:ly1, lx0:lx1] = lab
    for k in range(3):   # faint ruled lines
        y = int(ly0 + (ly1 - ly0) * (0.36 + 0.27 * k))
        cv2.line(body, (lx0 + int(w * 0.02), y), (lx1 - int(w * 0.02), y), (0.72, 0.78, 0.86), 1, cv2.LINE_AA)
    rgba = np.dstack([body, mask])
    return D.shadow_of(rgba, blur=w * 0.02, offset=(w * 0.01, w * 0.02), strength=0.6)


# ----------------------------------------------------------------- 7" vinyl single
@lru_cache(maxsize=4)
def vinyl_disc(d, label="#f4c430", text="SIDE A\n33⅓"):
    """Black record with grooves and a printed centre label (not yet rotated)."""
    R = d // 2
    img = np.zeros((d, d, 3), np.float32) + 0.045
    mask = np.zeros((d, d), np.float32)
    cv2.circle(mask, (R, R), R - 1, 1.0, -1, cv2.LINE_AA)
    for k in range(int(R * 0.36), R - 3, max(2, d // 220)):
        cv2.circle(img, (R, R), k, (0.08, 0.08, 0.085), 1, cv2.LINE_AA)
    cv2.circle(img, (R, R), int(R * 0.34), tuple(float(c) for c in hex2rgb(label)[:3]), -1, cv2.LINE_AA)
    txt = D.text_rgba(text, "anton", d * 0.05, "#141414", line_gap=0.95)
    D.over(img, txt, R - txt.shape[1] / 2, R - txt.shape[0] / 2 - d * 0.075)
    cv2.circle(img, (R, R), max(2, int(d * 0.012)), (0.02, 0.02, 0.02), -1, cv2.LINE_AA)
    return np.dstack([img, mask])


def vinyl_sheen(d):
    """Static specular highlight that doesn't spin with the record."""
    R = d // 2
    yy, xx = np.mgrid[0:d, 0:d].astype(np.float32)
    ang = np.arctan2(yy - R, xx - R)
    s = (np.cos(2 * (ang - 0.7)) ** 8) * 0.13
    rr = np.sqrt((xx - R) ** 2 + (yy - R) ** 2)
    s *= (rr > R * 0.36) & (rr < R - 2)
    return s[..., None].astype(np.float32)


# ----------------------------------------------------------------- die-cut sticker
@lru_cache(maxsize=32)
@lru_cache(maxsize=32)
def _cutout(path):
    """A cut-out (PNG with alpha) as float32 RGBA."""
    im = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if im is None:
        raise FileNotFoundError(path)
    if im.shape[2] == 3:
        im = np.dstack([im, np.full(im.shape[:2], 255, np.uint8)])
    return np.ascontiguousarray(cv2.cvtColor(im, cv2.COLOR_BGRA2RGBA).astype(np.float32) / 255.0)


@lru_cache(maxsize=64)
def image_sticker(path, height, border=0.05, border_color="#ffffff"):
    """A photo cut-out (PNG with alpha, e.g. made by tools/cutout.py) as a die-cut sticker `height` px tall."""
    src = _cutout(path)
    s = height / src.shape[0]
    t = cv2.resize(src, (max(2, int(src.shape[1] * s)), max(2, int(height))), interpolation=cv2.INTER_AREA)
    b = max(2, int(height * border))
    pad = b + 2
    a = np.pad(t[..., 3], pad)
    rim = cv2.dilate((a > 0.3).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * b + 1, 2 * b + 1)))
    rim = cv2.GaussianBlur(rim.astype(np.float32), (0, 0), 0.8)
    out = np.zeros(a.shape + (4,), np.float32)
    out[..., :3] = np.array(hex2rgb(border_color)[:3], np.float32)
    out[..., 3] = rim
    D.over_rgba(out, t, pad, pad)
    return D.shadow_of(out, blur=height * 0.04, offset=(height * 0.025, height * 0.04), strength=0.45)


def sticker(text, fname, size, color="#141414", border=0.09, border_color="#ffffff"):
    """Text or emoji as a die-cut vinyl sticker with a white rim and a soft shadow."""
    t = D.text_rgba(text, fname, size, color)
    b = max(2, int(size * border))
    pad = b + 2
    a = np.pad(t[..., 3], pad)
    rim = cv2.dilate((a > 0.3).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * b + 1, 2 * b + 1)))
    rim = cv2.GaussianBlur(rim.astype(np.float32), (0, 0), 0.8)
    out = np.zeros(a.shape + (4,), np.float32)
    out[..., :3] = np.array(hex2rgb(border_color)[:3], np.float32)
    out[..., 3] = rim
    D.over_rgba(out, t, pad, pad)
    return D.shadow_of(out, blur=size * 0.05, offset=(size * 0.03, size * 0.05), strength=0.45)
