"""Trip through Georgia: "Field notes" (the second film) -> out/fieldnotes_edl.json
Run: python tools/studio.py build trip-through-georgia-9648 fieldnotes   (then: studio.py preview trip-through-georgia-9648 fieldnotes)

Direction A, chosen by Sam on 2026-10-25; treatment out/treatment_fieldnotes.md (approved the same day).
The trip as a travel sketchbook: every stop starts as a pencil drawing and the photo's real colour floods in like
watercolour on the beat; one red ink line (the real GPS route) runs through the pages and carries the punchlines.
Every photo lands as a quick pencil sketch and floods with colour (Sam's v1 notes: no black-and-white pages); the
kick drum + banjo entry (0:58) is the rental-car punchline. Maps show Georgia's border and neighbours in pencil.
Round 3 (Sam: "shots are a bit too rushed"): every photo stays up >= 2 s and lands at its page's cut or a full bar before it;
the brass climax turns a page every two bars, not every bar.

Music: Mumford & Sons - The Cave, the whole song from its first strum (the MP3's 40 s spoken video intro and 30 s outro
are left out, as in the first film). No join. The last chord rings out, then the thank-you plays in silence.
Lyric word times: forced alignment on the vocal stem. The beat tracker counts verse 1 / chorus 1 and verse 3 in half
time (0.84 s beats); cuts there sit on the half-time beats or the 8th grid.
"""
import json, math, os, sys
sys.path.insert(0, os.environ.get("AM_TOOLS") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
os.environ.setdefault("AM_PROJECT", os.path.dirname(os.path.abspath(__file__)))
from am.common import CACHE, project, font as _font  # noqa: E402
from am.kit import Film, W  # noqa: E402
from am.props import countries  # noqa: E402

P = project()
SLUG = P["song"]["slug"]
SONG_IN, SONG_OUT, PRE = 40.12, 245.3, 0.8          # first strum at 40.2; the ring-out has faded by 245.3
OFF = SONG_IN - PRE                                 # film = song - OFF
VERSION = os.environ.get("AM_VERSION") or "fieldnotes"

F = Film(VERSION, "Trip through Georgia: Field notes", f"music/{P['song']['file']}", SLUG, [(SONG_IN, SONG_OUT, PRE)],
         grade={"preset": "golden", "overrides": {}},
         finish={"grain": 0.008, "vignette": 0.14, "halation": 0.03, "flicker": 0.0, "weave": 0.0})
bar, beat, cue = F.bar, F.beat, F.cue

PAPER, LEAD, RED, GREY = "#f1ead8", "#3b3936", "#b8432f", "#4a443c"
RED_DK = "#9e2410"                                                      # red ink for small text on a wash     # page, graphite, red fineliner, fine mono
NIGHT, CHALK, RED_NIGHT = "#17181f", "#e9e3d3", "#ec6a52"                                     # night pages: white pencil on black paper
TABLE = "#2b2520"                                                       # the desk under the book (seen when it turns)
LX, RX = 480, 1440                                                      # left / right page centres


def s(word, song_t):
    """Aligned sung onset of a word, given its song time."""
    return F.sung(word, song_t - OFF)


def at(word, song_t):
    """The 8th at or just before a sung word: where a lyric caption (or a lyric cut) lands."""
    return cue(s(word, song_t))


# ------------------------------------------------------------------ photos (contact-sheet number -> file)
IDX = dict(l.rstrip("\n").split("\t") for l in open(os.path.join(CACHE, "sheets", "index.txt"), encoding="utf-8") if "\t" in l)
VID = {"menu": "ps005_ef8eedba", "waterfall": "ps016_4269dbb6", "dog": "ps018_b49c4504"}
_files = sorted(os.listdir(os.path.join(os.environ["AM_PROJECT"], "photos")))


def ph(n):
    return IDX[str(n)]


def vid(k):
    return next(f for f in _files if f.startswith(VID[k]) and f.endswith(".mp4"))


def fit(n, maxw, maxh):
    m = F.META[ph(n)]
    a = m["w"] / m["h"]
    w, h = maxw, maxw / a
    if h > maxh:
        h, w = maxh, maxh * a
    return w, h


# ------------------------------------------------------------------ the sketchbook
def page(night=False):
    """A sketchbook spread: dot-grid paper (black paper for night pages). The gutter goes on top: see spread()."""
    return [{"type": "fill", "color": NIGHT if night else PAPER, "paper": True,
             "grid": {"kind": "dots", "step": 46, "color": "#5d5c68" if night else "#a89f8e", "alpha": 0.45 if night else 0.5}}]


def gutter(night=False):
    c = "#000000" if night else "#5a4a32"
    return [F.shape("rect", 960, 540, 46, 1080, c, alpha=0.2 if night else 0.07),
            F.shape("rect", 960, 540, 4, 1080, c, alpha=0.35 if night else 0.12)]


MOVES = [(1.0, 1.04), (1.04, 1.0), (1.0, 1.0)]
_mv = [0]


def paint(n, where, cx, cy, maxw, maxh, t=None, draw=0.3, bloom=None, color=0.82, night=False, zoom=None, feather=30,
          rot=0, focus="faces", **kw):
    """A photo painted on the page with the sketch look (multiplied onto the paper, like graphite and watercolour).
    t: the beat it lands on (the pencil sketches it in over `draw` s, the colour follows); None = there at the cut.
    bloom: (t0, t1) the colour floods in slowly instead. color: how far the colour goes (0 = pencil only)."""
    w, h = fit(n, maxw, maxh)
    if zoom is None:
        zoom = MOVES[_mv[0] % 3]
        _mv[0] += 1
    look = {"name": "sketch", "paper": "#000000" if night else "#ffffff", "lead": CHALK if night else LEAD,
            "strength": 3.0, "blur": 8, "lines": 0.22}
    if t is not None and draw:
        look["draw"] = [[round(t, 4), 0.0], [round(t + draw, 4), 1.0]]
    if bloom:
        look["color"] = [[round(bloom[0], 4), 0.0], [round(bloom[1], 4), color]]
    elif t is not None and color > 0:
        look["color"] = [[round(t + draw * 0.5, 4), 0.0], [round(t + draw + 0.35, 4), color]]
    else:
        look["color"] = color
    box = kw.pop("box", None) or [round(cx - w / 2, 1), round(cy - h / 2, 1), round(w, 1), round(h, 1)]
    L = F.photo(ph(n), where, zoom, focus, box=box, feather=feather, look=look, blend="screen" if night else "multiply", **kw)
    if rot:
        L["rot"] = rot
    if t is not None:
        L["show"] = [round(t - 0.02, 4), 99999]
    return L


def bleed(n, where, **kw):
    """The camera pushes into a painting until it fills the page (landscape holds); same pencil + watercolour, soft edges."""
    kw.setdefault("feather", 90)
    kw.setdefault("color", 0.9)
    return paint(n, where, 960, 540, 1920, 1080, box=[0, 0, 1920, 1080], **kw)


def on(n, cx, cy, maxw, maxh, u, v):
    """Screen position of the normalised point (u, v) of a painting laid out by paint() with zoom 1.0."""
    w, h = fit(n, maxw, maxh)
    return cx - w / 2 + u * w, cy - h / 2 + v * h


def clip(k, where, cx, cy, h, start, color=0.7):
    """A portrait phone clip painted on the page (a moving watercolour)."""
    w = h * 9 / 16
    return {"type": "video", "src": F.use(vid(k), where), "start": start, "box": [round(cx - w / 2, 1), round(cy - h / 2, 1), round(w, 1), h],
            "look": {"name": "sketch", "paper": "#ffffff", "lead": LEAD, "strength": 3.0, "blur": 8, "lines": 0.22, "color": color},
            "feather": 30, "blend": "multiply"}


def pencil(text, x, y, t0, size=64, anchor="mm", rot=0, color=LEAD, fnt="caveat", anim="write", **kw):
    dur = kw.pop("dur", round(min(0.6, 0.12 + 0.025 * len(text)), 3) if anim == "write" else 0.15)
    return F.text(text, x, y, t0, 99999, size, fnt, color, anim=anim, dur=dur, rot=rot, anchor=anchor, fade_out=0.0, **kw)


def ink(text, x, y, t0, size=84, **kw):
    """Red fineliner: the route's colour, and the punchlines."""
    kw.setdefault("color", RED)
    return pencil(text, x, y, t0, size, **kw)


def mono(text, x, y, t0, size=36, anchor="mm", color=GREY, **kw):
    return F.text(text, x, y, t0, 99999, size, "mono_regular", color, anim="fade", dur=0.2, anchor=anchor, fade_out=0.0, **kw)


def header(text, t0, night=False, x=120, y=92):
    F.sfx("pencil", t0, db=-27)
    return pencil(text, x, y, t0, 60, anchor="lm", color=CHALK if night else LEAD)


def tag(text, t0, x=120, y=92):
    """A header on a full-page painting: the pencil label on a scrap of paper laid on the painting, so it stays readable."""
    w = _font("caveat", 60).getlength(text)
    return [F.shape("rect", round(x + w / 2 + 10, 1), y + 4, round(w + 80), 84, PAPER, rot=-1.5, show=[round(t0 - 0.02, 4), 99999]),
            header(text, t0, x=x, y=y)]


def line(points, t0, dur=0.2, color=LEAD, width=4):
    return {"type": "marker", "kind": "line", "points": [[round(x, 1), round(y, 1)] for x, y in points], "t0": round(t0, 4),
            "dur": dur, "color": color, "width": width}


def arrow(x0, y0, x1, y1, t0, color=RED, width=6, bend=0.18, seed=1):
    return {"type": "marker", "kind": "arrow", "x0": round(x0), "y0": round(y0), "x1": round(x1), "y1": round(y1),
            "t0": round(t0, 4), "dur": 0.25, "color": color, "width": width, "seed": seed, "bend": bend}


def tick(x, y, t0, s_=1.0):
    return {"type": "marker", "kind": "line", "points": [[x, y], [x + 18 * s_, y + 26 * s_], [x + 62 * s_, y - 38 * s_]],
            "t0": round(t0, 4), "dur": 0.16, "color": RED, "width": 8}


def strokes(n, x, y, t0, h=50, gap=13, step=0.04, color=LEAD):
    """Tally strokes: groups of four + a slash."""
    out, k = [], 0
    for g in range(math.ceil(n / 5)):
        gx = x + g * gap * 5.8
        m = min(5, n - g * 5)
        for i in range(min(4, m)):
            j = ((k * 37) % 7 - 3) * 1.2
            out.append(line([[gx + i * gap + j, y - h / 2], [gx + i * gap - j * 0.5, y + h / 2]], t0 + k * step, 0.08, color, 4))
            k += 1
        if m == 5:
            out.append(line([[gx - 10, y + h * 0.3], [gx + 3 * gap + 12, y - h * 0.32]], t0 + k * step, 0.1, color, 4))
            k += 1
    return out


def khinkali(day, t0, x=1560, y=92):
    """The running gag: one stroke per day of khinkali, top right of each new day's page."""
    return [pencil("khinkali", x - 18, y, t0, 50, anchor="rm", fnt="caveat_light")] + strokes(day, x + 8, y, t0 + 0.1, h=44, gap=12)


TRIP = json.load(open(os.path.join(CACHE, "trip.json"), encoding="utf-8"))
ROUTE = [p for p in TRIP["route"] if 40 < p[0] < 47 and 41 < p[1] < 43.7]        # inside Georgia (no flights)
STEPS = {st["id"]: st for st in TRIP["steps"]}


def r_index(step_id):
    st = STEPS[step_id]
    return min(range(len(ROUTE)), key=lambda k: (ROUTE[k][0] - st["lon"]) ** 2 + (ROUTE[k][1] - st["lat"]) ** 2)


def km_at(i):
    tot = 0.0
    for a, b in zip(ROUTE[:i], ROUTE[1:i + 1]):
        la1, la2 = math.radians(a[1]), math.radians(b[1])
        h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(math.radians(b[0] - a[0]) / 2) ** 2
        tot += 2 * 6371 * math.asin(math.sqrt(h))
    return tot


def proj(box, pts, pad=0.04):
    """lon/lat -> page px inside box (x0, y0, x1, y1), equirectangular with cos-latitude, aspect kept, centred."""
    lons, lats = [p[0] for p in pts], [p[1] for p in pts]
    lo0, lo1, la0, la1 = min(lons) - pad, max(lons) + pad, min(lats) - pad * 0.7, max(lats) + pad * 0.7
    k = math.cos(math.radians((la0 + la1) / 2))
    sc = min((box[2] - box[0]) / ((lo1 - lo0) * k), (box[3] - box[1]) / (la1 - la0))
    ox = box[0] + ((box[2] - box[0]) - (lo1 - lo0) * k * sc) / 2
    oy = box[1] + ((box[3] - box[1]) - (la1 - la0) * sc) / 2
    return lambda lon, lat: (ox + (lon - lo0) * k * sc, oy + (la1 - lat) * sc)


GEO_B = (39.85, 46.85, 40.95, 43.7)                                     # lon0, lon1, lat0, lat1 around Georgia
_GEO = {code: polys for code, name, polys in countries() if code in ("GE", "RU", "TR", "AM", "AZ")}
NEIGH = {"RU": ("Russia", 43.2, 43.45), "TR": ("Turkey", 41.0, 41.08), "AM": ("Armenia", 44.6, 41.0),
         "AZ": ("Azerbaijan", 46.25, 41.2)}


def geo_proj(box):
    lo0, lo1, la0, la1 = GEO_B
    k = math.cos(math.radians((la0 + la1) / 2))
    sc = min((box[2] - box[0]) / ((lo1 - lo0) * k), (box[3] - box[1]) / (la1 - la0))
    ox = box[0] + ((box[2] - box[0]) - (lo1 - lo0) * k * sc) / 2
    oy = box[1] + ((box[3] - box[1]) - (la1 - la0) * sc) / 2
    return lambda lon, lat: (ox + (lon - lo0) * k * sc, oy + (la1 - lat) * sc)


def _segments(ring, pad=0.4):
    """Parts of a border ring that fall inside the map (a ring of Russia is the whole of Russia)."""
    lo0, lo1, la0, la1 = GEO_B[0] - pad, GEO_B[1] + pad, GEO_B[2] - pad, GEO_B[3] + pad
    segs, cur = [], []
    for lon, lat in ring:
        if lo0 <= lon <= lo1 and la0 <= lat <= la1:
            cur.append((lon, lat))
        elif cur:
            segs.append(cur)
            cur = []
    if cur:
        segs.append(cur)
    return [g for g in segs if len(g) > 1]


def georgia(box, t0, labels=False, dur=0.5):
    """Georgia in the sketchbook: a pale watercolour wash inside its border (pencil), the neighbours' borders fainter,
    and (on the big map) the neighbours' names and the Black Sea."""
    pj = geo_proj(box)
    L = [{"type": "shape", "kind": "poly", "x": 0, "y": 0, "rings": [[[round(c, 1) for c in pj(*p)] for p in poly[0]] for poly in _GEO["GE"]],
          "color": "#d9c48f", "alpha": 0.5, "blend": "multiply", "soft": 6, "grow": {"t": round(t0, 4), "dur": dur}}]
    for code in NEIGH:
        for poly in _GEO[code]:
            for seg in _segments(poly[0]):
                L.append(line([pj(*p) for p in seg], t0, 0.01, "#a39a8a", 2))
    for poly in _GEO["GE"]:
        L.append(line([pj(*p) for p in poly[0]], t0, dur, LEAD, 3))
    if labels:
        for code, (name, lon, lat) in NEIGH.items():
            L.append(pencil(name, *pj(lon, lat), t0 + dur, 46, color="#4a443c"))
        L.append(pencil("Black Sea", *pj(40.55, 42.15), t0 + dur, 50, color="#2c4a62", rot=-8))
    return L


def route_inset(i1, box, t0, dur=0.8, label=None, km=True, km_off=(-40, -4, "rm")):
    """A small map of Georgia with the red route so far (start -> route point i1) and a km count-up."""
    pj = geo_proj(box)
    pts = [list(pj(p[0], p[1])) for p in ROUTE[:i1 + 1]]
    L = georgia(box, t0 - 0.3)
    L += [line(pts, t0, dur, RED, 4), F.shape("circle", *pts[0], 16, color=RED),
          F.shape("circle", *pts[-1], 20, color=RED, grow={"t": round(t0 + dur, 4), "dur": 0.2}),
          F.shape("ring", *pts[-1], 44, color=RED, thick=0.12, grow={"t": round(t0 + dur, 4), "dur": 0.25})]
    if km:
        L.append(F.text("km {n}", pts[-1][0] + km_off[0], pts[-1][1] + km_off[1], t0 + dur, 99999, 52, "caveat", RED_DK, anim="pop",
                        dur=0.6, count=int(round(km_at(i1))), anchor=km_off[2], fade_out=0.0))      # darker red: it sits on the wash
    if label:
        L.append(pencil(label, pts[0][0] + 22, pts[0][1] + 34, t0, 44, anchor="lm", fnt="caveat_light"))
    return L


# ------------------------------------------------------------------ shots (contiguous)
CUR = [0.0]
PAGE_T = 0.5


def turn(dur=PAGE_T, back=False):
    return {"in": {"type": "page", "dur": dur, **({"dir": "back"} if back else {})}}


CUT = {}
DISS = F.tr("dissolve", 0.4)


def shot(t1, layers, sync, tr=None, fx=None, night=False, spread=True, **kw):
    """Append the next shot (from where the last one ended), close it with the gutter, clamp captions to the cut."""
    t0 = CUR[0]
    assert t1 > t0 + 0.3, (sync, t0, t1)
    if spread:
        layers = layers + gutter(night)
    for L in layers:
        if L["type"] in ("text", "bubble") and L.get("t1", 0) > t1:
            L["t1"] = round(t1, 4)
    sh = F.shot(t0, t1, layers, sync=sync, **(tr if tr is not None else CUT), **kw)
    if fx:
        sh["fx"] = fx
    if tr and tr.get("in", {}).get("type") == "page":
        F.sfx("page", t0 - tr["in"]["dur"] * 0.45, db=-23)
    CUR[0] = t1
    return sh


# ================================================================== INTRO: the first page (first strum -> bar 1)
T0 = F.b(40.22 - OFF)                              # the first strum (a pickup before bar 0)
L = page()
L += [pencil("Trip through\nGeorgia", RX, 430, T0, 128, dur=1.0, line_gap=1.0),
      mono("12.10. — 23.10.2026", RX, 640, bar(0)),
      pencil("this book belongs to", LX, 470, bar(0), 52, fnt="caveat_light"),
      pencil("Tom & Sam", LX, 560, bar(0), 96, dur=0.5),
      F.shape("circle", RX + 330, 900, 20, color=RED, grow={"t": bar(0), "dur": 0.2}),
      ink("km 0", RX + 300, 902, bar(0), 50, anchor="rm")]
F.sfx("pencil", T0, db=-26)
shot(bar(1), L, "intro: blank sketchbook; the title writes itself on the first strum, 'this book belongs to Tom & Sam' + km 0 on bar 0",
     tr={"in": {"type": "dip_black", "dur": 0.6, "align": "start"}})

# ================================================================== VERSE 1: TBILISI IN PENCIL (half-time bars, 3.4 s)
t_valley, t_sun, t_away, t_and = at("valley", 47.82), at("the", 50.16), at("away", 53.59), at("and", 55.28)
L = page() + [header("Tbilisi  ·  12.—13.10.", bar(1)),
              paint(17, "tbilisi: the valley", 1000, 580, 1500, 820, t=bar(1), draw=t_valley + 0.4 - bar(1),
                    bloom=(t_valley + 0.2, t_sun - 0.2), color=0.88, zoom=(1.0, 1.0))]
shot(t_sun, L, "'It's empty in the VALLEY of your heart': the old-town rooftops sketch themselves in, colour floods in on 'valley'",
     tr=turn())
L = page() + [bleed(30, "tbilisi: the sun", t=t_sun, draw=0.5, bloom=(t_sun + 0.3, t_away - 0.1), color=0.88, zoom=(1.0, 1.06))]
shot(t_away, L, "'The SUN, it rises slowly as you walk': the first colour of the film, blooming slowly over the line")
t_harv = at("the", 60.33)
L = page() + [header("Chronicles of Georgia", t_away),
              paint(9, "chronicles pillars", LX, 590, 700, 840, zoom=(1.0, 1.03), color=0.88),
              paint(15, "chronicles: the two of us", RX, 470, 820, 620, t=t_and, color=0.88, zoom=(1.0, 1.0)),
              pencil("Thx Keti for the tour!", RX, 880, t_and, 66, rot=-2)]
shot(t_harv, L, "'Away from all the fears': the Chronicles; 'And all the faults': the two of you on its stairs + your note; "
                "the page holds through 'you've left behind'")

# the food: Tom on his phone at an empty plate ('no food'), then the meat arrives in colour ('meat-eater')
t_no, t_for, t_you, t_meat, t_but = at("no", 61.20), at("for", 62.02), at("you", 63.76), at("meat-eater", 64.78), at("but", 67.13)
CL_X, CL_Y, CL_H = LX + 40, 560, 860
cw = CL_H * 9 / 16
plate = (CL_X - cw / 2 + 0.86 * cw, CL_Y - CL_H / 2 + 0.64 * CL_H)
L = page() + [clip("menu", "no food", CL_X, CL_Y, CL_H, 0.4, color=0.9),
              pencil("food?", 830, 210, t_no, 96, rot=-4),
              arrow(800, 260, plate[0] + 10, plate[1] - 30, t_for, color=LEAD, width=5, bend=-0.2, seed=2),
              paint(4, "the meat arrives", RX + 40, 600, 760, 600, t=t_you, draw=0.6,
                    bloom=(t_meat - 0.05, t_meat + 0.6), color=0.85, zoom=(1.0, 1.0))]
shot(t_but, L, "'The harvest left NO FOOD': Tom on his phone at an empty plate, 'food?' + arrow; 'MEAT-EATER': the meat platter "
               "sketches in on 'You' and floods with colour on 'meat-eater'", tr=turn())

# night: white pencil on black paper
L = page(True) + [paint(13, "night lamps", 960, 560, 1500, 900, night=True, color=0.88, zoom=(1.0, 1.04))]
shot(bar(9), L, "'But I have seen the same': a night page, the lamp and the TV tower over the cathedral courtyard across the spread",
     tr=turn(), night=True)
t_but2, t_hope = at("but", 74.76), at("hope", 77.50)
t_I2 = at("I", 79.70)
L = page(True) + [paint(19, "clock tower", LX, 570, 700, 860, night=True, color=0.88, zoom=(1.0, 1.04)),
                  paint(8, "sameba", RX, 560, 700, 880, t=t_but2, draw=1.2, night=True, bloom=(at("I", 76.35), t_hope + 0.5), color=0.95,
                        zoom=(1.0, 1.0)),
                  pencil("Trinity church", RX, 1030, t_hope, 54, color=CHALK)]
shot(t_I2, L, "chorus 1 'But I will hold on HOPE': Sameba drawn in white pencil on 'But', blooming gold on 'hope'", night=True)

L = page() + [header("Dry bridge market", t_I2),
              paint(29, "market stalls", LX, 590, 700, 840),
              paint(28, "drinking horn", RX, 590, 700, 840, t=at("noose", 82.59))]
shot(bar(13), L, "'And I won't let you choke': back to day, the Dry Bridge market; the drinking horn lands on 'noose'", tr=turn())
t_I3 = at("I", 89.88)
L = page() + [header("Tbilisi hike", bar(13)),
              paint(16, "hike panorama", 960, 590, 1560, 820, color=0.88, zoom=(1.0, 1.06))]
shot(t_I3, L, "'And I'll find strength in pain': the panorama from the hike, half coloured, slow push")

# the haircut: before -> the Mafia Barbershop -> after, and 'Sam?' on 'my NAME'
t_ways, t_know, t_name = at("ways", 91.08), at("know", 91.86), at("name", 92.76)
HY, HH, HW = 540, 700, 525
L = page() + [paint(1, "before", 340, HY, HW, HH, color=0.9, zoom=(1.0, 1.0)),
              pencil("before", 340, 950, t_I3, 60),
              paint(14, "mafia barbershop", 960, HY, HW, HH, t=t_ways, color=0.9, zoom=(1.0, 1.0)),
              pencil("during", 960, 950, t_ways, 60),
              paint(12, "after", 1580, HY, HW, HH, t=t_know, color=0.9, zoom=(1.0, 1.0)),
              pencil("after", 1580, 950, t_know, 60),
              ink("Sam?", 1640, 150, t_name, 90, rot=-6)]
shot(bar(18), L, "'And I will CHANGE MY WAYS': before (khachapuri hair) -> the Mafia Barbershop on 'ways' -> after on 'know'; "
                 "'my NAME': red 'Sam?'")

# ================================================================== THE BAND COMES IN: the rental car, 'Yes, no offroad.'
L = page() + [pencil("rental rule no. 1:", LX, 290, bar(18), 70),
              pencil("NO OFFROAD.", LX, 410, bar(18), 124, dur=0.4),
              line([[200, 475], [760, 479]], bar(18) + 0.3, 0.2, LEAD, 5),
              paint(72, "the roads", RX, 560, 680, 900, t=bar(18) + 0.02, draw=bar(19) - bar(18) - 0.15,
                    bloom=(bar(19) - 0.03, bar(19) + 0.55), color=0.92, zoom=(1.0, 1.0)),
              ink("Yes, no offroad.", LX + 10, 700, bar(19), 104, rot=-3)]
shot(bar(21), L, "bar 18: rental rule no. 1: NO OFFROAD; the road sketches itself in pencil -> KICK DRUM IN (bar 19): red "
                 "'Yes, no offroad.' and the colour floods the picture: a tyre stuck in a pothole in the road", tr=turn())

# ================================================================== 14.10.: the road north, in colour
L = page() + [header("14.10.  ·  Gamarjoba", bar(21)),
              paint(31, "gamarjoba: sam and the cat", LX, 600, 700, 800),
              paint(32, "khinkali", RX, 560, 640, 740, t=bar(22), color=0.9),
              pencil("Amai dit eten was crazy goed", RX, 990, bar(22), 56, rot=-2)] + khinkali(3, bar(22))
shot(bar(24), L, "bars 21-23: 14.10., your 'Gamarjoba' lunch stop: Sam and the cat; the khinkali lands on bar 22 with your note "
                 "and the khinkali tally (day 3)", tr=turn())
t_cause = cue(s("I", 109.80) - 0.2)                 # "'Cause" did not align; it sits just before "I"
sw_, sh_ = fit(36, 720, 540)
L = page() + [bleed(35, "the flag over the valley", zoom=(1.05, 1.0))] + tag("Gudauri", bar(24)) + [
              F.shape("rect", LX + 30, 610, sw_ + 44, sh_ + 44, PAPER, rot=2, show=[round(bar(25) - 0.02, 4), 99999]),
              paint(36, "selfie in the valley", LX + 30, 610, 720, 540, t=bar(25), color=0.92, zoom=(1.0, 1.0), feather=10, rot=2)]
shot(t_cause, L, "bars 24-25: the flag over the Gudauri valley fills the page; your selfie lands on a loose page on bar 25, "
                 "on the left, so the flag stays in view")

# ================================================================== VERSE 2: KAZBEGI
t_fill, t_you2 = at("fill", 111.28), at("you", 113.00)
L = page() + [paint(41, "nap: the puppy", LX, 580, 700, 840, color=0.85, zoom=(1.0, 1.04)),
              paint(42, "nap: the black dog", RX, 580, 700, 840, t=t_cause + 0.02, color=0.85, zoom=(1.0, 1.0)),
              pencil("z z z", RX + 230, 112, t_fill, 76, rot=-8)]
shot(t_you2, L, "''Cause I have other things to FILL my time': two stray dogs asleep in Gergeti; 'z z z' on 'fill'")
t_mine, t_which = at("mine", 115.53), at("which", 117.67)
MX, MY, MMW, MMH = RX + 60, 560, 680, 860
fx_, fy_ = on(45, MX, MY, MMW, MMH, 0.38, 0.33)
L = page(True) + [pencil("Vlees", LX - 40, 420, t_you2, 170, rot=-4, color=CHALK),
                  paint(45, "mine", MX, MY, MMW, MMH, color=0.9, zoom=(1.0, 1.0), night=True),
                  ink("mine.", LX + 80, 700, t_mine, 110, rot=-5, color=RED_NIGHT),
                  arrow(LX + 200, 690, fx_ - 70, fy_ + 40, t_mine + 0.05, seed=3, color=RED_NIGHT)]
shot(t_which, L, "'You take what is yours and I'll take MINE': dinner, an evening page; your label 'Vlees'; Sam behind the meat tower, "
                 "red 'mine.' + arrow", night=True)
t_refresh, t_mind = at("refresh", 118.47), at("mind", 120.60)
st = STEPS["275689441"]
L = page() + [paint(43, "gergeti trinity", LX - 20, 560, 680, 900, t=t_which, draw=0.7, bloom=(t_refresh - 0.05, t_refresh + 0.9),
                    color=0.88, zoom=(1.0, 1.03)),
              pencil("Gergeti Trinity", 1010, 250, t_which, 104, anchor="lm"),
              line([[1010, 310], [1300, 316], [1640, 306]], t_which + 0.5, 0.2, LEAD, 3),
              F.text("under Kazbek, {n} m up", 1016, 380, t_refresh, 99999, 62, "caveat_light", LEAD, anim="pop", dur=0.7,
                     count=2170, anchor="lm", fade_out=0.0),
              mono(f"{st['lat']:.4f}° N   {st['lon']:.4f}° E", 1018, 460, t_which, 36, anchor="lm")]
L += route_inset(r_index("275689441"), (1080, 560, 1780, 990), t_refresh + 0.3, dur=1.1, label="Tbilisi")
shot(bar(34), L, "'Which will REFRESH my broken mind': Gergeti Trinity under Kazbek, pencil -> colour on 'refresh'; "
                 "2,170 m counts up, the red route Tbilisi -> Gergeti draws itself, km 214")

t_post, t_I36 = at("post", 123.90), at("I", 126.21)
L = page() + [header("15.10.  ·  The border", bar(34)),
              paint(57, "the border: sam", LX, 590, 700, 820),
              paint(55, "the border: tom", RX, 560, 800, 620, t=t_post, color=0.85, zoom=(1.0, 1.0))] + khinkali(4, bar(34))
shot(t_I36, L, "'So tie me to a POST': 15.10., your label 'The border': Sam's stop hand at the sign, Tom at the other sign on 'post'",
     tr=turn())
t_know2 = at("I", 129.68)
L = page() + [bleed(52, "dariali under the mountain", zoom=(1.0, 1.05), focus=[0.5, 0.8])] + tag("Dariali", t_I36)
shot(t_know2, L, "'I can see widows and orphans through my tears': Dariali monastery, tiny under its mountain, fills the page "
                 "(a landscape hold)")
t_and2 = at("and", 131.97)
L = page() + [paint(64, "stone head: tom", LX, 560, 820, 640),
              paint(67, "stone head: sam", RX, 580, 700, 840, t=t_know2 + 0.02)]
shot(t_and2, L, "'I know my call despite my faults': Tom and Sam on the giant stone heads, both up for the whole line")
LPX, LPY, LPW, LPH = RX + 60, 560, 600, 780
p0 = on(66, LPX, LPY, LPW, LPH, 0.56, 0.43)
p1 = on(66, LPX, LPY, LPW, LPH, 0.2, 0.52)
lw_, lh_ = fit(66, LPW, LPH)
L = page() + [bleed(59, "larches", t=t_and2 + 0.02, draw=0.4, bloom=(t_and2 + 0.3, bar(41)), color=0.95, zoom=(1.04, 1.0))]
L += tag("orange hike", t_and2) + [
              F.shape("rect", LPX, LPY, lw_ + 44, lh_ + 44, PAPER),
              paint(66, "the leap", LPX, LPY, LPW, LPH, color=0.85, zoom=(1.0, 1.0), feather=10),
              arrow(p0[0] + 20, p0[1] - 60, p1[0], p1[1] - 30, at("growing", 133.11), color=LEAD, width=4, bend=0.45, seed=5)]
shot(bar(43), L, "'And despite my GROWING fears': the larches fill the page and flood with orange by bar 41; Sam leaping the "
                 "river on a loose page, a pencil arc traces the jump on 'growing'; the page holds through the instrumental")

# ================================================================== CHORUS 2: GORI + CRAZY CITY
L = page() + [header("16.10.  ·  Stalin top G ⚒️", bar(43)),
              paint(74, "stalin: sam", LX, 590, 700, 820),
              paint(76, "stalin: tom", RX, 590, 700, 820, t=beat(43, 2), zoom=(1.0, 1.0))] + khinkali(5, bar(43))
shot(bar(45), L, "chorus 2 'But I will hold on hope': 16.10., your label 'Stalin top G'; Sam's thumbs-up, Tom's hand on heart",
     tr=turn())
L = page() + [paint(75, "stalin statue", LX, 580, 700, 860, color=0.88),
              paint(73, "stalin's carriage", RX, 560, 800, 620, t=beat(45, 2), color=0.85)]
shot(bar(47), L, "'And I won't let you choke': the statue, Stalin's railway carriage on beat 3")
L = page() + [paint(77, "lenin & stalin carpet", 960, 580, 1440, 840, color=0.85, zoom=(1.0, 1.05))]
shot(bar(49), L, "bars 47-48: the Lenin & Stalin carpet across the spread")
L = page() + [bleed(80, "the tunnel up", zoom=(1.08, 1.0), focus="center")]
shot(beat(50, 2), L, "'And I'll find strength in pain': the rock-cut tunnel stairs at Uplistsikhe fill the page, slow push")
L = page() + [header("Crazy city", beat(50, 2)),
              paint(82, "uplistsikhe", LX, 580, 820, 640, color=0.85),
              paint(79, "uplistsikhe: sam", RX, 590, 700, 820, t=bar(51), zoom=(1.0, 1.0))]
shot(bar(52), L, "'And I will change my ways': your label 'Crazy city', the cave town; Sam on the rock on bar 51")
L = page() + [paint(85, "tom on the plateau", 960, 580, 1500, 860, color=0.8, zoom=(1.04, 1.0))]
shot(bar(53), L, "'I'll know my name as it's called again': Tom small on the Uplistsikhe plateau")

# ================================================================== VERSE 3: THE CAVE, THE BOOK TURNS
t_cave, t_and3 = at("cave", 162.64), at("and", 164.98)
L = page() + [header("17.10.  ·  Prometheus cave", bar(53)),
              paint(91, "stalactite curtain", LX, 590, 700, 840, color=0.88),
              paint(94, "come out of your cave", RX, 590, 700, 840, t=bar(53) + 0.02, draw=0.6,
                    bloom=(t_cave - 0.05, t_cave + 0.7), color=0.9, zoom=(1.0, 1.0))] + khinkali(6, bar(53))
shot(t_and3, L, "verse 3 'So come out of your CAVE': 17.10., Prometheus cave; Tom's cave selfie blooms on 'cave'", tr=turn())
t_up, t_down, t_when = at("upside", 166.94), at("down", 167.73), at("when", 170.26)
mid = round((t_up + t_down) / 2, 4)
L = page() + [paint(92, "upside down", 960, 470, 1400, 740, color=0.88, zoom=(1.0, 1.0), rot=180),
              pencil("this way up", 1920 - 920, 1080 - 92, t_and3, 72, rot=180),
              arrow(1920 - 1160, 1080 - 130, 1920 - 1160, 1080 - 40, t_and3 + 0.3, color=LEAD, width=5, bend=0.0, seed=6)]
shot(t_when, L, "'And see the world hanging UPSIDE DOWN': the stalactite hall drawn upside down; on 'up-side-down' the whole "
                "book turns 180° (lifted off the desk mid-turn) and the cave hangs the right way, 'this way up'",
     fx=[{"type": "rotate", "keys": [[t_up, 0], [t_down, 180]], "scale_keys": [[t_up, 1.0], [mid, 0.56], [t_down, 1.0]],
          "bg": TABLE}])
F.sfx("page", t_up, db=-22)
t_land = at("land", 172.88)
L = page(True) + [paint(96, "lit cave", LX, 580, 700, 860, color=0.85, night=True),
                  paint(97, "cave colours", RX, 580, 700, 860, t=t_when + 0.02, color=0.9, night=True)]
shot(t_land, L, "'When you know the maker's land': still underground, a black page: the lit cave halls, both up for the whole line",
     night=True)
t_so4 = at("so", 175.88)
L = page() + [header("Khoni", t_land),
              paint(103, "kinchkha falls", LX + 40, 580, 700, 860, color=0.85, zoom=(1.0, 1.0)),
              paint(100, "waterfall pool", RX, 580, 700, 860, t=t_land + 0.02)]
shot(t_so4, L, "'land': Khoni, the Kinchkha falls and the pool (both up for the whole page)")

# ================================================================== VERSE 3b: SIREN, MARKET, FREEDOM
t_and4 = at("and", 179.23)
SX, SY, SW, SH = RX, 580, 700, 880
tom = on(105, SX, SY, SW, SH, 0.46, 0.35)
L = page() + [paint(105, "siren", SX, SY, SW, SH, color=0.85, zoom=(1.0, 1.0)),
              ink("siren.", LX + 40, 460, t_so4, 130, rot=-6),
              arrow(LX + 240, 500, tom[0] - 90, tom[1] + 20, t_so4 + 0.1, seed=8)]
shot(t_and4, L, "'So make your SIREN'S call': Tom crouched on the white rock in the pool, red 'siren.' + arrow")
t_I5 = at("I", 182.84)
L = page() + [paint(104, "tom laughing", LX, 580, 700, 860, color=0.8),
              clip("waterfall", "sing all you want", RX, 560, 900, 8.6, color=0.85)]
shot(t_I5, L, "'And SING all you want': Tom under the icy waterfall (clip 8.6 s ->)")
t_hear, t_say, t_cause2, t_now = at("hear", 183.70), at("say", 185.42), at("cause", 185.98), at("now", 188.84)
L = page() + [header("18.10.  ·  Kutaisi", t_I5),
              paint(118, "market", LX, 590, 700, 820, zoom=(1.0, 1.05)),
              pencil("Georgian", RX - 280, 230, t_I5, 90, anchor="lm"),
              line([[RX - 280, 285], [RX + 40, 290]], t_I5 + 0.4, 0.15, LEAD, 3),
              pencil("1.  gamarjoba  =  hello", RX - 280, 400, t_hear, 64, anchor="lm"),
              pencil("2.  madloba  =  thank you", RX - 280, 510, t_say, 64, anchor="lm"),
              pencil("3.", RX - 280, 620, t_cause2, 64, anchor="lm"),
              ink("?", RX - 200, 622, t_cause2 + 0.2, 96, anchor="lm", anim="pop")] + khinkali(7, t_I5)
shot(t_now, L, "'I will NOT HEAR what you have to say': 18.10., the Kutaisi market; the phrasebook: gamarjoba on 'hear', "
               "madloba on 'say', line 3 stays empty ('?')", tr=turn())
t_to = at("to", 192.87)
L = page() + route_inset(r_index("276541862"), (150, 220, 830, 860), t_now + 0.2, dur=1.4, label="Tbilisi", km_off=(0, 70, "mm"))
L += [paint(109, "freedom: sam driving", RX + 30, 560, 840, 960, t=t_now, draw=0.3, bloom=(t_now + 0.1, t_now + 0.8), color=0.9,
            zoom=(1.0, 1.0))]
shot(t_to, L, "'Cause I need freedom NOW': Sam driving the rental; the red route so far draws itself to Kutaisi, km counts up")
L = page() + [header("Tskaltubo", t_to),
              paint(134, "no entry", RX, 570, 700, 900, color=0.9, zoom=(1.0, 1.04)),
              ink("Yes, no entry.", LX, 560, at("life", 193.88), 110, rot=-4)]
shot(bar(69), L, "'To LIVE MY LIFE as it's meant to be': Tskaltubo starts with the NO ENTRY tape; red 'Yes, no entry.' on 'life'")

# ================================================================== BRASS CLIMAX: the book riffles, a page every two bars
RIF = 0.36


def riffle(t1, layers, sync, night=False):
    shot(t1, layers, sync, tr=turn(RIF), night=night)


def bloom_in(n, where, cx, cy, maxw, maxh, t, **kw):
    return paint(n, where, cx, cy, maxw, maxh, bloom=(t + 0.12, t + 0.55), **kw)


DOG = {"type": "video", "src": F.use(vid("dog"), "tom and the dog"), "start": 6.0, "box": [round(LX - 253, 1), 95, 506, 900],
       "look": {"name": "sketch", "paper": "#ffffff", "lead": LEAD, "strength": 3.0, "blur": 8, "lines": 0.22,
                "color": [[bar(69) + 0.12, 0.0], [bar(69) + 0.55, 0.9]]}, "feather": 30, "blend": "multiply"}
riffle(bar(71), page() + [DOG, bloom_in(122, "abandoned station", RX, 560, 820, 640, bar(69), color=0.9)],
       "brass bars 69-70 (page turn on the downbeat): Tom and a stray dog at the abandoned station (clip 6.0 s ->), the station")
riffle(bar(73), page() + [bloom_in(143, "sanatorium window", LX + 10, 560, 860, 700, bar(71), color=0.9),
                          bloom_in(149, "tom on the landing", RX + 40, 570, 700, 900, bar(71), color=0.9)],
       "bars 71-72: the two of you in the sanatorium: Sam in the window, Tom on the broken landing")
riffle(bar(75), page() + [bleed(128, "rotunda tree", bloom=(bar(73) + 0.12, bar(73) + 0.55), zoom=(1.0, 1.05))],
       "bars 73-74: the tree inside the rotunda fills the page")
riffle(bar(77), page() + [header("19.10.  ·  Batumi", bar(75)),
                          bloom_in(157, "upside-down house", 960, 560, 1400, 760, bar(75), color=0.9),
                          ink("not the book this time.", 1180, 990, beat(75, 1), 76, rot=-2)] + khinkali(8, bar(75)),
       "bars 75-76: 19.10., Batumi's upside-down house: 'not the book this time.'")
AW, AH, AY = 540, 720, 570                          # three paintings across the spread, like the barber page
riffle(bar(80), page(True) + [pencil("Abastumani", 120, 92, bar(77), 60, anchor="lm", anim="pop", color=CHALK),
                              bloom_in(163, "sam at the telescope", 340, AY, AW, AH, bar(77), night=True, color=0.9),
                              bloom_in(167, "tom at the telescope", 1580, AY, AW, AH, bar(77), night=True, color=0.9),
                              paint(164, "the moon", 960, AY, AW, AH, t=bar(78), night=True, color=0.95, feather=90, zoom=(1.0, 1.0))],
       "bars 77-79: Abastumani, a night page: Sam at the eyepiece and Tom under the big telescope; the moon they were looking at "
       "lands between them on bar 78", night=True)
riffle(bar(82), page() + [header("20.10.  ·  Vardzia", bar(80)),
                          bloom_in(182, "vardzia arch", LX, 590, 700, 840, bar(80), color=0.9),
                          bloom_in(172, "vardzia cliff", RX, 570, 820, 640, bar(80), color=0.9)] + khinkali(9, bar(80)),
       "bars 80-81: 20.10., Vardzia: the arch, and the whole cliff of caves")

# ================================================================== FINAL CHORUS: the checklist, the last days, the signatures
LAST = F.b(240.272 - OFF)                          # the last played beat: the band stops on "again"
t_hold, t_and_f2, t_noose_f, t_and_f4, t_and_f5 = at("hold", 220.04), at("and", 221.46), at("on", 225.25), at("and", 228.33), at("and", 233.26)
t_my_f, t_name_f = at("my", 235.64), at("name", 236.10)
L = page() + [pencil("survived:", 150, 220, bar(82), 90, anchor="lm")]
items = [("the roads", t_hold), ("sketchy hotels", t_and_f2), ("taxi drivers", t_noose_f), ("khinkali, every day", t_and_f4)]
for k, (txt, tk) in enumerate(items):
    y = 350 + k * 108
    L += [tick(160, y - 6, tk), pencil(txt, 250, y, tk + 0.12, 70, anchor="lm")]
L += strokes(12, 250 + _font("caveat", 70).getlength("khinkali, every day") + 95, 350 + 3 * 108, t_and_f4 + 0.5, h=50, gap=12, step=0.03)
L += [ink("we made it.", 270, 790, t_and_f5, 100, anchor="lm", rot=-3),
      pencil("Tom", 300, 965, t_my_f, 104, rot=-5, dur=0.35),
      pencil("Sam", 640, 965, t_name_f, 104, rot=4, dur=0.35)]
right = [(185, "borjomi mountains", 82, 85, "21.10.  ·  Borjomi Hike"), (188, "big chill", 85, 88, "22.10.  ·  Big chill"),
         (192, "path to the swords", 88, 90, "23.10.  ·  Sword mountain"),
         (((194, "tom and the sword", RX - 195, 370), (196, "sam and the sword", RX + 195, 370)), None, 90, 92, None),
         (197, "sword hill", 92, None, None)]
lab_t = {}
for n, where, b0, b1, lab in right:
    t0_, t1_ = bar(b0), (bar(b1) if b1 else LAST)
    for n_, where_, cx_, mw_ in ([(n, where, RX, 760)] if isinstance(n, int) else n):     # one painting, or a pair side by side
        Lp = paint(n_, where_, cx_, 590, mw_, 800 if mw_ > 400 else 560, t=t0_ + 0.02, draw=0.25, color=0.9)
        Lp["show"] = [round(t0_ - 0.02, 4), round(t1_, 4)]
        L.append(Lp)
    if lab:
        lab_t[lab] = t0_
labs = list(lab_t.items())
for k, (lab, t0_) in enumerate(labs):
    t1_ = labs[k + 1][1] if k + 1 < len(labs) else LAST
    txt = pencil(lab, RX, 110, t0_, 58)
    txt["t1"] = round(t1_ - 0.05, 4)
    L.append(txt)
shot(LAST, L, "final chorus: the checklist page (one line per sung phrase, red ticks; the khinkali tally completes 12 strokes; "
              "'we made it.'; Tom signs on 'my', Sam on 'name') while the right page paints the last days, one per 2-3 bars",
     tr=turn())

# ================================================================== THE LAST CHORD: the whole loop; SILENCE: madloba
EP = F.near(F.song_end + 2 * F.beat_len)
BL = 4 * F.beat_len
F.B.edl["audio"]["fade_out"] = [round(F.song_end - 1.6, 3), round(F.song_end, 3)]
F.B.edl["meta"]["duration"] = round(EP + 4.5 * BL, 3)
F.duration = F.B.edl["meta"]["duration"]
BOX = (330, 330, 1590, 990)
pj = geo_proj(BOX)
pts = [list(pj(p[0], p[1])) for p in ROUTE]
t_r0, t_r1 = round(LAST + 0.25, 4), round(EP - 0.2, 4)
L = page() + georgia(BOX, LAST + 0.02, labels=True) + [line(pts, t_r0, t_r1 - t_r0, RED, 5)]
stops = {"275205857": ("Tbilisi", "lm", 28, 46), "275689441": ("Kazbegi", "rm", -28, -4), "276151132": ("Gori", "lm", 22, -32),
         "276541862": ("Kutaisi", "rm", -22, 36), "276854947": ("Batumi", "rm", -28, 0), "277058084": ("Vardzia", "rm", -28, 28),
         "277287847": ("Borjomi", "rm", -24, -24)}
for st in TRIP["steps"]:
    if st.get("skip"):
        continue
    x, y = pj(st["lon"], st["lat"])
    tt = round(t_r0 + (t_r1 - t_r0) * r_index(st["id"]) / (len(ROUTE) - 1), 4)
    L.append(F.shape("circle", x, y, 16 if st["id"] in stops else 10, color=RED, grow={"t": F.near(tt), "dur": 0.2}))
    if st["id"] in stops:
        name, anc, dx, dy = stops[st["id"]]
        L.append(pencil(name, x + dx, y + dy, F.near(tt), 50, anchor=anc))
vig = [(112, 240, 290, 300, 225), (159, 165, 660, 220, 290), (174, 250, 960, 300, 225), (61, 1745, 340, 220, 290),
       (21, 1745, 720, 300, 225), (199, 1800, 990, 160, 210)]
for k, (n, cx, cy, w_, h_) in enumerate(vig):
    L.append(paint(n, "the loop", cx, cy, w_, h_, t=F.near(LAST + (k + 1) * F.beat_len), draw=0.25, color=0.9, feather=22,
                   zoom=(1.0, 1.0)))
L += [mono("12.10. — 23.10.2026  ·  26 stops  ·  1,564 km", 960, 1045, F.near(LAST + 8 * F.beat_len), 34),
      ink("madloba!", 960, 110, F.near(EP + F.beat_len), 150, rot=-2, dur=0.5),
      pencil("Thank you Georgia", 960, 228, F.near(EP + BL), 84, dur=0.8),
      pencil("— Tom + Sam", 1430, 290, F.near(EP + 2 * BL), 64, rot=-4, dur=0.5)]
shot(F.duration, L, "the last chord: a page turn on the band's last hit; the whole loop draws itself in red ink over the ring-out, "
                    "a small painting lands per beat; silence: 'madloba!', 'Thank you Georgia', '— Tom + Sam'", tr=turn())
F.save()
