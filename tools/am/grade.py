"""Static colour grading: per-photo normalisation + a film-stock look per film.

Graded sources are cached in cache/graded/<preset>/<photo>.jpg (long side <= 2400 px).
Dynamic film texture (grain, flicker, vignette, gate weave) is added per frame by the renderer.

Per-photo overrides (from the EDL "grade.overrides") can set:
  wb (0..1 gray-world strength), exposure (target median luma), sat, warmth (-1..1)
"""
import os
import numpy as np
import cv2

from .common import CACHE, load_upright, photo_meta

MAX_SIDE = 2400

PRESETS = {
    # warm consumer film: lifted green-ish blacks, creamy warm highlights, soft, halation
    "consumer_film": {
        "curve": [(0, 0.04), (0.08, 0.10), (0.25, 0.265), (0.5, 0.53), (0.75, 0.775), (0.9, 0.895), (1, 0.955)],
        "shadow_tint": (-0.008, 0.016, -0.018), "high_tint": (0.035, 0.016, -0.035),
        "sat": 1.06, "halation": 0.11, "soften_phone": 0.9, "wb_phone": 0.55, "wb_film": 0.2, "target": 0.43,
    },
    # golden nostalgic: matte blacks, gold highlights, gentle saturation, strong bloom
    "golden": {
        "curve": [(0, 0.06), (0.1, 0.13), (0.3, 0.32), (0.55, 0.58), (0.8, 0.82), (1, 0.93)],
        "shadow_tint": (0.0, 0.006, 0.012), "high_tint": (0.05, 0.028, -0.04),
        "sat": 0.94, "halation": 0.16, "soften_phone": 1.1, "wb_phone": 0.5, "wb_film": 0.15, "target": 0.45,
    },
    # punchy cross-process: crushed blacks, hot saturation, magenta highs / green shadows
    "punchy": {
        "curve": [(0, 0.0), (0.1, 0.06), (0.3, 0.27), (0.55, 0.6), (0.8, 0.87), (1, 1.0)],
        "shadow_tint": (-0.01, 0.025, 0.0), "high_tint": (0.03, -0.012, 0.02),
        "sat": 1.22, "halation": 0.07, "soften_phone": 0.5, "wb_phone": 0.5, "wb_film": 0.2, "target": 0.44,
    },
}


def luma(img):
    return img[..., 0] * 0.2126 + img[..., 1] * 0.7152 + img[..., 2] * 0.0722


def gray_world(img, strength):
    if strength <= 0:
        return img
    l = luma(img)
    m = (l > 0.12) & (l < 0.88)
    sat = img.max(-1) - img.min(-1)
    m &= sat < 0.5
    if m.sum() < 500:
        return img
    means = img[m].mean(0)
    gains = (means.mean() / np.maximum(means, 1e-3)) ** strength
    gains /= gains.max() if gains.max() > 1.25 else 1.0
    return img * gains


def exposure(img, target):
    l = luma(img)
    med = float(np.median(l))
    if med <= 1e-3:
        return img
    g = np.clip(np.log(target) / np.log(np.clip(med, 0.02, 0.98)), 0.55, 1.45)
    if abs(g - 1) < 0.04:
        return img
    l2 = np.clip(l, 1e-4, 1) ** g
    ratio = (l2 / np.clip(l, 1e-4, None))[..., None]
    out = img * ratio
    # keep highlights from blowing out after lifting
    return out / np.maximum(1, out.max(-1, keepdims=True))


def apply_curve(img, pts):
    xs, ys = zip(*pts)
    lut = np.interp(np.linspace(0, 1, 1024), xs, ys).astype(np.float32)
    idx = np.clip((img * 1023).astype(np.int32), 0, 1023)
    return lut[idx]


def grade_array(img, preset, source, ov=None):
    """img: float32 RGB 0..1 (upright). Returns graded float32."""
    P = PRESETS[preset]
    ov = ov or {}
    wb = ov.get("wb", P["wb_phone"] if source == "phone" else P["wb_film"])
    img = gray_world(img, wb)
    img = exposure(img, ov.get("exposure", P["target"]))
    if source == "phone" and P["soften_phone"] > 0:
        s = P["soften_phone"] * max(img.shape[:2]) / 2400
        img = cv2.GaussianBlur(img, (0, 0), s)
    img = np.clip(img, 0, 1)
    img = apply_curve(img, P["curve"])
    l = luma(img)[..., None]
    ws = (1 - l) ** 2
    wh = l ** 2
    warm = ov.get("warmth", 0.0)
    img = img + ws * np.array(P["shadow_tint"], np.float32) + wh * np.array(P["high_tint"], np.float32)
    img = img + warm * np.array([0.03, 0.01, -0.03], np.float32)
    sat = ov.get("sat", P["sat"])
    img = l + (img - l) * sat
    if P["halation"] > 0:
        h, w = img.shape[:2]
        small = cv2.resize(img, (w // 4, h // 4), interpolation=cv2.INTER_AREA)
        hl = np.clip((luma(small) - 0.72) / 0.28, 0, 1)
        glow = cv2.GaussianBlur(hl, (0, 0), max(w, h) / 4 * 0.012)
        glow = cv2.resize(glow, (w, h), interpolation=cv2.INTER_LINEAR)[..., None]
        img = img + glow * np.array([1.0, 0.38, 0.16], np.float32) * P["halation"]
    return np.clip(img, 0, 1).astype(np.float32)


def graded_path(preset, name):
    return os.path.join(CACHE, "graded", preset, os.path.splitext(name)[0] + ".jpg")


def ensure_graded(preset, name, overrides=None, force=False):
    p = graded_path(preset, name)
    if os.path.exists(p) and not force:
        return p
    os.makedirs(os.path.dirname(p), exist_ok=True)
    src = load_upright(name, MAX_SIDE)
    img = np.asarray(src, np.float32) / 255
    out = grade_array(img, preset, photo_meta()[name]["source"], overrides)
    tmp = p + f".{os.getpid()}.tmp.jpg"
    cv2.imwrite(tmp, cv2.cvtColor((out * 255 + 0.5).astype(np.uint8), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 95])
    os.replace(tmp, p)  # atomic: other processes never see a half-written file
    return p


def photos_in(obj, acc=None):
    """All photo names referenced anywhere in an EDL structure."""
    acc = set() if acc is None else acc
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "src" and isinstance(v, str) and v.lower().endswith(".jpg"):
                acc.add(v)
            elif k == "srcs" and isinstance(v, list):
                acc.update(x for x in v if isinstance(x, str))
            else:
                photos_in(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            photos_in(v, acc)
    return acc
