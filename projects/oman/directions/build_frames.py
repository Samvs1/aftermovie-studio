"""Style frames for the Oman film: three directions, two frames each.

  A  "Golden hour"   a widescreen road movie that chases the sun (Ramadan: every day was about sunset)
  B  "Arches"        Oman frames everything in arches, and so does the film: photos through carved stone arches
  C  "Souq pop"      Gulf pop-art collage after Hassan Hajjaj: pattern borders, colour blocks, stickers, price tags

Run:  python tools/studio.py run oman ../projects/oman/directions/build_frames.py [a b c]
Writes directions/dir_<id>_edl.json, renders the stills at 1920 px and copies them to out/directions/<id>_<n>.png.
Mock-ups only: photos may repeat across directions; the film's builder enforces no-reuse.
"""
import os, shutil, subprocess, sys
sys.path.insert(0, os.environ.get("AM_TOOLS") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "tools"))
os.environ.setdefault("AM_PROJECT", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from am.common import CACHE, OUT, arabic, font, project  # noqa: E402
from am.kit import Film, W, H  # noqa: E402

TOOLS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "tools")
P = project()
SLUG = P["song"]["slug"]
SEG = 3.0
IDX = dict(l.rstrip("\n").split("\t") for l in open(os.path.join(CACHE, "sheets", "index.txt"), encoding="utf-8") if "\t" in l)


def ph(n):
    """Contact-sheet number -> photo file."""
    return IDX[str(n)]


def film(version, grade, finish):
    F = Film(version, "Oman directions", f"music/{P['song']['file']}", SLUG, [(52.9, 307.0, 0.0)],
             grade={"preset": grade, "overrides": {}}, finish=finish, tail=0.0)
    F.use = lambda src, where: src                 # noqa: E731  (mock-ups)
    F.shot(0.0, 1.0, [F.wall("#000000")], sync="pre")
    return F


def frames(F, builds):
    t, stills = 1.0, []
    for key, build in builds:
        layers, fx = build(F, t)
        s = F.shot(t, t + SEG, layers, sync=key)
        if fx:
            s["fx"] = fx
        stills.append((key, round(t + SEG * 0.7, 3)))
        t += SEG
    F.B.edl["meta"]["duration"] = round(t + 0.5, 3)
    F.duration = F.B.edl["meta"]["duration"]
    edl = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{F.version}_edl.json")   # not in out/: no Review entry
    F.save(edl)
    subprocess.run([sys.executable, "-W", "ignore", os.path.join(TOOLS, "render.py"), edl, "--width", "1920", "--stills",
                    ",".join(str(s_) for _, s_ in stills)], check=True)
    os.makedirs(os.path.join(OUT, "directions"), exist_ok=True)
    for key, s_ in stills:
        shutil.copy(os.path.join(CACHE, "render", f"{F.version}_{s_:07.3f}.png"), os.path.join(OUT, "directions", f"{key}.png"))
        print("wrote", f"out/directions/{key}.png")


def txt(F, text, x, y, size, fnt, color, **kw):
    return F.text(text, x, y, 0, 9999, size, fnt, color, fade_out=0, **kw)


# ================================================================== A: golden hour (widescreen road movie)
BAR = 140                                  # 2.39:1 letterbox bars at 1080p
CREAM = "#f4ead8"


def a_1(F, t):
    """Letterboxed verse: the stranger's desert tour, a documentary subtitle in the lower bar, day + place up top."""
    L = [F.wall("#000000"),
         F.full(ph(127), "A", (1.02, 1.06), box=[0, BAR, W, H - 2 * BAR], focus="faces"),
         txt(F, "DAY 8  ·  WAHIBA SANDS", 960, 72, 26, "mono_regular", "#cdbb9c", post=True, spacing=4),
         txt(F, "A stranger offered us a desert tour. We said yes.", 960, 1010, 46, "playfair_italic", CREAM, post=True)]
    return L, [{"type": "letterbox", "h": BAR}]


def a_2(F, t):
    """The signature: the bars snap open on the first chorus; 'I, I did it all' = Sam and Tom, arms wide, side by side."""
    L = [F.wall("#000000"),
         F.full(ph(79), "A", (1.0, 1.04), box=[0, 0, 954, H], focus="faces"),
         F.full(ph(91), "A", (1.0, 1.04), box=[966, 0, 954, H], focus="faces"),
         txt(F, "DAY 7  ·  JEBEL SHAMS", 60, 1030, 26, "mono_regular", CREAM, spacing=4, shadow=6, anchor="lm")]
    return L, [{"type": "letterbox", "keys": [[t, BAR], [t + 0.25, 0]]}]


# ================================================================== B: arches (stone, symmetry, Islamic geometry)
SAND, SAND_DK, INK_B, MARBLE, TURQ = "#dcc5a1", "#a8865c", "#3a2a1c", "#efe8dc", "#1f9e9a"


def arch_window(F, src, cx, top, w, h, point=0.55, focus="faces", frame=SAND_DK, line=10, rim=26):
    """A photo seen through a carved pointed arch: deep reveal (darker rim) + the window + a fine outline."""
    return [F.shape("arch", cx, top + h / 2 + 8, w + rim * 2, h + rim, color=frame, alpha=0.55, point=point),
            F.full(src, "B", (1.0, 1.05), box=[cx - w / 2, top, w, h], focus=focus, mask={"kind": "arch", "point": point}),
            F.shape("arch", cx, top + h / 2, w + 2, h + 2, color=frame, point=point, line=line)]


def b_1(F, t):
    """One arch: Tom dressed up in the Muttrah souq, the place name in English and Arabic either side."""
    L = [F.wall(SAND),
         F.shape("pattern", 960, 540, W, H, motif="star8", cell=120, colors=(SAND, "#d2b994", "#c9ad85"), alpha=0.6)]
    L += arch_window(F, ph(3), 960, 120, 560, 840, point=0.55)
    L += [txt(F, "MUTTRAH", 420, 520, 150, "bebas", INK_B),
          txt(F, arabic("مطرح"), 1500, 500, 150, "arabic_bold", INK_B),
          txt(F, "DAY 2  ·  THE SOUQ", 420, 640, 26, "mono_regular", "#6d5236", spacing=3),
          txt(F, "23.62° N  58.57° E", 1500, 640, 26, "mono_regular", "#6d5236", spacing=3)]
    return L, None


def b_2(F, t):
    """The arcade: 'I saw so many places' as five arches in a row, one desert moment in each (one per beat in the film)."""
    L = [F.wall(MARBLE), F.shape("rect", 960, 1040, W, 80, TURQ)]
    srcs = [ph(129), ph(113), ph(134), ph(141), ph(121)]
    w_, h_, gap = 300, 640, 54
    x0 = 960 - 2 * (w_ + gap)
    for i, s in enumerate(srcs):
        L += arch_window(F, s, x0 + i * (w_ + gap), 250, w_, h_, point=0.55, frame="#b9a68c", line=8, rim=18)
    L += [txt(F, "I SAW SO MANY PLACES", 960, 140, 120, "bebas", INK_B, spacing=6),
          txt(F, "DAY 8  ·  WAHIBA SANDS", 960, 1040, 28, "mono", "#ffffff", spacing=4)]
    return L, None


# ================================================================== C: souq pop (Hajjaj-style pop-art collage)
RED, GREEN, WHITE, SAFFRON, TEAL, INK_C = "#d7261e", "#0f8a4a", "#fbf6ea", "#f2a516", "#13a3a1", "#141414"


def price_tag(F, text, x, y, size=30, rot=-4, bg="#ffffff", fg=INK_C):
    w_ = font("mono", size).getlength(text) + size * 1.6
    return [F.shape("rect", x, y, w_, size * 2.0, bg, rot=rot),
            F.shape("circle", x - w_ / 2 + size * 0.55, y, size * 0.36, size * 0.36, RED, rot=rot),
            txt(F, text, x + size * 0.25, y, size, "mono", fg, rot=rot)]


def c_1(F, t):
    """Hajjaj portrait: Tom in a yellow turban framed by a star-tile border on Bedouin-tent stripes, stickers, a tag."""
    fw, fh = 760, 980
    L = [F.shape("pattern", 960, 540, W, H, motif="stripes", cell=96, colors=(TEAL, WHITE), prot=0.0),
         F.shape("rect", 960, 540, fw + 40, fh + 40, INK_C),
         F.shape("pattern", 960, 540, fw, fh, motif="star8", cell=84, colors=(RED, WHITE, GREEN),
                 hole=[70, 70, fw - 140, fh - 140]),
         F.full(ph(213), "C", (1.0, 1.0), box=[960 - fw / 2 + 70, 540 - fh / 2 + 70, fw - 140, fh - 140], focus="faces"),
         {"type": "sticker", "text": "🧃", "font": "emoji", "size": 150, "x": 470, "y": 250, "t": t, "rot": -12},
         {"type": "sticker", "text": "🐪", "font": "emoji", "size": 170, "x": 1480, "y": 850, "t": t, "rot": 8},
         F.shape("rect", 1500, 270, 420, 180, SAFFRON, rot=4),
         txt(F, arabic("عمان"), 1500, 262, 120, "arabic_heavy", INK_C, rot=4)]
    L += price_tag(F, "TOM · BRUSSELS → NIZWA", 520, 900, 30, rot=-5)
    return L, None


def c_2(F, t):
    """The souq wall: every place stacked like a market stall (one tile per 8th in the film), the hook on a red band."""
    cells = [ph(n) for n in (129, 134, 181, 146, 151, 99, 198, 113, 126, 160, 192, 141,
                             75, 110, 54, 166, 203, 158, 229, 121, 230, 79, 155, 195)]
    L = [F.wall(SAFFRON),
         {"type": "grid", "rows": 4, "cols": 6, "gap": 16, "box": [0, 0, W, H],
          "cells": [{"src": s, "zoom": 1.05} for s in cells]},
         F.shape("rect", 960, 560, W, 210, RED, rot=-2),
         txt(F, "I SAW SO MANY PLACES", 960, 555, 150, "anton", WHITE, rot=-2),
         {"type": "sticker", "text": "🧃", "font": "emoji", "size": 130, "x": 1700, "y": 380, "t": t, "rot": 14},
         {"type": "sticker", "text": "🐟", "font": "emoji", "size": 120, "x": 260, "y": 760, "t": t, "rot": -10}]
    L += price_tag(F, "15 DAYS · 5,227 KM · 0 RESTAURANTS OPEN", 1290, 720, 28, rot=3)
    return L, None


if __name__ == "__main__":
    which = sys.argv[1:] or ["a", "b", "c"]
    if "a" in which:
        frames(film("dir_a", "golden", {"grain": 0.01, "vignette": 0.24, "halation": 0.09, "flicker": 0.0, "weave": 0.0}),
               [("a_1", a_1), ("a_2", a_2)])
    if "b" in which:
        frames(film("dir_b", "golden", {"grain": 0.004, "vignette": 0.0, "halation": 0.02, "flicker": 0.0, "weave": 0.0}),
               [("b_1", b_1), ("b_2", b_2)])
    if "c" in which:
        frames(film("dir_c", "punchy", {"grain": 0.008, "vignette": 0.0, "halation": 0.0, "flicker": 0.0, "weave": 0.0}),
               [("c_1", c_1), ("c_2", c_2)])
