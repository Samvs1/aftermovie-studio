"""Bigger props: polaroid, photo-booth strip, film leader, camera-box label, contact sheet, map."""
import json, math, os
from functools import lru_cache

import numpy as np
import cv2

from .common import ASSETS, hex2rgb
from . import draw as D

CREAM = np.array(hex2rgb("#f5f1e8")[:3], np.float32)


# ----------------------------------------------------------------- polaroid
def developed(img, u):
    """Polaroid development look: dark olive-grey -> full image as u goes 0 -> 1."""
    if u >= 1:
        return img
    u = D.clamp01(u)
    gray = img.mean(-1, keepdims=True)
    sat = u ** 0.8
    col = gray + (img - gray) * sat
    col = col * (0.55 + 0.45 * u) + np.array([-0.03, 0.0, 0.05], np.float32) * (1 - u)
    base = np.array([0.21, 0.23, 0.22], np.float32)
    k = D.ease(u, "inout")
    return np.clip(base * (1 - k) + col * k, 0, 1)


def polaroid(photo_rgb, card_w, caption=None, caption_font="caveat", caption_color="#1f2a44", seed=0):
    """Build a polaroid card RGBA around an already-sampled square-ish photo patch."""
    pw = photo_rgb.shape[1]
    ph = photo_rgb.shape[0]
    side = (card_w - pw) // 2
    top = side
    bottom = int(card_w * 0.27)
    H = top + ph + bottom
    card = np.ones((H, card_w, 3), np.float32) * CREAM
    rng = np.random.default_rng(seed)
    card *= (0.97 + 0.03 * cv2.GaussianBlur(rng.random((H, card_w)).astype(np.float32), (0, 0), 2))[..., None]
    # inner photo with a faint inset edge
    card[top:top + ph, side:side + pw] = photo_rgb * 0.97
    cv2.rectangle(card, (side - 1, top - 1), (side + pw, top + ph), (0.86, 0.84, 0.8), 1, cv2.LINE_AA)
    rgba = np.dstack([card, np.ones((H, card_w), np.float32)])
    if caption:
        txt = D.text_rgba(caption, caption_font, card_w * 0.105, caption_color, jitter_seed=seed % 97)
        sc = min(1.0, (card_w * 0.9) / txt.shape[1])
        if sc < 1:
            txt = cv2.resize(txt, (int(txt.shape[1] * sc), int(txt.shape[0] * sc)), interpolation=cv2.INTER_AREA)
        D.over_rgba(rgba, txt, (card_w - txt.shape[1]) / 2, top + ph + (bottom - txt.shape[0]) / 2 + card_w * 0.005)
    return D.shadow_of(rgba, blur=card_w * 0.025, offset=(card_w * 0.012, card_w * 0.02), strength=0.5)


# ----------------------------------------------------------------- photo-booth strip
def booth_strip(frames, strip_w, color="#fbfaf6", label=""):
    """frames: list of RGB patches (same size). Returns RGBA vertical strip."""
    fw, fh = frames[0].shape[1], frames[0].shape[0]
    m = (strip_w - fw) // 2
    gap = int(m * 0.8)
    foot = int(strip_w * 0.16)
    H = m + len(frames) * fh + (len(frames) - 1) * gap + foot
    s = np.ones((H, strip_w, 3), np.float32) * np.array(hex2rgb(color)[:3], np.float32)
    y = m
    for f in frames:
        s[y:y + fh, m:m + fw] = f
        y += fh + gap
    rgba = np.dstack([s, np.ones((H, strip_w), np.float32)])
    if label:                                  # printed in the strip's foot, e.g. "LISBON  ★  2026"
        lab = D.text_rgba(label, "mono", strip_w * 0.075, "#3a3a3a")
        D.over_rgba(rgba, lab, (strip_w - lab.shape[1]) / 2, H - foot + (foot - lab.shape[0]) / 2)
    return D.shadow_of(rgba, blur=strip_w * 0.03, offset=(strip_w * 0.015, strip_w * 0.025), strength=0.5)


# ----------------------------------------------------------------- film leader
def leader_frame(W, H, number, sweep, seed):
    """Academy-style countdown frame. sweep 0..1 = clock hand progress within this number."""
    S = W / 1920
    img = np.ones((H, W, 3), np.float32) * 0.62
    cx, cy = W // 2, H // 2
    R = int(H * 0.40)
    # swept wedge darker
    ang = -90 + 360 * D.clamp01(sweep)
    wedge = np.zeros((H, W), np.float32)
    cv2.ellipse(wedge, (cx, cy), (W, W), 0, -90, ang, 1.0, -1, cv2.LINE_AA)
    img = img * (1 - 0.28 * wedge[..., None])
    vign = D.vignette(W, H, 0.55)
    img = img * vign
    lc = (0.95, 0.95, 0.93)
    th = max(2, int(5 * S))
    cv2.circle(img, (cx, cy), R, lc, th, cv2.LINE_AA)
    cv2.circle(img, (cx, cy), int(R * 0.86), lc, max(1, th // 2), cv2.LINE_AA)
    cv2.line(img, (0, cy), (W, cy), (0.15, 0.15, 0.15), max(1, int(3 * S)), cv2.LINE_AA)
    cv2.line(img, (cx, 0), (cx, H), (0.15, 0.15, 0.15), max(1, int(3 * S)), cv2.LINE_AA)
    num = D.text_rgba(str(number), "bebas", H * 0.62, "#141414")
    D.over(img, num, cx - num.shape[1] / 2, cy - num.shape[0] / 2 + H * 0.02)
    D.dust_and_scratches(img, seed, 1.4)
    return img


# ----------------------------------------------------------------- disposable camera box label
@lru_cache(maxsize=4)
def camera_label(w, title="SINGLE USE", sub="single-use camera", count="27", edition=""):
    """Single-use camera box panel (no brand): colour blocks + specs. title / sub / count / edition are the printed
    texts (Cool Kids: "ELEVATE 2026", "single-use camera · shot in amsterdam", "27", "cool kids\nedition")."""
    h = int(w * 0.62)
    img = np.zeros((h, w, 3), np.float32)
    yel = np.array(hex2rgb("#f4b400")[:3], np.float32)
    red = np.array(hex2rgb("#d7263d")[:3], np.float32)
    ink = np.array(hex2rgb("#141414")[:3], np.float32)
    img[:] = yel
    img[int(h * 0.64):] = red
    # diagonal stripe (kept below the subtitle line)
    pts = np.array([[0, int(h * 0.58)], [w, int(h * 0.47)], [w, int(h * 0.53)], [0, int(h * 0.64)]], np.int32)
    cv2.fillPoly(img, [pts], tuple(float(c) for c in ink), cv2.LINE_AA)
    rgba = np.dstack([img, np.ones((h, w), np.float32)])
    t1 = D.text_rgba(title, "anton", w * 0.13, "#141414")
    D.over_rgba(rgba, t1, w * 0.06, h * 0.06)
    t2 = D.text_rgba(sub, "mono", w * 0.036, "#141414")
    D.over_rgba(rgba, t2, w * 0.065, h * 0.06 + t1.shape[0] * 0.70)
    t3 = D.text_rgba(str(count), "anton", w * 0.16, "#ffffff")
    D.over_rgba(rgba, t3, w * 0.06, h * 0.655)
    t4 = D.text_rgba("EXPOSURES\nISO 400 · FLASH", "mono", w * 0.04, "#ffffff", align="left", line_gap=1.0)
    D.over_rgba(rgba, t4, w * 0.06 + t3.shape[1] * 0.92, h * 0.715)
    if edition:
        t5 = D.text_rgba(edition, "caveat", w * 0.075, "#ffffff", align="right", line_gap=0.9)
        D.over_rgba(rgba, t5, w - t5.shape[1] - w * 0.05, h * 0.655)
    # rounded corners
    mask = np.zeros((h, w), np.float32)
    r = int(w * 0.03)
    cv2.rectangle(mask, (r, 0), (w - r, h), 1, -1)
    cv2.rectangle(mask, (0, r), (w, h - r), 1, -1)
    for c in [(r, r), (w - r, r), (r, h - r), (w - r, h - r)]:
        cv2.circle(mask, c, r, 1, -1, cv2.LINE_AA)
    rgba[..., 3] = mask
    return D.shadow_of(rgba, blur=w * 0.02, offset=(w * 0.01, w * 0.02), strength=0.55)


# ----------------------------------------------------------------- contact sheet
def sprocket_strip(W, h, offset=0.0):
    """Black film edge with sprocket holes (RGB)."""
    s = np.zeros((h, W, 3), np.float32) + 0.03
    hole_w, hole_h = int(h * 0.42), int(h * 0.55)
    step = int(h * 1.05)
    x = -int(offset % step)
    while x < W:
        cv2.rectangle(s, (x, (h - hole_h) // 2), (x + hole_w, (h + hole_h) // 2), (0.82, 0.8, 0.74), -1, cv2.LINE_AA)
        x += step
    return s


# ----------------------------------------------------------------- map
@lru_cache(maxsize=1)
def countries():
    d = json.load(open(os.path.join(ASSETS, "geo", "ne_50m_admin_0_countries.geojson"), encoding="utf-8"))
    out = []
    for f in d["features"]:
        p = f["properties"]
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        out.append((p.get("ISO_A2_EH") or p.get("ISO_A2"), p.get("NAME"), polys))
    return out


class MapProj:
    def __init__(self, W, H, lon0=-11.0, lon1=44.5, lat0=34.0, lat1=60.5, margin=0.04):
        self.W, self.H = W, H
        self.k = math.cos(math.radians((lat0 + lat1) / 2))
        sx = W * (1 - 2 * margin) / ((lon1 - lon0) * self.k)
        sy = H * (1 - 2 * margin) / (lat1 - lat0)
        self.s = min(sx, sy)
        self.cx = (lon0 + lon1) / 2
        self.cy = (lat0 + lat1) / 2

    def __call__(self, lon, lat):
        return (self.W / 2 + (lon - self.cx) * self.k * self.s, self.H / 2 - (lat - self.cy) * self.s)


TINTS = {"ES": "#e9a23b", "BE": "#f2c94c", "NL": "#f08a24", "DE": "#c9a227", "PL": "#e05a6d", "TR": "#d9534f"}
WASHES = ["#e9a23b", "#e05a6d", "#7fb069", "#5fa8d3", "#f2c94c", "#b07cc6", "#f08a24", "#d9534f", "#4fb3a6", "#c9a227"]


@lru_cache(maxsize=4)
def base_map(W, H, highlight=("ES", "BE", "NL", "DE", "PL", "TR"), bounds=None):
    """Paper map with pencil coastlines/borders and watercolour washes on the highlighted countries.
    bounds = (lon0, lon1, lat0, lat1) frames any region (default: Europe, as in the Elevate films)."""
    paper = D.paper_texture(W, H, "#f1ead9").copy()
    proj = MapProj(W, H, *bounds) if bounds else MapProj(W, H)
    lo_a, lo_b, la_a, la_b = (bounds[0] - 25, bounds[1] + 25, bounds[2] - 20, bounds[3] + 20) if bounds else (-30, 60, 25, 72)
    S = W / 1920
    land = np.zeros((H, W), np.float32)
    wash = np.zeros((H, W, 3), np.float32)
    wash_a = np.zeros((H, W), np.float32)
    lines = np.zeros((H, W), np.float32)
    rng = np.random.default_rng(11)
    for iso, name, polys in countries():
        for poly in polys:
            ring = np.array(poly[0], np.float32)
            if ring[:, 0].max() < lo_a or ring[:, 0].min() > lo_b or ring[:, 1].max() < la_a or ring[:, 1].min() > la_b:
                continue
            pts = np.array([proj(lo, la) for lo, la in ring], np.float32)
            pi = np.round(pts * 8).astype(np.int32)
            cv2.fillPoly(land, [pi], 1.0, cv2.LINE_AA, shift=3)
            if iso in highlight:
                m = np.zeros((H, W), np.float32)
                cv2.fillPoly(m, [pi], 1.0, cv2.LINE_AA, shift=3)
                col = np.array(hex2rgb(TINTS.get(iso) if not bounds and iso in TINTS else WASHES[highlight.index(iso) % len(WASHES)])[:3], np.float32)
                wash += m[..., None] * col
                wash_a = np.maximum(wash_a, m)
            jitter = pts + rng.normal(0, 0.6 * S, pts.shape).astype(np.float32)
            cv2.polylines(lines, [np.round(jitter * 8).astype(np.int32)], True, 1.0, max(1, int(1.6 * S)), cv2.LINE_AA, shift=3)
    # watercolour: blurred, uneven
    noise = cv2.GaussianBlur(rng.random((H, W)).astype(np.float32), (0, 0), 18 * S)
    noise = (noise - noise.min()) / (noise.max() - noise.min() + 1e-6)
    wa = cv2.GaussianBlur(wash_a, (0, 0), 2.5 * S) * (0.25 + 0.3 * noise)
    wc = wash / np.maximum(wash_a[..., None], 1e-3)
    paper = paper * (1 - 0.05 * land[..., None])          # land a touch darker than sea
    paper = paper * (1 - wa[..., None]) + wc * wa[..., None]
    ink = np.array(hex2rgb("#5c5346")[:3], np.float32)
    la = np.clip(lines, 0, 1)[..., None] * 0.55
    paper = paper * (1 - la) + ink * la
    return paper.astype(np.float32), proj


def arc_points(p0, p1, bend=0.22, n=60):
    (x0, y0), (x1, y1) = p0, p1
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy)
    nx, ny = dy / max(L, 1), -dx / max(L, 1)
    if ny > 0:  # always bow upwards
        nx, ny = -nx, -ny
    cx, cy = mx + nx * L * bend, my + ny * L * bend
    t = np.linspace(0, 1, n)
    return np.stack([(1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t ** 2 * x1, (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t ** 2 * y1], 1)


def dashed(canvas, pts, color, width, dash=14, gap=10, progress=1.0):
    pts = D.stroke_path(pts, progress)
    if len(pts) < 2:
        return
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    acc = np.r_[0, np.cumsum(seg)]
    total = acc[-1]
    s = 0.0
    while s < total:
        e = min(total, s + dash)
        a = np.interp(np.linspace(s, e, 6), acc, pts[:, 0])
        b = np.interp(np.linspace(s, e, 6), acc, pts[:, 1])
        D.draw_marker(canvas, np.stack([a, b], 1), color, width)
        s += dash + gap
