"""Oman, inshallah: Sam + Tom's Ramadan road trip, cut to OneRepublic "I Lived" (album version, 3:54).

Direction C "Souq pop" (Sam's pick, 2026-10-25): the trip as loud Gulf pop art after Hassan Hajjaj. Photos are framed
prints in tiled borders on colour fields; facts are price tags; hooks are Anton slams on colour blocks; Arabic on blocks;
die-cut stickers (the Suntop juice box = Ramadan contraband). Verses: one framed photo per bar; choruses fill the frame
to bursting, then cut to one quiet photo. Story in trip order. Treatment: out/treatment.md.

Song bars are 0-indexed (bar 0 = first downbeat, 2.0 s per bar, constant 120 BPM); film time = song time - FIRST.
  python tools/studio.py build oman            -> out/inshallah_edl.json (+ the reading-time lint)
"""
import json, math, os, sys
sys.path.insert(0, os.environ.get("AM_TOOLS") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
os.environ.setdefault("AM_PROJECT", os.path.dirname(os.path.abspath(__file__)))
from am.common import CACHE, arabic, project  # noqa: E402
from am.kit import Film, W, H  # noqa: E402

P = project()
SLUG = P["song"]["slug"]
FIRST, LAST = 1.21, 234.2              # song seconds: just before the first guitar note -> after the ring-out
IDX = {int(k): v for k, v in (l.rstrip("\n").split("\t") for l in open(os.path.join(CACHE, "sheets", "index.txt"),
                                                                        encoding="utf-8") if "\t" in l)}
CLIPS = {n: name for n, name, *_ in json.load(open(os.path.join(CACHE, "sheets", "vgrid", "info.json")))}


def ph(n):
    """Contact-sheet number -> photo file (cache/shotlist.txt)."""
    return IDX[n]


def vc(n):
    """Clip number (V01..V72) -> video file."""
    return CLIPS[n]


# ------------------------------------------------------------------ palette (Omani flag + souq colours)
RED, GREEN, WHITE, SAFFRON, TEAL, INK = "#d7261e", "#0f8a4a", "#fbf6ea", "#f2a516", "#13a3a1", "#141414"
PINK, BLUE, SAND, CREAM, MAROON, NIGHT = "#ef5b8c", "#2453c7", "#e9c98f", "#f6eedd", "#7a1f2b", "#0e1733"
TEAL_DK = "#0d7c7a"                     # teal behind white type (>= 3:1)
FRAMES = {   # tile borders (motif, ground, figure, accent)
    "red": ("star8", (RED, WHITE, GREEN)), "green": ("diamond", (GREEN, WHITE, RED)), "teal": ("star8", (TEAL, WHITE, SAFFRON)),
    "saffron": ("diamond", (SAFFRON, WHITE, MAROON)), "blue": ("star8", (BLUE, WHITE, SAFFRON)), "pink": ("diamond", (PINK, WHITE, BLUE)),
    "maroon": ("star8", (MAROON, SAND, TEAL)), "chev": ("chevron", (RED, WHITE)),
}
STYLES = ["red", "teal", "saffron", "green", "blue", "pink", "maroon", "red"]

F = Film("inshallah", "Oman, inshallah", f"music/{P['song']['file']}", SLUG, [(FIRST, LAST, 0.0)],
         grade={"preset": "punchy", "overrides": {}},
         finish={"grain": 0.006, "vignette": 0.0, "halation": 0.0, "flicker": 0.0, "weave": 0.0}, duration=251.1)


# ------------------------------------------------------------------ timing
def bar(n):
    """Film time of song bar n (0-indexed downbeats)."""
    return F.bar(n)


def bt(n, k):
    """Beat k of bar n (k may be fractional: 2.5 = the 'and' of beat 3)."""
    return F.beat(n, k)


def sung(word, near_bar, tol=1.2):
    """The 8th at or just before the aligned onset of a sung word near a bar (fractional bars allowed)."""
    b = int(near_bar)
    return F.cue(F.sung(word, bar(b) + (near_bar - b) * 2.0 + 1.0, tol=tol))


# ------------------------------------------------------------------ backdrops + devices
def field(color):
    return F.wall(color)


def backdrop(motif, colors, cell=110, scroll=None, prot=0.0):
    """A full-frame tiled backdrop (tent stripes, chevrons, stars...), optionally drifting."""
    L = F.shape("pattern", W / 2, H / 2, W, H, motif=motif, cell=cell, colors=list(colors), prot=prot)
    if scroll:
        L["scroll"] = list(scroll)
    return L


def framed(n, cx, cy, fit, t, style="red", border=None, where="", **kw):
    """Photo #n as a Hajjaj print in one of the tile-border styles."""
    motif, cols = FRAMES[style]
    b = border or (58 if max(fit) > 700 else 44)
    return F.frame(ph(n), where or f"#{n}", cx, cy, fit, t, motif=motif, colors=cols, border=b, **kw)


def framed_clip(n, cx, cy, fit, t, start=0.0, style="teal", border=None, where="", **kw):
    motif, cols = FRAMES[style]
    b = border or (58 if max(fit) > 700 else 44)
    return F.vframe(vc(n), where or f"V{n:02d}", cx, cy, fit, t, start=start, motif=motif, colors=cols, border=b, **kw)


def full(n, style="teal", border=52, zoom=(1.02, 1.08), focus="faces", where=""):
    """A landscape photo full-bleed inside a tile screen-border (the holds)."""
    motif, cols = FRAMES[style]
    return [F.full(ph(n), where or f"#{n}", zoom, focus),
            F.shape("pattern", W / 2, H / 2, W, H, motif=motif, cell=border * 1.3, colors=list(cols),
                    hole=[border, border, W - 2 * border, H - 2 * border])]


def band(text, t0, t1, color=RED, fg=WHITE, y=560, rot=-2, size=150):
    """The hook slammed across the whole frame on a colour band."""
    return [F.shape("rect", W / 2, y, W + 240, size * 1.45, color, rot=rot, t0=round(t0, 4), t1=round(t1, 4),
                    enter={"t": round(t0 - 0.02, 4), "dur": 0.12, "type": "thump"}),
            F.text(text, W / 2, y, t0, t1, size, "anton", fg, rot=rot, anim="pop", dur=0.12, fade_out=0.06)]


def band_words(words, t1, color=RED, fg=WHITE, y=560, rot=-2, size=150):
    """The hook on a colour band, word by word on the sung syllables: words = [(text, t), ...] (the band lands with the
    first word). Words are laid out on one centred line."""
    from am.common import font as _f
    space = _f("anton", size).getlength(" ")
    widths = [_f("anton", size).getlength(w) for w, _ in words]
    x = W / 2 - (sum(widths) + space * (len(words) - 1)) / 2
    th = math.radians(rot)
    t0 = words[0][1]
    L = [F.shape("rect", W / 2, y, W + 240, size * 1.45, color, rot=rot, t0=round(t0, 4), t1=round(t1, 4),
                 enter={"t": round(t0 - 0.02, 4), "dur": 0.12, "type": "thump"})]
    for (w, t), wd in zip(words, widths):
        cx = x + wd / 2
        dx = cx - W / 2
        L.append(F.text(w, W / 2 + dx * math.cos(th), y + dx * math.sin(th), t, t1, size, "anton", fg, rot=rot, anim="pop",
                        dur=0.12, fade_out=0.06))
        slap(t, -21)
        x += wd + space
    return L


def suntop(t, x, y, size=300, rot=12):
    slap(t)
    return F.sticker(t, x, y, size, img="cutouts/suntop.png", rot=rot)


def slap(t, db=-22):
    """A sticker / tag / slab landing: a soft stamp on the beat."""
    F.sfx("stamp", t, db=db)


def flash(t, amount=0.55):
    F.B.flash(t, amount, 0.14)


def tag(text, x, y, t0, t1, size=40, rot=-3, bg=WHITE, fg=INK, sound=True):
    if sound:
        slap(t0, -24)
    return F.tag(text, x, y, t0, t1, size, rot=rot, bg=bg, fg=fg)


def slab(text, x, y, t0, t1, color=RED, fg=WHITE, fnt="anton", size=150, rot=-3, sound=True):
    if sound:
        slap(t0, -20)
    return F.block(text, x, y, t0, t1, color, fg, fnt, size, rot=rot)


def shot(t0, t1, layers, sync, **kw):
    return F.shot(round(t0, 4), round(t1, 4), layers, sync=sync, **kw)


# ================================================================== INTRO (bars 0-3): the JBL starts the song, the title
def intro():
    t1 = bar(4)
    L = [backdrop("stripes", (TEAL, WHITE), cell=96, scroll=[24, 0]),
         F.sticker(bar(0), 960, 500, 520, img="cutouts/jbl.png", rot=-6)]
    slap(bar(0), -18)
    L += slab("OMAN", 520, 230, bar(1), t1, RED, WHITE, "anton", 220, rot=-3)
    L += slab(arabic("عمان"), 1420, 240, bt(1, 2), t1, GREEN, WHITE, "arabic_heavy", 160, rot=3)
    L += slab("INSHALLAH", 560, 860, bar(2), t1, WHITE, INK, "anton", 130, rot=2)
    L += slab(arabic("إن شاء الله"), 1390, 850, bt(2, 2), t1, TEAL_DK, WHITE, "arabic_heavy", 104, rot=-2)
    L += tag("SAM + TOM  ·  15 DAYS", 960, 1012, bt(2, 3), t1, 40, rot=-1, bg=SAFFRON)
    shot(0.0, t1, L, "intro: JBL on bar 0, the title on the beats")


def flip(t, motif, colors, cell=110, scroll=None, t1=None):
    """A full-frame backdrop that takes over on a downbeat (the chorus colour flips, instead of white flashes)."""
    L = backdrop(motif, colors, cell=cell, scroll=scroll)
    L["t0"] = round(t, 4)
    if t1 is not None:
        L["t1"] = round(t1, 4)
    slap(t, -19)
    return L


def label(text, x, y, t0, t1, size=40, rot=0, bg=CREAM, fg=INK):
    """A plain label (no price-tag hole): for names in the thank-you."""
    slap(t0, -25)
    return F.block(text, x, y, t0, t1, bg, fg, "mono", size, pad=(30, 16), rot=rot)


# ================================================================== VERSE 1 (bars 4-19): Muscat, days 2-4, the Ramadan reveal
def verse1():
    # bars 4-5: "Hope when you take that jump / you don't fear the fall" = booking the flight
    t0, t1 = bar(4), bar(6)
    L = [backdrop("chevron", (SAFFRON, "#e8940c"), cell=120, scroll=[40, 0])]
    L += framed(6, 700, 560, (980, 735), t0, "blue", rot=-1)
    L += tag("CHEAP FLIGHT: BOOKED", 1380, 170, sung("Hope", 4), t1, 44, rot=3)
    L += tag("WHY SO CHEAP?", 1520, 900, bar(5), t1, 48, rot=-4)
    shot(t0, t1, L, "bar 4 'take that jump': the booking")

    # bars 6-7: the answer
    t0, t1 = bar(6), bar(8)
    L = [field(RED)]
    L += framed(1, 960, 610, (1180, 660), t0, "green")
    L += slab("RAMADAN", 690, 205, t0, t1, INK, WHITE, "anton", 170, rot=-4)
    L += slab(arabic("رمضان"), 1420, 215, bt(6, 1), t1, WHITE, INK, "arabic_heavy", 120, rot=3)
    L += tag("RESTAURANTS: CLOSED UNTIL SUNSET", 960, 980, bt(6, 2), t1, 40, rot=-2)
    shot(t0, t1, L, "bar 6: the answer, Ramadan")

    # bars 8-10.5: "water rises / you built a wall": Sam, then Tom, on the same sea wall (twin gag 1: SAME WALL)
    t0, t1 = bar(8), bt(10, 2)
    L = [backdrop("stripes", (BLUE, WHITE), cell=80, prot=90.0)]
    L += framed(16, 600, 540, (800, 600), t0, "teal", rot=-2)
    L += framed(19, 1400, 520, (480, 700), sung("You", 9), "red", rot=2)
    L += tag("MUTTRAH CORNICHE", 600, 975, bt(8, 2), t1, 40, rot=-1)
    L += tag("SAME WALL", 1400, 965, sung("You", 9), t1, 46, rot=3, bg=SAFFRON)
    shot(t0, t1, L, "bars 8-10: the sea wall, Sam then Tom on 'you built a wall' (SAME WALL)")

    # bars 10.5-11: Muscat from the viewpoint, the dashboard at 38 degrees
    t0, t1 = bt(10, 2), bar(12)
    L = full(12, "saffron")
    L += framed_clip(8, 1560, 520, (300, 540), t0, start=0.8, style="red", border=34)
    L += tag("38 °C  ·  IN APRIL", 1230, 960, t0, t1, 44, rot=-3)
    shot(t0, t1, L, "bars 10.5-11: viewpoint + dashboard 38 C")

    # bars 12-15: "the crowd screams out / it's screaming your name": the souq, Tom in a dishdasha
    t0, t1 = bar(12), bar(16)
    L = [field(SAFFRON), backdrop("diamond", (SAFFRON, "#f7c35a", MAROON), cell=90)]
    L += framed_clip(2, 680, 520, (1000, 563), t0, start=0.0, style="red", speed=0.6)
    L += framed(3, 1480, 560, (420, 600), sung("It's", 13), "green", rot=3)
    L += slab("TOM", 1490, 175, bar(14), t1, RED, WHITE, "anton", 120, rot=-4)
    L += slab(arabic("توم"), 1640, 950, bt(14, 1), t1, INK, WHITE, "arabic_heavy", 84, rot=3)
    L += tag("MUTTRAH SOUQ", 640, 960, bt(12, 2), t1, 44, rot=-2)
    shot(t0, t1, L, "bars 12-15: souq crowd, Tom's name on 'screaming your name'")

    # bars 16-18.5: "if everybody runs / you choose to stay": Abdoul's night tour (Tom's print gets two more beats)
    t0, t1 = bar(16), bt(18, 2)
    L = [field(NIGHT), backdrop("dots", (NIGHT, "#24346a"), cell=70)]
    L += framed(15, 640, 520, (500, 720), t0, "maroon", rot=-2)
    L += framed(18, 1290, 540, (480, 690), sung("You", 17), "teal", rot=2)
    L += tag("NIGHT TOUR WITH ABDOUL", 1180, 975, bt(16, 1), t1, 40, rot=-2)
    shot(t0, t1, L, "bars 16-17: night tour with Abdoul")

    # bars 18.5-19: the drum fill, day 4: the boat through the rock arch (into the dolphins)
    t0, t1 = bt(18, 2), bar(20)
    L = [{"type": "video", "src": F.use(vc(13), "V13"), "start": 4.0, "zoom": [1.0, 1.06],
                                "focus": [0.5, 0.5], "box": [0, 0, W, H]},
         F.shape("pattern", W / 2, H / 2, W, H, motif="star8", cell=68, colors=[RED, WHITE, GREEN],
                 hole=[52, 52, W - 104, H - 104])]
    shot(t0, t1, L, "bars 18-19: drum fill, the boat under the rock arch")


# ================================================================== PRE-CHORUS (bars 20-33): days 4-7
def pre():
    # bars 20-21: "Hope that you fall in love": dolphins
    t0, t1 = bar(20), bar(22)
    L = [field(BLUE), backdrop("stripes", (BLUE, "#2f63d8"), cell=60, prot=90.0, scroll=[0, 30])]
    L += framed_clip(11, 960, 500, (1300, 731), t0, start=0.3, style="teal")
    L += tag("DAY 4  ·  DOLPHINS", 1460, 975, bt(20, 2), t1, 44, rot=-3)
    shot(t0, t1, L, "bars 20-21: dolphins on 'fall in love'")

    # bars 22-23: the goat, the only witness of a sneaky bite
    t0, t1 = bar(22), bar(24)
    L = [backdrop("chevron", (SAFFRON, "#e8940c"), cell=100)]
    L += framed(23, 820, 560, (1000, 750), t0, "red", rot=-1)
    L += tag("NO EATING IN PUBLIC", 1420, 130, t0, t1, 44, rot=3)
    L += tag("ONLY WITNESS: ONE GOAT", 1440, 960, bt(22, 3), t1, 44, rot=-3)
    shot(t0, t1, L, "bars 22-23: the goat witness")

    # bars 24-25: Nizwa fort library, then the real Suntops hidden indoors (Sam's note that day: Recovering from Ramadan)
    t0, t1 = bar(24), bar(26)
    L = [field(MAROON), backdrop("star8", (MAROON, "#8f2a37", SAND), cell=110)]
    L += framed(46, 560, 610, (440, 640), t0, "saffron", rot=-2)
    L += framed(30, 1330, 590, (780, 585), sung("You", 25), "teal", rot=2)
    L += slab("RECOVERING FROM RAMADAN", 960, 140, bt(24, 2), t1, WHITE, INK, "anton", 84, rot=-2)
    shot(t0, t1, L, "bars 24-25: Nizwa, then the hidden Suntops (Sam's note 'Recovering from Ramadan')")

    # bars 26-27: the car, Sam then Tom (twin gag 2: SAME CAR), and the set-up for the pro driver
    t0, t1 = bar(26), bar(28)
    L = [backdrop("stripes", (TEAL, WHITE), cell=96, scroll=[30, 0])]
    L += framed(48, 520, 470, (760, 570), t0, "red", rot=-2)
    L += framed(49, 1400, 620, (760, 570), bt(26, 1), "green", rot=2)
    L += tag("SAME CAR", 1400, 965, bt(26, 1), t1, 46, rot=3, bg=SAFFRON)
    L += tag("(NOT A 4X4)", 520, 900, bt(26, 2), t1, 42, rot=-3)
    shot(t0, t1, L, "bars 26-27: the grey sedan, both (SAME CAR, not a 4x4)")

    # bar 28: "and I hope that you don't suffer": the camping scorpion
    t0, t1 = bar(28), sung("But", 29)
    L = [field("#1b1410"), backdrop("dots", ("#1b1410", "#3a2a1c"), cell=60)]
    L += framed(62, 920, 540, (540, 780), t0, "maroon")
    L += tag("OUR CAMPING NEIGHBOUR", 1460, 900, t0, t1, 42, rot=-4)
    shot(t0, t1, L, "bar 28: 'don't suffer' = the scorpion")

    # "but take the pain": DYING (Sam's label for that day), in the Airbnb bed (his note: sleep deprivation)
    t0, t1 = sung("But", 29), bt(30, 2)
    L = [field(INK), backdrop("dots", (INK, "#2a2a2a"), cell=60)]
    L += framed(67, 700, 540, (520, 780), t0, "red", rot=-3)
    L += slab("DYING", 1370, 420, t0, t1, RED, WHITE, "anton", 200, rot=4)
    L += tag("SLEEP-DEPRIVED", 1370, 700, bt(29, 2), t1, 48, rot=-3)
    shot(t0, t1, L, "'take the pain': DYING (Sam's label), sleep-deprived (his note)")
    t0, t1 = bt(30, 2), bar(32)
    L = [field(CREAM), backdrop("stripes", (CREAM, "#efe1c4"), cell=70)]
    L += framed(65, 700, 540, (520, 760), t0, "teal", rot=2)
    L += slab("RECOVERING. AGAIN.", 1350, 540, t0, t1, TEAL_DK, WHITE, "anton", 112, rot=-3)
    shot(t0, t1, L, "RECOVERING. AGAIN. (Sam's label)")

    # bars 32-33: "Hope when the moment comes / you'll say": made it up Jebel Shams in the sedan
    t0, t1 = bar(32), bar(34)
    L = [field(BLUE), backdrop("chevron", (BLUE, "#2f63d8"), cell=110, scroll=[40, 0])]
    L += framed(84, 820, 520, (980, 735), t0, "saffron", rot=-1)
    L += tag("4X4 RECOMMENDED", 1450, 150, t0, t1, 48, rot=3)
    L += tag('TOM: "I\'M A PRO DRIVER"', 1420, 950, bt(32, 3), t1, 46, rot=-3, bg=SAFFRON)     # Tom did all the driving
    shot(t0, t1, L, "bars 32-33: the mountain road, 'pro driver'")


# ================================================================== CHORUS 1 (bars 34-49): Jebel Shams, the desert
def chorus1():
    # bars 34-41.75: "I, I did it all" x2 builds: Sam, then the canyon, then Tom on the same rock (twin gag 3)
    t0, t1 = bar(34), bt(41, 3)
    L = [field(SAFFRON), backdrop("star8", (SAFFRON, "#f7c35a", RED), cell=120, scroll=[90, 0]),
         flip(bar(38), "star8", (RED, "#e2483f", SAFFRON), cell=120, scroll=[90, 0])]
    L += framed(79, 600, 560, (960, 720), t0, "red", rot=-2)
    for l_ in framed(75, 1430, 250, (430, 330), bar(36), "teal", border=26, rot=5):
        l_["show"] = [round(bar(36) - 0.03, 4), round(bar(38), 4)]
        L.append(l_)
    for l_ in framed(82, 1500, 862, (430, 330), bar(37), "pink", border=26, rot=-4):
        l_["show"] = [round(bar(37) - 0.03, 4), round(bar(38), 4)]
        L.append(l_)
    L += slab("I,", 1500, 260, t0, bar(36), RED, WHITE, "anton", 280, rot=4)
    L += slab("I DID IT ALL", 1500, 560, sung("did", 35), bar(38), INK, WHITE, "anton", 100, rot=-3)
    L += framed(91, 1380, 470, (760, 570), bar(38), "green", rot=3)
    L += slab("I,", 1290, 935, bar(38), t1, INK, WHITE, "anton", 120, rot=-3)
    L += slab("I DID IT ALL", 1625, 945, sung("did", 39), t1, RED, WHITE, "anton", 80, rot=2)
    L += tag("SAME ROCK", 1390, 130, bt(40, 1), t1, 46, rot=-3, bg=SAFFRON)
    shot(t0, t1, L, "bars 34-41.75: 'I, I did it all' builds: Sam, canyon prints, Tom on the same rock (SAME ROCK)")

    # bars 41.75-45.9: "I owned every second": a souq stall of two shelves, one print per beat (Jebel Shams night, then
    # the desert day in order); then "I SAW / SO / MANY / PLACES" lands word by word on a red band
    t0, t1 = bt(41, 3), bt(45, 3)
    L = [field(SAFFRON), backdrop("stripes", (SAFFRON, "#f7c35a"), cell=70, prot=90.0)]
    for y in (430, 985):                                              # the two shelves (planks)
        L.append(F.shape("rect", W / 2, y, W, 26, MAROON))
    shelf = [(71, 270, 255), (90, 740, 255), (122, 1180, 255), (127, 1650, 255),
             (129, 270, 805), (146, 740, 805), (113, 1180, 805), (141, 1650, 805)]
    for k, (n, x, y) in enumerate(shelf):
        tk = t0 + k * 0.5
        L += framed(n, x, y, (420, 300), tk, STYLES[k % 7], border=18, rot=[-2, 1, 2, -1][k % 4])
        slap(tk, -26)
    L += band_words([("I SAW", bt(43, 3)), ("SO", bar(44)), ("MANY", bt(44, 0.5)), ("PLACES", bt(44, 1.5))], t1, RED, WHITE,
                    y=575)
    shot(t0, t1, L, "bars 41.75-45: the stall (one print per beat) + 'I SAW / SO / MANY / PLACES' on the syllables")

    # "with every broken bone": the dune run, the fall lands on 'broken'
    t0, t1 = bt(45, 3), bt(47, 1.5)
    L = [field(SAND), backdrop("stripes", (SAND, "#e3bd7a"), cell=50, prot=45.0)]
    L += framed_clip(42, 960, 540, (520, 924), t0, start=3.75, style="pink", border=40)
    L += tag("WAHIBA SANDS  ·  DAY 8", 1500, 880, t0, t1, 42, rot=-3)
    shot(t0, t1, L, "'every broken bone': dune run, fall on 'broken'")

    # "I swear I lived": everything drops away (the song dips here)
    t0 = bt(47, 1.5)
    shot(t0, bar(49), [field(SAND)] + framed(112, 960, 540, (760, 960), t0, "saffron", border=30, enter=None),
         "'I swear I lived': quiet, the two of you on the ridge")
    shot(bar(49), bar(50), [field(SAND)] + framed(121, 960, 540, (760, 960), bar(49), "teal", border=30, enter=None),
         "bar 49: the guide walks into the dunes")


# ================================================================== VERSE 2 (bars 50-63): the desert evening, the pitstop, the wadi
def verse2():
    # bars 50-51: "spend your days / they all add up": a stranger's desert tour, camels in the window
    t0, t1 = bar(50), bar(52)
    L = [field(TEAL), backdrop("stripes", (TEAL, "#0f8f8d"), cell=90)]
    L += framed(126, 560, 500, (760, 570), t0, "saffron", rot=-2)
    L += framed_clip(35, 1380, 420, (720, 405), sung("But", 51), start=1.0, style="red", border=40)
    L += tag("A STRANGER OFFERED US\nA DESERT TOUR", 1400, 905, bt(50, 1), t1, 40, rot=-2)
    shot(t0, t1, L, "bars 50-51: the stranger's desert tour, camels at the window")

    # bars 52-53.75: tea in the tent, then the sunset wow
    t0, t1 = bar(52), bt(53, 3)
    L = [backdrop("chevron", (SAFFRON, "#e8940c"), cell=110, scroll=[30, 0])]
    L += framed(114, 560, 540, (480, 720), t0, "green", rot=-2)
    L += framed(151, 1340, 540, (480, 720), bar(53), "teal", rot=2)
    shot(t0, t1, L, "bars 52-53: tea in the tent, Sam's sunset face")

    # "and when that sun goes down": a saffron sun disc sinks behind the after-sunset glow, one notch per beat
    t0, t1 = bt(53, 3), sung("Hope", 55)
    sun = F.shape("circle", 960, 250, 420, 420, SAFFRON)
    sun["move"] = [[bar(54), 0, 0], [bt(54, 0.4), 0, 90], [bt(54, 1), 0, 90], [bt(54, 1.4), 0, 180], [bt(54, 2), 0, 180],
                   [bt(54, 2.4), 0, 270], [bt(54, 3), 0, 270], [bt(54, 3.4), 0, 380]]
    L = [field(MAROON), sun]
    L += framed(106, 960, 700, (1000, 560), t0, "red", enter=None, zoom=(1.0, 1.04), focus=[0.5, 0.7])
    L += slab(arabic("إفطار"), 330, 190, bt(54, 2), t1, GREEN, WHITE, "arabic_heavy", 110, rot=-4)
    shot(t0, t1, L, "'when that sun goes down': the disc sinks behind the glow, iftar")

    # "hope you raise your cup" + "oh, oh": the hosts, framed Hajjaj-style in Suntop boxes popping on the 8ths
    t0, t1 = sung("Hope", 55), bt(57, 3.5)
    L = [field(RED), backdrop("diamond", (RED, "#e2483f", WHITE), cell=100)]
    cx, cy, fw, fh = 820, 520, 860, 645
    L += framed(150, cx, cy, (fw, fh), t0, "saffron", border=30)
    ring = []
    nx, ny = 7, 5
    for i in range(nx):
        ring.append((cx - fw / 2 - 30 + i * (fw + 60) / (nx - 1), cy - fh / 2 - 82))
    for j in range(1, ny):
        ring.append((cx + fw / 2 + 82, cy - fh / 2 - 30 + j * (fh + 60) / ny))
    for i in range(nx - 1, -1, -1):
        ring.append((cx - fw / 2 - 30 + i * (fw + 60) / (nx - 1), cy + fh / 2 + 82))
    for j in range(ny - 1, 0, -1):
        ring.append((cx - fw / 2 - 82, cy - fh / 2 - 30 + j * (fh + 60) / ny))
    ts = sung("cup", 55)
    for k, (x, y) in enumerate(ring):
        L.append(F.sticker(round(ts + k * 0.125, 4), x, y, 120, img="cutouts/suntop.png", rot=[-12, 8, -4, 14][k % 4]))
    slap(ts, -18)
    L += tag("AFTER SUNSET:\nFOOD IS LEGAL", 1600, 560, t0, t1, 44, rot=-4)
    shot(t0, t1, L, "'raise your cup': the hosts framed in Suntop boxes (Hajjaj's product frame)")

    # "I wish that I could witness": the tents under the stars
    t0, t1 = bt(57, 3.5), sung("All", 59)
    L = [field(NIGHT), backdrop("dots", (NIGHT, "#26386e"), cell=60)]
    L += framed(155, 900, 500, (980, 735), t0, "blue")
    L += tag("A BED IN THE DESERT: 10 RIAL", 1300, 970, t0, t1, 40, rot=-2)
    shot(t0, t1, L, "'witness': the hosts' camp under the stars (a bed for 10 rial)")

    # "all your joy / and all your pain": the secret roadside lunch, Sam hiding behind a towel on 'pain'
    t0, t1 = sung("All", 59), sung("But", 61)
    L = [backdrop("stripes", (SAFFRON, WHITE), cell=80, scroll=[40, 0])]
    L += framed(168, 590, 560, (500, 740), t0, "teal", rot=-3)
    L += framed(167, 1370, 520, (760, 570), sung("pain", 61), "red", rot=2)
    L += [suntop(bt(59, 3), 1010, 250, 280, -10)]
    L += tag("SNUCK OFF FOR A QUICK BITE", 1360, 930, t0, t1, 40, rot=-2)
    shot(t0, t1, L, "'all your joy / all your pain': sneaking off for a quick bite (Sam's words)")

    # "but until my moment comes": Mohammed
    t0, t1 = sung("But", 61), bar(63)
    L = [field(TEAL), backdrop("diamond", (TEAL, "#2bb8b5", WHITE), cell=90)]
    L += framed(175, 740, 540, (540, 820), t0, "pink", rot=2)
    L += tag("MOHAMMED'S WADI TOUR", 1380, 540, t0, t1, 44, rot=-3)
    shot(t0, t1, L, "'until my moment comes': Mohammed")


# ================================================================== CHORUS 2 (bars 63-79): Sam jumps, Tom jumps, the burned feet
def chorus2():
    # "I'll say" -> "I!": Sam's take-off, the splash on the chorus downbeat
    t0, t1 = bar(63), bar(66)
    L = [field(GREEN), backdrop("star8", (GREEN, "#139a55", WHITE), cell=120, scroll=[60, 0]),
         flip(bar(64), "star8", (RED, "#e2483f", WHITE), cell=120, scroll=[60, 0])]
    L += framed_clip(44, 640, 540, (540, 960), t0, start=3.0, style="saffron", border=40)
    L += slab("I,", 1420, 380, bar(64), t1, INK, WHITE, "anton", 240, rot=-4)
    L += slab("I DID IT ALL", 1420, 700, sung("I", 64.5), t1, WHITE, INK, "anton", 104, rot=3)
    shot(t0, t1, L, "bars 63-65: Sam's take-off on 'I'll say', the splash on the chorus downbeat")

    shot(bar(66), bar(67), [field(SAFFRON)] + framed(169, 960, 540, (760, 960), bar(66), "red", border=30),
         "bar 66: Mohammed and a friend in the palm oasis")

    # Tom's jump, mirrored: frame on the right, splash on bar 68
    t0, t1 = bar(67), bt(70, 3)
    L = [field(SAFFRON), backdrop("chevron", (SAFFRON, "#e8940c"), cell=110, scroll=[-50, 0]),
         flip(bar(68), "chevron", (RED, "#e2483f"), cell=110, scroll=[-50, 0])]
    L += framed_clip(59, 1280, 540, (540, 960), t0, start=3.5, style="green", border=40)
    L += slab("I,", 500, 380, bar(68), t1, WHITE, INK, "anton", 240, rot=4)
    L += slab("I DID IT ALL", 500, 700, sung("did", 69), t1, INK, WHITE, "anton", 104, rot=-3)
    shot(t0, t1, L, "bars 67-69: Tom's jump, splash on bar 68")

    # the set-up: barefoot through the gorge
    t0, t1 = bt(70, 3), bt(71, 3)
    L = [backdrop("chevron", (SAND, "#dcb06a"), cell=90)]
    L += framed(186, 740, 540, (540, 820), t0, "maroon", rot=-2)
    L += [F.sticker(bar(71), 1400, 400, 300, img="cutouts/boots.png", rot=8)]
    slap(bar(71))
    L += tag("SHOES: OFF", 1400, 770, t0, t1, 52, rot=-4)
    shot(t0, t1, L, "bars 70-71: shoes off, barefoot (set-up)")

    # "I owned every second": 8 wadi prints drop one per beat; "I SAW / SO / MANY / PLACES" land as tags on the words
    t0, t1 = bt(71, 3), bt(75, 2)
    L = [field(RED), backdrop("star8", (RED, "#e2483f", SAFFRON), cell=120, scroll=[-50, 0])]
    stack = [171, 174, 179, 181, 180, 187, 190, 170]
    spots = [(410, 330, -6), (1500, 350, 5), (760, 610, 3), (1240, 690, -4), (300, 760, 7), (1640, 770, -7),
             (980, 340, -2), (960, 770, 4)]
    for k, (n, (x, y, r)) in enumerate(zip(stack, spots)):
        L += framed(n, x, y, (380, 500), t0 + k * 0.5, ["saffron", "green", "blue", "saffron", "pink", "green", "blue", "saffron"][k],
                    border=24, rot=r, enter="drop")
        F.sfx("drop", t0 + k * 0.5, db=-25)
    words = [("I SAW", bt(73, 3), 410, 520, -5), ("SO", bar(74), 1500, 560, 4), ("MANY", bt(74, 0.5), 760, 880, 3),
             ("PLACES", bt(74, 1.5), 1240, 930, -3)]
    for txt, tw, x, y, r in words:
        L += tag(txt, x, y, tw, t1, 64, rot=r, bg=WHITE)
    shot(t0, t1, L, "bars 71.75-75.5: the wadi prints drop per beat, the words land as price tags")

    # "with every broken bone": BROKEN BONE marked down -> BURNED FEET (Sam's barefoot hop over the hot rocks)
    t0, t1 = bt(75, 2), bt(77, 1.5)
    tb = sung("broken", 76)
    L = [field(SAFFRON), backdrop("diamond", (SAFFRON, "#f7c35a", RED), cell=90)]
    L += framed_clip(56, 690, 540, (540, 960), t0, start=17.5, style="red", border=40)
    L += tag("BROKEN BONE", 1390, 400, t0, t1, 56, rot=-3)
    L += [F.shape("rect", 1400, 402, 560, 34, RED, rot=-14, t0=round(tb, 4), t1=round(t1, 4),
                  enter={"t": round(tb - 0.02, 4), "dur": 0.1, "type": "thump"})]
    L += tag("BURNED FEET", 1420, 700, bt(76, 2), t1, 64, rot=4, bg=WHITE)
    slap(tb, -18)
    shot(t0, t1, L, "'every broken bone': BROKEN BONE marked down -> BURNED FEET")

    # "I swear I lived": Mohammed pulls Sam up (quiet, the song dips at 78); then waking up on the beach
    t0 = bt(77, 1.5)
    shot(t0, bt(78, 2), [field(SAFFRON)] + framed(192, 960, 540, (760, 960), t0, "teal", border=30, enter=None),
         "'I swear I lived': Mohammed's helping hand")
    t0, t1 = bt(78, 2), bar(80)
    L = [backdrop("stripes", (SAND, WHITE), cell=70)]
    L += framed(195, 760, 540, (560, 860), t0, "blue")
    L += tag("BEACH CAMP:\nWOKE UP HERE", 1390, 540, t0, t1, 46, rot=-3)
    shot(t0, t1, L, "bars 78.5-79: waking up on the beach")


# ================================================================== BRIDGE (bars 80-91): the meal, Eid, the mosque
def bridge():
    # each chant phrase flips the colour on its downbeat and gets its own layout
    t0, t1 = bar(80), bar(82)
    motif, cols = FRAMES["red"]
    L = [F.full(ph(203), "#203", (1.0, 1.05), "faces"),
         F.shape("pattern", W / 2, H / 2, W, H, motif=motif, cell=70, colors=list(cols), hole=[54, 54, W - 108, H - 108])]
    L += tag("PAID FOR BY A STRANGER\nWE NEVER SPOKE TO", 1380, 880, bt(80, 1), t1, 46, rot=-3)
    shot(t0, t1, L, "whoa 1: the meal a stranger paid for (full bleed)")
    slap(t0, -19)

    t0, t1 = bar(82), bar(84)
    fw, fh = 720, 960
    L = [backdrop("stripes", (TEAL, WHITE), cell=96, scroll=[40, 0])]
    L += F.frame(ph(213), "#213", 960, 540, (560, 760), t0, motif="star8", colors=(RED, WHITE, GREEN), border=70)
    L += tag("WADI SHAB", 1450, 900, bt(82, 1), t1, 46, rot=-3)
    shot(t0, t1, L, "whoa 2: Tom in the yellow turban, the c_1 portrait")

    # whoa 3: the Ramadan bookend: bar 6's layout returns; RAMADAN / IS OVER; the real Suntop on the Eid lawn
    t0, t1 = bar(84), bt(86, 1)
    ww, hh = F.print_size(ph(222), (520, 700))
    cx, cy = 960, 640
    L = [field(RED)]
    L += F.frame(ph(222), "#222", cx, cy, (520, 700), t0, motif="diamond", colors=(GREEN, WHITE, RED), border=50, zoom=(1.0, 1.0))
    L += slab("RAMADAN", 690, 205, t0, t1, INK, WHITE, "anton", 170, rot=-4)
    L += slab("IS OVER", 1300, 210, bt(84, 2), t1, GREEN, WHITE, "anton", 150, rot=3)
    sx, sy = cx - ww / 2 + 0.085 * ww, cy - hh / 2 + 0.955 * hh             # the real Suntop box in the photo
    L += [{"type": "marker", "kind": "circle", "x": round(sx, 1), "y": round(sy, 1), "rx": 78, "ry": 62, "t0": round(bar(85), 4),
           "dur": 0.25, "color": RED, "width": 10, "seed": 3}]
    L += tag("SUNTOP IN PUBLIC", 1450, 860, bar(85), t1, 44, rot=-4)
    shot(t0, t1, L, "whoa 3: the Ramadan bookend, RAMADAN IS OVER, the real Suntop circled")

    # whoa 4: Eid with Abdoul
    t0, t1 = bt(86, 1), bar(88)
    L = [field(GREEN), backdrop("star8", (GREEN, "#139a55", WHITE), cell=110, scroll=[60, 0])]
    L += framed(224, 700, 460, (900, 675), t0, "red", rot=-2)
    L += framed(225, 1530, 600, (380, 540), bar(87), "saffron", rot=4)
    L += slab(arabic("عيد مبارك"), 700, 950, bar(87), t1, RED, WHITE, "arabic_heavy", 90, rot=-2)
    L += tag("EID WITH ABDOUL", 1500, 150, t0, t1, 44, rot=3)
    shot(t0, t1, L, "whoa 4: Eid Mubarak with Abdoul")

    # "(with every broken bone) / I swear I lived": the Grand Mosque, calm, plain type, no tags or stickers
    t0, t1 = bar(88), bt(89, 1)
    L = [field(NIGHT), backdrop("star8", (NIGHT, "#16306b", "#c9a227"), cell=140)]
    L += framed(298, 960, 540, (600, 900), t0, "blue", border=30, enter=None, zoom=(1.0, 1.08))
    shot(t0, t1, L, "bar 88: the Grand Mosque dome")
    t0, t1 = bt(89, 1), bar(91)
    L = [field(NIGHT), backdrop("diamond", (NIGHT, "#16306b", "#c9a227"), cell=110)]
    L += framed(299, 700, 540, (540, 820), t0, "saffron", rot=-1, enter=None, border=30)
    L += [F.text("A GIFT FROM", 1370, 470, bt(89, 2), t1, 70, "anton", WHITE, anim="fade", dur=0.25, fade_out=0.1),
          F.text("A FRIENDLY OMANI", 1370, 570, bt(89, 2), t1, 70, "anton", WHITE, anim="fade", dur=0.25, fade_out=0.1)]
    shot(t0, t1, L, "'I swear I lived': Tom with the Quran he was given (plain type)")
    t0, t1 = bar(91), bar(92)
    shot(t0, t1, [field(NIGHT)] + framed(282, 960, 540, (760, 960), t0, "blue", border=30, enter=None),
         "bar 91: Sam under the mosque arch")


# ================================================================== FINAL CHORUS (bars 92-107): days 11-14
def final():
    t0, t1 = bar(92), bar(94)
    L = [field(SAFFRON), backdrop("star8", (SAFFRON, "#f7c35a", RED), cell=120, scroll=[100, 0])]
    L += framed(229, 760, 500, (900, 675), t0, "red", rot=-1)
    L += slab("I,", 1560, 300, t0, t1, RED, WHITE, "anton", 220, rot=4)
    L += slab(arabic("أنا"), 1560, 540, bt(92, 1), t1, GREEN, WHITE, "arabic_heavy", 130, rot=-3)
    L += tag("ALL OF A SUDDEN,\n100 PEOPLE APPEAR", 1560, 850, bt(92, 1), t1, 44, rot=-3)
    shot(t0, t1, L, "final 'I': the hot springs, 100 people appear")

    t0, t1 = bar(94), bar(96)
    L = [field(TEAL), backdrop("stripes", (TEAL, WHITE), cell=80, prot=90.0, scroll=[0, 60])]
    L += framed(228, 560, 500, (500, 740), t0, "saffron", rot=-3)
    L += framed_clip(66, 1320, 500, (430, 764), t0, start=4.0, style="pink", border=36)
    L += tag("TOM  ·  0 FISH", 560, 975, t0, t1, 44, rot=-2)
    L += tag("SAM  ·  ALL THE FISH", 1320, 975, t0, t1, 44, rot=2, bg=SAFFRON)
    shot(t0, t1, L, "the fish: Tom 0, Sam all of them")

    t0, t1 = bar(96), bar(98)
    L = [field(GREEN), backdrop("star8", (GREEN, "#139a55", SAFFRON), cell=110, scroll=[80, 0]),
         flip(bar(96), "star8", (RED, "#e2483f", WHITE), cell=110, scroll=[80, 0])]
    L += framed(232, 760, 540, (560, 840), t0, "saffron", rot=-2)
    L += slab("I,", 1450, 420, t0, t1, WHITE, INK, "anton", 260, rot=4)
    shot(t0, t1, L, "second final 'I': Tom and the giant coffee pot at the random Nakhal fair")

    t0, t1 = bar(98), bt(99, 3)
    L = [field(MAROON), backdrop("diamond", (MAROON, "#8f2a37", SAND), cell=100)]
    L += framed(250, 880, 500, (980, 735), t0, "teal", rot=-2)
    L += tag("LIFT + COFFEE FROM\nAN OIL PRODUCER", 1520, 880, t0, t1, 44, rot=-3)
    shot(t0, t1, L, "Jebel Akhdar: hitchhiked up, coffee from an oil producer")

    # "I owned every second that this world could give": the whole trip, one tile per 8th, in order (day 2 -> day 14)
    t0, t1 = bt(99, 3), bt(101, 3)
    recap = [5, 17, 26, 38, 54, 57, 78, 70, 134, 158, 189, 198, 199, 235, 99, 268]   # #99: the 12 Apr rainbow (ps011 by mistake)
    cells = [{"src": F.use(ph(n), f"recap #{n}"), "t": round(t0 + k * 0.25, 4), "zoom": 1.04, "rot": [-2, 1, 2, -1][k % 4]}
             for k, n in enumerate(recap)]
    L = [field(SAFFRON), {"type": "grid", "rows": 4, "cols": 4, "gap": 14, "box": [0, 0, W, H], "cells": cells}]
    for k in range(0, 16, 2):
        slap(t0 + k * 0.25, -27)
    shot(t0, t1, L, "bars 99.75-101.75: the whole trip in order, one tile per 8th")

    # "I saw so many places": the line fills the screen as a window onto the dunes, then the camera flies through it
    t0, t1 = bt(101, 3), bt(103, 1)
    L = [field(SAFFRON),
         F.type_mask(ph(143), "#143 knockout", "I SAW SO\nMANY PLACES", size=300, y=540, font="anton", zoom=[1.0, 1.0],
                     focus=[0.5, 0.5], fade=0, line_gap=0.92, scale=[[bt(102, 3), 1.0], [t1, 16.0]],
                     outline={"px": 6, "color": INK})]
    slap(t0, -18)
    shot(t0, t1, L, "bar 101.75: 'I saw so many places' as a knockout over the dunes, then through it")

    # "the things that I did / with every broken bone": the 12 Apr hike: lost, not enough water, the wrong food, and the
    # vultures circling (V31, filmed on that hike; Polarsteps filed it under 'Back at the Airbnb')
    t0, t1 = bt(103, 1), bt(105, 1.5)
    L = [field(SAFFRON), backdrop("chevron", (SAFFRON, "#e8940c"), cell=110, scroll=[30, 0])]
    L += framed_clip(31, 700, 470, (1060, 596), t0, start=5.6, style="red", border=44, zoom=(2.2, 2.4), focus=(0.52, 0.52))
    L += slab("LOST", 1560, 250, t0, t1, RED, WHITE, "anton", 230, rot=4)
    L += framed(102, 1560, 700, (330, 440), bt(103, 3), "teal", border=22, rot=3)
    L += tag("NOT ENOUGH WATER", 700, 960, bt(103, 3), t1, 48, rot=-2)
    L += tag("WRONG FOOD", 1560, 980, bt(104, 1), t1, 48, rot=3, bg=SAFFRON)
    shot(t0, t1, L, "the hike: vultures circling, LOST / NOT ENOUGH WATER / WRONG FOOD (Sam's note)")

    # "I swear I lived": the ride home in the rain (V29, 12 Apr night) with the brothers (#100, the one in the kumma
    # giving a thumbs up; Polarsteps filed it under 'Back at the Airbnb'): alhamdulillah, we survived (Sam's words)
    t0, t1 = bt(105, 1.5), bar(107)
    F.B.edl["grade"]["overrides"][ph(100)] = {"exposure": 0.42}           # a dark car selfie: lift it
    L = [field(NIGHT), backdrop("dots", (NIGHT, "#26386e"), cell=60)]
    L += framed_clip(29, 700, 440, (1000, 563), t0, start=4.4, style="green", border=44)
    L += framed(100, 1530, 720, (420, 315), t0, "saffron", border=22, rot=3)
    L += tag("RESCUED BY\n3 CRAZY OMANI BROTHERS", 700, 920, t0, t1, 44, rot=-2)
    L += slab(arabic("الحمد لله"), 1530, 330, bar(106), t1, GREEN, WHITE, "arabic_heavy", 120, rot=-4)
    shot(t0, t1, L, "'I swear I lived': the ride home in the rain with the brothers, alhamdulillah (Sam's note)")


# ================================================================== OUTRO (bars 107-116): the Germans, the delay, Istanbul
def outro():
    t0, t1 = bar(107), bar(109)
    L = [backdrop("star8", (BLUE, "#2f63d8", SAFFRON), cell=110, scroll=[60, 0])]
    L += framed(277, 520, 470, (740, 555), t0, "red", rot=-2)
    L += framed(289, 1400, 560, (740, 555), bt(107, 1), "saffron", rot=2)
    L += tag("THE GERMANS, AGAIN", 1400, 965, bt(107, 1), t1, 44, rot=-3)
    shot(t0, t1, L, "outro: the opera stairs, then dinner with the Germans (again)")

    t0, t1 = bar(109), bt(110, 2)
    L = [backdrop("stripes", (RED, WHITE), cell=90)]
    L += slab("FLIGHT DELAYED", 960, 470, t0, t1, INK, WHITE, "anton", 210, rot=-3)
    L += tag("24 HOURS+", 1250, 700, bt(109, 1), t1, 64, rot=4, bg=SAFFRON)
    L += [F.sticker(bt(109, 2), 540, 760, 230, text="✈️", rot=-18)]
    slap(bt(109, 2))
    shot(t0, t1, L, "flight delayed: 24 hours+ (Sam's note)")

    t0, t1 = bt(110, 2), bar(112)
    L = [field(TEAL), backdrop("diamond", (TEAL, "#2bb8b5", WHITE), cell=90)]
    L += framed(313, 700, 540, (540, 820), t0, "red", rot=2)
    L += tag("INFO POINT → INFO POINT", 1350, 540, t0, t1, 40, rot=-3)
    shot(t0, t1, L, "Istanbul airport, info point to info point (Sam's label)")

    t0, t1 = bar(112), bar(114)
    L = [backdrop("star8", (SAFFRON, "#f7c35a", GREEN), cell=110, scroll=[40, 0])]
    L += framed(315, 760, 470, (900, 675), t0, "green", rot=-1)
    L += tag('FREE HOTEL.\n"THEY HAD A BUFFET, MASHALLAH"', 1350, 900, bt(112, 1), t1, 40, rot=-3)
    shot(t0, t1, L, "the free hotel buffet (Sam's words)")

    t0, t1 = bar(114), 233.104
    L = [field(MAROON)]
    L += framed(314, 960, 540, (1200, 900), t0, "red", border=40, enter=None, zoom=(1.0, 1.06))
    shot(t0, t1, L, "bars 114-116: the Istanbul sunset, the ring-out")


# ================================================================== TAIL (silence): shukran
def tail():
    """One card in the silence: shukran, the strangers (Sam's approved list, verbatim) in two waves, then Sam + Tom."""
    names_a = ["ABDOUL", "MOHAMMED", "MARWAN", "THE DESERT HOSTS", "THE MAN WHO PAID FOR OUR MEAL",
               "THE OIL PRODUCER WHO BOUGHT THE COFFEE"]
    names_b = ["THE MAN AT THE MOSQUE WHO GAVE US THE QURAN", "THE GUIDE WHO DROVE US UP THE MOUNTAIN",
               "THE PAKISTANI FAMILY", "THE THREE BROTHERS", "THE GERMANS"]
    rows = [440, 535, 630, 725, 820, 915]
    t0, t1, wave2 = 233.104, F.duration, 242.604                    # on the felt pulse after the song (x.104 / x.604)
    L = [field(SAFFRON), F.shape("pattern", W / 2, H / 2, W, H, motif="star8", cell=70, colors=[RED, WHITE, GREEN],
                                hole=[54, 54, W - 108, H - 108], scroll=[30, 0])]
    L += slab(arabic("شكرا"), 700, 210, t0, t1, RED, WHITE, "arabic_heavy", 170, rot=-3)
    L += slab("THANK YOU", 1290, 225, t0 + 0.5, t1, INK, WHITE, "anton", 120, rot=3)
    for k, name in enumerate(names_a):
        L += label(name, 960, rows[k], t0 + 1.0 + k, wave2 - 0.5, 36, rot=[-1, 1][k % 2], bg=CREAM if k % 2 else WHITE)
    for k, name in enumerate(names_b):
        L += label(name, 960, rows[k], wave2 + k, t1, 36, rot=[-1, 1][k % 2], bg=CREAM if k % 2 else WHITE)
    L += slab("SAM + TOM", 960, 915, wave2 + 5.5, t1, GREEN, WHITE, "anton", 72, rot=-2)
    shot(t0, t1, L, "tail (silence): shukran, the strangers in two waves, Sam + Tom")


intro()
verse1()
pre()
chorus1()
verse2()
chorus2()
bridge()
final()
outro()
tail()
F.B.edl["audio"]["fade_out"] = [232.4, 233.0]
F.save()
