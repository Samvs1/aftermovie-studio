"""Style gallery: one shot per technique of the broadened vocabulary, rendered on a project's own photos.

  python tools/studio.py gallery <project>          -> out/style_gallery.jpg (one labelled sheet, ~2 min)

Also works as  studio.py run <project> templates/style_gallery.py  (same result). Modes used by `studio.py gallery`
for its progress steps: --edl-only (build out/style_gallery_edl.json) and --sheet-only (stills -> sheet).
Useful as a visual reference of what the engine can do with these photos, and as a check that every look / layer /
transition still works. Needs an analysed song in the project (its beat grid; the audio itself isn't used).
Photos are reused freely here: it's a reference sheet, not a film.
"""
import itertools, json, os, re, subprocess, sys
sys.path.insert(0, os.environ.get("AM_TOOLS") or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from am.common import CACHE, project  # noqa: E402

PDIR = os.environ.get("AM_PROJECT", ".")
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDL = os.path.join(PDIR, "out", "style_gallery_edl.json")
STILLS = os.path.join(CACHE, "style_gallery.json")
SHEET = os.path.join(PDIR, "out", "style_gallery.jpg")


SKIP = set("trip through with and the our from road summer winter spring autumn fall weekend holiday holidays vacation "
           "january february march april may june july august september october november december".split())


def knockout_word(P):
    """A word from the project for the knockout shots: the place, else the title, else SUMMER."""
    for src in (P.get("when_where"), P.get("title"), P.get("occasion")):
        for w in re.findall(r"[^\W\d_]{3,10}", src or ""):
            if w.lower() not in SKIP:
                return w.upper()
    return "SUMMER"


def build():
    from am.kit import Film
    P = project()
    auds = sorted(f[:-5] for f in os.listdir(os.path.join(CACHE, "audio")) if f.endswith(".json")) \
        if os.path.isdir(os.path.join(CACHE, "audio")) else []
    slug = (P.get("song") or {}).get("slug")
    slug = slug if slug in auds else (auds[0] if auds else None)
    if not slug:
        sys.exit("The gallery needs an analysed song in this project (Analyse step first).")
    A = json.load(open(os.path.join(CACHE, "audio", f"{slug}.json"), encoding="utf-8"))
    mdir = os.path.join(PDIR, "music")
    songs = [f for f in os.listdir(mdir) if not f.startswith(".")] if os.path.isdir(mdir) else []
    F = Film("style_gallery", "Style gallery", f"music/{songs[0] if songs else 'none.mp3'}", slug, [(0.0, A["duration"], 0.0)], tail=0.0)
    F.use = lambda src, where: src            # noqa: E731  (a reference sheet: photos may repeat)
    photos = sorted(F.META)
    if not photos:
        sys.exit("No analysed photos in this project yet.")

    def cycle(*lists):
        seen, pool = set(), []
        for x in itertools.chain(*lists):
            if x not in seen:
                seen.add(x)
                pool.append(x)
        return itertools.cycle(pool)
    land = [p for p in photos if not F.portrait(p)]
    land_faces = [p for p in land if F.META[p]["faces"]]
    port = [p for p in photos if F.portrait(p)]
    L_it, P_it = cycle(land_faces, land, port), cycle(port, land)
    L_ = lambda: next(L_it)                   # noqa: E731  landscapes (with faces first)
    P_ = lambda: next(P_it)                   # noqa: E731  portraits first
    word = knockout_word(P)
    ksize = min(560, int(1750 / (0.52 * len(word))))
    SEG = 2.4
    stills, t = [], 1.0

    def add(name, layers, fx=None, mid=0.5, tr=None, **kw):
        nonlocal t
        a, b = round(t, 3), round(t + SEG, 3)
        s = F.shot(a, b, layers, sync=name, **({"in": tr} if tr else {}), **kw)
        if fx:
            s["fx"] = fx
        stills.append((name, round(a + SEG * mid, 3)))
        t = b
        return s

    def label(txt):
        return F.text(txt, 30, 1040, 0, 9999, 30, "mono", "#ffffff", anchor="lm", stroke=3, stroke_color="#000000", fade_out=0,
                      post=True)

    F.shot(0.0, 1.0, [F.wall("#000000")], sync="pre")
    for look in ["bw", {"name": "duotone"}, {"name": "riso"}, {"name": "xerox"}, {"name": "cyanotype"}, {"name": "infrared"},
                 {"name": "chrome"}, {"name": "selective", "hue": 0, "width": 30}, {"name": "bleach"}, {"name": "faded"},
                 {"name": "thermal"}, {"name": "gameboy"}]:
        nm = look if isinstance(look, str) else look["name"]
        add(f"look: {nm}", [F.full(L_(), "gallery", (1.0, 1.04), look=look), label(f"look: {nm}")])
    add("knockout type", [F.wall("#0d0d0d"), {"type": "type_mask", "src": L_(), "text": word, "font": "anton",
                                              "size": ksize, "x": 960, "y": 540, "zoom": [1.0, 1.08]}, label("type_mask (knockout)")])
    a = t
    add("zoom through a letter", [F.wall("#f2ede4"), {"type": "type_mask", "src": L_(), "text": "GO", "font": "anton", "size": 700,
                                                      "x": 960, "y": 540, "scale": [[a + 0.3, 1.0], [a + 1.8, 22.0]], "ease": "in"},
                                  label("type_mask zoom-through")], mid=0.45)
    a = t
    add("poster shapes", [F.wall("#f3e9d2"), {"type": "shape", "kind": "circle", "x": 1250, "y": 470, "w": 760, "color": "#e85d2a",
                                              "grow": {"t": a, "dur": 0.4}},
                          F.full(P_(), "g", (1.0, 1.0), box=[300, 120, 560, 760], look={"name": "duotone", "dark": "#14213d", "light": "#f3e9d2"},
                                 blend="multiply"),
                          {"type": "shape", "kind": "stripes", "x": 1250, "y": 900, "w": 900, "h": 120, "n": 4, "color": "#14213d"},
                          F.text(word if len(word) <= 7 else "SUMMER", 1250, 470, a, 9999, 150, "anton", "#14213d", anim="rise", fade_out=0),
                          label("shapes + duotone multiply")])
    a = t
    add("slices", [F.wall("#111111"), {"type": "slices", "src": L_(), "n": 7, "t": a + 0.2, "stagger": 0.09, "dur": 0.35, "gap": 10},
                   label("slices")], mid=0.32)
    a = t
    words = [{"w": w, "t": round(a + 0.15 + i * 0.3, 3)} for i, w in enumerate("we were never this young again".split())]
    add("lyric stack", [F.full(L_(), "g", (1.05, 1.0), look="bw"), {"type": "lyric_type", "words": words, "mode": "stack", "font": "anton",
                                                                   "size": 150, "color": "#ffffff", "maxw": 1300, "case": "upper",
                                                                   "anim": "punch", "shadow": 6},
                        label("lyric_type stack")], mid=0.9)
    a = t
    add("lyric line", [F.wall("#0d1b2a"), {"type": "lyric_type", "words": words, "mode": "line", "font": "playfair_italic", "size": 96,
                                            "color": "#8da9c4", "accent": "#ffd166", "maxw": 1700, "anim": "rise"}, label("lyric_type line")],
        mid=0.75)
    a = t
    add("filmstrip", [F.wall("#1a1a1a"), {"type": "filmstrip", "srcs": [L_() for _ in range(7)], "y": 540, "h": 420,
                                          "advance": [round(a + 0.3 + 0.5 * k, 3) for k in range(4)], "rot": -4}, label("filmstrip")], mid=0.8)
    add("double exposure", [F.full(L_(), "g", (1.0, 1.06)), F.full(P_(), "g", (1.1, 1.0), box=[420, -60, 1080, 1200], blend="screen",
                                                                   opacity=0.85, feather=260), label("double exposure (screen)")])
    a = t
    add("torn collage", [F.wall("#cdb38f", True),
                         F.full(L_(), "g", (1.0, 1.0), box=[140, 160, 820, 560], rot=-4, edge="torn", shadow=True, look="xerox", seed=2),
                         F.full(P_(), "g", (1.0, 1.0), box=[1000, 90, 560, 760], rot=5, edge="torn", shadow=True, seed=3),
                         {"type": "shape", "kind": "rect", "x": 760, "y": 860, "w": 640, "h": 120, "color": "#e63946", "rot": -3},
                         F.text("the summer we\nmissed the bus", 760, 860, a, 9999, 64, "elite", "#ffffff", line_gap=0.9, rot=-3, fade_out=0),
                         label("torn collage + xerox")])
    a = t
    s = add("echo", [F.wall("#000000"), F.full(L_(), "g", (1.0, 1.0), box=[560, 240, 800, 560],
                                                enter={"t": a + 0.3, "dur": 0.6, "type": "slide", "from": [-900, 0]}),
                     label("echo trails")], mid=0.25)
    s["echo"] = {"n": 4, "dt": 0.05, "decay": 0.6}
    add("kaleido", [F.full(L_(), "g", (1.1, 1.2)), label("kaleido")], fx=[{"type": "kaleido", "n": 6}])
    add("mirror", [F.full(L_(), "g", (1.0, 1.0)), label("mirror")], fx=[{"type": "mirror", "mode": "x"}])
    a = t
    add("leak + letterbox", [F.full(L_(), "g", (1.0, 1.06), look="faded"), label("light leak + letterbox")],
        fx=[{"type": "light_leak", "amount": 0.45}, {"type": "letterbox", "keys": [[a, 0], [a + 0.8, 140]]}])
    add("riso frame", [F.wall("#ffffff"), F.full(P_(), "g", (1.0, 1.0), box=[660, 90, 600, 800]),
                       F.text("ZINE NO. 3", 960, 960, 0, 9999, 120, "anton", "#000000", fade_out=0), label("riso on the whole frame")],
        fx=[{"type": "look", "look": {"name": "riso", "ink1": "#ff48b0", "ink2": "#0078bf"}}])
    for trn in ["iris", "slices", "zoom", "luma", "spin"]:
        add(f"tr {trn} A", [F.full(L_(), "g", (1.0, 1.04)), label(f"transition: {trn}")])
        a = t
        add(f"tr {trn} B", [F.full(L_(), "g", (1.04, 1.0)), label(f"transition: {trn}")], tr={"type": trn, "dur": 0.6}, mid=0.0)
        stills.pop(-2)                                   # keep one frame per transition: mid-way through it
        stills[-1] = (f"transition: {trn}", round(a + 0.05, 3))
    F.B.edl["meta"]["duration"] = round(t + 0.5, 3)
    F.duration = F.B.edl["meta"]["duration"]
    F.save()
    json.dump(stills, open(STILLS, "w", encoding="utf-8"))
    return stills


def render(stills):
    subprocess.run([sys.executable, "-W", "ignore", os.path.join(TOOLS, "render.py"), EDL, "--width", "960", "--stills",
                    ",".join(str(s_) for _, s_ in stills)], check=True)


def sheet():
    import cv2
    import numpy as np
    stills = json.load(open(STILLS, encoding="utf-8"))
    tiles = []
    for name, s_ in stills:
        im = cv2.imread(os.path.join(CACHE, "render", f"style_gallery_{s_:07.3f}.png"))
        if im is None:
            continue
        im = cv2.resize(im, (480, 270), interpolation=cv2.INTER_AREA)
        tiles.append(np.vstack([im, np.full((34, 480, 3), 24, np.uint8)]))
        cv2.putText(tiles[-1], name, (10, 295), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (235, 235, 235), 1, cv2.LINE_AA)
    while len(tiles) % 4:
        tiles.append(np.full_like(tiles[0], 24))
    img = np.vstack([np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)])
    cv2.imwrite(SHEET, img, [cv2.IMWRITE_JPEG_QUALITY, 86])
    print("gallery sheet:", SHEET)


if __name__ == "__main__":
    if "--sheet-only" in sys.argv:
        sheet()
    else:
        st = build()
        print("STILLS " + ",".join(str(s_) for _, s_ in st))
        if "--edl-only" not in sys.argv:
            render(st)
            sheet()
