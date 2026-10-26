"""Trip through Georgia ("Yes, no offroad") -> out/georgia_edl.json
Run: python tools/studio.py build trip-through-georgia-9648   (then: studio.py preview trip-through-georgia-9648)

Tom and Sam's road trip, 12-23 Oct 2026, as a hand-kept road-trip journal: taped prints on kraft/paper,
handwritten place notes, a road atlas with a little rental car, speech bubbles in two languages.
Treatment: out/treatment.md (approved by Sam 2026-10-24).

Music: Mumford & Sons - The Cave, the whole song from its first strum. The MP3 is the music video's
audio: its first 40 s (spoken film intro) and last 30 s (outro ambience) are not the song and are left
out. No join. The last chord rings out, then the thank-you plays in silence.
Lyric word times: forced alignment on the vocal stem after re-fitting the LRC offset (+32.44 s).
The beat tracker counts the quiet stretches in half time (0.84 s beats): verse 1 / chorus 1 up to
song 89 s and the end of chorus 2 / verse 3 (song 149-178 s). Cuts there sit on the half-time beats or
on the 8th grid; the glitchy beats at song 88.6-90.3 s are avoided.
"""
import json, os, sys
sys.path.insert(0, os.environ.get("AM_TOOLS") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
os.environ.setdefault("AM_PROJECT", os.path.dirname(os.path.abspath(__file__)))
from am.common import CACHE, project, font as _font  # noqa: E402
from am.kit import Film, W  # noqa: E402

P = project()
SLUG = P["song"]["slug"]
SONG_IN, SONG_OUT, PRE = 40.12, 245.3, 0.8          # first strum at 40.2; the ring-out has faded by 245.3
OFF = SONG_IN - PRE                                 # film = song - OFF
VERSION = os.environ.get("AM_VERSION") or "georgia"

F = Film(VERSION, "Trip through Georgia", f"music/{P['song']['file']}", SLUG, [(SONG_IN, SONG_OUT, PRE)],
         grade={"preset": "golden", "overrides": {}},
         finish={"grain": 0.012, "vignette": 0.26, "halation": 0.06, "flicker": 0.005, "weave": 0.3})
INK, RED, RED_DK, KRAFT, CREAM = F.INK, F.RED, F.RED_DK, F.KRAFT, F.CREAM
DARK = "#171512"
bar, beat, cue = F.bar, F.beat, F.cue
SAM, TOM = F.person("Sam"), F.person("Tom")


def s(word, song_t):
    """Aligned sung onset of a word, given its song time (from the song map)."""
    return F.sung(word, song_t - OFF)


def at(word, song_t):
    """The 8th at or just before a sung word: where a lyric caption (or a lyric cut) lands."""
    return cue(s(word, song_t))


# ------------------------------------------------------------------ photos (contact-sheet number -> file)
PH = {1: "ps001_bbe56000", 2: "ps001_e86439a6", 4: "ps005_0374c5d4", 8: "ps005_25219215", 15: "ps005_8a56c134",
      17: "ps005_960715df", 21: "ps005_ad25b53b", 30: "ps005_fc8cc08e", 31: "ps006_833105ff", 32: "ps006_af8b5c63",
      33: "ps006_b3306993", 34: "ps007_5b3f62e9", 35: "ps007_63dedbd7", 36: "ps007_6cf21eab", 37: "ps007_9962b9eb",
      39: "ps008_639a1d36", 40: "ps008_b82b7b9e", 41: "ps008_b8fcae4c", 42: "ps008_cb4e658e", 43: "ps008_d08ffc54",
      44: "ps008_f47de3a7", 45: "ps009_a0c3bcb4", 46: "ps010_02aacdc6", 47: "ps010_0c59d8dc", 48: "ps010_3a0b2a34",
      50: "ps010_3bf53961", 52: "ps010_9541d80f", 53: "ps010_a59c526e", 55: "ps011_1b2bbf7f", 57: "ps011_eebf83ba",
      59: "ps012_11fd3879", 60: "ps012_25749013", 64: "ps012_a74efc20", 65: "ps012_d0ee6ebf", 66: "ps012_f2baba40",
      67: "ps012_f365f4e2", 72: "ps013_566fc4a2", 73: "ps013_6a4fe9fe", 74: "ps013_76698fd2", 75: "ps013_97334adf",
      76: "ps013_b14d20f2", 78: "ps014_0329b524", 79: "ps014_1070d09a", 80: "ps014_1077251c", 82: "ps014_424d9ffd",
      83: "ps014_4b252d31", 84: "ps014_61725de4", 85: "ps014_769c9e93", 89: "ps014_ffcafb10", 91: "ps015_53001b21",
      92: "ps015_68543805", 94: "ps015_7cb69298", 103: "ps016_b2ef88db", 104: "ps016_b84d2cab", 107: "ps016_d1f6b1ff",
      109: "ps016_fc9b221b", 118: "ps017_de2f28f9", 128: "ps020_1bd83b7e", 134: "ps020_5dea4ec9", 143: "ps020_86efc188",
      149: "ps020_d3bb59b3", 157: "ps021_450fb940", 163: "ps022_0e6e14ab", 164: "ps022_3d49272f", 167: "ps022_7e6e127e",
      170: "ps023_107aa189", 172: "ps023_281a0117", 182: "ps023_f46e6921", 185: "ps024_97c2da12", 188: "ps024_e10c48ab",
      192: "ps026_70ff1fa9", 194: "ps026_79d27472", 195: "ps026_81c37dd8", 196: "ps026_b34f2853", 197: "ps026_cd3fae9a",
      199: "ps026_edc73161"}
VID = {"waterfall": "ps016_4269dbb6", "priests": "ps017_682071c1", "dog": "ps018_b49c4504"}
_files = sorted(os.listdir(os.path.join(os.environ["AM_PROJECT"], "photos")))


def ph(n):
    pre = PH[n]
    hits = [f for f in F.META if f.startswith(pre)]
    assert len(hits) == 1, (n, hits)
    return hits[0]


def vid(k):
    return next(f for f in _files if f.startswith(VID[k]))


def face_uv(n, i=0):
    """Centre (u, v) of face i in photo n, normalised to the photo."""
    x, y, w, h = F.META[ph(n)]["faces"][i]["box"]
    return x + w / 2, y + h / 2


# ------------------------------------------------------------------ layout helpers
def pr(n, where, cx, cy, fit, rot, t_land, **kw):
    kw.setdefault("tapes", "light")
    kw.setdefault("zoom", (1.0, 1.0))
    kw.setdefault("sfx", False)                     # one soft drop per screen (two() / explicit), not per print
    return F.pr(ph(n), where, cx, cy, fit, rot, t_land, **kw)


def two(a, b, where, ta, tb, rots=(-3, 3), wall=None, fit=(600, 820), fit_b=None, **kw):
    """Two prints side by side (house style: portraits whole, two per screen), the second landing on its own beat."""
    lay = [wall or F.wall(KRAFT, True)]
    lay += pr(a, where, 520, 556, fit, rots[0], ta, **kw)
    lay += pr(b, where, 1400, 540, fit_b or fit, rots[1], tb, **kw)
    F.sfx("drop", ta, db=-24)
    return lay


def full(n, where, zoom=(1.0, 1.07), focus="faces", drift=None, **kw):
    return F.full(ph(n), where, zoom, focus, drift, **kw)


def vprint(k, where, cx, cy, h, rot, t_land, start, aspect=9 / 16, **kw):
    """A clip as a bordered print (portrait phone video), landing like the photo prints."""
    w = h * aspect
    L = {"type": "video", "src": F.use(vid(k), where), "start": start, "box": [cx - w / 2, cy - h / 2, w, h],
         "border": {"color": "#fbfaf4", "px": 16}, "shadow": True, "rot": rot,
         "enter": {"t": round(t_land - 0.02, 4), "dur": 0.12, "type": "thump"}}   # like F.pr: opaque on the cut frame
    L.update(kw)
    return L


def bubble(text, x, y, t0, t1, size=64, follow=None, tail=None, seed=0, **kw):
    L = {"type": "bubble", "text": text, "x": x, "y": y, "t0": round(t0, 4), "t1": round(t1, 4), "size": size, "seed": seed}
    if follow:
        L["follow"] = follow
    if tail:
        L["tail"] = list(tail)
    L.update(kw)
    return L


def arrow(x0, y0, x1, y1, t0, seed=1, bend=0.15, color=RED, width=9):
    return {"type": "marker", "kind": "arrow", "x0": round(x0), "y0": round(y0), "x1": round(x1), "y1": round(y1),
            "t0": round(t0, 4), "dur": 0.25, "color": color, "width": width, "seed": seed, "bend": bend}


def place(text, x, y, t0, t1, seed, size=66, rot=-3, **kw):
    """Handwritten place/date note on a taped paper scrap."""
    return F.note(text, x, y, t0, t1, size, seed=seed, rot=rot, anim="pop", **kw)


FLASH = {"in": {"type": "flash", "dur": 0.18, "amount": 0.8}}
CUT, WHIP, DISS = F.tr("cut"), F.tr("whip"), F.tr("dissolve")

# ================================================================== INTRO (first strum -> bar 2)
T0 = F.b(40.22 - OFF)                              # the first strum (a pickup before bar 0)
F.shot(0.0, bar(2), [F.wall(CREAM, True),
                     F.text("Trip through Georgia", W / 2, 455, T0, bar(2), 128, "playfair", INK, anim="fade", dur=0.8),
                     {"type": "flag", "code": "GE", "x": W / 2, "y": 250, "w": 150, "t": bar(0), "rot": -5, "seed": 2},
                     F.text("Tom & Sam  ·  October 2026", W / 2, 620, bar(1), bar(2), 64, "caveat", RED, anim="write", dur=0.6)],
       sync="intro: blank paper, the title fades in on the first strum, Georgian flag on bar 0, Tom & Sam on bar 1",
       **{"in": {"type": "dip_black", "dur": 0.6, "align": "start"}})
F.sfx("drop", bar(0), db=-24)

# ================================================================== VERSE 1: TBILISI + THE FOOD (half-time bars, 3.4 s)
t_sun = at("the", 50.16)
t_away = at("away", 53.59)
t_and = at("and", 55.28)
F.shot(bar(2), t_sun, [full(17, "tbilisi: the valley", (1.0, 1.06)),
                       place("Tbilisi  ·  12–13 Oct", 1480, 150, bar(2), t_sun, seed=1)],
       sync="'empty in the VALLEY': Tbilisi rooftops on the downbeat, chapter note", **DISS)
F.shot(t_sun, t_away, [full(30, "tbilisi: the sun", (1.08, 1.0), drift=((0, 0.04), (0, -0.04)))],
       sync="'The sun, it rises slowly': sunny Tbilisi from the hike (cut on 'The')", **CUT)
F.shot(t_away, t_and, [full(21, "chronicles", (1.0, 1.08))],
       sync="'Away from all the fears': the Chronicles of Georgia", **CUT)
L = [F.wall(CREAM, True)] + pr(15, "chronicles: the two of us", 960, 520, (1240, 860), -2, t_and)
L += [F.note("Thx Keti for the tour!", 1420, 935, t_and, bar(5), 68, seed=3, rot=-3, anim="write", dur=0.4)]
F.shot(t_and, bar(5), L, sync="'And all the faults you've left behind': Tom & Sam on the Chronicles stairs + their note", **CUT)
t_harv = at("the", 60.33)
F.shot(bar(5), t_harv, [F.wall(DARK)] + pr(8, "sameba at night", 960, 540, (700, 940), 2, bar(5), tapes="dark", zoom=(1.0, 1.07)),
       sync="bar 5: Sameba lit gold at night", **CUT)

# the food run
t_no, t_for = at("no", 61.20), at("for", 62.02)
NF_X, NF_Y, NF_S = 1390, 470, 150
x_l = NF_X - _font("caveat", NF_S).getlength("no food") / 2
x_r = x_l + _font("caveat", NF_S).getlength("no")
L = [F.wall(KRAFT, True)] + pr(1, "food: khachapuri", 640, 545, (620, 900), -3, t_harv, zoom=(1.07, 1.0))
L += [F.text("no food", NF_X, NF_Y, t_no, at("you", 63.76), NF_S, "caveat", INK, anim="write", dur=0.35),
      {"type": "marker", "kind": "line", "points": [[x_l - 14, NF_Y + 14], [x_r + 14, NF_Y - 12]], "t0": t_for, "dur": 0.16,
       "color": RED, "width": 12}]
F.shot(t_harv, at("you", 63.76), L, sync="'The harvest left NO FOOD for you to eat': 'no food' on 'no', 'no' crossed out on 'for'", **CUT)
t_meat = at("meat-eater", 64.78)
fx, fy = F.on_print(640, 545, ph(45), (620, 900), 3, *face_uv(45))
L = [F.wall(CREAM, True)] + pr(45, "food: the meat platter", 640, 545, (620, 900), 3, at("you", 63.76))
L += [F.text("meat-eater", 1400, 330, t_meat, at("but", 67.13), 120, "marker", RED, anim="pop", dur=0.14, rot=-5),
      arrow(1230, 380, fx + 60, fy - 40, t_meat + 0.05, seed=3)]
F.shot(at("you", 63.76), at("but", 67.13), L, sync="'You cannibal, you MEAT-EATER': the skewer platter, arrow at Sam", **CUT)
t_but1, t_I = at("but", 67.13), at("I", 68.84)
L = two(32, 4, "food: khinkali", t_but1, t_I, wall=F.wall(KRAFT, True), fit_b=(760, 600))
L += [F.note("khinkali (again)", 960, 110, t_but1, at("defeat", 71.14), 70, seed=5, rot=-2, anim="pop")]
F.shot(t_but1, at("defeat", 71.14), L, sync="'But I have SEEN THE SAME': khinkali (again), the meat plate lands on 'I know'", **CUT)
t_def = at("defeat", 71.14)
L = [F.wall(DARK)] + pr(2, "food coma", 700, 545, (640, 920), -2, t_def, tapes="dark")
L += [F.note("defeated.", 1420, 540, t_def, bar(10), 96, seed=7, rot=-4, anim="pop")]
F.shot(t_def, bar(10), L, sync="'in your DEFEAT': Sam asleep in the car, 'defeated.'", **CUT)

# ================================================================== CHORUS 1: THE RENTAL CAR + THE ROAD NORTH
CONTRACT = "RENTAL AGREEMENT\n\nRule 1:  NO OFFROAD."
cw = F.text_w(CONTRACT, "elite", 96)               # typed text is anchored at its left edge: centre it by hand
L = [F.wall(KRAFT, True),
     F.text(CONTRACT, W / 2 - cw / 2 + 34, 470, bar(10), bar(11), 96, "elite", INK, anim="type", dur=0.45,
            panel={"seed": 21, "tape": True, "pady": 50}, rot=-1.5, line_gap=1.1),
     F.text("x Tom        x Sam", W / 2 + 60, 790, beat(10, 1), bar(11), 80, "caveat", INK, anim="write", dur=0.4, rot=-2)]
F.shot(bar(10), bar(11), L, sync="'But I will hold on hope': the rental contract types out; signatures on beat 3", **FLASH)
F.sfx("shutter", bar(10) - 0.01, db=-20)
fx, fy = F.on_print(660, 545, ph(109), (640, 900), -2, *face_uv(109))
L = [F.wall(CREAM, True)] + pr(109, "the car: yes no offroad", 660, 545, (640, 900), -2, bar(11))
L += [bubble("Yes, no offroad.", 1390, 330, beat(11, 1), bar(12), 72, tail=(fx + 120, fy - 40), seed=3)]
F.shot(bar(11), bar(12), L, sync="'And I won't let you choke': Sam at the wheel, 'Yes, no offroad.' on beat 2", **CUT)
tx, ty = F.on_print(700, 545, ph(72), (640, 900), 2, 0.5, 0.5)
L = [F.wall(KRAFT, True)] + pr(72, "the roads", 700, 545, (640, 900), 2, bar(12))
L += [F.note("the main road.", 1440, 300, beat(12, 1), bar(13), 84, seed=9, rot=-4, anim="pop"),
      arrow(1300, 380, tx + 110, ty - 60, beat(12, 1) + 0.1, seed=4)]
F.shot(bar(12), bar(13), L, sync="'On the noose around your neck': the tyre in the pothole, 'the main road.'", **WHIP)
L = two(31, 33, "gamarjoba lunch stop", bar(13), beat(13, 1), wall=F.wall(CREAM, True))
fx, fy = F.on_print(520, 556, ph(31), (600, 820), -3, *face_uv(31, 0))
L += [bubble("Gamarjoba!", 900, 175, beat(13, 1), bar(14), 70, tail=(fx + 40, fy - 70), seed=5)]
F.shot(bar(13), bar(14), L, sync="'find strength in pain': the Gamarjoba lunch stop, cats; bubble on beat 2", **CUT)
L = [F.wall(CREAM, True), F.photo(ph(34), "gudauri mural", (1.0, 1.0), [0.5, 0.5], drift=((-0.06, 0), (0.06, 0)),
                                   box=[60, 300, 1800, 593], border={"color": "#fbfaf4", "px": 14}, shadow=True, rot=-1.5,
                                   enter={"t": bar(14) - 0.02, "dur": 0.12, "type": "thump"})]
F.shot(bar(14), bar(16), L, sync="'And I will change my ways': the Gudauri friendship mural as a wide strip (2 bars)", **WHIP)
F.sfx("drop", bar(14), db=-22)
L = [F.wall(KRAFT, True)] + pr(36, "names: selfie", 960, 545, (1300, 900), -1.5, bar(16))
t_my, t_name = at("my", 92.30), at("name", 92.76)
L += [F.circle(L, ph(36), TOM, t_my), F.circle(L, ph(36), SAM, t_name, seed=3)]
tx, ty = F.on_print(960, 545, ph(36), (1300, 900), -1.5, *face_uv(36, 1))
sx, sy = F.on_print(960, 545, ph(36), (1300, 900), -1.5, *face_uv(36, 0))
L += [F.text("Tom", tx - 20, ty - 190, t_my, bar(18), 96, "marker", RED, anim="pop", dur=0.14, rot=-6,
             panel={"seed": 11, "tape": False, "pady": 10}),
      F.text("Sam", sx + 20, sy - 190, t_name, bar(18), 96, "marker", RED, anim="pop", dur=0.14, rot=5,
             panel={"seed": 12, "tape": False, "pady": 10})]
F.shot(bar(16), bar(18), L, sync="'I'll know MY NAME': the best selfie, Tom circled on 'my', Sam on 'name'", **CUT)
F.shot(bar(18), bar(19), [full(35, "georgian flag", (1.05, 1.0))], sync="'called again' ring: the flag over the valley", **CUT)

# ================================================================== INTERLUDE: THE KICK COMES IN -> INTO THE CAUCASUS
TRIP = F.trip()
steps = [st for st in TRIP["steps"] if not st["skip"] and st.get("lon") is not None]
MAP_LABELS = {st["id"]: "" for st in steps}                     # only the big names (the rest would pile up)
MAP_LABELS.update({"275551750": "Tbilisi", "275689441": "Kazbegi", "276151132": "Gori", "276541862": "Kutaisi",
                   "276854947": "Batumi", "277058084": "Vardzia", "277287847": "Borjomi"})
m0 = bar(19)
pins1 = [m0] * 5 + [beat(19, 2), beat(20, 0), beat(20, 2), beat(20, 3)]       # Tbilisi x5, lunch, Gudauri, Gergeti, Stepantsminda
leg1 = F.map_bounds([[st["lon"], st["lat"]] for st in steps[:9]], pad=0.5, min_span=1.3)     # zoomed on the first leg
F.shot(m0, bar(21), [F.route_map(TRIP, pins1, labels=MAP_LABELS, car="🚗", zoom=(1.0, 1.05), bounds=leg1, label_size=62)],
       sync="interlude (kick drum in): route map 1, the car drives Tbilisi -> Kazbegi on the beats", **FLASH)
F.sfx("shutter", m0 - 0.01, db=-19)
for tp in pins1[5:]:
    F.sfx("drop", tp, db=-25)
F.shot(bar(21), bar(22), [full(37, "gudauri canyon", (1.0, 1.08), pulse=F.PUNCH)], sync="bar 21: Gudauri canyon, pulse on the kick", **CUT)
L = two(43, 40, "gergeti", bar(22), bar(23), wall=F.wall(CREAM, True), fit=(620, 860))
L += [place("Kazbegi  ·  14–15 Oct", 960, 100, bar(22), bar(24), seed=13)]
F.shot(bar(22), bar(24), L, sync="bars 22-23: Gergeti Trinity under Kazbek + the church on its hill, chapter note", **CUT)
F.shot(bar(24), bar(25), [full(52, "dariali monastery", (1.0, 1.08), pulse=F.PUNCH)], sync="bar 24: Dariali monastery", **CUT)
t_cause = cue(s("I", 109.80) - 0.2)                 # "'Cause" did not align; it sits just before "I"
F.shot(bar(25), t_cause, two(46, 47, "dariali", bar(25), beat(25, 2), wall=F.wall(KRAFT, True)),
       sync="bar 25: the pink church + the icon shrine", **CUT)

# ================================================================== VERSE 2: KAZBEGI
t_you2 = at("you", 113.00)
L = [F.wall(CREAM, True)] + pr(39, "fill my time", 760, 545, (640, 900), -2, t_cause)
F.shot(t_cause, t_you2, L, sync="''Cause I have other things to fill my time': Sam stretched out on the rocks", **CUT)
t_yours, t_mine = at("yours", 113.82), at("mine", 115.53)
L = [F.wall(KRAFT, True)] + pr(64, "stone heads: yours", 600, 520, (860, 700), -3, t_you2)
L += pr(67, "stone heads: mine", 1420, 545, (560, 800), 3, t_you2 + 0.0, sfx=False)
L += [F.text("yours", 600, 960, t_yours, bar(31), 96, "marker", RED, anim="pop", dur=0.14, rot=-4, panel={"seed": 51, "tape": False, "pady": 10}),
      F.text("mine", 1420, 1000, t_mine, bar(31), 96, "marker", RED, anim="pop", dur=0.14, rot=4, panel={"seed": 52, "tape": False, "pady": 10})]
F.shot(t_you2, bar(31), L, sync="'You take what is YOURS and I'll take MINE': Tom's stone head / Sam's stone head", **CUT)
t_ref = at("refresh", 118.47)
L = two(41, 42, "nap time", bar(31), beat(31, 1), wall=F.wall(CREAM, True), zoom=(1.0, 1.06))
L += [F.note("refreshing.", 960, 105, t_ref, bar(33), 76, seed=15, rot=-2, anim="pop")]
F.shot(bar(31), bar(33), L, sync="'Which will REFRESH my broken mind': two sleeping stray dogs", **CUT)
t_so = at("so", 122.88)
F.shot(bar(33), t_so, [full(48, "dariali churches", (1.06, 1.0))], sync="bar 33: Dariali churches under the mountain", **CUT)
t_post = at("post", 123.90)
px_, py_ = F.on_print(560, 556, ph(57), (600, 820), -3, 0.16, 0.62)
L = two(57, 55, "the border", t_so, beat(34, 1), wall=F.wall(CREAM, True), fit=(600, 820), fit_b=(760, 600))
L += [F.note("The border", 1400, 115, t_so, at("I", 126.21), 74, seed=17, rot=-3, anim="pop"),
      {"type": "flag", "code": "RU", "x": 1620, "y": 120, "w": 96, "t": t_so + 0.1, "rot": 6, "seed": 3},
      F.text("post", 190, 470, t_post, at("I", 126.21), 80, "marker", RED, anim="pop", dur=0.14, rot=-8, panel={"seed": 53, "tape": False, "pady": 10}),
      arrow(190, 520, px_ + 10, py_ - 20, t_post + 0.05, seed=7, bend=0.2)]
F.shot(t_so, at("I", 126.21), L, sync="'So tie me to a POST': Sam's stop hand at the border-zone post, Tom; arrow to the post", **CUT)
t_know = at("I", 129.68)
F.shot(at("I", 126.21), t_know, two(53, 50, "dariali icons", at("I", 126.21), beat(36, 3), wall=F.wall(DARK), tapes="dark", zoom=(1.0, 1.06)),
       sync="'widows and orphans through my tears': the painted dome + an icon", **CUT)
t_and2 = at("and", 131.97)
F.shot(t_know, t_and2, [F.wall(KRAFT, True)] + pr(60, "orange valley", 960, 540, (700, 940), 2, t_know, zoom=(1.0, 1.07)),
       sync="'I know my call despite my faults': the orange valley", **CUT)
F.shot(t_and2, bar(41), [F.wall(CREAM, True)] + pr(66, "growing fears", 960, 540, (700, 940), -3, t_and2),
       sync="'And despite my growing fears': Sam leaping across the river", **CUT)
F.shot(bar(41), bar(43), two(59, 65, "orange hike", bar(41), bar(42), wall=F.wall(KRAFT, True)),
       sync="bars 41-42: the orange larches + the horse", **CUT)

# ================================================================== CHORUS 2: GORI + UPLISTSIKHE
L = two(74, 76, "stalin top g", bar(43), beat(43, 2), wall=F.wall(DARK), tapes="dark")
L += [place("Gori  ·  Stalin top G ⚒️", 960, 100, bar(43), bar(45), seed=19)]
F.shot(bar(43), bar(45), L, sync="'But I will hold on hope': Sam thumbs-up + Tom hand-on-heart under Stalin, Sam's label", **FLASH)
F.sfx("shutter", bar(43) - 0.01, db=-20)
F.shot(bar(45), bar(46), [full(73, "stalin's carriage", (1.0, 1.08))], sync="bar 45: Stalin's railway carriage", **CUT)
F.shot(bar(46), bar(47), [F.wall(DARK)] + pr(75, "stalin statue", 960, 540, (640, 920), 2, bar(46), tapes="dark"),
       sync="bar 46: the statue", **CUT)
F.shot(bar(47), bar(49), [full(82, "uplistsikhe", (1.0, 1.08)), place("Crazy city  ·  Uplistsikhe", 1420, 140, bar(47), bar(49), seed=23)],
       sync="bars 47-48: the cave town, Sam's label", **WHIP)
F.shot(bar(49), bar(50), two(83, 79, "uplistsikhe: us", bar(49), beat(49, 2), wall=F.wall(CREAM, True)),
       sync="'find strength in pain': Tom + Sam on the rocks", **CUT)
F.shot(bar(50), beat(50, 2), [full(84, "uplistsikhe plain", (1.08, 1.0))], sync="bar 50 (half time): the river plain", **CUT)
F.shot(beat(50, 2), bar(51), [F.wall(DARK)] + pr(78, "round window", 960, 540, (640, 920), -2, beat(50, 2), tapes="dark"),
       sync="half bar: the round window", **CUT)
F.shot(bar(51), bar(52), [full(85, "tom on the plateau", (1.0, 1.08))], sync="'I'll know my name': Tom on the rock plateau", **CUT)
F.shot(bar(52), bar(53), [full(89, "cliff caves", (1.06, 1.0))], sync="'called again': the cliff caves", **CUT)
t_so3 = at("so", 161.59)
F.shot(bar(53), t_so3, [F.wall(DARK)] + pr(80, "the tunnel down", 960, 540, (640, 920), 2, bar(53), tapes="dark"),
       sync="the gap before verse 3: the rock tunnel going down", **CUT)

# ================================================================== VERSE 3: CAVES, CANYONS AND A CHOIR
t_cave, t_and3 = at("cave", 162.64), at("and", 164.98)
L = two(91, 94, "prometheus cave", t_so3, t_cave, wall=F.wall(DARK), tapes="dark")
L += [place("Prometheus cave  ·  17 Oct", 960, 96, t_so3, t_and3, seed=25)]
F.shot(t_so3, t_and3, L, sync="'So come out of your CAVE': the stalactite curtain, Tom's cave selfie lands on 'cave'", **DISS)
t_up, t_down = at("upside", 166.94), at("down", 167.73)
L = [F.wall(DARK)] + pr(92, "upside down", 960, 540, (1300, 880), 0, t_and3, tapes=None)
L[1]["turn"] = {"t": t_up, "dur": round(t_down - t_up, 3), "deg": 180}
t_und = at("understand", 168.62)
F.shot(t_and3, t_und, L, sync="'and see the world hanging UPSIDE DOWN': the stalactite print turns over from 'up-' to 'down'", **CUT)
F.sfx("charge", t_up, db=-22)
t_when = at("when", 170.26)
F.shot(t_und, t_when, [F.wall(CREAM, True)] + pr(107, "okatse walkway", 960, 540, (680, 940), -2, t_und, zoom=(1.07, 1.0)),
       sync="'understand dependence': the canyon walkway", **CUT)
t_wf = beat(57, 1)
F.shot(t_when, t_wf, two(103, 104, "kinchkha", t_when, beat(56, 2), wall=F.wall(KRAFT, True))
       + [place("Khoni  ·  17 Oct", 960, 96, t_when, t_wf, seed=27)],
       sync="'When you know the maker's land': the falls + Tom laughing on the rock", **CUT)
t_make, t_and4 = at("make", 176.12), at("and", 179.23)
L = [F.wall(DARK), vprint("waterfall", "siren's call", 820, 540, 960, -2, t_wf, start=8.6)]
L += [bubble("AAAAH!", 1380, 300, t_make, t_and4, 110, tail=(1000, 330), seed=7, font="marker")]
F.shot(t_wf, t_and4, L, sync="'So make your SIREN'S CALL': Tom under the icy waterfall (clip 8.6 s ->), 'AAAAH!' on 'make'", **CUT)
F.sfx("drop", t_wf, db=-22)
t_I5 = at("I", 182.84)
F.shot(t_and4, t_I5, [{"type": "video", "src": F.use(vid("priests"), "sing all you want"), "start": 9.0, "zoom": [1.05, 1.12],
                       "focus": [0.55, 0.5]},
                      place("Kutaisi  ·  18 Oct", 1500, 150, t_and4, t_I5, seed=29)],
       sync="'And SING all you want': the priests singing (clip 9.0 s ->)", **WHIP)
t_hear, t_cause2 = at("hear", 183.70), at("cause", 185.98)
L = [F.wall(CREAM, True)] + pr(118, "the market", 760, 545, (640, 900), -2, t_I5)
L += [bubble("ბლა ბლა ბლა?", 1400, 290, t_I5, t_cause2, 70, tail=(980, 420), seed=9, font="georgian"),
      bubble("Madloba!", 1430, 720, t_hear, t_cause2, 84, tail=(1600, 1080), seed=11)]
F.shot(t_I5, t_cause2, L, sync="'I will NOT HEAR what you have to say': the market - Georgian bubble, ours: 'Madloba!' on 'hear'", **CUT)
t_and5 = at("and", 189.40)
L = [F.wall(KRAFT, True), vprint("dog", "freedom", 700, 540, 960, 2, t_cause2, start=12.2),
     place("Tskaltubo  ·  18 Oct", 1400, 180, t_cause2, t_and5, seed=31)]
F.shot(t_cause2, t_and5, L, sync="''Cause I need FREEDOM now': Tom and the stray dog chasing him (clip 12.2 s ->)", **CUT)
t_to = at("to", 192.87)
L = [F.wall(CREAM, True)] + pr(134, "no entry", 700, 545, (640, 900), 2, t_and5)
L += [F.note("Yes, no entry.", 1420, 480, bar(65), t_to, 88, seed=33,
             rot=-4, anim="pop")]
F.shot(t_and5, t_to, L, sync="'And I need to know how': the NO ENTRY tape -> 'Yes, no entry.' (callback)", **CUT)
F.shot(t_to, bar(69), [full(143, "live my life", (1.0, 1.08))], sync="'To LIVE MY LIFE as it's meant to be': Sam in the sanatorium window", **DISS)

# ================================================================== BRASS CLIMAX: one photo per bar
BR = dict(fx=[F.CYM])
F.shot(bar(69), bar(70), [full(128, "rotunda tree", (1.0, 1.1), pulse=F.PUNCH)], sync="brass bar 69: the tree inside the rotunda", **FLASH, **BR)
F.sfx("shutter", bar(69) - 0.01, db=-19)
F.shot(bar(70), bar(71), [F.wall(DARK)] + pr(149, "tom broken stairs", 960, 540, (640, 920), -2, bar(70), tapes="dark"),
       sync="bar 70: Tom on the broken stairs", **CUT, **BR)
F.shot(bar(71), bar(73), [full(157, "upside-down house", (1.0, 1.07)), place("Batumi: still upside down", 1400, 150, bar(71), bar(73), seed=35)],
       sync="bars 71-72: Batumi's upside-down house - callback", **WHIP, **BR)
L = two(164, 163, "observatory", bar(73), bar(74), wall=F.wall(DARK), tapes="dark")
L += [place("Abastumani observatory", 960, 96, bar(73), bar(75), seed=37)]
F.shot(bar(73), bar(75), L, sync="bars 73-74: the moon through the telescope, Sam at the eyepiece", **CUT, **BR)
F.shot(bar(75), bar(76), [F.wall(DARK)] + pr(167, "tom telescope", 960, 540, (640, 920), 2, bar(75), tapes="dark"),
       sync="bar 75: Tom under the big telescope", **CUT, **BR)
F.shot(bar(76), bar(78), [full(172, "vardzia", (1.0, 1.08)), place("Vardzia  ·  20 Oct", 1480, 150, bar(76), bar(78), seed=39)],
       sync="bars 76-77: Vardzia cave city", **WHIP, **BR)
F.shot(bar(78), bar(79), two(182, 170, "vardzia arches", bar(78), beat(78, 2), wall=F.wall(KRAFT, True)),
       sync="bar 78: the arch over the cave city + Sam in the bell tower", **CUT, **BR)
F.shot(bar(79), bar(80), [full(185, "borjomi", (1.06, 1.0)), place("Borjomi", 1560, 150, bar(79), bar(80), seed=41)],
       sync="bar 79: Borjomi hike", **CUT, **BR)
F.shot(bar(80), bar(81), [F.wall(CREAM, True)] + pr(188, "big chill", 960, 540, (640, 920), -2, bar(80))
       + [place("Big chill", 1500, 200, bar(80), bar(81), seed=43)], sync="bar 80: the spa day", **CUT, **BR)
L = two(195, 192, "sword mountain", bar(81), beat(81, 2), wall=F.wall(KRAFT, True))
L += [place("Sword mountain", 960, 96, bar(81), bar(82), seed=45)]
F.shot(bar(81), bar(82), L, sync="bar 81: Didgori, Tom on the steps + the path to the swords", **CUT, **BR)

# ================================================================== FINAL CHORUS: THE WHOLE LOOP, THE NUMBERS, THE NAMES
groups = [[0] * 5, [1], [1.5], [2], [2], [2.5], [2.5], [3], [4], [4.5], [5.5], [6], [6.5], [7], [7], [7], [8.5], [9.5],
          [10.5], [11.5], [12], [13]]
beat_t = [beat(82, 0)] + [beat(82 + q // 4, q % 4) for q in range(1, 16)]


def bt(k):
    """Film time of beat k (fractional ok) counted from bar 82."""
    i = int(k)
    return beat_t[i] if k == i else round(beat_t[i] + (k - i) * (beat_t[i + 1] - beat_t[i]), 4)


pins2 = [bt(k) for g in groups for k in g]
assert len(pins2) == len(steps), (len(pins2), len(steps))
F.shot(bar(82), bar(86), [F.route_map(TRIP, pins2, labels=MAP_LABELS, car="🚗", zoom=(1.0, 1.04), label_size=54)],
       sync="final chorus: route map 2, the car drives the whole loop (all 26 stops on the beats)", **FLASH)
F.sfx("shutter", bar(82) - 0.01, db=-19)
for k in (1, 4, 6.5, 8.5, 10.5, 13):
    F.sfx("drop", bt(k), db=-25)
T = TRIP["trip"]
L = [F.wall(CREAM, True)]
for j, (val, lab) in enumerate([(T["days"], "days"), (1560, "km"), (len(steps), "stops")]):
    x = W / 2 + (j - 1) * 560
    tj = beat(86, j)
    L += [F.text("{n}", x, 380, tj, bar(89), 190, "anton", INK, anim="pop", dur=0.6, count=val),
          F.text(lab, x, 540, tj, bar(89), 64, "caveat", RED, anim="pop")]
    F.sfx("drop", tj, db=-23)
L += [F.text("khinkali: every day", W / 2, 720, bar(87), bar(89), 76, "caveat", INK, anim="write", dur=0.4, rot=-2),
      F.text("Georgian words known: 2", W / 2, 850, bar(87), bar(89), 76, "caveat", INK, anim="write", dur=0.4, rot=-2)]
F.shot(bar(86), bar(89), L, sync="'On the noose around your neck': stats count up, one per beat; two handwritten lines on bar 87", **CUT)
L = two(194, 196, "strength", bar(89), beat(89, 1), wall=F.wall(KRAFT, True))
L += [F.note("found it.", 960, 100, beat(89, 1), bar(91), 84, seed=47, rot=-3, anim="pop")]
F.shot(bar(89), bar(91), L, sync="'And I'll find STRENGTH in pain': Tom and Sam pulling the giant swords, 'found it.'", **CUT)
F.shot(bar(91), bar(92), [F.wall(DARK)] + pr(199, "two swords", 960, 540, (640, 920), 2, bar(91), tapes="dark", zoom=(1.0, 1.07)),
       sync="'And I will change my ways': two giant swords against the sky", **CUT)
L = [F.wall(KRAFT, True)] + pr(44, "names again", 960, 545, (1300, 900), 1.5, bar(92))
t_my2, t_name2 = at("my", 235.64), at("name", 236.10)
L += [F.circle(L, ph(44), TOM, t_my2, seed=5), F.circle(L, ph(44), SAM, t_name2, seed=6)]
tx, ty = F.on_print(960, 545, ph(44), (1300, 900), 1.5, *face_uv(44, 1))
sx, sy = F.on_print(960, 545, ph(44), (1300, 900), 1.5, *face_uv(44, 0))
LAST = F.b(240.272 - OFF)                         # the last played beat: the band stops on "again"
L += [F.text("Tom", tx - 40, ty - 245, t_my2, LAST, 96, "marker", RED, anim="pop", dur=0.14, rot=-6,
             panel={"seed": 13, "tape": False, "pady": 10}),
      F.text("Sam", sx + 40, sy - 245, t_name2, LAST, 96, "marker", RED, anim="pop", dur=0.14, rot=5,
             panel={"seed": 14, "tape": False, "pady": 10})]
F.shot(bar(92), LAST, L, sync="'I'll know MY NAME as it's called again': the Gergeti selfie, names tagged again (callback)", **CUT)
EP = F.near(F.song_end + 2 * F.beat_len)
F.shot(LAST, EP, [full(197, "the closer", (1.0, 1.1))], sync="the last chord rings out: Didgori, held", **DISS)
F.B.edl["audio"]["fade_out"] = [round(F.song_end - 1.6, 3), round(F.song_end, 3)]

# ================================================================== SILENCE: MADLOBA
BL = 4 * F.beat_len
F.B.edl["meta"]["duration"] = round(EP + 4.5 * BL, 3)
F.duration = F.B.edl["meta"]["duration"]
ep = [F.wall("#efe8d8", True),
      F.text("Madloba!", W / 2, 400, F.near(EP + F.beat_len), F.duration, 190, "marker", RED, anim="pop", dur=0.2, rot=-3, fade_out=0.0),
      F.text("Thank you Georgia", W / 2, 610, F.near(EP + BL), F.duration, 92, "caveat", INK, anim="write", dur=0.9, fade_out=0.0),
      F.text("— Tom + Sam", 1380, 820, F.near(EP + 2 * BL), F.duration, 76, "caveat", INK, anim="write", dur=0.5, rot=-4, fade_out=0.0),
      {"type": "flag", "code": "GE", "x": 560, "y": 830, "w": 120, "t": F.near(EP + 2 * BL), "rot": -8, "seed": 4}]
F.shot(EP, F.duration, ep, sync="silence: Madloba!, then 'Thank you Georgia', signed", **{"in": {"type": "dip_black", "dur": 0.6}})
F.save()
