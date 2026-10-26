"""Author the Cool Kids EDL ("COOL KIDS / 27 EXPOSURES", v2) -> out/cool_kids_edl.json

Run: python tools/studio.py build elevate-2026 cool_kids   (then preview / final)

v2 after Sam's feedback:
  * the song plays continuously from the first note; ONE join between two identical chorus lines
    (end of chorus-2 cycle 1 -> end of final-chorus cycle 1; 0.89 spectral correlation, placed in a
    vocal gap at the same bar position) so the music never jumps
  * slower: mostly one photo per bar, holds on landscapes
  * every photo is used exactly once (enforced by use())
  * playful lyric-literal annotations ("her!" energy) through both verses
  * epilogue after the song ends: the intro guitar returns softly under a handwritten thank-you
"""
import json, os, sys
sys.path.insert(0, os.environ.get("AM_TOOLS") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
os.environ.setdefault("AM_PROJECT", os.path.dirname(os.path.abspath(__file__)))   # this film's project folder
from am.builder import Builder  # noqa: E402
from am.common import OUT, CACHE  # noqa: E402
from am.photo import plan_crop, face_on_screen  # noqa: E402

SONG = "music/Echosmith - Cool Kids [Official Music Video].mp3"
JOIN_SRC, JOIN_DST = 128.627, 187.695          # both in a vocal gap, same position in the bar
SEG1 = (0.15, JOIN_SRC, 0.0)
SEG2 = (JOIN_DST, 221.60, round(JOIN_SRC - 0.15, 4))
SONG_END = SEG2[2] + SEG2[1] - SEG2[0]         # film time where the song has fully rung out (~162.4)
DUR = 174.8                                   # song ends ~162.4; the thank-you note plays out in silence

B = Builder("cool_kids", "Cool Kids / 27 Exposures", SONG, "cool_kids", [SEG1, SEG2],
            grade={"preset": "consumer_film", "overrides": {"img0016.jpg": {"wb": 0}, "img0017.jpg": {"wb": 0},
                                                            "img0018.jpg": {"wb": 0}}},
            finish={"grain": 0.012, "vignette": 0.28, "halation": 0.07, "flicker": 0.006, "weave": 0.35},
            duration=DUR)
W, H = 1920, 1080
INK, RED = "#1f2a44", "#c8371f"
BEAT = 60 / 129.998
PULSE = {"on": "kicks", "amount": 0.03, "decay": 0.12, "min": 0.4}

# ------------------------------------------------------------------ musical grid (film time)
song_db = json.load(open(os.path.join(CACHE, "audio", "cool_kids.json")))["downbeats"]


def bar(n):
    """Film time of song bar n (bar 0 = first downbeat of the intro; bars >= 101 are after the join)."""
    s = song_db[n]
    t = s - SEG1[0] if s < JOIN_SRC else s - SEG2[0] + SEG2[2]
    return B.snap(t, "beats", 0.03)


def beat(n, k):
    return B.snap(bar(n) + k * BEAT, "beats", 0.05)


def b(t):
    return B.snap(t, "beats")


# ------------------------------------------------------------------ every photo exactly once
USED = {}


def use(src, where):
    if src in USED:
        raise SystemExit(f"photo {src} used twice: {USED[src]!r} and {where!r}")
    USED[src] = where
    return src


MOTIONS = [((1.0, 1.10), ((0, 0), (0, 0))), ((1.13, 1.0), ((0, 0), (0, 0))), ((1.1, 1.1), ((-0.07, 0), (0.07, 0))),
           ((1.1, 1.1), ((0.07, 0), (-0.07, 0))), ((1.02, 1.13), ((0, 0.05), (0, -0.03)))]
_mi = [0]


def photo(src, where, zoom=None, focus="faces", drift=None, **kw):
    if zoom is None:
        zoom, drift = MOTIONS[_mi[0] % len(MOTIONS)]
        _mi[0] += 1
    L = {"type": "photo", "src": use(src, where), "zoom": list(zoom), "focus": focus,
         "drift": [list(d) for d in (drift or ((0, 0), (0, 0)))]}
    L.update(kw)
    return L


def text(t, x, y, t0, t1, size=72, font="caveat", color="#ffffff", **kw):
    L = {"type": "text", "text": t, "x": x, "y": y, "t0": round(t0, 4), "t1": round(t1, 4), "size": size, "font": font, "color": color}
    L.update(kw)
    return L


def note(t, x, y, t0, t1, size=72, color=INK, seed=0, tape=True, **kw):
    """Handwritten caption on a taped paper note (readable on any photo)."""
    return text(t, x, y, t0, t1, size, "caveat", color, panel={"seed": seed, "tape": tape}, **kw)


def datestamp(t0, t1, txt="'26 9 19"):
    return {"type": "seven", "text": txt, "x": W - 190, "y": H - 80, "h": 38, "t0": t0, "t1": t1}


exposures = []


META = json.load(open(os.path.join(CACHE, "photos.json")))
_pr = [0]


TABLES = [{"type": "fill", "paper": True, "color": "#f3eee2"}, {"type": "fill", "paper": True, "color": "#cdb38f"},
          {"type": "fill", "color": "#161412"}]


def single(src, t0, t1, sync, tr="cut", extra=None, print_=None, **kw):
    """One photo shot. Portrait photos are laid on a table as a bordered print (whole picture visible);
    print_=False keeps a deliberate full-frame crop (e.g. a vertical tilt)."""
    exposures.append(t0)
    m = META[src]
    bg = None
    if print_ is not False and m["h"] > m["w"] * 1.1:
        hgt = 900
        wid = hgt * m["w"] / m["h"]
        side = (-1) ** _pr[0]
        _pr[0] += 1
        cx = W / 2 + side * 160
        kw.pop("pulse", None)
        kw.pop("focus", None)
        zoom = kw.pop("zoom", (1.0, 1.06))
        table = TABLES[(_pr[0] - 1) % len(TABLES)]
        lay = [dict(table), photo(src, sync, (min(zoom), min(zoom) + 0.05), "faces", box=[cx - wid / 2, (H - hgt) / 2, wid, hgt],
                                  border={"color": "#f6f2e8", "px": 18}, shadow=True, rot=side * 2.5, **kw)] + (extra or [])
    else:
        lay = [photo(src, sync, **kw)] + (extra or [])
    if tr == "flash":
        trans = {"type": "flash", "dur": 0.14, "amount": 0.7}
        B.sfx("shutter", t0, db=-21)
    else:
        trans = {"type": tr, "dur": 0.22 if tr == "whip" else 0.25}
    return B.shot(t0, t1, lay, sync=sync, **{"in": trans})


# ================================================================== INTRO: leader + camera box (guitar intro, bars 0-4)
B.shot(0.0, bar(0), [text("ELEVATE 2026\n— roll 1 —", W / 2, H / 2, 0.15, bar(0), 84, "elite", "#e9e4d6", anim="fade", dur=0.5, fade_out=0.2)],
       sync="first guitar notes")
B.shot(bar(0), bar(4), [{"type": "leader", "numbers": [[bar(0), 5], [bar(1), 4], [bar(2), 3], [bar(3), 2]], "end": bar(4)}],
       sync="leader: one number per downbeat")
B.sfx("projector", bar(0), db=-32, dur=bar(4) - bar(0))
flags = [("ES", -230, -150), ("BE", 250, -170), ("NL", -300, 170), ("DE", 300, 160), ("PL", -40, -235), ("TR", 40, 225)]
box = [{"type": "label", "cx": W / 2, "cy": H / 2 - 20, "w": 860, "rot": -3, "title": "ELEVATE 2026",
        "sub": "single-use camera · shot in amsterdam", "count": "27", "edition": "cool kids\nedition",
        "enter": {"t": bar(4) - 0.05, "dur": 0.32, "type": "drop", "from": [0, -900], "spin": 10}}]
for k, (code, dx, dy) in enumerate(flags):
    tb = beat(4, 1 + k // 2) + (0.0 if k % 2 == 0 else BEAT / 2)
    box.append({"type": "flag", "code": code, "x": W / 2 + dx * 1.55, "y": H / 2 - 20 + dy * 1.25, "w": 120, "rot": -14 + k * 6,
                "t": round(tb, 4), "seed": k})
    B.sfx("drop", tb, db=-23)
box.append(text("six countries, one roll of film", W / 2, H - 80, beat(4, 3), bar(5), 52, "caveat", INK, anim="write", dur=0.35))
B.shot(bar(4), bar(5), box, bg="paper", sync="bar 4: box drops; flags in pairs on the beats", **{"in": {"type": "dip_white", "dur": 0.25}})
B.sfx("drop", bar(4) + 0.25, db=-16)
B.sfx("wind", beat(4, 1) - 0.05, db=-25, dur=0.5)

# ================================================================== BAND ENTRY: the flash + the first day (bars 5-12)
B.sfx("shutter", bar(5) - 0.01, db=-9)
single("1000053556.jpg", bar(5), bar(6), "bar 5 band entry: Maria fires the disposable", "cut",
       zoom=(1.25, 1.4), focus="person:2", drift=((0, 0), (0.03, 0)), pulse=PULSE)
B.edl["shots"][-1]["in"] = {"type": "flash", "dur": 0.2, "amount": 1.0}
single("1000052753.jpg", bar(6), bar(8), "bars 6-7: the boat day, wide slow pan", "cut", zoom=(1.12, 1.12), drift=((0.08, 0), (-0.08, 0)))
single("1000052742.jpg", bar(8), bar(9), "bar 8", "flash", zoom=(1.0, 1.08))
single("1000052751.jpg", bar(9), bar(10), "bar 9", "cut", zoom=(1.12, 1.0))
single("1000052743.jpg", bar(10), bar(12), "bars 10-11: Tim points at the sky, tilt up", "flash", zoom=(1.12, 1.18), focus="person:6",
       drift=((0, 0.12), (0.05, -0.2)), print_=False)
single("1000051838.jpg", bar(12), bar(13), "bar 12: the bridge, first group photo", "cut", zoom=(1.0, 1.1), drift=((0, 0.04), (0, -0.01)))

# ================================================================== VERSE 1 (bars 13-24): meet the cool kids
STOP1, STOP2A, STOP2B = (29.72, 30.41), (37.11, 37.80), (38.95, 39.42)   # song 29.87 / 37.26 / 39.10 (band cuts on the 8th)


def polaroid_card(src, who, cap, cx, cy, w, rot, td, seed, focus, dev=1.0, frm=(0, -820), spin=12):
    exposures.append(td)
    return {"type": "polaroid", "src": use(src, who), "focus": focus, "zoom": "auto:0.5", "cx": cx, "cy": cy, "w": w, "rot": rot,
            "caption": cap, "seed": seed, "develop": {"t": round(td + 0.05, 4), "dur": dev},
            "enter": {"t": round(td - 0.14, 4), "dur": 0.22, "type": "drop", "from": list(frm), "spin": spin}}


# Table A, bars 13-16: "She sees them walking in a straight line" -> cards land in a straight row; Maja's lands crooked
rowA = [("Gabriel", "¡hola!", "img0011.jpg", "person:4", "ES", ("REINO DE", "ESPAÑA", "#b3261e", "circle")),
        ("Maja", "cześć!", "1000052387.jpg", "person:7", "PL", ("RZECZPOSPOLITA", "POLSKA", "#7a2c8f", "circle")),
        ("Tim", "hallo!", "1000052196.jpg", "person:6", "DE", ("BUNDESREPUBLIK", "DEUTSCHLAND", "#1f6b45", "rect")),
        ("Esra", "merhaba!", "1000053970.jpg", "person:11", "TR", ("CUMHURİYETİ", "TÜRKİYE", "#b3261e", "circle"))]
tabA, xs = [], [285, 735, 1185, 1635]
for k, (name, hello, src, foc, code, (st_top, st_mid, scol, shape)) in enumerate(rowA):
    td = bar(13 + k)
    rot = 14 if name == "Maja" else (-1.5 + k)
    tabA.append(polaroid_card(src, name, f"{name} — {hello}", xs[k], 470, 360, rot, td, k + 3, foc))
    tabA.append({"type": "flag", "code": code, "x": xs[k] + 135, "y": 265, "w": 92, "rot": rot + 10, "t": beat(13 + k, 1), "seed": k})
    ts = round(STOP1[0] + 0.03, 4) if name == "Tim" else beat(13 + k, 2)      # Tim's stamp lands in the song's silence
    tabA.append({"type": "stamp", "top": st_top, "mid": st_mid, "bottom": "* 2026 *", "size": 135, "color": scol, "shape": shape,
                 "x": xs[k] + 120, "y": 735, "rot": -16 + 9 * k, "t": ts, "seed": k})
    B.sfx("drop", td, db=-19)
    B.sfx("stamp", ts, db=-10 if name == "Tim" else -17)
tabA.append(text("(not really her style)", 735, 880, beat(14, 1), bar(17), 50, "caveat", "#9e2410", rot=-4, anim="write", dur=0.4))
tabA.append(text("(pause)", 1660, 930, STOP1[0], STOP1[1], 96, "caveat", RED, rot=-6, anim="pop", fade_out=0.08))
B.sfx("wind", STOP1[0] + 0.12, db=-16, dur=0.48)
B.shot(bar(13), bar(17), tabA, bg="paper", freeze=[list(STOP1)],
       sync="bars 13-16: one polaroid per bar in a straight row; Maja crooked on 'not really her style'; Tim's stamp inside stop 1",
       **{"in": {"type": "dip_white", "dur": 0.2}})

# bars 17-18: "And they all got the same heartbeat / but hers is falling behind" -> 3x3 grid pulsing on the kick
hb = [("1000052394.jpg", "person:1", "Sam"), ("1000052015.jpg", "person:2", "Maria"), ("1000052045.jpg", "person:3", "Jakub"),
      ("1000053662.jpg", "person:4", "Gabriel"), ("1000051973.jpg", "person:5", "Daria"), ("1000052060.jpg", "person:6", "Tim"),
      ("img0005.jpg", "person:7", "Maja"), ("img0020.jpg", "person:11", "Esra")]
cells = []
for k, (src, foc, who) in enumerate(hb):
    tc = round(bar(17) + k * BEAT / 4, 4)          # one cell per 16th note
    cells.append({"src": use(src, f"heartbeat grid: {who}"), "focus": foc, "zoom": 2.3, "t": tc})
    exposures.append(tc)
B.shot(bar(17), bar(19), [
    {"type": "fill", "color": "#f5f1e8"},
    {"type": "grid", "rows": 2, "cols": 4, "box": [40, 150, 1840, 790], "gap": 18, "cells": cells,
     "pulse": {"on": "kicks", "amount": 0.07, "decay": 0.13, "min": 0.35, "late_cell": 7, "lag": round(-BEAT / 2, 4)}},
    note("six countries.", 700, 80, beat(17, 2), bar(19), 84, INK, seed=1, rot=-3, boil=True),
    note("one heartbeat.", 1220, 1000, bar(18), bar(19), 92, RED, seed=2, rot=2, boil=True),
    text("(a bit behind)", 1610, 940, beat(18, 1), bar(19), 50, "caveat", "#9e2410", rot=-3, anim="write", dur=0.35),
], sync="bars 17-18: 'same heartbeat' grid, cells on 16ths; Esra's cell pulses an 8th late on 'falling behind'",
    **{"in": {"type": "flash", "dur": 0.12, "amount": 0.6}})


def spotlight(n, stop, name, hello, src, foc, s1, s2, seed, mirror=False, table=None):
    """One full bar: the card lands on the downbeat, two stamps thunk inside the song's stop."""
    t0 = bar(n)
    tA, tB = round(stop[0] + 0.05, 4), round(stop[0] + 0.33, 4)
    X = (lambda x: W - x) if mirror else (lambda x: x)
    L = ([table] if table else []) + [
         polaroid_card(src, name, f"{name} — {hello}", X(760), 545, 470, 4 if mirror else -4, t0, seed, foc, dev=0.6,
                       frm=(200 if mirror else -200, -900), spin=-10 if mirror else 10),
         {"type": "stamp", "top": s1[0], "mid": s1[1], "bottom": "* 2026 *", "size": 230, "color": s1[2], "shape": "circle",
          "x": X(1290), "y": 330, "rot": 12 if mirror else -12, "t": tA, "seed": seed},
         {"type": "marker", "kind": "arrow", "x0": X(1300), "y0": 480, "x1": X(1360), "y1": 650, "t0": round(tA + 0.08, 4), "dur": 0.18,
          "color": RED, "width": 8, "seed": seed},
         {"type": "stamp", "top": s2[0], "mid": s2[1], "bottom": "* 2026 *", "size": 230, "color": s2[2], "shape": "rect",
          "x": X(1420), "y": 790, "rot": -7 if mirror else 7, "t": tB, "seed": seed + 1}]
    B.sfx("drop", t0, db=-14)
    B.sfx("stamp", tA, db=-9)
    B.sfx("stamp", tB, db=-9)
    return B.shot(t0, bar(n + 1), L, bg="paper", sync=f"bar {n}: {name} lands on the downbeat; stamps inside the stop",
                  **{"in": {"type": "whip", "dur": 0.22} if mirror else {"type": "cut"}})


spotlight(19, STOP2A, "Maria", "¡hola! / salut!", "1000053480.jpg", "person:2",
          ("REINO DE", "ESPAÑA", "#b3261e"), ("BELGIË · BELGIQUE", "BRUXELLES", "#2b3f9e"), 21)
spotlight(20, STOP2B, "Sam", "hoi!", "1000052124.jpg", "person:1",
          ("BELGIË · BELGIQUE", "BELGIË", "#2b3f9e"), ("NEDERLAND", "AMSTERDAM", "#e07a1f"), 31,
          mirror=True, table={"type": "fill", "paper": True, "color": "#cdb38f"})

# Table B, bars 21-23: "Nothing in this world could ever bring them down"
rowB = [("Daria", "hallo!", "img0007.jpg", "person:5", "DE", ("BUNDESREPUBLIK", "FRANKFURT", "#1f6b45", "rect")),
        ("Kuba", "cześć!", "img0001.jpg", "person:3", "PL", ("RZECZPOSPOLITA", "POLSKA", "#7a2c8f", "circle"))]
tabB, xsB = [{"type": "fill", "color": "#161412"}], [660, 1260]
for k, (name, hello, src, foc, code, (st_top, st_mid, scol, shape)) in enumerate(rowB):
    td = bar(21 + k)
    tabB.append(polaroid_card(src, name, f"{name} — {hello}", xsB[k], 480, 430, -3 + 6 * k, td, k + 13, foc))
    tabB.append({"type": "flag", "code": code, "x": xsB[k] + 160, "y": 230, "w": 104, "rot": 8 - 6 * k, "t": beat(21 + k, 1), "seed": k + 7})
    tabB.append({"type": "stamp", "top": st_top, "mid": st_mid, "bottom": "* 2026 *", "size": 150, "color": scol, "shape": shape,
                 "x": xsB[k] + 150, "y": 800, "rot": 12 - 18 * k, "t": beat(21 + k, 2), "seed": k + 7})
    B.sfx("drop", td, db=-19)
    B.sfx("stamp", beat(21 + k, 2), db=-17)
B.shot(bar(21), bar(23), tabB, bg="paper", sync="bars 21-22: Daria, Kuba, one per bar", **{"in": {"type": "dip_white", "dur": 0.2}})
single("img0019.jpg", bar(23), bar(25), "bars 23-24: '...could ever bring them down' -> unbothered", "flash",
       zoom=(1.05, 1.18), focus="person:4",
       extra=[note("unbothered.", 1480, 260, beat(23, 2), bar(25), 76, INK, seed=4, rot=-5, anim="pop")])

# ================================================================== PRE-CHORUS 1 (bars 25-28)
single("1000052042.jpg", bar(25), bar(26), "bar 25: 'Yeah, they're invincible'", "whip", zoom=(1.0, 1.12),
       extra=[note("invincible.", 420, 220, B.word("they're", 47.97), bar(26), 80, INK, seed=5, rot=4, anim="pop")])
_c = plan_crop("1000052108.jpg", 16 / 9, 1.03, "center")
_fx, _fy, _fw, _fh = face_on_screen("1000052108.jpg", _c, (0, 0, W, H), "person:5")
exposures.append(bar(26))
B.shot(bar(26), bar(27), [photo("1000052108.jpg", "background: her", (1.0, 1.06), "center"),
                          {"type": "marker", "kind": "circle", "follow": {"layer": 0, "face": "person:5"}, "t0": beat(26, 1),
                           "dur": 0.35, "color": RED, "width": 7, "seed": 4},
                          text("her!", _fx + _fw * 2.4, _fy - _fh * 0.4, beat(26, 2), bar(27), 96, "caveat", RED, rot=-8, anim="pop",
                               panel={"seed": 3, "tape": False})],
       sync="bar 26: 'and she's just in the background' -> circle + her!", **{"in": {"type": "cut"}})
exposures.append(bar(27))
B.shot(bar(27), bar(28), [photo("img0010.jpg", "background: them too", (1.0, 1.06), "faces"),
                          note("them too!", 1500, 230, beat(27, 1), bar(28), 72, RED, seed=6, rot=5, anim="pop", tape=False),
                          {"type": "marker", "kind": "arrow", "x0": 1440, "y0": 300, "x1": 1290, "y1": 470, "t0": beat(27, 1) + 0.2,
                           "dur": 0.22, "color": RED, "width": 7, "seed": 5}],
       sync="bar 27: the people in the back", **{"in": {"type": "whip", "dur": 0.22}})
BREATH = 54.25                                       # the band drops under "says" (song 54.4)
exposures.append(bar(28))
B.shot(bar(28), bar(29), [photo("img0036.jpg", "and she says", (1.05, 1.2), "person:2", ((0, 0), (0.04, 0)), freeze_at=BREATH),
                          note("and she says...", 1450, 880, B.word("And", 53.7), BREATH, 70, INK, seed=11, anim="write", dur=0.4, tape=False),
                          note("cheese!", 1450, 880, BREATH + 0.02, bar(29), 120, RED, seed=12, rot=-6, anim="pop")],
       sync="bar 28: 'and she says' -> freezes when the band drops; flash charging", **{"in": {"type": "cut"}})
B.sfx("charge", B.word("says", 54.1), db=-23, dur=bar(29) - B.word("says", 54.1) - 0.02)

# ================================================================== CHORUS 1 (bars 29-35)
B.sfx("shutter", bar(29) - 0.01, db=-9)
single("1000053519.jpg", bar(29), bar(30), "chorus downbeat = FLASH", "cut", zoom=(1.0, 1.08), pulse=PULSE, print_=False)
B.edl["shots"][-1]["in"] = {"type": "flash", "dur": 0.22, "amount": 1.0}
single("1000051970.jpg", bar(30), bar(31), "bar 30", "cut", zoom=(1.0, 1.07), pulse=PULSE, extra=[datestamp(bar(30), bar(31))])
strips = [(["img0012.jpg", "1000052224.jpg", "img0038.jpg"], 640, -4), (["1000052075.jpg", "img0031.jpg", "1000053619.jpg"], 1280, 4)]
sl = [{"type": "fill", "paper": True, "color": "#efe7d6"}]
for k, (srcs, cx, rot) in enumerate(strips):
    for s_ in srcs:
        use(s_, "photo-booth strip")
    t_in = beat(31, 2 * k)
    sl.append({"type": "strip", "srcs": srcs, "cx": cx, "cy": 545, "w": 330, "rot": rot, "drift_y": -40, "label": "ELEVATE  ★  2026",
               "enter": {"t": round(t_in - 0.05, 4), "dur": 0.3, "type": "slide", "from": [0, 1100]}})
    exposures.append(t_in)
    B.sfx("drop", t_in, db=-19)
sl.append(note("fit in? we fit in.", W / 2, 1000, bar(32), bar(33), 60, INK, seed=13, rot=-2, anim="write", dur=0.4, tape=False))
B.shot(bar(31), bar(33), sl, sync="bars 31-32: 'they seem to fit in' -> photo-booth strips", **{"in": {"type": "dip_white", "dur": 0.18}})
single("1000053410.jpg", bar(33), bar(34), "bar 33: karaoke", "flash", zoom=(1.25, 1.4), focus="person:1", pulse=PULSE, print_=False)
single("img0013.jpg", bar(34), bar(35), "bar 34", "cut", zoom=(1.0, 1.06), pulse=PULSE)
single("1000052087.jpg", bar(35), bar(36), "bar 35: 'like the cool kids'", "flash", zoom=(1.0, 1.1), pulse=PULSE)


# ================================================================== POST-CHORUS 1 (bars 36-44): the attic, unhurried
def twins(n, a, b_, seed):
    t0 = bar(n)
    exposures.append(t0)
    return B.shot(t0, bar(n + 1), [{"type": "fill", "color": "#0e0e0e"},
                                   photo(a, "twin (phone)", (1.0, 1.06), "faces", box=[0, 0, 955, 1080]),
                                   photo(b_, "twin (film)", (1.06, 1.0), "faces", box=[965, 0, 955, 1080]),
                                   text("phone", 478, 1020, t0, bar(n + 1), 40, "mono", INK, anim="fade", panel={"seed": seed, "tape": False, "padx": 18}),
                                   text("film", 1442, 1020, t0, bar(n + 1), 40, "mono", INK, anim="fade", panel={"seed": seed + 1, "tape": False, "padx": 18})],
                  sync=f"bar {n}: the same moment on phone | film", **{"in": {"type": "flash", "dur": 0.12, "amount": 0.6}})


twins(36, "1000052383.jpg", "img0006.jpg", 20)
single("1000052608.jpg", bar(37), bar(38), "bar 37", "cut", zoom=(1.0, 1.08), extra=[datestamp(bar(37), bar(38))])
exposures.append(bar(38))
g4 = ["1000052056.jpg", "1000052378.jpg", "1000052386.jpg", "1000052356.jpg"]   # + Gabriel's armchair cameo
B.shot(bar(38), bar(39), [{"type": "grid", "rows": 2, "cols": 2, "box": [0, 0, W, H], "gap": 12,
                           "cells": [{"src": use(s_, "attic grid"), "zoom": 1.0, "t": beat(38, i)} for i, s_ in enumerate(g4)]}],
       bg="#f5f1e8", sync="bar 38: 2x2 attic grid, one cell per beat", **{"in": {"type": "cut"}})
single("1000052092.jpg", bar(39), bar(40), "bar 39", "flash", zoom=(1.1, 1.0), focus="person:3")
single("1000051776.jpg", bar(40), bar(41), "bar 40", "cut", zoom=(1.0, 1.1), extra=[datestamp(bar(40), bar(41))])
twins(41, "1000051792.jpg", "img0002.jpg", 24)
single("1000052068.jpg", bar(42), bar(43), "bar 42: Gabriel reading on the bed", "cut", zoom=(1.0, 1.12), focus="person:4",
       extra=[note("(studying)", 1500, 230, beat(42, 1), bar(43), 70, INK, seed=14, rot=4, anim="pop")])
single("img0027.jpg", bar(43), bar(44), "bar 43", "flash", zoom=(1.12, 1.0))
single("img0014.jpg", bar(44), bar(45), "bar 44", "cut", zoom=(1.0, 1.08))

# ================================================================== VERSE 2 (bars 45-60): the nights
STOPA, STOPB, STOPC = (88.69, 89.45), (90.65, 91.34), (96.188, 96.88)   # band cut-outs, snapped to the 8th
CLUE = B.word("But", 86.73)                         # next phrase starts on the sung word
exposures.append(bar(45))
B.shot(bar(45), CLUE, [photo("1000053168.jpg", "big smile", (1.0, 1.1), "person:3"),
                       {"type": "marker", "kind": "circle", "follow": {"layer": 0, "face": "person:3"}, "t0": B.word("talking", 84.64),
                        "dur": 0.3, "color": "#fff1a8", "width": 8, "seed": 6},
                       note("big smile.", 520, 220, B.word("big", 85.57), CLUE, 74, RED, seed=15, rot=-4, anim="pop", tape=False)],
       sync="bar 45: 'He sees them talking with a big smile' -> circle the smile", **{"in": {"type": "dip_white", "dur": 0.2}})
single("img0029.jpg", CLUE, STOPA[0], "'but they haven't got a clue' (cut on the word 'But')", "cut", zoom=(1.0, 1.1),
       extra=[note("no clue.", 1450, 260, B.word("haven't", 87.19), STOPA[0], 80, INK, seed=16, rot=5, anim="pop")])
exposures.append(STOPA[0])
B.shot(STOPA[0], bar(48), [photo("img0028.jpg", "stop A", (1.0, 1.08)),
                          note("(pause)", 1600, 900, STOPA[0], STOPA[1], 90, RED, seed=23, rot=-5, anim="pop", fade_out=0.06, tape=False)],
       freeze=[list(STOPA)], fx=[{"type": "freeze_look"}], sync="stop A: the band cuts out -> the frame freezes", **{"in": {"type": "flash", "dur": 0.12, "amount": 0.6}})
B.sfx("wind", STOPA[0] + 0.1, db=-16, dur=0.5)
exposures.append(bar(48))
B.shot(bar(48), bar(49), [photo("img0026.jpg", "stop B", (1.08, 1.0)),
                          note("(still paused)", 1480, 900, STOPB[0], STOPB[1], 84, RED, seed=24, rot=-4, anim="pop", fade_out=0.06, tape=False)],
       freeze=[list(STOPB)], fx=[{"type": "freeze_look"}], sync="bar 48: stop B", **{"in": {"type": "cut"}})
B.sfx("shutter", STOPB[0] + 0.15, db=-17)
single("1000053483.jpg", bar(49), bar(50), "bar 49: 'yeah, they're living the good life' (suits)", "flash", zoom=(1.0, 1.1),
       extra=[note("the good life.", 440, 210, B.word("living", 92.37), bar(50), 74, INK, seed=17, rot=-3, anim="write", dur=0.4)])
exposures.append(bar(50))
B.shot(bar(50), STOPC[0], [photo("1000052613.jpg", "him", (1.0, 1.08), "person:1"),
                           {"type": "marker", "kind": "circle", "follow": {"layer": 0, "face": "person:1"}, "t0": B.word("Can't", 94.15),
                            "dur": 0.3, "color": RED, "width": 7, "seed": 8},
                           note("him.", 1420, 300, B.word("he", 94.89), STOPC[0], 90, RED, seed=18, rot=-6, anim="pop", tape=False)],
       sync="bar 50: 'can't see what he is going through' -> circle him (holds to the stop)", **{"in": {"type": "cut"}})
exposures.append(STOPC[0])
B.shot(STOPC[0], bar(52), [photo("img0033.jpg", "stop C", (1.0, 1.06))],
       freeze=[list(STOPC)], fx=[{"type": "freeze_look"}], sync="stop C: the band cuts out -> freeze", **{"in": {"type": "flash", "dur": 0.12, "amount": 0.6}})
B.sfx("stamp", STOPC[0] + 0.05, db=-15)
single("img0032.jpg", bar(52), bar(53), "bar 52: the band thins out", "dissolve", zoom=(1.1, 1.0))
exposures.append(bar(53))
B.shot(bar(53), bar(55), [photo("img0021.jpg", "fast cars", (1.0, 1.12), "faces"),
                          note("fast cars", 1420, 230, B.word("driving", 99.98), bar(55), 84, INK, seed=19, rot=-4, anim="pop", tape=False),
                          {"type": "marker", "kind": "line", "points": [[1270, 236], [1575, 222]], "t0": B.word("cars", 100.86), "dur": 0.18,
                           "color": RED, "width": 9},
                          text("night bus", 1440, 330, B.word("But", 101.48), bar(55), 92, "caveat", RED, rot=-7, anim="write", dur=0.35,
                               panel={"seed": 25, "tape": False})],
       sync="bars 53-54: 'they're driving fast cars' -> crossed out: night bus", **{"in": {"type": "flash", "dur": 0.14, "amount": 0.8}})
def prints(t0, t1, items, sync, table, extra=None, tr="cut"):
    """Two (or more) bordered prints landing on a table, one per given time; each photo shown whole."""
    lay = [dict(table)]
    xs = {1: [W / 2], 2: [560, 1360], 3: [400, 960, 1520]}[len(items)]
    for k, (src, t_land) in enumerate(items):
        m = META[src]
        if m["h"] > m["w"]:
            hh = 780
            ww = hh * m["w"] / m["h"]
        else:
            ww = 760
            hh = ww * m["h"] / m["w"]
        exposures.append(t_land)
        rot = (-3, 3.5, -2)[k]
        lay.append(photo(src, sync, (1.0, 1.04), "faces", box=[xs[k] - ww / 2, (H - hh) / 2 - 10, ww, hh],
                         border={"color": "#f6f2e8", "px": 18}, shadow=True, rot=rot,
                         enter={"t": round(t_land - 0.14, 4), "dur": 0.22, "type": "drop", "from": [0, -900], "spin": 8 - 16 * k}))
        B.sfx("drop", t_land, db=-17)
    trans = {"type": "flash", "dur": 0.12, "amount": 0.6} if tr == "flash" else {"type": tr, "dur": 0.22}
    return B.shot(t0, t1, lay + (extra or []), sync=sync, **{"in": trans})


def sparkles(times, spots, kind="sparkle", color="#ffe066", size=34, seed=0):
    return [{"type": "doodle", "kind": kind, "x": x, "y": y, "size": size, "t": round(t, 4), "dur": 0.16, "color": color,
             "width": 6, "seed": seed + i} for i, (t, (x, y)) in enumerate(zip(times, spots))]


# bar 55: 'but they don't know where they're going' -> arrows in every direction
single("img0016.jpg", bar(55), bar(56), "bar 55: 'don't know where they're going' -> arrows everywhere", "cut", zoom=(1.0, 1.08),
       extra=[note("where to??", 1540, 860, B.word("where", 103.19), bar(56), 78, INK, seed=28, rot=6, anim="pop", tape=False)] +
             [{"type": "marker", "kind": "arrow", "x0": x0, "y0": y0, "x1": x1, "y1": y1, "t0": round(B.word("going", 103.86) + 0.06 * i, 4),
               "dur": 0.16, "color": "#fff1a8", "width": 7, "seed": 40 + i}
              for i, (x0, y0, x1, y1) in enumerate([(1560, 780, 1760, 660), (1480, 790, 1290, 690), (1560, 940, 1600, 1060)])])
# bar 56: the club -> doodled sparkles pop on the beats
single("img0017.jpg", bar(56), bar(57), "bar 56: the club, sparkles on the beats", "whip", zoom=(1.1, 1.0),
       extra=sparkles([beat(56, k) for k in range(4)], [(240, 200), (1700, 210), (1760, 900), (170, 920)], seed=50))
exposures.append(bar(57))
tri = ["img0018.jpg", "img0022.jpg", "1000052362.jpg"]
B.shot(bar(57), bar(58), [{"type": "fill", "color": "#0e0e0e"}] + [
    photo(s_, "club triptych", (1.0, 1.08), "faces", box=[k * 643, 0, 634, 1080],
          enter={"t": beat(57, k), "dur": 0.2, "type": "slide", "from": [0, (-1) ** k * 1100]})
    for k, s_ in enumerate(tri)], sync="bar 57: 'in the fast lane' -> triptych, one panel per beat", **{"in": {"type": "flash", "dur": 0.1, "amount": 0.6}})
# bars 58-59: 'living life without knowing' -> two prints land, one per downbeat
prints(bar(58), bar(60), [("img0025.jpg", bar(58)), ("1000053515.jpg", bar(59))],
       "bars 58-59: 'living life without knowing' -> two prints", TABLES[1],
       extra=[note("(no plan. no idea. no regrets.)", W / 2, 985, B.word("without", 110.41), bar(60), 62, INK, seed=29, rot=-2,
                   anim="write", dur=0.45, tape=False)], tr="dissolve")
# bar 60: 'and he says' -> Kuba: "can we have a bigger one?"
exposures.append(bar(60))
B.shot(bar(60), bar(61), [photo("img0037.jpg", "and he says", (1.0, 1.08), "person:3"),
                          {"type": "bubble", "text": "can we have\na bigger one?", "x": 900, "y": 150, "size": 62,
                           "follow": {"layer": 0, "face": "person:3"}, "t0": B.word("And", 112.79), "t1": bar(61), "seed": 3}],
       sync="bar 60: 'and he says' -> Kuba's line in a speech bubble", **{"in": {"type": "cut"}})

# ================================================================== CHORUS 2, cycle 1 (bars 61-68)
B.sfx("shutter", bar(61) - 0.01, db=-9)
single("1000053636.jpg", bar(61), bar(62), "chorus 2 downbeat = FLASH: the bigger one", "cut", zoom=(1.0, 1.08), pulse=PULSE,
       extra=[note("(granted.)", 1520, 220, beat(61, 2), bar(62), 74, RED, seed=30, rot=-5, anim="pop", tape=False)])
B.edl["shots"][-1]["in"] = {"type": "flash", "dur": 0.22, "amount": 1.0}
single("1000053167.jpg", bar(62), bar(63), "bar 62: hearts on the beats", "cut", zoom=(1.0, 1.1), pulse=PULSE,
       extra=sparkles([beat(62, k) for k in range(1, 4)], [(330, 330), (1600, 260), (1450, 860)], "heart", "#ffffff", 44, 60))
prints(bar(63), bar(65), [("1000053175.jpg", bar(63)), ("1000052364.jpg", bar(64))],
       "bars 63-64: two prints, one per downbeat", TABLES[2],
       extra=sparkles([beat(63, 2), beat(64, 2), beat(64, 3)], [(980, 170), (250, 900), (1700, 930)], "star", "#ffe066", 34, 70),
       tr="flash")
single("img0024.jpg", bar(65), bar(66), "bar 65: the lounge, stars on the beats", "cut", zoom=(1.0, 1.1), pulse=PULSE,
       extra=sparkles([beat(65, k) for k in range(1, 4)], [(300, 240), (1640, 220), (960, 980)], "star", "#fff1a8", 32, 80))
single("img0004.jpg", bar(66), bar(67), "bar 66", "flash", zoom=(1.0, 1.06))
single("img0034.jpg", bar(67), bar(101), "bars 67-68: 'like the cool kids' -> spoiler (holds over the join)", "flash", zoom=(1.0, 1.12),
       pulse=PULSE,
       extra=[note("spoiler:", 1560, 250, B.word("Like", 125.47), bar(101), 80, INK, seed=21, rot=-6, anim="pop"),
              note("you were.", 1590, 390, B.word("cool", 126.77), bar(101), 112, RED, seed=22, rot=-3, anim="pop", boil=True),
              text("roll complete", 1560, 150, bar(68), bar(101), 40, "mono", INK, anim="fade", dur=0.25,
                   panel={"seed": 26, "tape": False, "padx": 18})])
B.sfx("rewind", bar(68) + 0.05, db=-15, dur=0.8)

# ================================================================== FINAL CHORUS cycle 2 (bars 101-108): contact-sheet credits
credits = [("Gabriel", "Still hoping for our Texel trip", "1000052424.jpg", "person:4"),
           ("Maria", "Future latina soccer mom", "1000054136.jpg", "person:2"),
           ("Tim", "'You need to take your pants off'", "img0009.jpg", "person:6"),
           ("Daria", "Best photographer", "img0030.jpg", "person:5"),
           ("Esra", "The OG baddest banana 😎", "1000053165.jpg", "person:11"),
           ("Jakub", "professional 'banana' eater 🍑🍌", "1000052748.jpg", "person:3"),
           ("Maja", "Don't trust her with piggyback rides", "1000053170.jpg", "person:7")]
frames = [{"src": use(s_, f"credit: {n}"), "focus": f, "name": n, "role": r, "t": bar(101 + i), "zoom": "auto:0.3"}
          for i, (n, r, s_, f) in enumerate(credits)]
B.shot(bar(101), bar(109), [{"type": "contact", "cols": 4, "y0": 100, "fw": 360, "fh": 240, "gx": 92, "gy": 222, "first_no": 12,
                             "loupe": [960, 380], "end": bar(108), "release": bar(108), "frames": frames}],
       bg="#0a0a0a", sync="final chorus cycle 2: one credit per bar; the whole sheet on the last bar", **{"in": {"type": "dip_white", "dur": 0.25}})
for i in range(7):
    B.sfx("shutter", bar(101 + i), db=-23)

# ================================================================== POST-CHORUS (bars 109-114): the map
A = (4.90, 52.37)
arcs = [
    {"to": [-3.70, 40.42], "t": beat(109, 2), "label": "Gabriel", "flag": "ES", "label_off": [0, 58], "flag_off": [-70, -40]},
    {"to": [4.35, 50.85], "t": bar(110), "label": "Maria (via España)", "flag": "BE", "label_off": [-270, 55], "flag_off": [-60, 70], "bend": 0.6},
    {"to": [8.68, 50.11], "t": beat(110, 2), "label": "Tim & Daria", "flag": "DE", "label_off": [150, 45], "flag_off": [70, -45]},
    {"to": [19.40, 52.10], "t": bar(111), "label": "Maja & Kuba", "flag": "PL", "label_off": [0, 60], "flag_off": [0, -62]},
    {"to": [32.85, 39.93], "t": beat(111, 2), "label": "Esra", "flag": "TR", "label_off": [0, 60], "flag_off": [-10, -62]},
    {"to": list(A), "from": [4.47, 50.50], "t": bar(112), "label": "Sam (stays ♥)", "color": "#b3261e", "bend": -0.9,
     "label_off": [-235, -60], "size": 46},
]
B.shot(bar(109), bar(115), [
    {"type": "map", "home": list(A), "home_t": bar(109), "arcs": arcs, "zoom": [1.0, 1.07], "focus_px": [820, 560]},
    note("shot in amsterdam.", 1010, 900, bar(113), bar(115), 74, INK, seed=7, rot=-3, anim="write", dur=0.5),
    note("developed in six countries.", 1080, 1000, bar(114), bar(115), 74, RED, seed=8, rot=-2, anim="write", dur=0.6, tape=False),
], bg="#f1ead9", sync="post-chorus: an arc every 2 beats; tagline on the downbeats", **{"in": {"type": "dip_white", "dur": 0.3}})

# ================================================================== ENDING + ring-out + Sam's button
single("img0035.jpg", bar(115), bar(117), "ending: everyone in the mirror", "dissolve", zoom=(1.0, 1.1),
       extra=[note("the cool kids.", W / 2, 925, beat(115, 1), bar(117), 92, INK, seed=9, rot=-2, anim="write", dur=0.5),
              text("elevate 2026 · amsterdam", W / 2, 1030, beat(115, 3), bar(117), 36, "mono", INK, anim="fade", dur=0.4,
                   panel={"seed": 27, "tape": False, "padx": 18})])
RO = bar(117)
B.sfx("runout", RO, db=-17, dur=2.2)
BTN = b(RO + 2 * BEAT)
exposures.append(BTN)
B.shot(RO, b(RO + 8 * BEAT), [
    {"type": "fill", "color": "#090909"},
    {"type": "polaroid", "src": use("img0003.jpg", "Sam's button"), "focus": "person:1", "zoom": "auto:0.5", "cx": 620, "cy": 545,
     "w": 380, "rot": -5, "caption": "Sam", "seed": 41, "enter": {"t": round(BTN - 0.15, 4), "dur": 0.25, "type": "drop", "from": [0, -900], "spin": 8}},
    text("edited by Sam", 1250, 420, b(BTN + BEAT), b(RO + 8 * BEAT), 54, "mono_regular", "#bdb6a6", anim="type", dur=0.45),
    text("'I have too much time\non my hands guys'", 1260, 590, b(BTN + 3 * BEAT), b(RO + 8 * BEAT), 80, "caveat", "#f5f1e8",
         anim="write", dur=0.7, rot=-3),
], sync="ring-out: the film burns out -> 4th-wall button", **{"in": {"type": "burn", "dur": 0.7}})
B.sfx("drop", BTN, db=-15)

# ================================================================== EPILOGUE: the thank-you note, in silence
EP = b(RO + 8 * BEAT)                                  # two bars after the last chord (felt pulse continues)
lines = ["to my new, loving friend group —",
         "thank you for the late nights, the deep talks,",
         "the bridge dates and every flash in between.",
         "wherever life takes you now,",
         "there's always a couch for you in amsterdam ♥"]
ep = [{"type": "fill", "paper": True, "color": "#efe8d8"}]
for i, line in enumerate(lines):
    ep.append(text(line, 960, 210 + i * 120, b(EP + 4 * BEAT * i + 0.0001), DUR, 66, "caveat", RED if i == 4 else INK,
                   anim="write", dur=0.9, rot=-1.2 + (i % 2) * 1.0, fade_out=0.0))
SIGN = b(EP + 4 * BEAT * 5)
ep.append(text("— sam", 1400, 860, SIGN, DUR, 84, "caveat", INK, anim="write", dur=0.5, rot=-4, fade_out=0.0))
ep.append({"type": "doodle", "kind": "heart", "x": 1300, "y": 960, "size": 46, "t": b(SIGN + 2 * BEAT), "dur": 0.6, "color": RED,
           "width": 7, "boil": False})
B.shot(EP, DUR, ep, sync="epilogue in silence: one handwritten line per (felt) bar", **{"in": {"type": "dip_black", "dur": 0.8, "align": "start"}})

# ================================================================== exposure counter 27 -> 1 across the roll
END1 = bar(68)
ex = sorted(set(round(t, 4) for t in exposures if bar(5) <= t < END1))
steps = [[t, max(1, 27 - round(i * 26 / max(len(ex) - 1, 1)))] for i, t in enumerate(ex)] + [[END1, 0]]
B.edl["overlays"].append({"type": "counter", "t0": bar(5), "t1": bar(101) - 0.02, "steps": steps, "x": 1810, "y": 64, "h": 46})

p = B.save(os.path.join(OUT, "cool_kids_edl.json"))
print("wrote", p, "| shots:", len(B.edl["shots"]), "| unique photos:", len(USED), "| duration:", DUR)
