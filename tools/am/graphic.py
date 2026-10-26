"""Graphic vocabulary beyond the scrapbook: knockout type, shapes, slices, kinetic lyric type, film strips,
graphic transitions and music-video shot effects. Wired into frame.py; all coordinates in design px (1920x1080).

Layers
  type_mask   a photo seen through giant letters (window), optionally zooming through them to reveal the photo
              {src, text, font, size, x, y, zoom, focus, scale: [[t, s], ...], invert, look, outline}
  shape       flat shapes: circle | ring | rect | stripes | triangle | line | poly (rings of design px)   {kind, x, y, w, h, color, alpha, rot,
              blend: normal|multiply|screen|overlay, grow: {t, dur}, spin, enter/exit}
  slices      a photo cut into N strips that slide in (and out) one after another
              {src, n, axis: x|y, t, stagger, dur, from: alternate|up|down|left|right, gap, exit: {t, stagger, dur}}
  lyric_type  kinetic typography on the sung words  {words: [{w, t}], mode: replace|stack|line, font, size, color,
              accent, x, y, maxw, anim: punch|rise|fade|type, case: upper|lower, t1}
  filmstrip   a strip of frames with sprocket bands, scrolling or advancing a frame per beat
              {srcs, y, h, t0, speed (px/s) | advance: [t, ...], rot}
Transitions  iris | slices | zoom | strobe | luma | spin | page (a sketchbook page turning over the spine; dir: next|back)
Shot fx      look | strobe | mirror | kaleido | light_leak | letterbox | zoom_blur | torch | rotate
             (echo + stutter: shot keys)
Fill         "grid": {kind: dots|squares, step, color, alpha} turns a fill into a sketchbook page
"""
import math
from functools import lru_cache

import numpy as np
import cv2

from .common import hex2rgb, DESIGN_W, DESIGN_H, font as F
from . import draw as D
from . import looks as LK


def _rgb(h):
    return np.array(hex2rgb(h)[:3], np.float32)


def keyed(keys, t, default=1.0, ease="inout"):
    """Interpolate [[t, v], ...] keyframes with easing."""
    if not keys:
        return default
    if t <= keys[0][0]:
        return keys[0][1]
    for (ta, va), (tb, vb) in zip(keys[:-1], keys[1:]):
        if t < tb:
            return va + (vb - va) * D.ease((t - ta) / max(tb - ta, 1e-4), ease)
    return keys[-1][1]


# ----------------------------------------------------------------- blend-mode compositing
def blend_into(canvas, rgb, alpha, x0, y0, mode="normal", opacity=1.0):
    """Composite an RGB patch with an alpha map onto canvas at (x0, y0) with a blend mode (clipped)."""
    H, W = canvas.shape[:2]
    h, w = alpha.shape[:2]
    x0, y0 = int(round(x0)), int(round(y0))
    ax0, ay0 = max(0, -x0), max(0, -y0)
    cx0, cy0, cx1, cy1 = max(0, x0), max(0, y0), min(W, x0 + w), min(H, y0 + h)
    if cx1 <= cx0 or cy1 <= cy0:
        return
    src = rgb[ay0:ay0 + cy1 - cy0, ax0:ax0 + cx1 - cx0]
    a = alpha[ay0:ay0 + cy1 - cy0, ax0:ax0 + cx1 - cx0][..., None] * opacity
    dst = canvas[cy0:cy1, cx0:cx1]
    if mode == "multiply":
        mix = dst * src
    elif mode == "screen":
        mix = 1 - (1 - dst) * (1 - src)
    elif mode == "overlay":
        mix = np.where(dst < 0.5, 2 * dst * src, 1 - 2 * (1 - dst) * (1 - src))
    elif mode == "lighten":
        mix = np.maximum(dst, src)
    elif mode == "difference":
        mix = np.abs(dst - src)
    else:
        mix = src
    dst[:] = dst * (1 - a) + mix * a


def place_blend(canvas, rgba, cx, cy, scale=1.0, rot=0.0, opacity=1.0, mode="normal"):
    if opacity <= 0.002 or scale <= 0.01:
        return
    p = D.transform_rgba(rgba, scale, rot)
    blend_into(canvas, p[..., :3], p[..., 3], cx - p.shape[1] / 2, cy - p.shape[0] / 2, mode, opacity)


# ----------------------------------------------------------------- type_mask
@lru_cache(maxsize=64)
def _text_alpha(text, font, size, spacing, line_gap):
    a = D.text_rgba(text, font, size, "#ffffff", spacing=spacing, line_gap=line_gap)[..., 3]
    return np.ascontiguousarray(a)


def draw_type_mask(ctx, canvas, shot, L, t, photo_crop_at):
    t0, t1 = L.get("t0", shot["t0"]), L.get("t1", shot["t1"])
    if t < t0 or t > t1:
        return
    crop, box = photo_crop_at(ctx, shot, L, t)
    bx, by, bw, bh = [int(round(ctx.px(v))) for v in box]
    patch = ctx.sources.get(L["src"]).sample(crop, bw, bh)
    if L.get("look"):
        patch = LK.apply(patch, L["look"], ctx.S, t)
    a = _text_alpha(L["text"], L.get("font", "anton"), int(ctx.px(L.get("size", 420))), ctx.px(L.get("spacing", 0)),
                    L.get("line_gap", 0.9))
    s = keyed(L.get("scale"), t, 1.0, L.get("ease", "in"))
    X, Y = ctx.px(L.get("x", DESIGN_W / 2)), ctx.px(L.get("y", DESIGN_H / 2))
    h, w = a.shape
    M = np.float32([[s, 0, X - w / 2 * s - bx], [0, s, Y - h / 2 * s - by]])
    m = cv2.warpAffine(a, M, (bw, bh), flags=cv2.INTER_LINEAR, borderValue=0)
    if L.get("invert"):
        m = 1 - m
    op = D.clamp01((t - t0) / max(L.get("fade", 0.12), 1e-3)) if L.get("fade", 0.12) else 1.0
    if L.get("outline"):
        o = L["outline"]
        k = max(1, int(ctx.px(o.get("px", 6))))
        edge = np.clip(cv2.dilate(m, np.ones((2 * k + 1, 2 * k + 1), np.uint8)) - m, 0, 1)
        blend_into(canvas, np.broadcast_to(_rgb(o.get("color", "#ffffff")), (bh, bw, 3)), edge, bx, by, "normal", op)
    blend_into(canvas, patch, m, bx, by, L.get("blend", "normal"), op)


# ----------------------------------------------------------------- torn paper
@lru_cache(maxsize=64)
def torn_mask(h, w, seed=1, depth=14):
    """Ragged alpha for a torn-paper cut-out (depth = max tear in px)."""
    rng = np.random.default_rng(seed)
    m = np.ones((h, w), np.float32)
    d = max(2, int(depth))
    for side in range(4):
        n = w if side % 2 == 0 else h
        prof = cv2.GaussianBlur(rng.random((1, n)).astype(np.float32), (0, 0), 6)[0]
        prof = (prof - prof.min()) / (np.ptp(prof) + 1e-6)
        fine = rng.random(n).astype(np.float32) * 0.35
        cut = ((prof * 0.75 + fine) * d).astype(int)
        for i, c in enumerate(cut):
            if c <= 0:
                continue
            if side == 0:
                m[:c, i] = 0
            elif side == 2:
                m[h - c:, i] = 0
            elif side == 1:
                m[i, w - c:] = 0
            else:
                m[i, :c] = 0
    return cv2.GaussianBlur(m, (0, 0), 0.6)


@lru_cache(maxsize=64)
def feather_mask(h, w, px):
    """Alpha that fades to 0 over px at every edge (smooth)."""
    px = max(1, int(px))
    ramp_y = np.clip(np.minimum(np.arange(h), np.arange(h)[::-1]) / px, 0, 1)
    ramp_x = np.clip(np.minimum(np.arange(w), np.arange(w)[::-1]) / px, 0, 1)
    m = np.outer(ramp_y, ramp_x).astype(np.float32)
    return m * m * (3 - 2 * m)


# ----------------------------------------------------------------- arches, stars, masks
def arch_points(w, h, point=0.5, n=40):
    """Outline (x, y) of a pointed two-centred arch filling a w x h box: point 0 = round arch, 1 = equilateral
    (the Omani fort / mosque arch is about 0.5). Springing line sits where the arc meets the jambs."""
    c = point * w / 2
    R = w / 2 + c
    a = math.sqrt(max(R * R - c * c, 1e-6))                # rise of the arch above the springing line
    k = min(1.0, h / a)                                    # squash the arch if the box is too short for it
    ys = a * k
    ta = math.acos(max(-1.0, min(1.0, -c / R)))
    left = [(w / 2 + c + R * math.cos(th), ys - R * math.sin(th) * k) for th in np.linspace(math.pi, ta, n)]
    right = [(w / 2 - c + R * math.cos(th), ys - R * math.sin(th) * k) for th in np.linspace(math.pi - ta, 0, n)]
    return [(0, h)] + left + right[1:] + [(w, h)]


def star8_points(w, h):
    """The eight-pointed star (two overlapping squares) centred in a w x h box."""
    s = min(w, h) / math.sqrt(2)
    cx, cy = w / 2, h / 2
    sq = [(-s / 2, -s / 2), (s / 2, -s / 2), (s / 2, s / 2), (-s / 2, s / 2)]
    rot = [((x - y) / math.sqrt(2), (x + y) / math.sqrt(2)) for x, y in sq]
    return [[(cx + x, cy + y) for x, y in sq], [(cx + x, cy + y) for x, y in rot]]


@lru_cache(maxsize=128)
def shape_mask(kind, h, w, point=0.5, line=0.0):
    """Alpha (h x w) for photo/video masks and shape layers: arch | star8 | circle; line > 0 = outline (px)."""
    h, w = max(2, int(h)), max(2, int(w))
    m = np.zeros((h, w), np.float32)
    S = 4                                                   # sub-pixel precision for fillPoly
    if kind == "arch":
        polys = [arch_points(w, h, point)]
    elif kind == "star8":
        polys = star8_points(w, h)
    elif kind == "circle":
        cv2.ellipse(m, (w // 2, h // 2), (w // 2 - 1, h // 2 - 1), 0, 0, 360, 1.0, -1, cv2.LINE_AA)
        polys = []
    else:
        raise ValueError(kind)
    for p in polys:
        cv2.fillPoly(m, [np.round(np.asarray(p) * S).astype(np.int32)], 1.0, cv2.LINE_AA, shift=2)
    if line > 0:
        k = max(1, int(round(line)))
        m = np.clip(m - cv2.erode(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1))), 0, 1)
    return m


@lru_cache(maxsize=64)
def pattern_rgba(motif, w, h, cell, colors, hole=None, rot=0.0):
    """A tiled geometric pattern filling w x h px (design px already scaled): star8 | stripes | chevron | diamond |
    dots; colors = (ground, figure[, accent]) hex. hole = (x, y, w, h) px left transparent (frames)."""
    w, h, cell = max(2, int(w)), max(2, int(h)), max(6, int(cell))
    cols = [np.array(hex2rgb(c)[:3], np.float32) for c in colors] + [None, None]
    g, f, acc = cols[0], cols[1], cols[2] if cols[2] is not None else cols[1]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    if rot:
        th = math.radians(rot)
        xx, yy = xx * math.cos(th) + yy * math.sin(th), -xx * math.sin(th) + yy * math.cos(th)
    u, v = (xx % cell) / cell - 0.5, (yy % cell) / cell - 0.5          # position inside the cell, centred
    if motif == "star8":                     # star = union of a square and a 45-degree square; diamonds at corners
        s = 0.30
        fig = (np.maximum(np.abs(u), np.abs(v)) < s) | (np.maximum(np.abs(u + v), np.abs(u - v)) / math.sqrt(2) < s)
        corner = (np.abs(np.abs(u) - 0.5) + np.abs(np.abs(v) - 0.5)) < 0.14
        a2 = corner.astype(np.float32)
    elif motif == "stripes":
        fig = u < 0.0
        a2 = np.zeros_like(u)
    elif motif == "chevron":
        fig = ((np.abs(u) + v * 2) % 1.0) < 0.5
        a2 = np.zeros_like(u)
    elif motif == "diamond":
        fig = (np.abs(u) + np.abs(v)) < 0.42
        a2 = ((np.abs(u) + np.abs(v)) < 0.16).astype(np.float32)
    elif motif == "dots":
        fig = (u * u + v * v) < 0.09
        a2 = np.zeros_like(u)
    else:
        raise ValueError(motif)
    fig = cv2.GaussianBlur(fig.astype(np.float32), (0, 0), 0.6)
    a2 = cv2.GaussianBlur(a2, (0, 0), 0.6)
    rgb = g * (1 - fig[..., None]) + f * fig[..., None]
    rgb = rgb * (1 - a2[..., None]) + acc * a2[..., None]
    alpha = np.ones((h, w), np.float32)
    if hole:
        hx, hy, hw, hh = [int(round(q)) for q in hole]
        alpha[max(0, hy):max(0, hy + hh), max(0, hx):max(0, hx + hw)] = 0
    return np.dstack([rgb, alpha]).astype(np.float32)


# ----------------------------------------------------------------- shape
def _shape_rgba(kind, w, h, color, alpha, n=7, thick=0.12, point=0.5, line=0.0):
    w, h = max(2, int(w)), max(2, int(h))
    m = np.zeros((h, w), np.float32)
    if kind in ("arch", "star8"):           # filled, or an outline of `line` px
        m = shape_mask(kind, h, w, point, line).copy()
    elif kind == "tag":                     # a price tag: pointed left end with a punched hole
        k = min(w * 0.16, h * 0.5)
        S = 4
        poly = np.array([[k, 0], [w - 1, 0], [w - 1, h - 1], [k, h - 1], [0, h / 2]]) * S
        cv2.fillPoly(m, [np.round(poly).astype(np.int32)], 1.0, cv2.LINE_AA, shift=2)
        cv2.circle(m, (int(k * 0.8), h // 2), max(2, int(h * 0.11)), 0.0, -1, cv2.LINE_AA)
    elif kind == "circle":
        cv2.ellipse(m, (w // 2, h // 2), (w // 2 - 1, h // 2 - 1), 0, 0, 360, 1.0, -1, cv2.LINE_AA)
    elif kind == "ring":
        cv2.ellipse(m, (w // 2, h // 2), (w // 2 - 1, h // 2 - 1), 0, 0, 360, 1.0, max(2, int(min(w, h) * thick)), cv2.LINE_AA)
    elif kind == "rect":
        m[:] = 1.0
    elif kind == "stripes":
        sw = h / (2 * n)
        for i in range(n):
            m[int(2 * i * sw):int((2 * i + 1) * sw)] = 1.0
    elif kind == "triangle":
        cv2.fillPoly(m, [np.array([[w // 2, 0], [w - 1, h - 1], [0, h - 1]], np.int32)], 1.0, cv2.LINE_AA)
    elif kind == "line":
        m[h // 2 - max(1, h // 2):h // 2 + max(1, h // 2)] = 1.0
    else:
        raise ValueError(kind)
    rgba = np.zeros((h, w, 4), np.float32)
    rgba[..., :3] = _rgb(color)
    rgba[..., 3] = m * alpha
    return rgba


def _draw_poly(ctx, canvas, L, t, enter_exit):
    """kind "poly": filled polygon(s) in design px ("rings": [[[x, y], ...], ...]), e.g. a watercolour wash on a map.
    "soft": edge blur in px; "grow": {"t", "dur"} fades it in."""
    rings = [np.asarray(r, np.float32) * ctx.S for r in L["rings"] if len(r) > 2]
    if not rings:
        return
    allp = np.concatenate(rings)
    x0, y0 = np.floor(allp.min(0)) - 4
    x1, y1 = np.ceil(allp.max(0)) + 4
    w, h = int(x1 - x0), int(y1 - y0)
    m = np.zeros((h, w), np.float32)
    cv2.fillPoly(m, [np.round((r - [x0, y0]) * 4).astype(np.int32) for r in rings], 1.0, cv2.LINE_AA, shift=2)
    if L.get("soft"):
        m = cv2.GaussianBlur(m, (0, 0), max(0.5, L["soft"] * ctx.S))
    op = enter_exit(L, t)[4] * L.get("opacity", 1.0)
    if "grow" in L:
        g = L["grow"]
        op *= D.clamp01((t - g["t"]) / max(g.get("dur", 0.3), 1e-3))
    if op <= 0.002:
        return
    blend_into(canvas, np.broadcast_to(_rgb(L.get("color", "#e85d2a")), (h, w, 3)), m * L.get("alpha", 1.0), x0, y0,
               L.get("blend", "normal"), op)


def draw_shape(ctx, canvas, shot, L, t, enter_exit):
    if t < L.get("t0", shot["t0"]) or t > L.get("t1", shot["t1"]):
        return
    if L["kind"] == "poly":
        return _draw_poly(ctx, canvas, L, t, enter_exit)
    w, h = L.get("w", 400), L.get("h", L.get("w", 400))
    if L["kind"] == "pattern":              # tiled geometric pattern (borders, tent stripes, tiles); "hole" = frame
        hole = tuple(ctx.px(q) for q in L["hole"]) if L.get("hole") else None
        args = (L.get("motif", "star8"), tuple(L.get("colors", ("#c8371f", "#f3eee2", "#1d7a4f"))))
        cell = int(max(6, ctx.px(L.get("cell", 64))))
        pw, phh = int(max(2, ctx.px(w))), int(max(2, ctx.px(h)))
        if L.get("scroll"):                 # the pattern drifts (px/s, design px): a moving border / backdrop
            base = pattern_rgba(args[0], pw + cell, phh + cell, cell, args[1], None, L.get("prot", 0.0))
            dt = t - shot["t0"]
            ox = int(round(ctx.px(L["scroll"][0]) * dt)) % cell
            oy = int(round(ctx.px(L["scroll"][1]) * dt)) % cell
            rgba = base[oy:oy + phh, ox:ox + pw].copy()
            if hole:
                hx, hy, hw, hh = [int(round(q)) for q in hole]
                rgba[max(0, hy):max(0, hy + hh), max(0, hx):max(0, hx + hw), 3] = 0
        else:
            rgba = pattern_rgba(args[0], pw, phh, cell, args[1], hole, L.get("prot", 0.0)).copy()
        rgba[..., 3] *= L.get("alpha", 1.0)
    else:
        rgba = _shape_rgba(L["kind"], ctx.px(w), ctx.px(h), L.get("color", "#ff5c35"), L.get("alpha", 1.0), L.get("n", 7),
                           L.get("thick", 0.12), L.get("point", 0.5), ctx.px(L.get("line", 0)))
    dx, dy, sc, rot, op = enter_exit(L, t)
    if "grow" in L:
        g = L["grow"]
        sc *= D.ease((t - g["t"]) / max(g.get("dur", 0.3), 1e-3), g.get("ease", "back")) if t >= g["t"] else 0.0
    if "move" in L:                         # keyframed offset [[t, dx, dy], ...] (e.g. a sun sinking on the beats)
        mx, my = move_at(L["move"], t)
        dx, dy = dx + mx, dy + my
    rot += L.get("rot", 0) + L.get("spin", 0) * (t - shot["t0"])
    clip = L.get("clip")                    # [x, y, w, h] design px: only this rectangle is drawn (behind a horizon)
    keep = canvas.copy() if clip else None
    place_blend(canvas, rgba, ctx.px(L["x"] + dx), ctx.px(L["y"] + dy), sc, rot, op * L.get("opacity", 1.0), L.get("blend", "normal"))
    if clip:
        restore_outside(canvas, keep, [ctx.px(v) for v in clip])


def move_at(keys, t):
    """Keyframed (dx, dy) offsets: [[t, dx, dy], ...] eased between keys."""
    if t <= keys[0][0]:
        return keys[0][1], keys[0][2]
    for (ta, xa, ya), (tb, xb, yb) in zip(keys[:-1], keys[1:]):
        if t < tb:
            u = D.ease((t - ta) / max(tb - ta, 1e-4), "inout")
            return xa + (xb - xa) * u, ya + (yb - ya) * u
    return keys[-1][1], keys[-1][2]


def restore_outside(canvas, keep, rect):
    """Put back every pixel outside rect (x, y, w, h in output px) from keep."""
    H, W = canvas.shape[:2]
    x0, y0 = max(0, int(rect[0])), max(0, int(rect[1]))
    x1, y1 = min(W, int(rect[0] + rect[2])), min(H, int(rect[1] + rect[3]))
    inner = canvas[y0:y1, x0:x1].copy()
    canvas[:] = keep
    if x1 > x0 and y1 > y0:
        canvas[y0:y1, x0:x1] = inner


# ----------------------------------------------------------------- slices
def draw_slices(ctx, canvas, shot, L, t, photo_crop_at):
    crop, box = photo_crop_at(ctx, shot, L, t)
    bx, by, bw, bh = [int(round(ctx.px(v))) for v in box]
    patch = ctx.sources.get(L["src"]).sample(crop, bw, bh)
    if L.get("look"):
        patch = LK.apply(patch, L["look"], ctx.S, t)
    n, axis = L.get("n", 6), L.get("axis", "x")
    gap = int(ctx.px(L.get("gap", 0)))
    t_in, stg, dur = L.get("t", shot["t0"]), L.get("stagger", 0.08), L.get("dur", 0.35)
    ex = L.get("exit")
    frm = L.get("from", "alternate")
    span = bw if axis == "x" else bh
    edges = np.linspace(0, span, n + 1).astype(int)
    H, W = canvas.shape[:2]
    for i in range(n):
        a0, a1 = edges[i] + gap // 2, edges[i + 1] - gap // 2
        if a1 <= a0:
            continue
        u = D.ease((t - (t_in + i * stg)) / max(dur, 1e-3), "out") if t >= t_in + i * stg else 0.0
        if ex and t >= ex["t"] + i * ex.get("stagger", stg):
            u = 1 - D.ease((t - (ex["t"] + i * ex.get("stagger", stg))) / max(ex.get("dur", dur), 1e-3), "in")
        if u <= 0:
            continue
        sign = {"alternate": (1 if i % 2 else -1), "up": -1, "down": 1, "left": -1, "right": 1}.get(frm, 1)
        off = int((1 - u) * (bh if axis == "x" else bw) * 1.05 * sign)
        if axis == "x":                       # vertical strips sliding up/down
            sub = patch[:, a0:a1]
            y0 = by + off
            ys0, ys1 = max(0, y0), min(H, y0 + bh)
            if ys1 > ys0:
                canvas[ys0:ys1, bx + a0:bx + a1] = sub[ys0 - y0:ys1 - y0]
        else:                                 # horizontal strips sliding left/right
            sub = patch[a0:a1]
            x0 = bx + off
            xs0, xs1 = max(0, x0), min(W, x0 + bw)
            if xs1 > xs0:
                canvas[by + a0:by + a1, xs0:xs1] = sub[:, xs0 - x0:xs1 - x0]


# ----------------------------------------------------------------- kinetic lyric type
def _layout(words, font, size, maxw, spacing):
    f = F(font, size)
    space = f.getlength(" ")
    lines, cur, w = [], [], 0.0
    for i, wd in enumerate(words):
        ww = f.getlength(wd)
        if cur and w + space + ww > maxw:
            lines.append((cur, w))
            cur, w = [], 0.0
        cur.append((i, wd, ww))
        w = w + (space if len(cur) > 1 else 0) + ww
    if cur:
        lines.append((cur, w))
    asc, desc = f.getmetrics()
    lh = (asc + desc) * spacing
    pos = {}
    for li, (items, lw) in enumerate(lines):
        x = -lw / 2
        for i, wd, ww in items:
            pos[i] = (x + ww / 2, (li - (len(lines) - 1) / 2) * lh)
            x += ww + space
    return pos


def draw_lyric_type(ctx, canvas, shot, L, t):
    t1 = L.get("t1", shot["t1"])
    words = [w for w in L["words"] if w["t"] <= t] if t <= t1 else []
    if not words:
        return
    case = L.get("case")
    fix = (lambda s: s.upper()) if case == "upper" else (lambda s: s.lower()) if case == "lower" else (lambda s: s)
    font, size = L.get("font", "anton"), L.get("size", 140)
    color, accent = L.get("color", "#ffffff"), L.get("accent", L.get("color", "#ffffff"))
    X, Y = L.get("x", DESIGN_W / 2), L.get("y", DESIGN_H / 2)
    anim = L.get("anim", "punch")
    mode = L.get("mode", "replace")
    stroke, shadow = ctx.px(L.get("stroke", 0)), ctx.px(L.get("shadow", 0))

    def put(txt, x, y, age, col):
        p = D.clamp01(age / 0.16)
        sc, op, dy = 1.0, 1.0, 0.0
        if anim == "punch":
            sc, op = 1.0 + 0.28 * (1 - D.ease(p, "out")), D.clamp01(age / 0.05)
        elif anim == "rise":
            dy, op = 26 * (1 - D.ease(p, "out")), p
        elif anim == "fade":
            op = D.ease(D.clamp01(age / 0.25), "inout")
        elif anim == "type":
            txt = txt[:max(1, int(len(txt) * D.clamp01(age / 0.12)))]
        rgba = D.text_rgba(txt, font, ctx.px(size), col, stroke, L.get("stroke_color", "#000000"), shadow)
        D.place(canvas, rgba, ctx.px(x), ctx.px(y + dy), sc, L.get("rot", 0), op)
    if mode == "replace":
        w = words[-1]
        put(fix(w["w"]), X, Y, t - w["t"], color)
        return
    all_words = [fix(w["w"]) for w in L["words"]]
    pos = _layout(tuple(all_words), font, int(size), L.get("maxw", 1500), L.get("line_gap", 1.0))
    last = len(words) - 1
    for i, w in enumerate(words):
        px, py = pos[i]
        col = accent if (mode == "line" and i == last) else color
        put(all_words[i], X + px, Y + py, t - w["t"], col)


# ----------------------------------------------------------------- filmstrip
def draw_filmstrip(ctx, canvas, shot, L, t, sources_sample):
    srcs = L["srcs"]
    h = L.get("h", 330)
    fh = h * 0.72
    fw = fh * L.get("aspect", 1.45)
    gap = h * 0.12
    pitch = fw + gap
    t0 = L.get("t0", shot["t0"])
    if "advance" in L:                         # one frame per given time, eased
        shift = 0.0
        for ta in L["advance"]:
            if t >= ta:
                shift += D.ease((t - ta) / 0.22, "out")
        shift *= pitch
    else:
        shift = L.get("speed", 140) * max(0.0, t - t0)
    S = ctx.S
    strip_h = int(ctx.px(h))
    W = canvas.shape[1]
    strip = np.zeros((strip_h, W, 3), np.float32) + 0.03
    band = int(strip_h * 0.13)
    from .props import sprocket_strip
    sb = sprocket_strip(W, band, offset=ctx.px(shift))
    strip[:band] = sb
    strip[strip_h - band:] = sb
    x_start = ctx.px(L.get("x0", 60)) - ctx.px(shift)
    for k, s in enumerate(srcs):
        x = x_start + ctx.px(k * pitch)
        if x > W or x + ctx.px(fw) < 0:
            continue
        patch = sources_sample(s, fw / fh, int(ctx.px(fw)), int(ctx.px(fh)), L.get("zoom", 1.1))
        if L.get("look"):
            patch = LK.apply(patch, L["look"], S, t)
        y = (strip_h - patch.shape[0]) // 2
        x0, x1 = int(round(x)), int(round(x)) + patch.shape[1]
        a0, a1 = max(0, -x0), patch.shape[1] - max(0, x1 - W)
        if a1 > a0:
            strip[y:y + patch.shape[0], max(0, x0):min(W, x1)] = patch[:, a0:a1]
    rgba = np.dstack([strip, np.ones(strip.shape[:2], np.float32)])
    D.place(canvas, rgba, W / 2, ctx.px(L.get("y", DESIGN_H / 2)), 1.0, L.get("rot", 0), 1.0)


# ----------------------------------------------------------------- transitions
def _leaf(img, w_new, side, shade):
    """Half a page squeezed to w_new px against the spine (side: 'r' = right half, 'l' = left half), shaded."""
    H, W = img.shape[:2]
    half = img[:, W // 2:] if side == "r" else img[:, :W // 2]
    w_new = max(1, int(w_new))
    sq = cv2.resize(half, (w_new, H), interpolation=cv2.INTER_AREA)
    ramp = np.linspace(0, 1, w_new, dtype=np.float32)
    ramp = ramp if side == "r" else ramp[::-1]                # darker towards the lifted edge
    return sq * (1 - shade * (0.35 + 0.65 * ramp))[None, :, None]


def page_turn(prev, cur, u, tr):
    """A sketchbook page turning over the spine (centre of the frame): the right page of prev lifts and folds onto the
    left, revealing cur underneath; its back is cur's left page. tr: {"dir": "next" | "back"}; centred on the cut."""
    if tr.get("dir", "next") == "back":
        return np.ascontiguousarray(page_turn(np.ascontiguousarray(prev[:, ::-1]), np.ascontiguousarray(cur[:, ::-1]), u,
                                              {"dir": "next"})[:, ::-1])
    H, W = cur.shape[:2]
    hw = W // 2
    out = np.empty_like(cur)
    out[:, :hw] = prev[:, :hw]
    out[:, hw:] = cur[:, hw:]
    e = D.ease(u, "inout")
    c = math.cos(math.pi * e)                                 # +1 flat right .. 0 upright .. -1 flat left
    w = abs(c) * hw
    if c > 0:                                                 # the front of the leaf (prev's right page) lifting
        leaf = _leaf(prev, w, "r", 0.5 * (1 - c))
        x0 = hw
        sh_x0, sh_x1 = hw + int(w), min(W, hw + int(w) + int(0.25 * hw * (1 - c) + 2))
    else:                                                     # the back of the leaf (cur's left page) settling
        leaf = _leaf(cur, w, "l", 0.5 * (1 + c))
        x0 = hw - leaf.shape[1]
        sh_x0, sh_x1 = max(0, x0 - int(0.25 * hw * (1 + c) + 2)), x0
    if sh_x1 > sh_x0:                                         # soft shadow the lifted leaf throws on the page below
        g = np.linspace(0.55, 0.0, sh_x1 - sh_x0, dtype=np.float32)
        g = g if c > 0 else g[::-1]
        out[:, sh_x0:sh_x1] *= (1 - g * (1 - abs(c)))[None, :, None]
    out[:, x0:x0 + leaf.shape[1]] = leaf
    out[:, hw - 2:hw + 2] *= 0.82                             # the gutter
    return out


def transition(typ, prev, cur, u, S, tr, t):
    H, W = cur.shape[:2]
    if typ == "iris":
        cx, cy = W * tr.get("cx", 0.5), H * tr.get("cy", 0.5)
        R = math.hypot(max(cx, W - cx), max(cy, H - cy)) * 1.02
        yy, xx = np.ogrid[0:H, 0:W]
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        if tr.get("close"):                    # silent-film iris: closes on prev to black, opens on cur
            r = (1 - D.ease(min(1, u * 2), "inout")) * R if u < 0.5 else D.ease((u - 0.5) * 2, "inout") * R
            m = np.clip((r - dist) / (6 * S + 1), 0, 1)[..., None]
            return (prev if u < 0.5 else cur) * m
        m = np.clip((D.ease(u, "inout") * R - dist) / (6 * S + 1), 0, 1)[..., None]
        return cur * m + prev * (1 - m)
    if typ == "slices":
        n = tr.get("n", 8)
        out = prev.copy()
        edges = np.linspace(0, W, n + 1).astype(int)
        for i in range(n):
            ui = D.ease(np.clip((u - i * 0.5 / n) / 0.5, 0, 1), "out")
            off = int((1 - ui) * H * (1 if i % 2 else -1))
            y0, y1 = max(0, off), min(H, H + off)
            if y1 > y0 and ui > 0:
                out[y0:y1, edges[i]:edges[i + 1]] = cur[y0 - off:y1 - off, edges[i]:edges[i + 1]]
        return out
    if typ == "zoom":
        def zm(img, s, cx=W / 2, cy=H / 2):
            M = cv2.getRotationMatrix2D((cx, cy), 0, s)
            return cv2.warpAffine(img, M, (W, H), borderMode=cv2.BORDER_REFLECT)
        if u < 0.5:
            k = D.ease(u * 2, "in")
            return np.clip(zm(prev, 1 + 1.6 * k) * (1 - 0.25 * k) + 0.25 * k, 0, 1)
        k = D.ease((u - 0.5) * 2, "out")
        return np.clip(zm(cur, 1.6 - 0.6 * k) * (0.75 + 0.25 * k) + 0.25 * (1 - k), 0, 1)
    if typ == "strobe":
        seg = int(u * tr.get("flips", 6))
        return cur if seg % 2 else prev
    if typ == "luma":
        l = LK.luma(cur)
        thr = 1.05 - 1.15 * D.ease(u, "inout")
        m = np.clip((l - thr) / 0.12, 0, 1)[..., None]
        return cur * m + prev * (1 - m)
    if typ == "page":
        return page_turn(prev, cur, u, tr)
    if typ == "spin":
        def rot(img, a, s):
            M = cv2.getRotationMatrix2D((W / 2, H / 2), a, s)
            return cv2.warpAffine(img, M, (W, H), borderMode=cv2.BORDER_REFLECT)
        e = D.ease(u, "inout")
        return rot(prev, -90 * e, 1 + 0.6 * e) * (1 - e) + rot(cur, 90 * (1 - e), 1.6 - 0.6 * e) * e
    return None


# ----------------------------------------------------------------- shot fx
@lru_cache(maxsize=4)
def _kaleido_maps(W, H, n, rot):
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    cx, cy = W / 2, H / 2
    dx, dy = xx - cx, yy - cy
    r = np.sqrt(dx * dx + dy * dy)
    a = np.arctan2(dy, dx) + rot
    seg = 2 * math.pi / n
    a = np.abs(((a % seg) + seg) % seg - seg / 2)
    return (cx + r * np.cos(a)).astype(np.float32), (cy + r * np.sin(a)).astype(np.float32)


def _leak_field(W, H, t, seed, colors, scale):
    """Soft drifting light blobs (warm leaks)."""
    rng = np.random.default_rng(seed)
    img = np.zeros((H // 4 + 1, W // 4 + 1, 3), np.float32)
    h, w = img.shape[:2]
    for k in range(4):
        cx = (rng.random() + 0.08 * math.sin(t * 0.7 + k * 1.7)) * w
        cy = (rng.random() + 0.08 * math.cos(t * 0.5 + k)) * h
        r = (0.25 + 0.35 * rng.random()) * w * scale
        yy, xx = np.ogrid[0:h, 0:w]
        g = np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * r * r)))[..., None]
        img += g * _rgb(colors[k % len(colors)])
    return cv2.resize(np.clip(img, 0, 1.4), (W, H), interpolation=cv2.INTER_LINEAR)


def _flicker(t, seed):
    """Deterministic candle flicker in ~0..1 (sum of incommensurate sines)."""
    v = sum(math.sin(t * f + seed * p) * a for f, p, a in ((7.3, 1.1, 0.5), (13.1, 2.3, 0.3), (23.7, 0.7, 0.2)))
    return 0.5 + 0.5 * v


def torchlight(canvas, t, fx, ctx):
    """Warm pool of light around (cx, cy) with a flickering radius; outside it the frame falls to near black.
    {amount (0..1 darkness of the edges), cx, cy (0..1), r (fraction of the width), color, flicker, on (music pulse)}"""
    H, W = canvas.shape[:2]
    seed = fx.get("seed", 3)
    fl = _flicker(t, seed) * fx.get("flicker", 1.0)
    cx = W * (fx.get("cx", 0.5) + 0.012 * math.sin(t * 1.7 + seed))
    cy = H * (fx.get("cy", 0.5) + 0.012 * math.cos(t * 1.3 + seed))
    r = W * fx.get("r", 0.42) * (0.94 + 0.08 * fl)
    if fx.get("on") and ctx.music is not None:
        r *= 1 + 0.08 * ctx.music.pulse(fx["on"], t, fx.get("decay", 0.25), 0.3)
    yy, xx = np.ogrid[0:H, 0:W]
    d = np.sqrt(((xx - cx) / r) ** 2 + ((yy - cy) / r) ** 2)
    light = np.clip(1 - d, 0, 1) ** 1.6
    amt = fx.get("amount", 0.85)
    gain = (1 - amt) + amt * light * (0.9 + 0.12 * fl)
    warm = _rgb(fx.get("color", "#ffb066"))
    tint = 1 + (warm - 1) * fx.get("warmth", 0.35)
    return np.clip(canvas * gain[..., None] * tint, 0, 1)


def page_grid(canvas, S, g):
    """Sketchbook page: {"kind": dots|squares, "step": design px, "color", "alpha"} over the page."""
    H, W = canvas.shape[:2]
    step = g.get("step", 48) * S
    col = _rgb(g.get("color", "#9c9384"))
    a = g.get("alpha", 0.35)
    m = np.zeros((H, W), np.float32)
    if g.get("kind", "dots") == "dots":
        r = max(1, int(round(1.6 * S)))
        for y in np.arange(step / 2, H, step):
            for x in np.arange(step / 2, W, step):
                cv2.circle(m, (int(x), int(y)), r, 1.0, -1, cv2.LINE_AA)
    else:
        th = max(1, int(round(1.2 * S)))
        for y in np.arange(step / 2, H, step):
            cv2.line(m, (0, int(y)), (W, int(y)), 1.0, th, cv2.LINE_AA)
        for x in np.arange(step / 2, W, step):
            cv2.line(m, (int(x), 0), (int(x), H), 1.0, th, cv2.LINE_AA)
    m = m[..., None] * a
    return canvas * (1 - m) + col * m


def shot_fx(ctx, canvas, shot, fx, t):
    """Apply one of the graphic shot effects; returns True when handled."""
    typ = fx["type"]
    H, W = canvas.shape[:2]
    if typ == "look":
        canvas[:] = LK.apply(canvas, fx["look"], ctx.S, t)
    elif typ == "strobe":
        v = ctx.music.pulse(fx.get("on", "snares"), t, fx.get("decay", 0.05), fx.get("min", 0.6), window=(shot["t0"] - 0.02, shot["t1"]))
        if v > fx.get("threshold", 0.55):
            mode = fx.get("mode", "invert")
            if mode == "invert":
                canvas[:] = 1 - canvas
            elif mode == "white":
                canvas[:] = canvas * 0.25 + 0.75
            else:
                canvas[:] = canvas * 0.15
    elif typ == "mirror":
        m = fx.get("mode", "x")
        if m in ("x", "quad"):
            canvas[:, W - W // 2:] = canvas[:, :W // 2][:, ::-1]
        if m in ("y", "quad"):
            canvas[H - H // 2:] = canvas[:H // 2][::-1]
    elif typ == "kaleido":
        mx, my = _kaleido_maps(W, H, fx.get("n", 6), round(fx.get("spin", 0.15) * (t - shot["t0"]), 2))
        canvas[:] = cv2.remap(canvas, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    elif typ == "light_leak":
        amt = fx.get("amount", 0.35)
        if fx.get("on"):
            amt *= 0.55 + 0.9 * ctx.music.pulse(fx["on"], t, fx.get("decay", 0.6), 0.3)
        leak = _leak_field(W, H, t, fx.get("seed", 3), fx.get("colors", ["#ff7a1a", "#ffb347", "#ff3d6e", "#ffd28a"]), fx.get("scale", 1.0))
        canvas[:] = 1 - (1 - canvas) * (1 - np.clip(leak * amt, 0, 1))
    elif typ == "letterbox":
        hh = int(ctx.px(keyed(fx.get("keys"), t, fx.get("h", 140))))
        if hh > 0:
            canvas[:hh] = 0
            canvas[H - hh:] = 0
    elif typ == "torch":       # a flickering torch / candle lighting the frame: warm pool of light, dark edges
        canvas[:] = torchlight(canvas, t, fx, ctx)
    elif typ == "rotate":      # the whole frame turns (e.g. 180 = the world upside down): keys [[t, deg], ...]
        a = keyed(fx.get("keys"), t, fx.get("deg", 0.0))
        s = keyed(fx.get("scale_keys"), t, fx.get("scale", 1.0))     # e.g. the book lifted (smaller) mid-turn
        if abs(a) > 0.01 or abs(s - 1) > 1e-3:
            M = cv2.getRotationMatrix2D((W / 2, H / 2), a, s)
            bgc = tuple(float(c) for c in _rgb(fx.get("bg", "#000000")))
            canvas[:] = cv2.warpAffine(canvas, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=bgc)
    elif typ == "zoom_blur":
        v = fx.get("amount", 0.06) * (ctx.music.pulse(fx.get("on", "kicks"), t, fx.get("decay", 0.12), fx.get("min", 0.4))
                                      if fx.get("on", "kicks") else 1.0)
        if v > 0.004:
            acc = canvas.copy()
            for k in range(1, 5):
                M = cv2.getRotationMatrix2D((W / 2, H / 2), 0, 1 + v * k / 4)
                acc += cv2.warpAffine(canvas, M, (W, H), borderMode=cv2.BORDER_REFLECT)
            canvas[:] = acc / 5
    else:
        return False
    return True
