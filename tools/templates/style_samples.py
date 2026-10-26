"""Style samples for the studio's brief page: one representative frame per visual language of the stylebook.

  python tools/studio.py run _style-samples templates/style_samples.py

Renders on the public-domain photos in projects/_style-samples (CC0 / public-domain mark, from Openverse; the
licences are in its photos_meta.json) and writes app/static/styles/<key>.jpg + styles.json + CREDITS.md, which ship
with the app. Only needed again when a style is added or changed. Every frame is made with the real engine, so the
samples show what a film can actually look like.
"""
import json, os, subprocess, sys
sys.path.insert(0, os.environ.get("AM_TOOLS") or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import cv2  # noqa: E402
from am.common import CACHE  # noqa: E402
from am.kit import Film, W, H  # noqa: E402

PDIR = os.environ["AM_PROJECT"]
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(os.path.dirname(TOOLS), "app", "static", "styles")
SEG = 3.0


def bracket(x, y, w, h, c="#ffffff", k=46, th=5):
    """Camera-screen focus brackets (four corners) as thin rects."""
    out = []
    for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
        cx, cy = x + sx * w / 2, y + sy * h / 2
        out.append(Film.shape("rect", cx - sx * k / 2, cy, k, th, c))
        out.append(Film.shape("rect", cx, cy - sy * k / 2, th, k, c))
    return out


def ransom(word, cx, y, size, seed, F):
    """Ransom-note letters: each its own font, colour and paper block."""
    fonts = ["anton", "playfair", "marker", "elite", "bebas", "mono"]
    inks = [("#111111", "#f4f1ea"), ("#ffffff", "#e63946"), ("#111111", "#ffd23f"), ("#ffffff", "#1d3557"), ("#111111", "#ffffff")]
    out, x = [], cx - len(word) * size * 0.42
    for i, ch in enumerate(word):
        fg, bg = inks[(i * 7 + seed) % len(inks)]
        rot = ((i * 37 + seed * 11) % 17) - 8
        out.append(F.shape("rect", x, y, size * 0.78, size * 1.02, bg, rot=rot))
        out.append(F.text(ch, x, y, 0, 9999, size * 0.8, fonts[(i * 5 + seed) % len(fonts)], fg, rot=rot, fade_out=0))
        x += size * 0.84
    return out


# ---------------------------------------------------------------------------------------------------------- the styles
# each: name (the brief's chip value), line (what it is), fits (when it suits), grade, build(F, t) -> (layers, fx, still offset)
def s_scrapbook(F, t):
    L = [F.wall("#d9c7a5", True)]
    L += F.pr("a5b5c64a.jpg", "s", 690, 500, (980, 660), -4, t + 0.1, sfx=False)
    L += F.pr("4cec3e51.jpg", "s", 1450, 540, (560, 760), 5, t + 0.1, sfx=False)
    L += [{"type": "seven", "text": "'26 8 14", "x": 1040, "y": 790, "h": 34},
          F.note("the night we missed\nthe last train", 640, 950, t + 0.2, t + 9, 60, seed=3)]
    L += F.doodles([t + 0.3, t + 0.4], [(110, 940), (1800, 960)], "star", "#c8371f", 44)
    return L, None, 2.2


def s_vhs(F, t):
    L = [F.full("1ca339fd.jpg", "s", (1.04, 1.07)),
         {"type": "osd", "icon": "play", "text": "PLAY", "x": 90, "y": 92, "size": 46, "post": True},
         F.text("SP  0:14:22", 1830, 92, 0, 9999, 40, "mono", "#ffffff", anchor="rm", stroke=2, stroke_color="#000000", fade_out=0,
                post=True)]
    L += [dict(x, post=True) for x in F.vcr("[CROWD CHEERING]", t + 0.1, t + 9, y=975)]
    return L, [{"type": "vhs", "amount": 0.9}], 2.2


def s_kinetic(F, t):
    words = [{"w": w, "t": round(t + 0.1 + 0.15 * i, 3)} for i, w in enumerate(["WE'RE", "NOT", "LEAVING", "YET"])]
    L = [F.full("c0c2c54c.jpg", "s", (1.06, 1.08), look={"name": "bw", "contrast": 1.4}),
         F.shape("rect", 960, 540, 1920, 1080, "#000000", alpha=0.4),
         F.lyric_type(words, x=960, y=540, mode="stack", font="anton", size=200, maxw=1500, color="#ffffff", accent="#ffd23f",
                      line_gap=0.9)]
    return L, None, 2.4


def s_swiss(F, t):
    L = [F.wall("#f2f0eb"),
         F.full("09969a96.jpg", "s", (1.0, 1.0), box=[110, 110, 1040, 860], look={"name": "bleach", "amount": 0.6}),
         F.shape("rect", 1480, 150, 560, 10, "#e63312"),
         F.text("07", 1220, 330, 0, 9999, 300, "anton", "#e63312", anchor="lm", fade_out=0),
         F.text("Somewhere\nbetween\ncities", 1226, 640, 0, 9999, 88, "narrow", "#111111", anchor="lm", align="left",
                line_gap=0.95, fade_out=0),
         F.text("VIENNA   48.21°N 16.37°E", 1228, 880, 0, 9999, 28, "mono_regular", "#444444", anchor="lm", fade_out=0),
         F.text("06:12   DAY 07 / 14", 1228, 924, 0, 9999, 28, "mono_regular", "#444444", anchor="lm", fade_out=0)]
    return L, None, 2.2


def s_riso(F, t):
    L = [F.wall("#f2ede4", True),
         F.full("fa15413d.jpg", "s", (1.0, 1.0), box=[100, 130, 780, 520], rot=-5, edge="torn", seed=4, shadow=True),
         F.full("716b5435.jpg", "s", (1.0, 1.0), box=[830, 80, 420, 600], rot=4, edge="torn", seed=7, shadow=True),
         F.full("244218a4.jpg", "s", (1.0, 1.0), box=[1250, 300, 590, 420], rot=-3, edge="torn", seed=9, shadow=True),
         F.text("ISSUE No. 3", 560, 870, 0, 9999, 150, "anton", "#141414", rot=-3, fade_out=0),
         F.text("SUMMER\nSPECIAL", 1520, 880, 0, 9999, 92, "anton", "#141414", line_gap=0.88, rot=2, fade_out=0)]
    return L, [{"type": "look", "look": {"name": "riso", "ink1": "#ff48b0", "ink2": "#0078bf", "offset": 5}}], 2.2


def s_super8(F, t):
    L = [F.full("4170e1b4.jpg", "s", (1.08, 1.1), look={"name": "faded", "amount": 0.7}),
         F.text("la playa, agosto", 960, 975, 0, 9999, 48, "playfair_italic", "#fff3dc", shadow=4, fade_out=0)]
    return L, [{"type": "light_leak", "amount": 0.36, "seed": 3}], 2.2


def s_nouvelle(F, t):
    """Two shots: an iris closes on the photo (silent-film style); the still is caught mid-iris."""
    a = F.shot(t, t + 1.6, [F.full("c150cab8.jpg", "s", (1.0, 1.02), look={"name": "bw", "contrast": 1.45}),
                            F.text("— chapitre deux —", 840, 790, 0, 9999, 42, "playfair_italic", "#f4f1ea", shadow=4, fade_out=0)],
               sync="nouvelle a")
    F.shot(t + 1.6, t + SEG, [F.wall("#000000")], sync="nouvelle b", **{"in": {"type": "iris", "close": True, "dur": 1.2, "cx": 0.44}})
    return None, None, 1.6 - 0.34


def s_poster(F, t):
    L = [F.wall("#f3e9d2", True),
         F.shape("circle", 1270, 420, 680, color="#e85d2a"),
         F.full("3593cae5.jpg", "s", (1.0, 1.0), box=[170, 140, 700, 800], look={"name": "duotone", "dark": "#14213d", "light": "#f3e9d2"},
                blend="multiply"),
         F.shape("stripes", 1270, 900, 860, 110, "#14213d", n=4),
         F.text("THE ALPS\nBY ROAD", 1270, 430, 0, 9999, 150, "anton", "#14213d", line_gap=0.88, fade_out=0),
         F.text("GRAND TOUR  ·  VOL. II", 1270, 700, 0, 9999, 48, "bebas", "#14213d", fade_out=0)]
    return L, None, 2.2


def s_haze(F, t):
    L = [F.full("4ebd654b.jpg", "s", (1.04, 1.06), look={"name": "faded", "amount": 0.5}),
         F.full("eef24149.jpg", "s", (1.0, 1.0), box=[560, -120, 860, 1300], blend="screen", opacity=0.8, feather=300,
                look={"name": "faded", "amount": 0.6}),
         F.shape("rect", 960, 975, 1920, 150, "#1a1020", alpha=0.45),
         F.text("and the light stayed", 960, 968, 0, 9999, 50, "playfair_italic", "#fff6e8", shadow=4, fade_out=0)]
    return L, [{"type": "light_leak", "amount": 0.32, "seed": 11, "colors": ["#ff9a3c", "#ffd29a", "#ff6f91", "#ffe0b0"]}], 2.2


def s_club(F, t):
    L = [F.full("55a73433.jpg", "s", (1.15, 1.2)),
         F.text("ALL\nNIGHT", 960, 545, 0, 9999, 230, "anton", "#ffffff", line_gap=0.82, stroke=6, stroke_color="#000000",
                fade_out=0, post=True)]
    return L, [{"type": "kaleido", "n": 6, "spin": 0.3}, {"type": "look", "look": {"name": "thermal"}}], 2.2


def s_cyanotype(F, t):
    L = [F.wall("#f4f1ea", True)]
    L += F.pr("94b05022.jpg", "s", 720, 470, (900, 600), -2, t + 0.1, tapes=False, sfx=False, look={"name": "cyanotype"})
    L += F.pr("aea4b8a5.jpg", "s", 1430, 520, (520, 720), 3, t + 0.1, tapes=False, sfx=False, look={"name": "cyanotype"})
    L += [F.text("fig. 3 - the long shadows, 7 p.m.", 720, 880, 0, 9999, 36, "elite", "#1f2a44", fade_out=0)]
    return L, None, 2.2


def s_infrared(F, t):
    L = [F.full("de57e2d7.jpg", "s", (1.04, 1.06), look={"name": "infrared"}),
         F.text("a different planet, apparently", 100, 980, 0, 9999, 42, "inter", "#ffffff", anchor="lm", shadow=4, fade_out=0)]
    return L, None, 2.2


def s_y2k(F, t):
    L = [F.full("ba4d5fb4.jpg", "s", (1.02, 1.04), look={"name": "chrome"})]
    L += bracket(960, 400, 560, 420)
    L += [F.shape("rect", 960, 990, 1920, 180, "#000000", alpha=0.45)]
    L += [{"type": "seven", "text": "'03 7 21", "x": 1600, "y": 985, "h": 70, "opacity": 1.0},
          F.text("1/60   F2.8   ISO 400", 100, 985, 0, 9999, 32, "mono", "#ffffff", anchor="lm", shadow=3, fade_out=0),
          F.shape("rect", 1760, 92, 96, 44, "#ffffff"), F.shape("rect", 1760, 92, 84, 32, "#3a3a3a"),
          F.shape("rect", 1815, 92, 10, 20, "#ffffff")]
    L += [F.shape("rect", 1730 + 22 * k, 92, 16, 24, "#ffffff") for k in range(3)]
    return L, None, 2.2


def s_collage(F, t):
    L = [F.wall("#ece4d4", True),
         F.full("7437e7ae.jpg", "s", (1.0, 1.0), box=[60, 70, 660, 440], rot=-6, edge="torn", seed=2, shadow=True, look="xerox"),
         F.full("268df303.jpg", "s", (1.0, 1.0), box=[650, 50, 560, 420], rot=4, edge="torn", seed=5, shadow=True),
         F.full("2b10b02e.jpg", "s", (1.0, 1.0), box=[1200, 90, 660, 450], rot=-3, edge="torn", seed=8, shadow=True),
         F.full("59c7aea7.jpg", "s", (1.0, 1.0), box=[90, 560, 560, 400], rot=4, edge="torn", seed=3, shadow=True, look="bw"),
         F.full("4f51c65b.jpg", "s", (1.0, 1.0), box=[1280, 580, 560, 400], rot=5, edge="torn", seed=6, shadow=True)]
    L += ransom("BEST", 960, 640, 120, 1, F) + ransom("SUMMER", 960, 800, 120, 4, F)
    L += [{"type": "sticker", "text": "WOW!", "t": t + 0.1, "x": 1630, "y": 520, "size": 120, "color": "#e63946", "rot": 12,
           "font": "marker"}]
    return L, None, 2.2


def s_wes(F, t):
    L = [F.wall("#f4c7c3"),
         F.shape("rect", 960, 560, 700, 860, "#fdf0e6"),
         F.full("b8621f3b.jpg", "s", (1.0, 1.0), box=[675, 175, 570, 760], look={"name": "faded", "amount": 0.6}),
         F.text("PART III", 960, 92, 0, 9999, 70, "bebas", "#9b2335", fade_out=0),
         F.shape("rect", 700, 92, 260, 4, "#9b2335"), F.shape("rect", 1220, 92, 260, 4, "#9b2335"),
         F.text("THE COVERED BRIDGE", 960, 1010, 0, 9999, 54, "bebas", "#9b2335", fade_out=0),
         F.shape("circle", 400, 560, 34, color="#9b2335"), F.shape("circle", 1520, 560, 34, color="#9b2335")]
    return L, None, 2.2


def s_minimal(F, t):
    L = [F.full("f2c185df.jpg", "s", (1.04, 1.06), look={"name": "faded", "amount": 0.35}),
         F.text("we drove until the road ran out.", 960, 1012, 0, 9999, 40, "playfair_italic", "#f4ecd8", fade_out=0, post=True)]
    return L, [{"type": "letterbox", "h": 140}], 2.2


def s_diary(F, t):
    L = [F.wall("#efe6d2", True)]
    L += F.pr("268df303.jpg", "s", 600, 420, (720, 480), -3, t + 0.1, tapes="light", sfx=False, look={"name": "sepia", "amount": 0.6})
    L += [F.text("day 4", 1240, 220, 0, 9999, 100, "caveat", "#3d3d3d", anchor="lm", fade_out=0),
          F.text("salty hair, no plan,\nthree gelatos before noon", 1240, 400, 0, 9999, 58, "caveat", "#4a4a4a", anchor="lm",
                 align="left", fade_out=0),
          F.text("14.08.", 360, 760, 0, 9999, 64, "caveat", "#4a4a4a", rot=-4, fade_out=0),
          {"type": "marker", "kind": "line", "points": [[1220, 640], [1330, 700], [1420, 690], [1520, 780], [1660, 820], [1720, 900]],
           "t0": t + 0.1, "dur": 0.3, "color": "#555555", "width": 5}]
    L += F.doodles([t + 0.3, t + 0.35], [(1220, 640), (1735, 905)], "heart", "#c8371f", 40)
    return L, None, 2.2


def s_maps(F, t):
    stops = [("Amsterdam", 4.90, 52.37), ("Brussels", 4.35, 50.85), ("Paris", 2.35, 48.86), ("Lyon", 4.83, 45.76),
             ("Milan", 9.19, 45.46), ("Vienna", 16.37, 48.21)]
    trip = {"trip": {"countries": ["NL", "BE", "FR", "IT", "AT"]}, "route": [],
            "steps": [{"id": str(i), "label": n, "lon": lo, "lat": la, "skip": False} for i, (n, lo, la) in enumerate(stops)]}
    L = [F.route_map(trip, [t + 0.1 + 0.15 * i for i in range(len(stops))], zoom=(1.0, 1.0)),
         F.shape("rect", 960, 1010, 1920, 140, "#14213d", alpha=0.92),
         F.text("6 CITIES   ·   14 DAYS   ·   1,642 KM", 960, 1010, 0, 9999, 44, "mono", "#ffffff", fade_out=0)]
    return L, None, 2.4


STYLES = [
    ("scrapbook", "scrapbook", "Disposable scrapbook", "Prints taped to a table, handwritten notes, flashes and orange date stamps.",
     "warm indie pop, friend groups, disposable cameras", "consumer_film", s_scrapbook),
    ("vhs", "VHS rockumentary", "VHS rockumentary", "A camcorder tape: REC light, closed captions, glitchy cuts, a band-on-tour mockumentary.",
     "jokey rock, ironic lyrics, big personalities", "punchy", s_vhs),
    ("kinetic", "kinetic lyrics", "Kinetic lyrics", "The lyric is the star: giant words punch in on the syllables over the photos.",
     "wordy songs, singalongs, strong hooks", "punchy", s_kinetic),
    ("swiss", "Swiss editorial", "Swiss editorial", "A magazine grid: clean photos, huge numbers, captions as data, hard cuts on the downbeat.",
     "cool, confident, electronic or minimal pop", "punchy", s_swiss),
    ("riso", "risograph zine", "Risograph zine", "A two-ink DIY print: torn cut-outs, misregistered colour, stamped headlines.",
     "punk pop, scrappy summers, DIY energy", "consumer_film", s_riso),
    ("super8", "Super 8", "Super 8 home movie", "A sun-bleached home movie: light leaks, flicker, soft colour, barely any text.",
     "nostalgic folk, slow builds, old friends", "golden", s_super8),
    ("nouvelle", "French New Wave", "French New Wave", "Black and white, jump cuts, an iris closing in, serif title cards.",
     "melancholic or French indie, black-and-white photos", "punchy", s_nouvelle),
    ("poster", "travel poster", "Travel poster", "Saul Bass-style flat shapes and duotone photos: every chapter becomes a poster.",
     "upbeat, jazzy, trips and cities", "consumer_film", s_poster),
    ("haze", "dream pop haze", "Dream pop haze", "Overexposed and soft: double exposures, motion trails, long dissolves.",
     "dreamy, reverb-heavy, slower songs", "golden", s_haze),
    ("club", "club strobe", "Club strobe", "Strobes on the snare, kaleidoscopes and mirrors, the fastest cuts saved for the drop.",
     "dance, house, techno, high tempo", "punchy", s_club),
    ("cyanotype", "cyanotype", "Cyanotype darkroom", "Sun-print blues, prints developing on paper, typewriter captions.",
     "gentle acoustic, the sea, summer light", "consumer_film", s_cyanotype),
    ("infrared", "infrared", "Infrared dream", "False-colour film: green turns pink, landscapes look like another planet.",
     "psychedelic, warm guitars, nature trips", "golden", s_infrared),
    ("y2k", "Y2K digicam", "Y2K digicam", "A 2003 point-and-shoot: blown flash, chrome colour, date stamp, camera-screen framing.",
     "2000s pop, party nostalgia", "punchy", s_y2k),
    ("collage", "collage chaos", "Collage chaos", "Maximalist cut-and-paste: torn photos, ransom-note letters, stickers piling up on the beat.",
     "hyperpop, punk, big chaotic friend groups", "consumer_film", s_collage),
    ("wes", "symmetry / Wes-ish", "Symmetry / Wes-ish", "Pastel, centred and symmetrical, with chapter title cards.",
     "whimsical, orchestral pop, road trips", "golden", s_wes),
    ("minimal", "cinematic minimal", "Cinematic minimal", "Letterboxed, slow and golden, few words; one huge moment at the climax.",
     "big emotional builds, ballads, endings", "golden", s_minimal),
    ("diary", "diary sketchbook", "Diary sketchbook", "A travel journal: pencil notes, dates, little drawings, a page per stop.",
     "intimate singer-songwriter, solo trips", "consumer_film", s_diary),
    ("maps", "maps & motion", "Maps & motion", "The route draws itself, numbers count up, coordinates as captions.",
     "travel films with many places", "consumer_film", s_maps),
]


def main():
    only = set(sys.argv[1:])
    os.makedirs(DEST, exist_ok=True)
    slug = "time_to_pretend"                                   # any analysed song: stills need its grid, not its audio
    dur = json.load(open(os.path.join(CACHE, "audio", f"{slug}.json"), encoding="utf-8"))["duration"]
    srcp = os.path.join(CACHE, "style_sources.json")             # style key -> photos it uses (for the credits)
    sources = json.load(open(srcp, encoding="utf-8")) if os.path.exists(srcp) else {}
    for grade in ("consumer_film", "golden", "punchy"):
        todo = [s for s in STYLES if s[5] == grade and (not only or s[0] in only)]
        if not todo:
            continue
        F = Film(f"style_samples_{grade}", "Style samples", "music/none.mp3", slug, [(0.0, dur, 0.0)],
                 grade={"preset": grade, "overrides": {}}, tail=0.0)
        F.use = lambda src, where: src                         # noqa: E731  (samples, not a film)
        t, stills = 1.0, []
        F.shot(0.0, 1.0, [F.wall("#000000")], sync="pre")
        for key, _, _, _, _, _, build in todo:
            n0 = len(F.B.edl["shots"])
            layers, fx, off = build(F, t)
            if layers is not None:
                s = F.shot(t, t + SEG, layers, sync=key)
                if fx:
                    s["fx"] = fx
            sources[key] = sorted({x for sh in F.B.edl["shots"][n0:] for L in sh["layers"]
                                   for x in ([L["src"]] if L.get("src") else L.get("srcs", []))})
            stills.append((key, round(t + off, 3)))
            t += SEG
        F.B.edl["meta"]["duration"] = round(t + 0.5, 3)
        F.duration = F.B.edl["meta"]["duration"]
        F.save()
        edl = os.path.join(PDIR, "out", f"style_samples_{grade}_edl.json")
        subprocess.run([sys.executable, "-W", "ignore", os.path.join(TOOLS, "render.py"), edl, "--width", "1280", "--stills",
                        ",".join(str(s_) for _, s_ in stills)], check=True)
        for key, s_ in stills:
            im = cv2.imread(os.path.join(CACHE, "render", f"style_samples_{grade}_{s_:07.3f}.png"))
            cv2.imwrite(os.path.join(DEST, f"{key}.jpg"), cv2.resize(im, (960, 540), interpolation=cv2.INTER_AREA),
                        [cv2.IMWRITE_JPEG_QUALITY, 84])
            print("wrote", key)
    json.dump([{"key": k, "name": n, "title": ti, "line": li, "fits": fi, "img": f"/static/styles/{k}.jpg"}
               for k, n, ti, li, fi, _, _ in STYLES], open(os.path.join(DEST, "styles.json"), "w", encoding="utf-8"),
              indent=1, ensure_ascii=False)
    meta = json.load(open(os.path.join(PDIR, "photos_meta.json"), encoding="utf-8"))
    json.dump(sources, open(srcp, "w", encoding="utf-8"), indent=1)
    used = {x for k, *_ in STYLES for x in sources.get(k, [])}    # credits: every photo the current samples use
    if used:
        lines = ["# Style sample photos", "",
                 "The sample frames in this folder were rendered by Aftermovie Studio from these photos, all released "
                 "into the public domain (CC0 or the Public Domain Mark), found via Openverse.", ""]
        for f in sorted(used):
            m = meta[os.path.splitext(f)[0]]
            lic = "CC0 1.0" if m["license"] == "cc0" else "Public Domain Mark 1.0"
            lines.append(f"- \"{(m.get('title') or 'untitled').strip()[:90]}\" by {m.get('creator') or 'unknown'}, {lic}: "
                         f"{m['foreign_landing_url']}")
        open(os.path.join(DEST, "CREDITS.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("done:", DEST)


if __name__ == "__main__":
    main()
