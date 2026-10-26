"""Drawing primitives. Everything returns / works on float32 RGBA (premultiplied=False) or RGB arrays.

Coordinates passed in here are already in output pixels (the frame compositor scales design px).
"""
import math, os, re
from functools import lru_cache

import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFilter

from .common import font, hex2rgb, ASSETS

EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF️]")


# ----------------------------------------------------------------- easing
def clamp01(x):
    return max(0.0, min(1.0, x))


def ease(x, kind="inout"):
    x = clamp01(x)
    if kind == "linear":
        return x
    if kind == "in":
        return x * x * x
    if kind == "out":
        return 1 - (1 - x) ** 3
    if kind == "back":  # overshoot then settle
        c1, c3 = 1.70158, 2.70158
        return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2
    if kind == "expo_out":
        return 1 if x >= 1 else 1 - 2 ** (-10 * x)
    if kind == "elastic":
        if x in (0, 1):
            return x
        return 2 ** (-10 * x) * math.sin((x * 10 - 0.75) * (2 * math.pi) / 3) + 1
    return x * x * (3 - 2 * x)  # smooth in-out


# ----------------------------------------------------------------- compositing
def over(canvas, rgba, x, y, opacity=1.0):
    """Alpha-composite RGBA (h,w,4) onto canvas (H,W,3) with top-left at integer x,y (clipped)."""
    H, W = canvas.shape[:2]
    h, w = rgba.shape[:2]
    x0, y0 = int(round(x)), int(round(y))
    ax0, ay0 = max(0, -x0), max(0, -y0)
    cx0, cy0 = max(0, x0), max(0, y0)
    cx1, cy1 = min(W, x0 + w), min(H, y0 + h)
    if cx1 <= cx0 or cy1 <= cy0:
        return
    src = rgba[ay0:ay0 + (cy1 - cy0), ax0:ax0 + (cx1 - cx0)]
    a = src[..., 3:4] * opacity
    dst = canvas[cy0:cy1, cx0:cx1]
    dst *= (1 - a)
    dst += src[..., :3] * a


def transform_rgba(rgba, scale=1.0, rot=0.0):
    """Scale + rotate an RGBA patch around its centre; returns new patch (expanded)."""
    if abs(scale - 1) < 1e-3 and abs(rot) < 1e-3:
        return rgba
    h, w = rgba.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), -rot, scale)
    cos, sin = abs(M[0, 0]), abs(M[0, 1])
    nw, nh = int(h * sin + w * cos) + 2, int(h * cos + w * sin) + 2
    M[0, 2] += nw / 2 - w / 2
    M[1, 2] += nh / 2 - h / 2
    interp = cv2.INTER_AREA if scale < 0.7 else cv2.INTER_LINEAR
    return cv2.warpAffine(rgba, M, (max(1, nw), max(1, nh)), flags=interp, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))


def place(canvas, rgba, cx, cy, scale=1.0, rot=0.0, opacity=1.0):
    """Composite rgba centred at (cx, cy) with scale/rotation."""
    if opacity <= 0.002 or scale <= 0.01:
        return
    p = transform_rgba(rgba, scale, rot)
    over(canvas, p, cx - p.shape[1] / 2, cy - p.shape[0] / 2, opacity)


def screen(canvas, rgb, amount=1.0):
    canvas[:] = 1 - (1 - canvas) * (1 - rgb * amount)


def shadow_of(rgba, blur, offset=(0, 0), strength=0.5, pad=None):
    """Return a bigger RGBA with a soft drop shadow beneath the patch."""
    need = int(math.ceil(max(abs(offset[0]), abs(offset[1]))))
    pad = max(pad if pad is not None else int(blur * 2.5), 0) + need + 1
    h, w = rgba.shape[:2]
    out = np.zeros((h + 2 * pad, w + 2 * pad, 4), np.float32)
    a = np.zeros((h + 2 * pad, w + 2 * pad), np.float32)
    ox, oy = int(offset[0]), int(offset[1])
    a[pad + oy:pad + oy + h, pad + ox:pad + ox + w] = rgba[..., 3]
    if blur > 0:
        a = cv2.GaussianBlur(a, (0, 0), blur)
    out[..., 3] = a * strength
    # paste original on top
    sub = out[pad:pad + h, pad:pad + w]
    al = rgba[..., 3:4]
    sub[..., :3] = rgba[..., :3] * al + sub[..., :3] * (1 - al)
    sub[..., 3:4] = al + sub[..., 3:4] * (1 - al)
    return out


# ----------------------------------------------------------------- text
@lru_cache(maxsize=16)
def _cmap(fname):
    from fontTools.ttLib import TTFont
    from .common import FONTS
    fn = FONTS[fname][0]
    return set(TTFont(fn if os.path.isabs(fn) else os.path.join(ASSETS, "fonts", fn)).getBestCmap())


def has_glyph(fname, ch):
    return ord(ch) in _cmap(fname)


@lru_cache(maxsize=512)
def text_rgba(text, fname, size, color="#ffffff", stroke=0, stroke_color="#000000", shadow=0.0,
              spacing=0, line_gap=1.08, align="center", jitter_seed=-1):
    """Render (multi-line) text to an RGBA float32 patch. Emoji are drawn in colour."""
    if fname in ("marker", "anton", "bebas") and any(ord(c) > 255 and not EMOJI_RE.match(c) and not has_glyph(fname, c)
                                                     for c in text):
        fname = "caveat" if fname == "marker" else "narrow"
    f = font(fname, size)
    ef = font("emoji", size * 0.92)
    lines = text.split("\n")
    pad = int(size * 0.35 + stroke * 2 + shadow * 2)
    # measure
    def runs(line):
        out, buf, is_e = [], "", None
        for ch in line:
            e = bool(EMOJI_RE.match(ch))
            if is_e is None or e == is_e:
                buf += ch
            else:
                out.append((buf, is_e))
                buf = ch
            is_e = e
        if buf:
            out.append((buf, is_e))
        return out

    def run_w(s, e):
        if e:
            return ef.getlength(s)
        return f.getlength(s) + spacing * max(0, len(s) - 1)

    widths = [sum(run_w(s, e) for s, e in runs(l)) for l in lines]
    asc, desc = f.getmetrics()
    lh = int((asc + desc) * line_gap)
    W = int(max(widths + [1]) + 2 * pad)
    H = int(lh * len(lines) + 2 * pad)
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    col = tuple(int(c * 255) for c in hex2rgb(color)[:3])
    scol = tuple(int(c * 255) for c in hex2rgb(stroke_color)[:3])
    rng = np.random.default_rng(jitter_seed) if jitter_seed >= 0 else None
    for li, line in enumerate(lines):
        lw = widths[li]
        x = pad + (W - 2 * pad - lw) * (0.5 if align == "center" else (1.0 if align == "right" else 0.0))
        y = pad + li * lh
        for s, e in runs(line):
            if e:
                d.text((x, y + size * 0.06), s, font=ef, embedded_color=True)
                x += ef.getlength(s)
            else:
                for ch in (s if (spacing or rng is not None) else [s]):
                    dy = float(rng.normal(0, size * 0.018)) if rng is not None else 0
                    d.text((x, y + dy), ch, font=f, fill=col + (255,), stroke_width=int(stroke), stroke_fill=scol + (255,))
                    x += f.getlength(ch) + (spacing if (spacing or rng is not None) else 0)
    arr = np.asarray(im, np.float32) / 255
    if shadow > 0:
        arr = shadow_of(arr, blur=shadow, offset=(0, shadow * 0.4), strength=0.55)
    return arr


# ----------------------------------------------------------------- 7-segment digits (date stamp / counter)
SEG = {
    "0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd", "6": "afgedc",
    "7": "abc", "8": "abcdefg", "9": "abcdfg", "-": "g", " ": "", "'": "'",
}


@lru_cache(maxsize=64)
def seven_seg(text, h, color="#ff8a1e", glow=True):
    """Orange LCD-style date imprint, e.g. "'26 9 19". h = digit height in px."""
    w = h * 0.56
    th = max(2, h * 0.14)
    gap = h * 0.2
    slant = h * 0.08
    xs = []
    total = 0
    for ch in text:
        cw = w * 0.35 if ch == "'" else (w * 0.55 if ch == " " else w)
        xs.append((ch, total, cw))
        total += cw + gap
    pad = int(h * 0.6)
    W, H = int(total + 2 * pad), int(h + 2 * pad)
    a = np.zeros((H, W), np.float32)

    def seg_poly(x0, name):
        y0 = pad
        g = th * 0.18          # gap between segments
        hh = h / 2
        t2 = th / 2

        def hseg(y):           # horizontal hexagon centred on y
            return [(x0 + t2 + g, y), (x0 + th + g, y - t2), (x0 + w - th - g, y - t2), (x0 + w - t2 - g, y),
                    (x0 + w - th - g, y + t2), (x0 + th + g, y + t2)]

        def vseg(x, ya, yb):   # vertical hexagon centred on x from ya to yb
            return [(x, ya + g), (x + t2, ya + t2 + g), (x + t2, yb - t2 - g), (x, yb - g), (x - t2, yb - t2 - g), (x - t2, ya + t2 + g)]
        P = {"a": hseg(y0 + t2), "g": hseg(y0 + hh), "d": hseg(y0 + h - t2),
             "f": vseg(x0 + t2, y0 + t2, y0 + hh), "b": vseg(x0 + w - t2, y0 + t2, y0 + hh),
             "e": vseg(x0 + t2, y0 + hh, y0 + h - t2), "c": vseg(x0 + w - t2, y0 + hh, y0 + h - t2)}
        pts = np.array(P[name], np.float32)
        pts[:, 0] += (pad + h - pts[:, 1]) / h * slant   # italic slant
        return pts

    for ch, x, cw in xs:
        x0 = pad + x
        if ch == "'":
            pts = np.array([(x0 + cw * 0.3, pad), (x0 + cw * 0.8, pad), (x0 + cw * 0.5, pad + h * 0.28), (x0 + cw * 0.1, pad + h * 0.28)], np.float32)
            pts[:, 0] += slant
            cv2.fillPoly(a, [np.round(pts * 4).astype(np.int32)], 1.0, lineType=cv2.LINE_AA, shift=2)
            continue
        for s in SEG.get(ch, ""):
            pts = seg_poly(x0, s)
            cv2.fillPoly(a, [np.round(pts * 4).astype(np.int32)], 1.0, lineType=cv2.LINE_AA, shift=2)
    col = np.array(hex2rgb(color)[:3], np.float32)
    out = np.zeros((H, W, 4), np.float32)
    if glow:
        g = cv2.GaussianBlur(a, (0, 0), h * 0.12)
        alpha = np.clip(a * 0.95 + g * 0.55, 0, 1)
        core = np.clip(a, 0, 1)[..., None]
        out[..., :3] = col * (1 - core * 0.25) + core * 0.25  # hot core slightly lighter
    else:
        alpha = a
        out[..., :3] = col
    out[..., 3] = alpha
    return out


# ----------------------------------------------------------------- flags (hand-made stickers)
FLAG_SPECS = {
    "ES": ("h", [("#c60b1e", 1), ("#ffc400", 2), ("#c60b1e", 1)]),
    "BE": ("v", [("#1a1a1a", 1), ("#fdda24", 1), ("#ef3340", 1)]),
    "NL": ("h", [("#ae1c28", 1), ("#ffffff", 1), ("#21468b", 1)]),
    "DE": ("h", [("#1a1a1a", 1), ("#dd0000", 1), ("#ffce00", 1)]),
    "PL": ("h", [("#ffffff", 1), ("#dc143c", 1)]),
    "TR": ("h", [("#e30a17", 1)]),
    "RU": ("h", [("#ffffff", 1), ("#0039a6", 1), ("#d52b1e", 1)]),
    "GE": ("h", [("#ffffff", 1)]),              # the crosses are drawn below
}


@lru_cache(maxsize=64)
def flag_sticker(code, w, rot_seed=0, border=True):
    """A small die-cut sticker of a flag with white border + soft shadow. Returns RGBA."""
    h = int(w * 2 / 3)
    ss = 3
    W, H = w * ss, h * ss
    img = np.zeros((H, W, 3), np.float32)
    orient, bands = FLAG_SPECS[code]
    tot = sum(b for _, b in bands)
    pos = 0
    for colr, b in bands:
        c = np.array(hex2rgb(colr)[:3], np.float32)
        if orient == "h":
            y0, y1 = int(H * pos / tot), int(H * (pos + b) / tot)
            img[y0:y1] = c
        else:
            x0, x1 = int(W * pos / tot), int(W * (pos + b) / tot)
            img[:, x0:x1] = c
        pos += b
    if code == "TR":
        m = np.zeros((H, W), np.float32)
        cx, cy, r = int(W * 0.38), H // 2, int(H * 0.25)
        cv2.circle(m, (cx, cy), r, 1.0, -1, cv2.LINE_AA)
        cv2.circle(m, (int(cx + r * 0.25), cy), int(r * 0.8), 0.0, -1, cv2.LINE_AA)
        sx, sy, sr = int(W * 0.56), cy, H * 0.12
        pts = []
        for k in range(10):
            ang = -math.pi / 2 + k * math.pi / 5 + math.pi / 2
            rr = sr if k % 2 == 0 else sr * 0.42
            pts.append((sx + rr * math.cos(ang - math.pi / 2), sy + rr * math.sin(ang - math.pi / 2)))
        cv2.fillPoly(m, [np.array(pts, np.int32)], 1.0, cv2.LINE_AA)
        img = img * (1 - m[..., None]) + m[..., None]
    if code == "GE":       # five-cross flag: a big red St George's cross + four small crosses
        red = np.array(hex2rgb("#e8112d")[:3], np.float32)
        m = np.zeros((H, W), np.float32)
        bw = int(H * 0.2)
        cv2.rectangle(m, (0, H // 2 - bw // 2), (W, H // 2 + bw // 2), 1.0, -1)
        cv2.rectangle(m, (W // 2 - bw // 2, 0), (W // 2 + bw // 2, H), 1.0, -1)
        for qx in (0.25, 0.75):
            for qy in (0.25, 0.75):
                cx, cy, s, th = int(W * qx), int(H * qy), int(H * 0.11), max(2, int(H * 0.045))
                cv2.rectangle(m, (cx - s, cy - th), (cx + s, cy + th), 1.0, -1)
                cv2.rectangle(m, (cx - th, cy - s), (cx + th, cy + s), 1.0, -1)
        img = img * (1 - m[..., None]) + red * m[..., None]
    # hand-cut wobbly rounded rect mask
    rng = np.random.default_rng(hash(code) % 1000 + rot_seed)
    mask = np.zeros((H, W), np.float32)
    rad = int(H * 0.12)
    cv2.rectangle(mask, (rad, 0), (W - rad, H), 1.0, -1)
    cv2.rectangle(mask, (0, rad), (W, H - rad), 1.0, -1)
    for cx_, cy_ in [(rad, rad), (W - rad, rad), (rad, H - rad), (W - rad, H - rad)]:
        cv2.circle(mask, (cx_, cy_), rad, 1.0, -1, cv2.LINE_AA)
    img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_AREA)
    # paper texture
    img = img * (0.94 + 0.06 * rng.random((h, w, 1), np.float32))
    rgba = np.dstack([img, mask])
    if border:
        b = max(3, int(w * 0.07))
        big = np.zeros((h + 2 * b, w + 2 * b, 4), np.float32)
        m2 = np.zeros((h + 2 * b, w + 2 * b), np.float32)
        m2[b:b + h, b:b + w] = mask
        m2 = cv2.dilate(m2, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * b + 1, 2 * b + 1)))
        big[..., :3] = 0.97
        big[..., 3] = m2
        sub = big[b:b + h, b:b + w]
        sub[..., :3] = sub[..., :3] * (1 - mask[..., None]) + img * mask[..., None]
        rgba = big
    return shadow_of(rgba, blur=max(2, w * 0.04), offset=(w * 0.02, w * 0.03), strength=0.45)


# ----------------------------------------------------------------- passport stamp
@lru_cache(maxsize=64)
def passport_stamp(top, mid, bottom, size, color="#2b3f9e", shape="circle", seed=0):
    """Ink stamp: circular (or rectangular) double border with text. Rough ink texture."""
    S = size
    pad = int(S * 0.08)
    W = H = S + 2 * pad
    if shape == "rect":
        H = int(S * 0.62) + 2 * pad
    im = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(im)
    lw = max(2, S // 40)
    if shape == "circle":
        d.ellipse([pad, pad, W - pad, H - pad], outline=255, width=lw * 2)
        d.ellipse([pad + S * 0.07, pad + S * 0.07, W - pad - S * 0.07, H - pad - S * 0.07], outline=255, width=lw)
        # arc text: top and bottom
        def arc_text(txt, radius, top_side=True, fsize=S * 0.11):
            f = font("mono", fsize)
            total = sum(f.getlength(c) for c in txt) + fsize * 0.15 * (len(txt) - 1)
            ang_span = total / radius
            ang = -math.pi / 2 - ang_span / 2 if top_side else math.pi / 2 + ang_span / 2
            for c in txt:
                cw = f.getlength(c) + fsize * 0.15
                a_mid = ang + (cw / 2 / radius) * (1 if top_side else -1)
                ch = Image.new("L", (int(fsize * 1.6), int(fsize * 1.6)), 0)
                ImageDraw.Draw(ch).text((fsize * 0.8, fsize * 0.8), c, font=f, fill=255, anchor="mm")
                rot = math.degrees(a_mid) + (90 if top_side else -90)
                ch = ch.rotate(-rot, resample=Image.BICUBIC)
                x = W / 2 + radius * math.cos(a_mid) - ch.width / 2
                y = H / 2 + radius * math.sin(a_mid) - ch.height / 2
                im.paste(255, (int(x), int(y)), ch)
                ang += (cw / radius) * (1 if top_side else -1)
        arc_text(top, S * 0.355, True)
        if bottom:
            arc_text(bottom, S * 0.355, False)
        fsz = S * 0.17
        while font("anton", fsz).getlength(mid) > S * 0.6 and fsz > 6:
            fsz *= 0.93
        d.text((W / 2, H / 2), mid, font=font("anton", fsz), fill=255, anchor="mm")
        d.line([W / 2 - S * 0.25, H / 2 - S * 0.13, W / 2 + S * 0.25, H / 2 - S * 0.13], fill=255, width=lw)
        d.line([W / 2 - S * 0.25, H / 2 + S * 0.13, W / 2 + S * 0.25, H / 2 + S * 0.13], fill=255, width=lw)
    else:
        d.rounded_rectangle([pad, pad, W - pad, H - pad], radius=S * 0.05, outline=255, width=lw * 2)
        d.rounded_rectangle([pad + S * 0.04, pad + S * 0.04, W - pad - S * 0.04, H - pad - S * 0.04], radius=S * 0.03, outline=255, width=lw)
        ft = S * 0.085
        while font("mono", ft).getlength(top) > S * 0.8 and ft > 6:
            ft *= 0.92
        d.text((W / 2, pad + S * 0.13), top, font=font("mono", ft), fill=255, anchor="mm")
        fm = S * 0.16
        while font("anton", fm).getlength(mid) > S * 0.82 and fm > 6:
            fm *= 0.93
        d.text((W / 2, H / 2 + S * 0.01), mid, font=font("anton", fm), fill=255, anchor="mm")
        if bottom:
            d.text((W / 2, H - pad - S * 0.12), bottom, font=font("mono", S * 0.08), fill=255, anchor="mm")
    a = np.asarray(im, np.float32) / 255
    rng = np.random.default_rng(seed + len(mid))
    noise = cv2.GaussianBlur(rng.random(a.shape).astype(np.float32), (0, 0), max(1, S / 160))
    ink = np.clip(a * (0.55 + 0.75 * noise), 0, 1)
    ink = np.where(noise < 0.33, ink * 0.25, ink)  # dry patches
    col = np.array(hex2rgb(color)[:3], np.float32)
    out = np.zeros((H, W, 4), np.float32)
    out[..., :3] = col
    out[..., 3] = ink * 0.88
    return out


# ----------------------------------------------------------------- marker strokes
def stroke_path(points, progress=1.0):
    """Cut a polyline to a fraction of its length."""
    pts = np.asarray(points, np.float32)
    if len(pts) < 2 or progress >= 1:
        return pts
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    L = seg.sum() * clamp01(progress)
    acc, out = 0.0, [pts[0]]
    for i, s in enumerate(seg):
        if acc + s >= L:
            f = (L - acc) / max(s, 1e-6)
            out.append(pts[i] + (pts[i + 1] - pts[i]) * f)
            break
        out.append(pts[i + 1])
        acc += s
    return np.array(out, np.float32)


def draw_marker(canvas, points, color="#ff3b30", width=8, progress=1.0, opacity=1.0):
    pts = stroke_path(points, progress)
    if len(pts) < 2:
        return
    H, W = canvas.shape[:2]
    x0, y0 = np.floor(pts.min(0) - width * 2).astype(int)
    x1, y1 = np.ceil(pts.max(0) + width * 2).astype(int)
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
    if x1 <= x0 or y1 <= y0:
        return
    m = np.zeros((y1 - y0, x1 - x0), np.float32)
    p = np.round((pts - [x0, y0]) * 8).astype(np.int32)
    cv2.polylines(m, [p], False, 1.0, thickness=max(1, int(width)), lineType=cv2.LINE_AA, shift=3)
    m = np.clip(m, 0, 1)[..., None] * opacity * 0.92
    col = np.array(hex2rgb(color)[:3], np.float32)
    region = canvas[y0:y1, x0:x1]
    region *= (1 - m)
    region += col * m


def hand_circle(cx, cy, rx, ry, seed=0, turns=1.15, n=90):
    rng = np.random.default_rng(seed)
    a0 = rng.uniform(0, 2 * math.pi)
    pts = []
    for i in range(n):
        t = i / (n - 1)
        a = a0 + t * turns * 2 * math.pi
        wob = 1 + 0.05 * math.sin(3 * a + seed) + 0.03 * rng.normal()
        pts.append((cx + rx * wob * math.cos(a), cy + ry * wob * math.sin(a)))
    return pts


def hand_arrow(x0, y0, x1, y1, seed=0, bend=0.18):
    """Curved arrow from (x0,y0) to (x1,y1) as two polylines (shaft, head)."""
    rng = np.random.default_rng(seed)
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy)
    nx, ny = -dy / max(L, 1), dx / max(L, 1)
    cx, cy = mx + nx * L * bend, my + ny * L * bend
    shaft = []
    for i in range(40):
        t = i / 39
        x = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t * t * x1
        y = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t * t * y1
        shaft.append((x + rng.normal(0, 0.6), y + rng.normal(0, 0.6)))
    ang = math.atan2(y1 - shaft[-4][1], x1 - shaft[-4][0])
    hl = max(18, L * 0.14)
    head = [(x1 + hl * math.cos(ang + 2.6), y1 + hl * math.sin(ang + 2.6)), (x1, y1),
            (x1 + hl * math.cos(ang - 2.6), y1 + hl * math.sin(ang - 2.6))]
    return shaft, head


# ----------------------------------------------------------------- film texture banks
@lru_cache(maxsize=4)
def grain_bank(w, h, n=10, seed=7):
    rng = np.random.default_rng(seed)
    bank = []
    for _ in range(n):
        g = rng.normal(0, 1, (h // 2 + 2, w // 2 + 2)).astype(np.float32)
        g = cv2.GaussianBlur(g, (0, 0), 0.65)
        g = cv2.resize(g, (w + 4, h + 4), interpolation=cv2.INTER_LINEAR)
        g /= g.std() + 1e-6
        bank.append(g.astype(np.float16))
    return bank


@lru_cache(maxsize=4)
def vignette(w, h, strength=0.35, roundness=1.0):
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    nx, ny = (x - w / 2) / (w / 2), (y - h / 2) / (h / 2)
    r = np.sqrt(nx ** 2 * (1.0 if roundness else 1) + ny ** 2 * roundness)
    v = 1 - strength * np.clip((r - 0.45) / 0.95, 0, 1) ** 1.6
    return v[..., None].astype(np.float32)


@lru_cache(maxsize=8)
def paper_texture(w, h, tint="#f3eee2", seed=3):
    rng = np.random.default_rng(seed)
    base = np.array(hex2rgb(tint)[:3], np.float32)
    n1 = cv2.GaussianBlur(rng.random((h, w)).astype(np.float32), (0, 0), 1.2)
    n2 = cv2.resize(rng.random((h // 40 + 2, w // 40 + 2)).astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC)
    fib = np.zeros((h, w), np.float32)
    for _ in range(int(w * h / 9000)):
        x, y = rng.integers(0, w), rng.integers(0, h)
        a = rng.uniform(0, math.pi)
        l = rng.uniform(4, 22) * w / 1920
        cv2.line(fib, (int(x), int(y)), (int(x + l * math.cos(a)), int(y + l * math.sin(a))), 1.0, 1, cv2.LINE_AA)
    t = 1 + (n1 - 0.5) * 0.05 + (n2 - 0.5) * 0.06 - fib * 0.05
    return np.clip(base * t[..., None], 0, 1).astype(np.float32)


def dust_and_scratches(canvas, seed, amount=1.0):
    """Sparse dust specks + occasional vertical scratch (leader / old film feel)."""
    rng = np.random.default_rng(seed)
    H, W = canvas.shape[:2]
    S = W / 1920
    for _ in range(int(rng.poisson(5 * amount))):
        x, y = rng.integers(0, W), rng.integers(0, H)
        r = max(1, int(rng.uniform(1, 3.5) * S))
        col = 0.05 if rng.random() < 0.7 else 0.95
        cv2.circle(canvas, (int(x), int(y)), r, (col, col, col), -1, cv2.LINE_AA)
    if rng.random() < 0.35 * amount:
        x = int(rng.uniform(0.1, 0.9) * W)
        col = 0.85 if rng.random() < 0.5 else 0.15
        cv2.line(canvas, (x, 0), (x + int(rng.normal(0, 6 * S)), H), (col, col, col), max(1, int(S)), cv2.LINE_AA)


def over_rgba(dst, src, x, y, opacity=1.0):
    """Composite straight-alpha RGBA src onto RGBA dst in place (top-left at x, y)."""
    H, W = dst.shape[:2]
    h, w = src.shape[:2]
    x0, y0 = int(round(x)), int(round(y))
    ax0, ay0 = max(0, -x0), max(0, -y0)
    cx0, cy0 = max(0, x0), max(0, y0)
    cx1, cy1 = min(W, x0 + w), min(H, y0 + h)
    if cx1 <= cx0 or cy1 <= cy0:
        return
    s = src[ay0:ay0 + (cy1 - cy0), ax0:ax0 + (cx1 - cx0)]
    d = dst[cy0:cy1, cx0:cx1]
    sa = s[..., 3:4] * opacity
    da = d[..., 3:4]
    oa = sa + da * (1 - sa)
    d[..., :3] = (s[..., :3] * sa + d[..., :3] * da * (1 - sa)) / np.maximum(oa, 1e-6)
    d[..., 3:4] = oa


@lru_cache(maxsize=128)
def note_panel(w, h, color="#f6f1e4", seed=0, tape=True):
    """Torn-paper note with a strip of washi tape; RGBA with soft shadow."""
    rng = np.random.default_rng(seed + 101)
    w, h = max(8, int(w)), max(8, int(h))
    base = np.array(hex2rgb(color)[:3], np.float32)
    img = np.ones((h, w, 3), np.float32) * base
    img *= (0.965 + 0.035 * cv2.GaussianBlur(rng.random((h, w)).astype(np.float32), (0, 0), 1.5))[..., None]
    mask = np.ones((h, w), np.float32)
    # slightly ragged edges
    for side in range(4):
        n = (w if side % 2 == 0 else h)
        prof = np.clip(cv2.GaussianBlur(rng.random((1, n)).astype(np.float32), (0, 0), 3)[0] * 5, 0, 5).astype(int)
        for i, d in enumerate(prof):
            if side == 0:
                mask[:d, i] = 0
            elif side == 2:
                mask[h - d:, i] = 0
            elif side == 1:
                mask[i, w - d:] = 0
            else:
                mask[i, :d] = 0
    rgba = np.dstack([img, mask])
    if tape:
        tw, th = int(min(w * 0.35, 160)), int(max(18, h * 0.22))
        tp = np.zeros((th, tw, 4), np.float32)
        tp[..., :3] = np.array(hex2rgb("#e9d8a6")[:3], np.float32)
        tp[..., 3] = 0.72
        tp = transform_rgba(tp, 1.0, float(rng.uniform(-8, 8)))
        big = np.zeros((h + tp.shape[0], w, 4), np.float32)
        big[tp.shape[0] // 2:tp.shape[0] // 2 + h] = rgba
        over_rgba(big, tp, (w - tp.shape[1]) / 2 + rng.uniform(-w * 0.1, w * 0.1), 0)
        rgba = big
    return shadow_of(rgba, blur=max(3, w * 0.012), offset=(w * 0.006, w * 0.01), strength=0.42)


# ----------------------------------------------------------------- doodles + speech bubble
def doodle_points(kind, cx, cy, size, seed=0):
    """Hand-drawn doodle polylines (list of point lists) centred at cx, cy."""
    rng = np.random.default_rng(seed)
    j = lambda: rng.normal(0, size * 0.025)  # noqa: E731
    if kind == "star":
        pts = []
        for k in range(11):
            a = -math.pi / 2 + k * math.pi / 5
            r = size if k % 2 == 0 else size * 0.45
            pts.append((cx + r * math.cos(a) + j(), cy + r * math.sin(a) + j()))
        return [pts]
    if kind == "heart":
        pts = []
        for k in range(48):
            t = k / 47 * 2 * math.pi
            x = 16 * math.sin(t) ** 3
            y = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
            pts.append((cx + x * size / 17 + j(), cy + y * size / 17 + j()))
        return [pts]
    if kind == "sparkle":
        s = size
        return [[(cx, cy - s), (cx + s * 0.12, cy - s * 0.12), (cx + s, cy), (cx + s * 0.12, cy + s * 0.12),
                 (cx, cy + s), (cx - s * 0.12, cy + s * 0.12), (cx - s, cy), (cx - s * 0.12, cy - s * 0.12), (cx, cy - s)]]
    if kind == "swirl":
        pts = [(cx + size * (k / 40) * math.cos(k / 40 * 4 * math.pi), cy + size * (k / 40) * math.sin(k / 40 * 4 * math.pi)) for k in range(41)]
        return [pts]
    raise ValueError(kind)


def speech_bubble(text, fname, size, tail_dx, tail_dy, seed=0, color="#1f2a44", fill="#fffdf6"):
    """Hand-drawn speech bubble RGBA; the tail tip sits at (tail_dx, tail_dy) relative to the bubble centre.
    Returns (rgba, (cx, cy)) where cx, cy is the bubble centre inside the patch."""
    txt = text_rgba(text, fname, size, color, line_gap=1.0)
    bw, bh = txt.shape[1] * 0.92 + size * 1.1, txt.shape[0] * 0.8 + size * 0.9
    pad = int(max(abs(tail_dx), abs(tail_dy)) + size)
    Wp, Hp = int(bw + 2 * pad), int(bh + 2 * pad)
    cx, cy = Wp / 2, Hp / 2
    m = np.zeros((Hp, Wp), np.float32)
    cv2.ellipse(m, (int(cx), int(cy)), (int(bw / 2), int(bh / 2)), 0, 0, 360, 1.0, -1, cv2.LINE_AA)
    ang = math.atan2(tail_dy, tail_dx)
    base = 0.32
    p1 = (cx + bw / 2 * 0.8 * math.cos(ang + base), cy + bh / 2 * 0.8 * math.sin(ang + base))
    p2 = (cx + bw / 2 * 0.8 * math.cos(ang - base), cy + bh / 2 * 0.8 * math.sin(ang - base))
    tip = (cx + tail_dx, cy + tail_dy)
    cv2.fillPoly(m, [np.array([p1, tip, p2], np.int32)], 1.0, cv2.LINE_AA)
    edge = cv2.dilate(m, np.ones((int(size * 0.13) + 1,) * 2, np.uint8)) - m
    rgba = np.zeros((Hp, Wp, 4), np.float32)
    rgba[..., :3] = np.array(hex2rgb(fill)[:3], np.float32)
    rgba[..., 3] = m
    ink = np.array(hex2rgb(color)[:3], np.float32)
    e = np.clip(edge, 0, 1)[..., None]
    rgba[..., :3] = rgba[..., :3] * (1 - e) + ink * e
    rgba[..., 3] = np.maximum(rgba[..., 3], e[..., 0])
    over_rgba(rgba, txt, cx - txt.shape[1] / 2, cy - txt.shape[0] / 2)
    return shadow_of(rgba, blur=size * 0.18, offset=(size * 0.06, size * 0.1), strength=0.35), (cx, cy)
