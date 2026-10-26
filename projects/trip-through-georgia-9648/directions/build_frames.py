"""Style frames for the second Georgia film: three directions, two frames each.

  A  "Field notes"     diary sketchbook + maps: every stop drawn in pencil, then the photo floods in like watercolour
  B  "Two words"       Georgian script as the star: giant Mkhedruli knockouts, B&W photos, flag red, a vocabulary counter
  C  "Out of the cave" Plato's cave: photos projected on a torch-lit cave wall until the song walks out into daylight

Run:  python tools/studio.py run trip-through-georgia-9648 ../projects/trip-through-georgia-9648/directions/build_frames.py [a b c]
Writes directions/dir_<id>_edl.json, renders the stills at 1920 px and copies them to out/directions/<id>_<n>.png.
Mock-ups only: photos may repeat across directions; the film's builder enforces no-reuse.
"""
import json, math, os, shutil, subprocess, sys
sys.path.insert(0, os.environ.get("AM_TOOLS") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "tools"))
os.environ.setdefault("AM_PROJECT", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from am.common import CACHE, OUT, font, project  # noqa: E402
from am.kit import Film, W, H  # noqa: E402

TOOLS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "tools")
P = project()
SLUG = P["song"]["slug"]
SEG = 3.0
IDX = dict(l.rstrip("\n").split("\t") for l in open(os.path.join(CACHE, "sheets", "index.txt"), encoding="utf-8") if "\t" in l)


def ph(n):
    """Contact-sheet number -> photo file."""
    return IDX[str(n)]


TRIP = json.load(open(os.path.join(CACHE, "trip.json"), encoding="utf-8"))
ROUTE = [p for p in TRIP["route"] if 40 < p[0] < 47 and 41 < p[1] < 43.7]        # inside Georgia (no flights)


def km_to(lon, lat):
    i = min(range(len(ROUTE)), key=lambda k: (ROUTE[k][0] - lon) ** 2 + (ROUTE[k][1] - lat) ** 2)
    tot = 0.0
    for a, b in zip(ROUTE[:i], ROUTE[1:i + 1]):
        la1, la2 = math.radians(a[1]), math.radians(b[1])
        h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(math.radians(b[0] - a[0]) / 2) ** 2
        tot += 2 * 6371 * math.asin(math.sqrt(h))
    return tot


def proj(box, bounds):
    """lon/lat -> page px inside box (x0, y0, x1, y1), equirectangular with cos-latitude, aspect kept."""
    lo0, lo1, la0, la1 = bounds
    k = math.cos(math.radians((la0 + la1) / 2))
    s = min((box[2] - box[0]) / ((lo1 - lo0) * k), (box[3] - box[1]) / (la1 - la0))
    ox = box[0] + ((box[2] - box[0]) - (lo1 - lo0) * k * s) / 2
    oy = box[1] + ((box[3] - box[1]) - (la1 - la0) * s) / 2
    return lambda lon, lat: (ox + (lon - lo0) * k * s, oy + (la1 - lat) * s)


def film(version, grade, finish):
    F = Film(version, "Georgia directions", f"music/{P['song']['file']}", SLUG, [(40.12, 245.3, 0.0)],
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


# ================================================================== A: field notes (diary sketchbook + maps)
PAPER, LEAD, INK = "#f1ead8", "#3b3936", "#b8432f"         # page, graphite, the red fineliner of the route
DOTS = {"kind": "dots", "step": 46, "color": "#a89f8e", "alpha": 0.5}


def pencil(F, t, text, x, y, size, **kw):
    return F.text(text, x, y, 0, 9999, size, kw.pop("fnt", "caveat"), kw.pop("color", LEAD), fade_out=0, **kw)


def a_1(F, t):
    """Gergeti Trinity half-drawn, half-watercoloured; the day's entry and the route so far in red ink."""
    st = next(s for s in TRIP["steps"] if s["id"] == "275689441")
    L = [{"type": "fill", "color": PAPER, "paper": True, "grid": DOTS},
         F.full(ph(43), "A", (1.0, 1.0), box=[150, 80, 690, 920], focus="center", feather=46,
                look={"name": "sketch", "color": 0.4, "paper": PAPER, "lead": LEAD, "strength": 3.2, "blur": 9})]
    L += [pencil(F, t, "14.10.", 968, 150, 60, anchor="lm", rot=-2),
          pencil(F, t, "Gergeti Trinity", 960, 270, 118, anchor="lm"),
          pencil(F, t, "under Kazbek, 2,170 m up", 966, 385, 64, anchor="lm", fnt="caveat_light"),
          {"type": "marker", "kind": "line", "points": [[968, 326], [1240, 333], [1560, 324]], "t0": t, "dur": 0.01,
           "color": LEAD, "width": 3},
          F.text(f"{st['lat']:.4f}° N   {st['lon']:.4f}° E", 970, 470, 0, 9999, 30, "mono_regular", "#6b645a", anchor="lm",
                 fade_out=0)]
    # the route so far, in red ink: Tbilisi -> Gergeti (real GPS track)
    seg = ROUTE[:min(range(len(ROUTE)), key=lambda k: (ROUTE[k][0] - st["lon"]) ** 2 + (ROUTE[k][1] - st["lat"]) ** 2) + 1]
    lons, lats = [p[0] for p in seg], [p[1] for p in seg]
    pj = proj((1060, 560, 1780, 980), (min(lons) - 0.05, max(lons) + 0.05, min(lats) - 0.03, max(lats) + 0.03))
    pts = [list(pj(p[0], p[1])) for p in seg]
    L += [{"type": "marker", "kind": "line", "points": pts, "t0": t, "dur": 0.01, "color": INK, "width": 5},
          F.shape("circle", *pts[0], 22, color=INK), F.shape("circle", *pts[-1], 26, color=INK),
          F.shape("ring", *pts[-1], 54, color=INK, thick=0.12),
          pencil(F, t, "Tbilisi", pts[0][0] - 30, pts[0][1] + 6, 52, anchor="rm"),
          pencil(F, t, "km " + f"{km_to(st['lon'], st['lat']):,.0f}", pts[-1][0] - 44, pts[-1][1] - 4, 50, anchor="rm", color=INK)]
    return L, None


def a_2(F, t):
    """The loop: a double page with the whole route in red ink and little watercolours at the stops."""
    L = [{"type": "fill", "color": PAPER, "paper": True, "grid": DOTS},
         F.shape("rect", 960, 540, 46, 1080, "#5a4a32", alpha=0.07), F.shape("rect", 960, 540, 4, 1080, "#5a4a32", alpha=0.12)]
    steps = [s for s in TRIP["steps"] if not s.get("skip")]
    lons, lats = [p[0] for p in ROUTE], [p[1] for p in ROUTE]
    pj = proj((120, 170, 1800, 880), (min(lons) - 0.1, max(lons) + 0.1, min(lats) - 0.08, max(lats) + 0.08))
    L.append({"type": "marker", "kind": "line", "points": [list(pj(p[0], p[1])) for p in ROUTE], "t0": t, "dur": 0.01,
              "color": INK, "width": 5})
    stops = {"275205857": ("Tbilisi", "mm", 0, 58), "275689441": ("Kazbegi", "rm", -30, -4), "276151132": ("Gori", "rm", -26, -32),
             "276541862": ("Kutaisi", "lm", 26, 30), "276854947": ("Batumi", "rm", -30, 0), "277058084": ("Vardzia", "rm", -30, 26),
             "277287847": ("Borjomi", "rm", -26, -22)}
    for s in steps:
        x, y = pj(s["lon"], s["lat"])
        L.append(F.shape("circle", x, y, 18 if s["id"] in stops else 11, color=INK))
        if s["id"] in stops:
            name, anc, dx, dy = stops[s["id"]]
            L.append(pencil(F, t, name, x + dx, y + dy, 56, anchor=anc))
    # watercolour vignettes near their stops (the last one still being painted)
    vig = [(8, 1700, 860, 240, 320, 1.0), (43, 1650, 280, 230, 300, 1.0), (172, 1150, 930, 300, 220, 1.0),
           (143, 380, 215, 330, 245, 1.0), (157, 300, 900, 300, 225, 0.45)]
    for n, cx, cy, w_, h_, c in vig:
        L.append(F.full(ph(n), "A", (1.0, 1.0), box=[cx - w_ / 2, cy - h_ / 2, w_, h_], focus="center", feather=26,
                        look={"name": "sketch", "color": c, "paper": PAPER, "lead": LEAD}))
    L += [pencil(F, t, "one loop, one rental car", 1010, 100, 72, rot=-1),
          F.text("12.10 — 23.10.2026   ·   26 STOPS   ·   1,564 KM", 1010, 168, 0, 9999, 28, "mono_regular", "#6b645a",
                 fade_out=0)]
    return L, None


# ================================================================== B: two words (Georgian type, B&W, flag red)
RED, BLK, OFF = "#e1251b", "#111111", "#f2efe8"
BW = {"name": "bw", "contrast": 1.4}


def mono(F, text, x, y, size=30, color=BLK, **kw):
    return F.text(text, x, y, 0, 9999, size, "mono", color, fade_out=0, **kw)


def counter(F, n, x=120, y=110, on_photo=False):
    """WORDS UNDERSTOOD: n, the running gag (n turns red when it clicks up)."""
    lab = "WORDS UNDERSTOOD:"
    w_ = font("mono", 30).getlength(lab)
    L = []
    if on_photo:
        L.append(F.shape("rect", x + (w_ + 90) / 2 - 18, y, w_ + 120, 72, OFF))
    L += [mono(F, lab, x, y, 30, BLK, anchor="lm"), mono(F, str(n), x + w_ + 40, y, 30, RED if n else BLK, anchor="lm")]
    if n:
        L.append(F.shape("ring", x + w_ + 49, y + 1, 58, color=RED, thick=0.1))
    return L


def fit(text, fnt, maxw, size):
    return min(size, size * maxw / font(fnt, size).getlength(text))


def b_1(F, t):
    word = "საქართველო"
    size = fit(word, "georgian_black", 1760, 460)
    L = [F.wall(OFF),
         F.type_mask(ph(37), "B", word, size=size, y=520, font="georgian_black", look={"name": "bw", "contrast": 1.3}, zoom=[1.0, 1.0],
                     focus=[0.5, 0.6], fade=0, outline={"px": 3, "color": BLK}),
         F.shape("rect", 180, 900, 120, 12, RED),
         F.text("SAKARTVELO", 120, 960, 0, 9999, 92, "anton", BLK, anchor="lm", fade_out=0),
         mono(F, "= GEORGIA, IN GEORGIAN", 640, 972, 30, "#555555", anchor="lm"),
         mono(F, "12—23.10.2026", 1800, 972, 30, "#555555", anchor="rm")]
    L += counter(F, 0)
    return L, None


def b_2(F, t):
    word = "გამარჯობა!"
    size = fit(word, "georgian_black", 1300, 230)
    L = [F.full(ph(118), "B", (1.06, 1.06), look=BW, focus="center"),
         F.shape("rect", 960, 515, 1520, 330, RED),
         F.text(word, 960, 500, 0, 9999, size, "georgian_black", "#ffffff", fade_out=0),
         F.shape("rect", 960, 760, 760, 112, OFF),
         F.text("GAMARJOBA!  (HELLO)", 960, 762, 0, 9999, 72, "anton", BLK, fade_out=0)]
    L += counter(F, 1, on_photo=True)
    return L, None


# ================================================================== C: out of the cave (Plato's cave -> daylight)
CHALK = "#eadfc9"
OCHRE = {"name": "tritone", "shadow": "#1a0f08", "mid": "#a5612e", "high": "#f6dcae", "contrast": 1.15}


def tally(x, y, n, t, h=86, gap=26, color=CHALK, seed=0):
    """Tally marks scratched into the rock: groups of four strokes + a slash."""
    out, k = [], 0
    for g in range(math.ceil(n / 5)):
        gx = x + g * (gap * 5.6)
        m = min(5, n - g * 5)
        for i in range(min(4, m)):
            j = ((seed + k) * 37 % 9 - 4) * 1.5
            out.append({"type": "marker", "kind": "line", "points": [[gx + i * gap + j, y - h / 2], [gx + i * gap - j * 0.6, y + h / 2]],
                        "t0": t, "dur": 0.01, "color": color, "width": 6})
            k += 1
        if m == 5:
            out.append({"type": "marker", "kind": "line", "points": [[gx - 16, y + h * 0.28], [gx + 3 * gap + 18, y - h * 0.3]],
                        "t0": t, "dur": 0.01, "color": color, "width": 6})
    return out


def c_1(F, t):
    """Inside the cave: Kazbegi projected onto the rock by torchlight; the khinkali days scratched in the wall."""
    L = [F.full(ph(90), "C", (1.12, 1.12), focus="center",
                look={"name": "tritone", "shadow": "#070403", "mid": "#4a3020", "high": "#b48c66", "contrast": 1.2}),
         F.full(ph(36), "C", (1.0, 1.0), box=[430, 150, 1060, 795], focus="faces", look=OCHRE, blend="screen", opacity=0.92,
                feather=170)]
    L += [dict(x, post=True) for x in tally(1480, 900, 15, t, color="#d9cbb2")]
    L += [F.text("khinkali", 1585, 808, 0, 9999, 74, "caveat", "#d9cbb2", rot=-5, fade_out=0, post=True)]
    return L, [{"type": "torch", "amount": 0.82, "cx": 0.48, "cy": 0.46, "r": 0.62, "color": "#ffb066", "warmth": 0.3}]


def c_2(F, t):
    """The way out: the cave mouth opens onto the first full-colour daylight of the film."""
    L = [F.wall("#050403"),
         F.full(ph(182), "C", (1.0, 1.02), focus="center", box=[555, 0, 810, 1080], feather=70)]
    return L, [{"type": "torch", "amount": 0.35, "cx": 0.5, "cy": 0.55, "r": 0.7, "color": "#ffd6a0", "warmth": 0.08, "flicker": 0.3}]


DIRS = {
    "a": ("dir_a", "golden", {"grain": 0.01, "vignette": 0.18, "halation": 0.04, "flicker": 0.0, "weave": 0.0},
          [("a_1", a_1), ("a_2", a_2)]),
    "b": ("dir_b", "punchy", {"grain": 0.006, "vignette": 0.0, "halation": 0.0, "flicker": 0.0, "weave": 0.0},
          [("b_1", b_1), ("b_2", b_2)]),
    "c": ("dir_c", "punchy", {"grain": 0.016, "vignette": 0.3, "halation": 0.05, "flicker": 0.008, "weave": 0.2},
          [("c_1", c_1), ("c_2", c_2)]),
}

if __name__ == "__main__":
    for k in (sys.argv[1:] or DIRS):
        v, grade, finish, builds = DIRS[k]
        frames(film(v, grade, finish), builds)
