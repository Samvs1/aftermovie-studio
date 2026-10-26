"""Author the Time to Pretend EDL ("THE BAD BANANAS: FATED TO PRETEND") -> out/time_to_pretend_edl.json
Run: python tools/studio.py build elevate-2026 time_to_pretend   (then preview / final)

A jokey rockumentary on a home-video tape. The eight Bad Bananas are a band that can't play any
instruments; MGMT's rock-star lyrics get hijacked line by line.

Music: the song plays continuously from the first note with ONE join between two identical chorus
lines: chorus 1 "We're fated to | pretend" -> final chorus "fated to | pretend" (bar 49 -> 93, same bar
position, mel corr 0.918, cut in a -34 dB vocal gap). Verses 2-3 drop out, and so do the drug lines
they contain; the verse-1 drug lines play under the band roll call and are never captioned or illustrated.
After the final hit the tape stops (tape-stop on the ring-out) and the liner-notes thank-you plays in silence.

v2 (Sam's review of v1): captions were late and rushed.
  * word times now come from forced alignment on the vocal stem (tools/align_words.py); LRC word times
    ran ~0.6 s late inside lines
  * every lyric cue sits on the beat / 8th at or just before the sung onset (cue())
  * reading time is linted below: no caption may be cut off before it can be read, nothing reveals in a
    shot's last beat
  * house-rule arrow points at the circled cup; "where are they now" is 4 two-person screens of 2 bars
"""
import json, math, os, sys
import numpy as np
sys.path.insert(0, os.environ.get("AM_TOOLS") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
os.environ.setdefault("AM_PROJECT", os.path.dirname(os.path.abspath(__file__)))   # this film's project folder
from am.builder import Builder  # noqa: E402
from am.common import OUT, CACHE, font as _font  # noqa: E402

SONG = "music/MGMT - Time to Pretend (Official HD Video).mp3"
PRE = 1.0                                          # one second of black before the tape starts
JOIN_SRC, JOIN_DST = 115.683, 220.231              # find_joins: bar 49 -> 93, both in a vocal gap
SEG1 = (0.30, JOIN_SRC, PRE)
SEG2 = (JOIN_DST, 258.81, round(PRE + JOIN_SRC - 0.30, 4))
SONG_END = SEG2[2] + SEG2[1] - SEG2[0]             # ~154.96

BEAT = 0.59408                                     # 100.996 BPM, click-steady grid
W, H = 1920, 1080
INK, RED, RED_DK = "#1f2a44", "#c8371f", "#9e2410"
YEL, PINK, TEAL, BLACK, NEWS, KRAFT, BLUE = "#ffd400", "#ff5c9d", "#22b8c9", "#141414", "#f1ead9", "#cdb38f", "#1d3bd1"

song_db = json.load(open(os.path.join(CACHE, "audio", "time_to_pretend.json")))["downbeats"]


def song2film(s):
    return s - SEG1[0] + SEG1[2] if s < JOIN_SRC else s - SEG2[0] + SEG2[2]


HIT = song2film(song_db[108])                      # the song's final hit (~153.14)
EP = HIT + 6 * BEAT                                # liner notes start (felt pulse continues)
DUR = round(EP + 28 * BEAT, 3)

B = Builder("time_to_pretend", "The Bad Bananas: Fated to Pretend", SONG, "time_to_pretend", [SEG1, SEG2],
            grade={"preset": "punchy", "overrides": {"1000053168.jpg": {"wb": 0.45}, "img0017.jpg": {"wb": 0},
                                                     "1000052364.jpg": {"exposure": 0.4}}},
            finish={"grain": 0.012, "vignette": 0.24, "halation": 0.06, "flicker": 0.004, "weave": 0.2},
            duration=DUR)
B.edl["meta"]["notes"] = "see out/time_to_pretend_notes.md"
EP = B.snap(EP, "beats")


# ------------------------------------------------------------------ musical grid (film time)
def bar(n):
    """Film time of song bar n (bars <= 48 before the join, bars >= 93 after it)."""
    return B.snap(song2film(song_db[n]), "beats", 0.03)


def beat(n, k):
    """Beat k of bar n; k may be fractional in 8ths (k=2.5 = the 'and' of beat 3)."""
    if k == int(k):
        return B.snap(bar(n) + k * BEAT, "beats", 0.05)
    return round(beat(n, int(k)) + (k - int(k)) * BEAT, 4)


def b(t):
    return B.snap(t, "beats")


_beats = B.grid("beats")
EIGHTHS = np.sort(np.r_[_beats, (_beats[:-1] + _beats[1:]) / 2])


def sung(word, near):
    """Aligned sung onset (film time) of a lyric word near a film time."""
    return B.word(word, near, tol=0.35)


def cue(onset):
    """The 8th-note grid point at or just before a sung onset: captions land with the voice, never after it."""
    g = EIGHTHS[EIGHTHS <= onset + 0.05]
    return round(float(g[-1]), 4)


# ------------------------------------------------------------------ every photo exactly once
USED = {}
META = json.load(open(os.path.join(CACHE, "photos.json")))


def use(src, where):
    if src in USED:
        raise SystemExit(f"photo {src} used twice: {USED[src]!r} and {where!r}")
    USED[src] = where
    return src


def photo(src, where, zoom=(1.0, 1.08), focus="faces", drift=None, **kw):
    L = {"type": "photo", "src": use(src, where), "zoom": list(zoom), "focus": focus,
         "drift": [list(d) for d in (drift or ((0, 0), (0, 0)))]}
    L.update(kw)
    return L


def text(t, x, y, t0, t1, size=72, fnt="caveat", color="#ffffff", **kw):
    L = {"type": "text", "text": t, "x": x, "y": y, "t0": round(t0, 4), "t1": round(t1, 4), "size": size, "font": fnt, "color": color}
    L.update(kw)
    return L


def note(t, x, y, t0, t1, size=72, color=INK, seed=0, tape=True, **kw):
    """Handwritten caption on a taped paper note (readable on any photo)."""
    return text(t, x, y, t0, t1, size, "caveat", color, panel={"seed": seed, "tape": tape, "pady": 16}, **kw)


def text_w(t, fnt, size, stroke=0):
    pad = size * 0.35 + stroke * 2
    return max(_font(fnt, size).getlength(line) for line in t.split("\n")) + 2 * pad


def vcr(t, t0, t1, y=1000, size=48, cx=W / 2):
    """Narration as typed closed captions: white mono on a black box, centred. Returns two layers."""
    w_ = text_w(t, "mono", size, 2)
    box = {"type": "rect", "x": cx - w_ / 2 + 4, "y": y - size * 0.78, "w": w_ - 8, "h": size * 1.5, "color": "#000000",
           "alpha": 0.82, "show": [round(t0, 4), round(t1, 4)]}
    return [box, text(t, cx - w_ / 2, y, t0, t1, size, "mono", "#ffffff", anim="type", dur=min(0.3, 0.012 * len(t)),
                      stroke=2, stroke_color="#000000", fade_out=0.0)]


def slam(t, x, y, t0, t1, size=200, color="#111111", fnt="anton", **kw):
    return text(t, x, y, t0, t1, size, fnt, color, anim="pop", dur=0.14, fade_out=0.06, **kw)


def wall(color, paper=False):
    return {"type": "fill", "color": color, "paper": paper}


def tape(x, y, rot, t, dark=True):
    w_, h_ = 150, 42
    return {"type": "rect", "x": x - w_ / 2, "y": y - h_ / 2, "w": w_, "h": h_, "rot": rot,
            "color": "#2c2c2c" if dark else "#b9b7b0", "alpha": 0.94, "enter": {"t": round(t, 4), "dur": 0.1, "type": "pop"}}


def print_size(src, fit):
    a = META[src]["w"] / META[src]["h"]
    ww, hh = fit[0], fit[0] / a
    if hh > fit[1]:
        hh, ww = fit[1], fit[1] * a
    return ww, hh


def on_print(cx, cy, src, fit, rot, u, v):
    """Screen position of the normalised point (u, v) of a print laid out by pr() with zoom 1.0."""
    ww, hh = print_size(src, fit)
    dx, dy = (u - 0.5) * ww, (v - 0.5) * hh
    th = math.radians(rot)
    return cx + dx * math.cos(th) - dy * math.sin(th), cy + dx * math.sin(th) + dy * math.cos(th)


def pr(src, where, cx, cy, fit, rot, t_land, zoom=(1.0, 1.04), focus="faces", tapes="dark", border="#fbfaf4", **kw):
    """A print slapped onto the wall at t_land and gaffer-taped at the top corners; the whole photo is visible."""
    ww, hh = print_size(src, fit)
    L = photo(src, where, zoom, focus, box=[round(cx - ww / 2, 1), round(cy - hh / 2, 1), round(ww, 1), round(hh, 1)],
              border={"color": border, "px": 16}, shadow=True, rot=rot,
              enter={"t": round(t_land, 4), "dur": 0.12, "type": "thump"}, **kw)
    out = [L]
    if tapes:
        th = math.radians(rot)
        for sx in (-1, 1):
            dx, dy = sx * (ww / 2 - 6), -hh / 2 - 6
            x = cx + dx * math.cos(th) - dy * math.sin(th)
            y = cy + dx * math.sin(th) + dy * math.cos(th)
            out.append(tape(x, y, rot + sx * 38, t_land + 0.05, tapes == "dark"))
    B.sfx("drop", t_land, db=-21)
    return out


def idx(layers, src):
    return next(i for i, L in enumerate(layers) if L.get("src") == src)


def circle(layers, src, pid, t0, color=RED, seed=1, width=8):
    return {"type": "marker", "kind": "circle", "follow": {"layer": idx(layers, src), "face": f"person:{pid}"},
            "t0": round(t0, 4), "dur": 0.3, "color": color, "width": width, "seed": seed}


def doodles(times, spots, kind="star", color="#ffe066", size=36, seed=0):
    return [{"type": "doodle", "kind": kind, "x": x, "y": y, "size": size, "t": round(t, 4), "dur": 0.16, "color": color,
             "width": 6, "seed": seed + i} for i, (t, (x, y)) in enumerate(zip(times, spots))]


def check(x, y, t, s=1.0):
    return {"type": "marker", "kind": "line", "points": [[x, y], [x + 18 * s, y + 26 * s], [x + 62 * s, y - 38 * s]],
            "t0": round(t, 4), "dur": 0.16, "color": RED, "width": 9}


VHS = {"type": "vhs", "amount": 1.0}
VHS_SOFT = {"type": "vhs", "amount": 0.55, "band": False}
SPLIT = {"type": "rgb_split", "on": "snares", "amount": 12}
CYM = {"type": "flash_on", "on": "cymbals", "amount": 0.28, "min": 0.8}
PUNCH = {"on": "kicks", "amount": 0.035, "decay": 0.11, "min": 0.45}


def tr(kind, dur=None):
    return {"in": {"type": kind, "dur": dur or {"whip": 0.22, "glitch": 0.2, "dissolve": 0.3}.get(kind, 0.25)}}


# sung onsets (film time) from the forced alignment, used for every lyric cue below
S = {k: sung(*v) for k, v in {
    "Im1": ("I'm", 29.89), "rough": ("rough", 30.64), "Im2": ("I'm", 31.10), "raw": ("raw", 31.94), "Im3": ("I'm", 32.52),
    "Lets": ("Let's", 39.35), "music": ("music", 40.21), "make2": ("make", 40.85), "money": ("money", 41.45),
    "Find": ("Find", 41.99), "models": ("models", 42.61), "for": ("for", 43.25), "wives": ("wives", 43.51),
    "This": ("This", 67.56), "to_live": ("to", 69.63), "and_die": ("and", 70.67), "Weve": ("We've", 72.66),
    "now": ("now", 74.68), "Yeah": ("Yeah", 86.58), "but": ("but", 88.67), "Get": ("Get", 91.62), "offices": ("offices", 92.61),
    "for_the": ("for", 94.31), "morning": ("morning", 94.85), "commute": ("commute", 95.53),
    "Forget": ("Forget", 105.91), "and_our": ("and", 108.97), "friends": ("friends", 109.99), "Were1": ("We're", 112.41),
    "To1": ("To", 118.64), "Were2": ("We're", 122.26), "to2": ("to", 123.44), "To2": ("To", 128.16),
}.items()}

# ================================================================== PRE-ROLL + the tape (bars 0-2)
B.shot(0.0, bar(0), [wall("#050505")], sync="pre-roll: black")
cas = [wall("#3a2c22", True),
       {"type": "cassette", "cx": W / 2, "cy": 560, "w": 1150, "rot": -3,
        "enter": {"t": round(bar(0) - 0.14, 4), "dur": 0.22, "type": "drop", "from": [0, -900], "spin": 6}},
       text("THE BAD BANANAS", W / 2, 352, beat(0, 1), bar(2), 82, "marker", INK, anim="write", dur=0.4, rot=-3, fade_out=0),
       text("fated to pretend  ·  tour '26", W / 2 + 4, 432, beat(0, 3), bar(2), 56, "caveat", INK, anim="write", dur=0.45, rot=-3,
            fade_out=0),
       text("DO NOT TAPE OVER!!", W / 2 + 8, 497, bar(1), bar(2), 42, "marker", RED, anim="write", dur=0.3, rot=-3, fade_out=0)]
B.shot(bar(0), bar(2), cas, sync="bars 0-1: the tape lands; its label writes itself on the beats")
B.sfx("drop", bar(0), db=-15)

B.shot(bar(2), bar(3), [wall(BLUE),
                        {"type": "osd", "icon": "play", "text": "PLAY", "x": 110, "y": 120, "size": 66, "t0": bar(2)},
                        {"type": "osd", "text": "SP", "x": 1690, "y": 120, "size": 54, "t0": bar(2)}],
       fx=[{"type": "vhs", "amount": 0.7, "band": False}, {"type": "static", "t0": beat(2, 3), "t1": bar(3), "amount": 0.85}],
       sync="bar 2: into the VCR (clunk) -> PLAY; snow on beat 4")
B.sfx("clunk", bar(2), db=-12)
B.sfx("static", beat(2, 3), db=-27, dur=BEAT)

# ================================================================== COLD OPEN (bars 3-6): the narrator, a card per downbeat
B.shot(bar(3), bar(4), [photo("1000052753.jpg", "cold open: amsterdam", (1.04, 1.14), "faces", ((0.04, 0), (-0.03, 0))),
                        *vcr("amsterdam, 2026.", bar(3), bar(4))],
       fx=[VHS], sync="bar 3: the boat, home-video look", **tr("cut"))
L4 = [wall(BLACK)] + pr("1000052196.jpg", "cold open", 640, 500, (560, 800), -3, bar(4), tapes="light") + \
     pr("1000052742.jpg", "cold open", 1280, 500, (560, 800), 3, beat(4, 2), tapes="light", zoom=(1.04, 1.0)) + \
     [*vcr("8 friends. 6 countries.", bar(4), bar(5))]
B.shot(bar(4), bar(5), L4, fx=[VHS], sync="bar 4: two prints, one per half bar", **tr("cut"))
L5 = [wall(YEL)] + pr("1000051838.jpg", "cold open: one band", W / 2, 500, (900, 830), -2, bar(5), zoom=(1.0, 1.06)) + \
     [*vcr("one band.", bar(5), bar(6))]
B.shot(bar(5), bar(6), L5, fx=[VHS], sync="bar 5: the bridge group taped to the wall", **tr("glitch"))
L6 = [wall(KRAFT, True)] + pr("1000052751.jpg", "cold open", 640, 500, (560, 800), 2, bar(6)) + \
     pr("1000052424.jpg", "cold open", 1280, 500, (560, 800), -3, beat(6, 2), zoom=(1.0, 1.0)) + \
     [*vcr("(zero musical talent.)", bar(6), bar(7))]
B.shot(bar(6), bar(7), L6, fx=[VHS], sync="bar 6: two prints; the kick drum builds", **tr("cut"))

# ================================================================== SYNTH HOOK (bars 7-10): the band's world, a note per downbeat
L7 = [wall(PINK)] + pr("1000052743.jpg", "tour manager", 760, 530, (640, 900), -2, bar(7), zoom=(1.0, 1.05))
L7 += [circle(L7, "1000052743.jpg", 6, beat(7, 1), "#111111", 3),
       note("tour manager.", 1440, 420, bar(7), bar(8), 92, INK, seed=1, rot=-4, anim="pop"),
       note("(has a map)", 1470, 590, beat(7, 1), bar(8), 66, RED_DK, seed=2, rot=3, anim="pop", tape=False)]
B.shot(bar(7), bar(8), L7, fx=[VHS_SOFT], sync="bar 7: hook starts -> Tim circled: tour manager", **tr("cut"))
L8 = [wall(TEAL)] + pr("1000052108.jpg", "HQ", 1180, 530, (640, 900), 3, bar(8), zoom=(1.05, 1.0))
L8 += [note("HQ:", 470, 400, bar(8), bar(9), 120, INK, seed=3, rot=-5, anim="pop"),
       note("the attic.", 500, 600, bar(8), bar(9), 92, INK, seed=4, rot=-2, anim="pop", tape=False)]
B.shot(bar(8), bar(9), L8, fx=[VHS_SOFT], sync="bar 8: the attic = HQ", **tr("whip"))
B.shot(bar(9), bar(10), [photo("img0011.jpg", "rehearsals", (1.0, 1.1), "person:4", ((0, 0.02), (0, -0.02))),
                         note("rehearsals: nightly.", 1350, 230, bar(9), bar(10), 84, INK, seed=5, rot=4, anim="pop")],
       fx=[VHS_SOFT], sync="bar 9: rehearsals", **tr("cut"))
L10 = [wall(BLACK)] + pr("1000052092.jpg", "mostly screaming", 700, 530, (640, 900), -3, bar(10), zoom=(1.1, 1.0), tapes="light")
L10 += [note("(mostly screaming.)", 1370, 540, bar(10), bar(11), 84, INK, seed=6, rot=-3, anim="pop")]
B.shot(bar(10), bar(11), L10, fx=[VHS_SOFT, SPLIT], sync="bar 10: Kuba screams into the drop", **tr("cut"))

# ================================================================== TITLE (bar 11: the drums) - one word per 8th, then a held read
title = [wall("#101010"),
         photo("1000051970.jpg", "title: the band photo", (1.0, 1.04), "faces", box=[60, 50, 735, 980],
               halftone={"cell": 9, "mode": "color", "paper": "#f4ecd8"}, pulse={"on": "kicks", "amount": 0.05, "decay": 0.1, "min": 0.4}),
         slam("THE", 1350, 230, bar(11), bar(12), 140, "#ffffff"),
         slam("BAD", 1350, 470, beat(11, 0.5), bar(12), 310, YEL),
         slam("BANANAS", 1350, 760, beat(11, 1), bar(12), 240, YEL)]
B.shot(bar(11), bar(12), title, fx=[SPLIT], sync="bar 11 drums in: THE / BAD / BANANAS on 8ths, held for the rest of the bar", **tr("glitch"))

# ================================================================== VERSE 1
# bars 12-14: "I'm feelin' rough / I'm feelin' raw / I'm in the prime of my life" -> one print + word per phrase, held
t_rough, t_raw, t_prime = cue(S["Im1"]), cue(S["Im2"]), cue(S["Im3"])
L12 = [wall(NEWS, True)] + \
      pr("img0028.jpg", "rough", 360, 600, (520, 420), -3, t_rough, zoom=(1.05, 1.0)) + \
      pr("1000052060.jpg", "raw", 960, 600, (400, 540), 2, t_raw, zoom=(1.04, 1.0)) + \
      pr("img0013.jpg", "prime of my life", 1560, 600, (520, 420), -2, t_prime, zoom=(1.0, 1.04))
L12 += [slam("ROUGH.", 360, 220, t_rough, bar(15), 120, RED, "marker", rot=-4),
        slam("RAW.", 960, 200, t_raw, bar(15), 120, RED, "marker", rot=3),
        slam("PRIME.", 1560, 220, t_prime, bar(15), 120, RED, "marker", rot=-3),
        text("(of our lives)", 1560, 930, t_prime, bar(15), 64, "caveat", INK, anim="pop", rot=-2)]
L12 += doodles([beat(14, k) for k in range(1, 4)], [(160, 980), (1830, 140), (700, 980)], "sparkle", "#111111", 36, 10)
B.shot(bar(12), bar(15), L12, sync="bars 12-14: rough / raw / prime - each print and word land on the start of its sung phrase; held 4 s",
       **tr("cut"))

# bars 15-18: "Let's make some music, make some money, find some models for wives" -> THE PLAN
plan = [wall("#f7f2e6", True),
        text("THE PLAN:", 420, 170, bar(15), bar(19), 104, "marker", INK, anim="pop", dur=0.16, fade_out=0)]
items = [("1. make some music", cue(S["Lets"]), cue(S["music"]), "img0017.jpg", (1290, 290), (600, 400), -6),
         ("2. make some money", cue(S["make2"]), cue(S["money"]), "1000053501.jpg", (1690, 580), (380, 510), 5),
         ("3. find some models", cue(S["Find"]), cue(S["models"]), "1000051973.jpg", (1180, 760), (380, 510), -3)]
for k, (it, t_w, t_tick, src, (cx, cy), fit, rot) in enumerate(items):
    y = 340 + k * 130
    plan.append(text(it, 120, y, t_w, bar(19), 74, "caveat", INK, anim="write", dur=0.3, anchor="lm", fade_out=0))
    plan.append(check(120 + text_w(it, "caveat", 74) + 4, y + 4, t_tick))
    plan += pr(src, f"the plan: {it}", cx, cy, fit, rot, t_tick, zoom=(1.0, 1.03))
plan.append(text("4. ...for wives", 120, 730, cue(S["for"]), bar(19), 74, "caveat", INK, anim="write", dur=0.3, anchor="lm", fade_out=0))
plan.append(text("(pending)", 330, 850, bar(18), bar(19), 84, "caveat", RED, anim="pop", rot=-5, fade_out=0))
B.shot(bar(15), bar(19), plan, sync="bars 15-18: the plan; each item on its sung phrase, evidence on the key word, '(pending)' on the downbeat after 'wives'",
       **tr("cut"))

# bar 19: instrumental -> MEET THE BAND
B.shot(bar(19), bar(20), [wall(YEL),
                          slam("MEET THE", W / 2, 360, bar(19), bar(20), 220),
                          slam("BAND.", W / 2, 640, beat(19, 1), bar(20), 330),
                          text("(in order of appearance)", W / 2, 900, bar(19), bar(20), 64, "caveat", "#111111", anim="pop")],
       fx=[SPLIT], sync="bar 19: MEET THE BAND", **tr("glitch"))

# bars 20-27: ROLL CALL, one Bad Banana per bar (the drug lines play underneath: nothing illustrates them)
roll = [("SAM", "lead vocals", "1000053410.jpg", 1, "BE", PINK),
        ("MARIA", "flash photography", "1000053556.jpg", 2, "ES", TEAL),
        ("KUBA", "hype man", "img0037.jpg", 3, "PL", YEL),
        ("GABRIEL", "wardrobe (optional)", "img0019.jpg", 4, "ES", PINK),
        ("TIM", "rules & regulations", "1000052045.jpg", 6, "DE", TEAL),
        ("DARIA", "attitude", "1000052224.jpg", 5, "DE", YEL),
        ("MAJA", "stunts", "img0012.jpg", 7, "PL", PINK),
        ("ESRA", "the boss", "1000053970.jpg", 11, "TR", TEAL)]
for k, (name, role, src, pid, flag, col) in enumerate(roll):
    n = 20 + k
    left = k % 2 == 0
    portrait = META[src]["h"] > META[src]["w"]
    if portrait:
        pcx, tcx = (600, 1390) if left else (1320, 560)
    else:
        pcx, tcx = (540, 1420) if left else (1380, 520)
    fit = (620, 900) if portrait else (820, 620)
    nsz = round(min(230, 230 * 780 / text_w(name, "anton", 230)))
    lay = [wall(col)] + pr(src, f"roll call: {name}", pcx, 540, fit, -3 if left else 3, bar(n),
                           zoom=(1.0, 1.06) if k % 2 else (1.06, 1.0), pulse=PUNCH)
    lay += [circle(lay, src, pid, beat(n, 1), "#111111", 20 + k),
            slam(name, tcx, 430, bar(n), bar(n + 1), nsz),
            text(role, tcx, 640, bar(n), bar(n + 1), 66, "marker", "#111111", anim="pop", dur=0.14, rot=-3),
            {"type": "flag", "code": flag, "x": tcx, "y": 800, "w": 130, "rot": 8 - 4 * k, "t": beat(n, 2), "seed": k}]
    B.shot(bar(n), bar(n + 1), lay, sync=f"bar {n}: roll call {name}; name + role on the downbeat, circled on beat 2, flag on beat 3",
           **tr(["cut", "whip", "cut", "whip", "glitch", "whip", "cut", "whip"][k]))

# bar 28: "This is our decision" -> the committee
t_live, t_vision, t_fun = cue(S["to_live"]), cue(S["Weve"]), cue(S["now"])
L28 = [wall(KRAFT, True)] + pr("1000052748.jpg", "the committee", W / 2, 520, (620, 860), -2, bar(28))
L28 += [note("the committee.", 1480, 520, cue(S["This"]), t_live, 92, INK, seed=8, rot=-3, anim="pop")]
B.shot(bar(28), t_live, L28, sync="'This is our decision' -> the committee (until 'to live fast')", **tr("glitch"))
# "to live fast and die young" -> two prints, one per half-line
L29 = [wall(NEWS, True)] + pr("1000053519.jpg", "live fast", 600, 600, (560, 780), -3, t_live, zoom=(1.0, 1.08)) + \
      pr("img0029.jpg", "nap young", 1340, 580, (760, 540), 3, cue(S["and_die"]), zoom=(1.0, 1.0), focus="center")
L29 += [slam("LIVE FAST.", 600, 125, t_live, t_vision, 110, RED, "marker", rot=-4),
        note("(and nap young.)", 1340, 920, cue(S["and_die"]), t_vision, 84, INK, seed=9, rot=3, anim="pop")]
B.shot(t_live, t_vision, L29, sync="'to live fast' / 'and die young' -> live fast, nap young", **tr("cut"))
# "We've got the vision" -> Maja's glasses
L31 = [photo("img0036.jpg", "the vision", (1.0, 1.06), "faces")]
L31 += [circle(L31, "img0036.jpg", 7, beat(30, 1), "#fff1a8", 31),
        note("the vision.", 1500, 840, t_vision, t_fun, 84, INK, seed=10, rot=-4, anim="pop"),
        note("(she has glasses)", 1530, 975, t_vision, t_fun, 56, RED_DK, seed=32, rot=2, anim="pop", tape=False)]
B.shot(t_vision, t_fun, L31, fx=[CYM], sync="'We've got the vision' -> circle the glasses", **tr("whip"))
# "...now let's have some fun"
L32 = [wall(YEL)] + pr("1000052042.jpg", "fun", W / 2, 530, (640, 880), -2, t_fun, zoom=(1.0, 1.08), pulse=PUNCH)
L32 += [slam("(fun.)", 1590, 520, t_fun, beat(32, 2), 150, RED, "marker", rot=-6)]
L32 += doodles([beat(31, k) for k in range(1, 4)] + [bar(32), beat(32, 1)],
               [(330, 260), (1600, 860), (420, 860), (1620, 200), (300, 560)], "sparkle", "#111111", 44, 40)
B.shot(t_fun, beat(32, 2), L32, sync="'now let's have some fun' -> fun, sparkles on the beats", **tr("cut"))

# ================================================================== THE PANTS RULE (synth break: bar 32 beat 3 -> bar 35)
P_SRC, P_CX, P_CY, P_FIT, P_ROT = "1000052613.jpg", 560, 540, (620, 900), -3
cup_x, cup_y = on_print(P_CX, P_CY, P_SRC, P_FIT, P_ROT, 0.232, 0.905)       # the front red cup
L33 = [wall(KRAFT, True)] + pr(P_SRC, "pants rule: the table", P_CX, P_CY, P_FIT, P_ROT, beat(32, 2), zoom=(1.0, 1.0))
L33 += [text("HOUSE RULE #1", 1330, 210, beat(32, 2), bar(34), 92, "marker", INK, anim="pop", rot=-2),
        text("(by tim)", 1330, 310, beat(32, 2), bar(34), 64, "caveat", INK, anim="pop", rot=-2),
        note("hit THAT cup\n= pants off.", 1330, 560, bar(33), bar(34), 96, INK, seed=11, rot=-3, anim="pop", line_gap=1.0),
        {"type": "marker", "kind": "circle", "x": round(cup_x), "y": round(cup_y), "rx": 64, "ry": 56, "t0": bar(33), "dur": 0.25,
         "color": RED, "width": 9, "seed": 5},
        {"type": "marker", "kind": "arrow", "x0": 1060, "y0": 690, "x1": round(cup_x + 70), "y1": round(cup_y - 62),
         "t0": beat(33, 0.5), "dur": 0.25, "color": RED, "width": 9, "seed": 6, "bend": 0.12}]
B.shot(beat(32, 2), bar(34), L33, sync="Tim's rule: the card on beat 3 of bar 32, the rule + circled cup + arrow on the downbeat", **tr("glitch"))
B.sfx("stamp", bar(33), db=-17)
L34 = [wall(BLACK)] + pr("1000052364.jpg", "pants rule: respected", 700, 540, (620, 900), 2, bar(34), zoom=(1.0, 1.06), tapes="light")
L34 += [note("the rule was\nrespected.", 1420, 520, bar(34), bar(35), 100, INK, seed=13, rot=-3, anim="pop", line_gap=1.0)]
B.shot(bar(34), bar(35), L34, sync="bar 34: the rule was respected", **tr("cut"))
L35 = [wall(PINK)] + pr("1000052356.jpg", "pants rule: Gabriel", 640, 540, (620, 900), -3, bar(35), zoom=(1.0, 1.0))
L35 += [{"type": "sticker", "text": "🍌", "font": "anton", "size": 230, "t": beat(35, 1), "rot": -24,
         "follow": {"layer": idx(L35, "1000052356.jpg"), "face": "biggest", "off": [0.35, 3.5]}},
        note("...religiously.", 1390, 540, bar(35), bar(36), 104, INK, seed=15, rot=-4, anim="pop")]
B.shot(bar(35), bar(36), L35, sync="bar 35: Gabriel, banana-censored on beat 2", **tr("whip"))
B.sfx("stamp", beat(35, 1), db=-13)

# ================================================================== PRE-CHORUS
t_but, t_get, t_for = cue(S["but"]), cue(S["Get"]), cue(S["for_the"])
B.shot(bar(36), t_but, [photo("img0026.jpg", "overwhelming", (1.0, 1.08), "faces", pulse=PUNCH),
                        note("overwhelming.", 1450, 230, cue(S["Yeah"]), t_but, 88, INK, seed=16, rot=-4, anim="pop")],
       fx=[CYM], sync="'Yeah, it's overwhelming' (note on 'Yeah')", **tr("cut"))
L37 = [wall(TEAL)] + pr("1000052068.jpg", "what else can we do", 700, 540, (620, 900), 3, t_but, zoom=(1.0, 1.06))
L37 += [slam("(study??)", 1390, 540, t_but, t_get, 130, RED, "marker", rot=4, panel={"seed": 33, "tape": True, "pady": 18})]
B.shot(t_but, t_get, L37, sync="'but what else can we do?' -> Gabriel and his tiny book: (study??)", **tr("whip"))
B.shot(t_get, t_for, [photo("img0034.jpg", "get jobs in offices", (1.0, 1.08), "faces", pulse=PUNCH),
                      note("jobs in offices:", 1400, 200, t_get, t_for, 76, INK, seed=18, rot=-3, anim="pop"),
                      note("done.", 1560, 330, cue(S["offices"]), t_for, 92, RED, seed=19, rot=4, anim="pop", tape=False),
                      check(1660, 330, cue(S["offices"]) + 0.12, 1.2)],
       fx=[CYM], sync="'Get jobs in offices' -> done (the suits)", **tr("glitch"))
B.shot(t_for, bar(41), [photo("img0021.jpg", "morning commute", (1.0, 1.1), "faces"),
                        note("the morning commute.", 1300, 230, t_for, bar(41), 80, INK, seed=21, rot=-3, anim="write", dur=0.3),
                        {"type": "marker", "kind": "line", "points": [[1150, 232], [1395, 222]], "t0": cue(S["morning"]), "dur": 0.16,
                         "color": RED, "width": 9},
                        text("4am", 1270, 92, cue(S["commute"]), bar(41), 110, "caveat", RED, anim="pop", rot=-8,
                             panel={"seed": 22, "tape": False, "pady": 14})],
       sync="'for the morning commute' -> crossed out: 4am (night bus)", **tr("whip"))

# ================================================================== KUBA'S LINE (synth break, bars 41-43)
L41 = [photo("1000053168.jpg", "kuba, every time", (1.0, 1.06), "person:3")]
L41 += [note("kuba, every. single. time:", 1300, 880, bar(41), beat(42, 2), 72, INK, seed=23, rot=-2, anim="pop"),
        {"type": "bubble", "text": "can we have\na bigger one?", "x": 760, "y": 200, "size": 64,
         "follow": {"layer": 0, "face": "person:3"}, "t0": beat(41, 2), "t1": beat(42, 2), "seed": 4}]
B.shot(bar(41), beat(42, 2), L41, sync="bars 41-42: Kuba's line in a speech bubble (restaurant)", **tr("cut"))
single = [wall("#161616"),
          {"type": "vinyl", "cx": 1240, "cy": 520, "d": 640, "label": YEL, "text": "KUBA\n45 RPM", "spin": 200,
           "enter": {"t": beat(42, 3), "dur": 0.35, "type": "slide", "from": [-380, 0]}},
          photo("img0001.jpg", "the hit single (sleeve)", (1.0, 1.0), "person:3", box=[600, 190, 660, 660],
                border={"color": "#fbfaf4", "px": 10}, shadow=True, rot=-2,
                enter={"t": beat(42, 2), "dur": 0.12, "type": "thump"}),
          slam("KUBA", 750, 250, beat(42, 2), bar(44), 96, "#ffffff", stroke=5, stroke_color="#111111", rot=-2),
          {"type": "rect", "x": 606, "y": 680, "w": 648, "h": 160, "color": "#111111", "alpha": 0.9, "rot": -2,
           "enter": {"t": beat(42, 2), "dur": 0.12, "type": "thump"}},
          slam("CAN WE HAVE\nA BIGGER ONE?", 930, 760, beat(42, 2), bar(44), 70, YEL, stroke=5, stroke_color="#111111", rot=-2,
               line_gap=0.95),
          {"type": "stamp", "top": "CERTIFIED", "mid": "PLATINUM", "bottom": "★ 1 COPY ★", "size": 330, "color": "#aeb4c8",
           "shape": "circle", "x": 1560, "y": 300, "rot": 12, "t": bar(43), "seed": 3},
          note("(bought by kuba.)", 1540, 900, bar(43), bar(44), 76, INK, seed=24, rot=-3, anim="pop")]
B.shot(beat(42, 2), bar(44), single, sync="bars 42-43: the hit single; the record slides out, platinum on the downbeat", **tr("glitch"))
B.sfx("stamp", bar(43), db=-11)

# ================================================================== CHORUS (bars 44-48) -> join -> final chorus (93-98)
t_and, t_were1 = cue(S["and_our"]), cue(S["Were1"])
B.shot(bar(44), t_and, [photo("1000053165.jpg", "forget about our mothers", (1.0, 1.1), "faces", ((0.03, 0), (-0.03, 0)), pulse=PUNCH),
                        note("hi mom! 👋", 1480, 220, cue(S["Forget"]), t_and, 110, INK, seed=25, rot=-4, anim="pop")],
       fx=[CYM], sync="chorus: 'Forget about our mothers' -> hi mom! (on 'Forget')", **tr("glitch"))
L46 = [photo("img0035.jpg", "and our friends", (1.0, 1.06), "faces", pulse=PUNCH)]
t_never = cue(S["friends"])
L46 += [slam("never.", 1540, 210, t_never, t_were1, 150, RED, "marker", rot=-6, panel={"seed": 35, "tape": True, "pady": 18})]
L46 += doodles([bar(46), beat(46, 1), beat(46, 2)], [(1270, 160), (1810, 130), (1300, 330)], "heart", "#ffffff", 44, 50)
B.shot(t_and, t_were1, L46, fx=[CYM], sync="'...and our friends' -> never. (on 'friends')", **tr("cut"))
L47 = [wall(YEL)] + pr("1000053480.jpg", "pretending to be adults", 640, 540, (620, 900), -3, t_were1, zoom=(1.0, 1.06))
L47 += [note("(pretending to", 1360, 440, t_were1, bar(93), 84, INK, seed=26, rot=-3, anim="pop"),
        note("be adults.)", 1380, 600, t_were1, bar(93), 96, INK, seed=27, rot=2, anim="pop", tape=False)]
B.shot(t_were1, bar(93), L47, sync="'We're fated to pretend' (the music join sits inside this shot)", **tr("whip"))
t_to1 = cue(S["To1"])
L93 = [wall(BLACK)] + pr("1000052383.jpg", "pretending to be in a movie (phone)", 600, 500, (520, 760), -3, bar(93), tapes="light") + \
      pr("img0006.jpg", "pretending to be in a movie (film)", 1320, 500, (520, 760), 3, t_to1, tapes="light", zoom=(1.04, 1.0))
L93 += [note("(pretending to be in a movie.)", W / 2, 985, t_to1, bar(95), 80, INK, seed=28, rot=-2, anim="pop")]
B.shot(bar(93), bar(95), L93, sync="'To pretend' -> the cigarette shot, phone + film twin; caption on 'To'", **tr("cut"))
B.shot(bar(95), bar(97), [{"type": "video", "src": "1000053594.mp4", "start": 10.9, "zoom": [1.04, 1.1], "focus": [0.55, 0.45]},
                          {"type": "osd", "icon": "rec", "text": "REC", "x": 90, "y": 92, "size": 46, "color": "#ff3b30", "blink": BEAT,
                           "t0": bar(95)},
                          *vcr("LIVE FOOTAGE · THE TERRACE", bar(95), bar(97), y=990),
                          *vcr("(pretending to be a band.)", cue(S["to2"]), bar(97), y=915)],
       fx=[VHS], sync="bars 95-96: 'We're fated to pretend' -> live footage (the terrace hand-dance)", **tr("glitch"))
B.shot(bar(97), bar(99), [photo("img0025.jpg", "not sad it's over", (1.0, 1.12), "faces", ((0, 0.02), (0, -0.01))),
                          note("(pretending we're not sad it's over.)", W / 2, 960, cue(S["To2"]), bar(99), 76, INK, seed=31,
                               rot=-1.5, anim="write", dur=0.5)],
       sync="bars 97-98: the last 'To pretend' -> the bittersweet one (slow push, no pulses)", **tr("dissolve"))

# ================================================================== WHERE ARE THEY NOW (outro, bars 99-106): 4 screens x 2 bars
pairs = [[("GABRIEL", "now: MADRID", "Still hoping for\nour Texel trip", "1000053662.jpg", "ES"),
          ("MARIA", "now: BRUSSELS", "Future latina\nsoccer mom", "1000054136.jpg", "BE")],
         [("TIM", "now: FRANKFURT", "'You need to take\nyour pants off'", "img0009.jpg", "DE"),
          ("DARIA", "now: FRANKFURT", "Best photographer", "img0007.jpg", "DE")],
         [("MAJA", "now: POLAND", "Don't trust her with\npiggyback rides", "1000052387.jpg", "PL"),
          ("JAKUB", "now: POLAND", "professional\n'banana' eater 🍑🍌", "1000052087.jpg", "PL")],
         [("ESRA", "now: TÜRKİYE", "The OG baddest\nbanana 😎", "img0020.jpg", "TR"),
          ("SAM", "still in: AMSTERDAM", "edited by Sam —\n'I have too much time\non my hands guys'", "1000052124.jpg", "NL")]]
HDR = "where are they now?"
for k, pair in enumerate(pairs):
    n = 99 + 2 * k
    t0, t1 = bar(n), bar(n + 2)
    lay = [wall(["#0e0e0e", "#1c1230", "#0e0e0e", "#0c2629"][k]),
           text(HDR, W / 2 - text_w(HDR, "mono", 40) / 2 if k == 0 else W / 2, 52, t0, t1, 40, "mono", "#bdb6a6",
                anim="type" if k == 0 else "fade", dur=0.4 if k == 0 else 0.01, fade_out=0)]
    for j, (name, city, quote, src, flag) in enumerate(pair):
        x = (500, 1420)[j]
        t_in, t_q = beat(n, j), beat(n, 1.5 + 0.5 * j)   # A lands on 1, B on 2; quotes on the "and" of 2 and on 3
        portrait = META[src]["h"] > META[src]["w"]
        fit = (380, 470) if portrait else (560, 400)
        lay += pr(src, f"where are they now: {name}", x, 365, fit, (-2, 2)[j], t_in,
                  zoom=(1.0, 1.04) if (j + k) % 2 else (1.04, 1.0), tapes="light", desat=0.15)
        nw = text_w(name, "anton", 110) - 77
        lay += [slam(name, x, 690, t_in, t1, 110, "#ffffff"),
                {"type": "flag", "code": flag, "x": round(x + nw / 2 + 62), "y": 690, "w": 92, "rot": 8 - 4 * j, "t": t_in,
                 "seed": 30 + 2 * k + j},
                text(city, x - text_w(city, "mono", 44) / 2, 778, t_in, t1, 44, "mono", YEL, anim="type", dur=0.3, fade_out=0.06),
                text(quote, x, 905, t_q, t1, 60 if quote.count("\n") < 2 else 54, "caveat", "#f6e7c1", anim="write", dur=0.35,
                     rot=-2, line_gap=0.95, fade_out=0.06)]
    B.shot(t0, t1, lay, fx=[VHS_SOFT], sync=f"outro bars {n}-{n + 1}: where are they now: {pair[0][0]} + {pair[1][0]}",
           **tr(["cut", "whip", "cut", "whip"][k]))

# ================================================================== FAREWELL TOUR POSTER (last bar + final hit) -> tape stop
STOP_T = b(HIT + 4 * BEAT)
poster = [wall("#efe6d2", True),
          photo("1000053175.jpg", "farewell tour poster", (1.0, 1.05), "faces", box=[70, 60, 720, 960],
                halftone={"cell": 10, "mode": "color", "paper": "#efe6d2"}),
          slam("THE BAD BANANAS", 1340, 150, bar(107), DUR, 120, "#111111"),
          slam("FAREWELL TOUR", 1340, 320, bar(107), DUR, 150, "#c8371f"),
          text("2026 – 27", 1340, 440, bar(107), DUR, 54, "mono", "#111111", anim="pop", dur=0.14),
          slam("BRUSSELS · MADRID · FRANKFURT", 1340, 590, beat(107, 1), DUR, 74, "#111111"),
          slam("POLAND · TÜRKİYE · AMSTERDAM*", 1340, 700, beat(107, 1), DUR, 74, "#111111"),
          text("*residency", 1650, 800, beat(107, 2), DUR, 56, "caveat", RED_DK, anim="pop", rot=-4),
          {"type": "stamp", "top": "", "mid": "SOLD OUT", "bottom": "", "size": 330, "color": "#c8371f", "shape": "rect",
           "x": 1330, "y": 900, "rot": -9, "t": bar(108), "seed": 8}]
TS = round(bar(108) + 0.16, 4)
B.shot(bar(107), STOP_T, poster, fx=[{"type": "wobble", "t0": TS, "dur": 1.15, "dark": 0.45}],
       sync="last bar: the tour poster (title on 1, cities on 2); SOLD OUT on the final hit; the tape stops", **tr("glitch"))
B.sfx("stamp", bar(108), db=-9)
B.edl["audio"]["fx"].append({"type": "tape_stop", "t": TS, "dur": 1.15})

# ================================================================== STOP / EJECT, then the liner notes in silence
B.shot(STOP_T, EP, [wall(BLUE),
                    {"type": "osd", "icon": "stop", "text": "STOP", "x": 110, "y": 120, "size": 66, "t0": STOP_T, "t1": b(STOP_T + BEAT)},
                    {"type": "osd", "icon": "eject", "text": "EJECT", "x": 110, "y": 120, "size": 66, "t0": b(STOP_T + BEAT)}],
       fx=[{"type": "vhs", "amount": 0.7, "band": False}], sync="silence: STOP, then EJECT a beat later", **tr("cut"))
B.sfx("clunk", b(STOP_T + BEAT), db=-14)
lines = ["to my new, loving friend group —",
         "thank you for the late nights, the deep talks,",
         "the bridge dates and every flash in between.",
         "wherever life takes you now,",
         "there's always a couch for you in amsterdam ♥"]
ln = [wall("#f2ecdf", True),
      text("LINER NOTES  ·  SPECIAL THANKS", 210, 160, EP, DUR, 40, "mono", "#7a7264", anim="fade", dur=0.6, anchor="lm", fade_out=0)]
for i, line in enumerate(lines):
    ln.append(text(line, 200, 290 + i * 118, b(EP + 4 * BEAT * i + 0.0001), DUR, 62, "elite", RED if i == 4 else INK,
                   anim="type", dur=0.03 * len(line), fade_out=0.0))
SIGN = b(EP + 4 * BEAT * 5)
ln.append(text("— sam", 1420, 900, SIGN, DUR, 92, "caveat", INK, anim="write", dur=0.5, rot=-4, fade_out=0.0))
ln.append({"type": "sticker", "text": "🍌", "font": "anton", "size": 120, "x": 1640, "y": 905, "rot": 18, "t": b(SIGN + 2 * BEAT)})
B.shot(EP, DUR, ln, sync="liner notes in silence: one typed line per (felt) bar, signed, banana sticker", **{"in": {"type": "dip_black", "dur": 0.5}})

# ================================================================== VCR display across the tape
B.edl["overlays"].append({"type": "osd", "t0": bar(3), "t1": STOP_T - 0.01, "counter_t0": bar(3), "x": 70, "y": 64, "size": 30,
                          "opacity": 0.85,
                          "states": [[bar(3), "play", "PLAY"], [bar(99), "pause", "PAUSE", True], [bar(107), "play", "PLAY"],
                                     [TS, "stop", "STOP"]],
                          "hide": [[bar(11), bar(12)], [bar(19), bar(20)], [bar(95), bar(97)]]})


# ================================================================== reading-time lint (Sam: "you cannot read it in time")
def need(L):
    """Seconds a caption must stay fully visible: ~0.8 s to notice + ~55 ms per character, 1.4..3.0 s."""
    n = len(L["text"].replace("\n", " "))
    return min(3.0, max(1.4, 0.8 + 0.055 * n))


p = B.save(os.path.join(OUT, "time_to_pretend_edl.json"))
bad = []
for s in B.edl["shots"]:
    t_end = s["t1"]
    for L in s["layers"]:
        if L["type"] != "text" or L.get("t1", 0) >= DUR - 1e-3 and s is B.edl["shots"][-1]:
            continue
        shown = min(L["t1"], t_end) - L["t0"] - (L.get("dur", 0.2) if L.get("anim") in ("write", "type") else 0.1)
        if shown < need(L) - 1e-3:
            bad.append(f"  {s['id']} {L['t0']:7.2f}  {L['text'][:38]!r:42s} visible {shown:.2f}s < {need(L):.2f}s")
print("wrote", p, "| shots:", len(B.edl["shots"]), "| unique photos:", len(USED), "| duration:", DUR, "| song ends:", round(SONG_END, 3))
print(f"reading-time lint: {len(bad)} caption(s) too short" + ("" if not bad else ":\n" + "\n".join(bad)))
