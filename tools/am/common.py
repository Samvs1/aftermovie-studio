"""Paths, metadata, fonts and photo sources shared by the engine."""
import json, os
from functools import lru_cache

import numpy as np
from PIL import Image, ImageOps, ImageFont

ENGINE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the studio install
# The project being worked on: AM_PROJECT (set by tools/studio.py and the project builders). A project folder
# (projects/<name>/) holds photos/, music/, cache/, out/, review/ and project.json.
ROOT = os.path.abspath(os.environ["AM_PROJECT"]) if os.environ.get("AM_PROJECT") else ENGINE
PHOTOS = os.path.join(ROOT, "photos")
CACHE = os.path.join(ROOT, "cache")
OUT = os.path.join(ROOT, "out")
MUSIC = os.path.join(ROOT, "music") if os.path.isdir(os.path.join(ROOT, "music")) else os.path.join(ROOT, "Music")
ASSETS = os.path.join(ENGINE, "assets")
MODELS = os.path.join(ENGINE, "models")
IMAGE_EXT = (".jpg", ".jpeg")

DESIGN_W, DESIGN_H = 1920, 1080  # EDL coordinates are always in this space

FONTS = {
    "caveat": ("Caveat[wght].ttf", 700),
    "caveat_light": ("Caveat[wght].ttf", 500),
    "marker": ("PermanentMarker-Regular.ttf", None),
    "anton": ("Anton-Regular.ttf", None),
    "bebas": ("BebasNeue-Regular.ttf", None),
    "elite": ("SpecialElite-Regular.ttf", None),
    "playfair": ("PlayfairDisplay[wght].ttf", 500),
    "playfair_italic": ("PlayfairDisplay-Italic[wght].ttf", 400),
    "mono": ("SpaceMono-Bold.ttf", None),
    "mono_regular": ("SpaceMono-Regular.ttf", None),
    "narrow": ("ArchivoNarrow[wght].ttf", 700),
    "inter": ("Inter[opsz,wght].ttf", None),
    "emoji": ("C:/Windows/Fonts/seguiemj.ttf", None),
    "georgian": ("C:/Windows/Fonts/sylfaen.ttf", None),      # Georgian script (Windows ships Sylfaen)
    "georgian_black": ("NotoSansGeorgian[wdth,wght].ttf", (900, 100)),   # heavy Mkhedruli for knockouts (OFL)
    "georgian_bold": ("NotoSansGeorgian[wdth,wght].ttf", (700, 100)),
    "georgian_light": ("NotoSansGeorgian[wdth,wght].ttf", (300, 100)),
    # Arabic (Windows system fonts): PIL here has no complex-script layout, so pass text through arabic() first
    "arabic": ("C:/Windows/Fonts/seguisb.ttf", None),            # Segoe UI Semibold
    "arabic_bold": ("C:/Windows/Fonts/segoeuib.ttf", None),
    "arabic_light": ("C:/Windows/Fonts/segoeuil.ttf", None),
    "arabic_naskh": ("C:/Windows/Fonts/times.ttf", None),         # Times New Roman's Arabic is a Naskh
    "arabic_heavy": ("C:/Windows/Fonts/tahomabd.ttf", None),
}

# Arabic letter -> presentation forms (isolated, final[, initial, medial]); 2-tuples only join to the right
_AR = {"ء": (0xFE80,), "آ": (0xFE81, 0xFE82), "أ": (0xFE83, 0xFE84), "ؤ": (0xFE85, 0xFE86), "إ": (0xFE87, 0xFE88),
       "ئ": (0xFE89, 0xFE8A, 0xFE8B, 0xFE8C), "ا": (0xFE8D, 0xFE8E), "ب": (0xFE8F, 0xFE90, 0xFE91, 0xFE92),
       "ة": (0xFE93, 0xFE94), "ت": (0xFE95, 0xFE96, 0xFE97, 0xFE98), "ث": (0xFE99, 0xFE9A, 0xFE9B, 0xFE9C),
       "ج": (0xFE9D, 0xFE9E, 0xFE9F, 0xFEA0), "ح": (0xFEA1, 0xFEA2, 0xFEA3, 0xFEA4), "خ": (0xFEA5, 0xFEA6, 0xFEA7, 0xFEA8),
       "د": (0xFEA9, 0xFEAA), "ذ": (0xFEAB, 0xFEAC), "ر": (0xFEAD, 0xFEAE), "ز": (0xFEAF, 0xFEB0),
       "س": (0xFEB1, 0xFEB2, 0xFEB3, 0xFEB4), "ش": (0xFEB5, 0xFEB6, 0xFEB7, 0xFEB8), "ص": (0xFEB9, 0xFEBA, 0xFEBB, 0xFEBC),
       "ض": (0xFEBD, 0xFEBE, 0xFEBF, 0xFEC0), "ط": (0xFEC1, 0xFEC2, 0xFEC3, 0xFEC4), "ظ": (0xFEC5, 0xFEC6, 0xFEC7, 0xFEC8),
       "ع": (0xFEC9, 0xFECA, 0xFECB, 0xFECC), "غ": (0xFECD, 0xFECE, 0xFECF, 0xFED0), "ف": (0xFED1, 0xFED2, 0xFED3, 0xFED4),
       "ق": (0xFED5, 0xFED6, 0xFED7, 0xFED8), "ك": (0xFED9, 0xFEDA, 0xFEDB, 0xFEDC), "ل": (0xFEDD, 0xFEDE, 0xFEDF, 0xFEE0),
       "م": (0xFEE1, 0xFEE2, 0xFEE3, 0xFEE4), "ن": (0xFEE5, 0xFEE6, 0xFEE7, 0xFEE8), "ه": (0xFEE9, 0xFEEA, 0xFEEB, 0xFEEC),
       "و": (0xFEED, 0xFEEE), "ى": (0xFEEF, 0xFEF0), "ي": (0xFEF1, 0xFEF2, 0xFEF3, 0xFEF4)}
_LAM_ALEF = {"ا": (0xFEFB, 0xFEFC), "أ": (0xFEF7, 0xFEF8), "إ": (0xFEF9, 0xFEFA), "آ": (0xFEF5, 0xFEF6)}


def arabic(text):
    """Shape Arabic for a renderer without complex-script layout: contextual letter forms, lam-alef and Allah
    ligatures, diacritics dropped, then reversed into visual (left-to-right) order. Pure Arabic text only."""
    words = []
    for word in text.split(" "):
        word = "".join(c for c in word if not ("\u064B" <= c <= "\u0652"))
        if word.strip("،") == "الله":
            words.append("\uFDF2" + ("،" if word.endswith("،") else ""))
            continue
        out, i = [], 0
        joins_prev = False                     # the previous letter reaches forward into this one
        while i < len(word):
            c = word[i]
            if c == "ل" and i + 1 < len(word) and word[i + 1] in _LAM_ALEF:
                out.append(chr(_LAM_ALEF[word[i + 1]][1 if joins_prev else 0]))
                joins_prev, i = False, i + 2
                continue
            forms = _AR.get(c)
            if not forms:
                out.append(c)
                joins_prev, i = False, i + 1
                continue
            nxt = word[i + 1] if i + 1 < len(word) else ""
            joins_next = len(forms) == 4 and nxt in _AR
            if joins_prev and joins_next:
                f = forms[3]
            elif joins_prev:
                f = forms[1] if len(forms) > 1 else forms[0]
            elif joins_next:
                f = forms[2]
            else:
                f = forms[0]
            out.append(chr(f))
            joins_prev, i = joins_next, i + 1
        words.append("".join(out))
    return " ".join(words)[::-1].replace("،", "،")


@lru_cache(maxsize=256)
def font(name, size):
    fn, wght = FONTS[name]
    path = fn if os.path.isabs(fn) else os.path.join(ASSETS, "fonts", fn)
    f = ImageFont.truetype(path, max(4, int(round(size))))
    if wght is not None:
        try:
            f.set_variation_by_axes(list(wght) if isinstance(wght, tuple) else [wght])
        except Exception:
            pass
    return f


@lru_cache(maxsize=1)
def photo_meta():
    return json.load(open(os.path.join(CACHE, "photos.json")))


@lru_cache(maxsize=1)
def faces_people():
    p = os.path.join(CACHE, "faces_people.json")       # written once people are named (studio cast)
    return json.load(open(p)) if os.path.exists(p) else {}


@lru_cache(maxsize=1)
def cast():
    p = os.path.join(CACHE, "cast.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {"people": {}}


def project():
    """The project brief (project.json), or {} if there is none."""
    p = os.path.join(ROOT, "project.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}


def load_upright(name, max_side=None):
    """Original photo, rotated upright, optionally downscaled. Returns PIL RGB."""
    m = photo_meta()[name]
    im = ImageOps.exif_transpose(Image.open(os.path.join(PHOTOS, name))).convert("RGB")
    if m["rot"]:
        im = im.rotate(-90 * m["rot"], expand=True)
    if max_side and max(im.size) > max_side:
        s = max_side / max(im.size)
        im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    return im


def faces(name, min_score=0.7, min_size=0.025):
    """Face boxes (normalized x, y, w, h) for an upright photo, with person ids."""
    m = photo_meta()[name]
    who = faces_people().get(name, [])
    out = []
    for i, f in enumerate(m["faces"]):
        x, y, w, h = f["box"]
        if f["score"] >= min_score and w >= min_size:
            out.append({"box": (x, y, w, h), "person": who[i] if i < len(who) else None, "score": f["score"]})
    return out


def person_name(pid):
    p = cast()["people"].get(str(pid))
    return p["name"] if p else None


def hex2rgb(h, alpha=None):
    h = h.lstrip("#")
    c = tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    if len(h) == 8:
        c = c + (int(h[6:8], 16) / 255,)
    return c
