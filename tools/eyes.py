"""The eyes: pictures of a rendered aftermovie laid against the song and the edit, so a model that can't watch a video
can judge it (the studio's critic does the looking; the director opens only the pictures it needs).

  python tools/studio.py run <p> eyes.py look out/v2_preview.mp4           sheets, moments, beats + index.md
  python tools/studio.py run <p> eyes.py strip out/v2_preview.mp4 --at 63.4 [--n 8]   consecutive frames around a time

Writes cache/eyes/<video name>/:
  sheet_N.jpg   one tile per shot, grabbed from the video once the shot has settled (the board's time), with the film
                time, the song's bar:beat, section and sung line (the word sung then in [brackets]), the shot's photos
                and every line of text on it with its source (F.said origin). Without an EDL: a tile every 2 s.
  moments.jpg   a frame on each ★★/★★★ moment of the song (in film time: after a join some are cut out).
  beats.jpg     the loudest section's downbeats: the frame just before each and the frame on it (does it change *on*
                the beat?).
  strip_atT.jpg consecutive frames around one time (the frame at T outlined).
  index.md      the pictures and what the studio measured: shots, their length, cuts on the beat, text, the QA summary.
Times on the tiles are film seconds (what the user's notes and the preview use); the song's own time is in brackets
when a join makes them differ.
"""
import argparse, glob, json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from am.util import STUDIO, jload, load_project, song_slug  # noqa: E402
from am.song import Song, FilmClock, at_film  # noqa: E402

TILE_W, TILE_H, MARGIN, COLS = 400, 225, 104, 4
PER_SHEET = 20


def project_dir():
    p = os.environ.get("AM_PROJECT")
    if not p:
        raise SystemExit("no project: run this through `python tools/studio.py run <project> eyes.py ...`")
    return os.path.abspath(p)


def rel(p, start):
    return os.path.relpath(p, start).replace("\\", "/")


def mmss(t):
    if t is None:
        return "-"
    m, s = divmod(max(0.0, float(t)), 60)
    return f"{int(m)}:{s:04.1f}"


def out_dir(video, pdir=None):
    pdir = pdir or project_dir()
    stem = os.path.splitext(os.path.basename(video))[0]
    return os.path.join(pdir, "cache", "eyes", re.sub(r"[^A-Za-z0-9._-]+", "_", stem))


def version_of(video):
    """out/v2_preview.mp4, out/v2_preview_share.mp4, out/v2.mp4, out/v2_share.mp4, out/rounds/v2_r3.mp4 -> "v2"."""
    b = os.path.splitext(os.path.basename(video))[0]
    for suf in (r"_preview_share$", r"_preview$", r"_share$", r"_r\d+$"):
        if re.search(suf, b):
            return re.sub(suf, "", b)
    return b


def edl_of(pdir, video):
    v = version_of(video)
    e = jload(os.path.join(pdir, "out", f"{v}_edl.json"), None)
    return v, (e if isinstance(e, dict) and e.get("shots") else None)


def probe(video):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height,r_frame_rate,codec_type",
                        "-of", "json", video], capture_output=True, text=True, encoding="utf-8", errors="replace")
    d = json.loads(r.stdout or "{}")
    vs = next((s for s in d.get("streams") or [] if s.get("codec_type") == "video"), {})
    num, _, den = str(vs.get("r_frame_rate") or "30/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 30.0
    return {"duration": float((d.get("format") or {}).get("duration") or 0), "width": int(vs.get("width") or 0),
            "height": int(vs.get("height") or 0), "fps": fps}


def grab(video, t, w=TILE_W):
    """One frame of the video at time t, as a PIL image w wide (a black one when ffmpeg can't)."""
    from PIL import Image
    import io
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", video, "-frames:v", "1",
                        "-vf", f"scale={w}:-2", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
    try:
        return Image.open(io.BytesIO(r.stdout)).convert("RGB")
    except Exception:
        return Image.new("RGB", (w, w * 9 // 16), (0, 0, 0))


def font(size, mono=False):
    from PIL import ImageFont
    names = ("SpaceMono-Regular.ttf",) if mono else ("Inter[opsz,wght].ttf", "NotoSans[wdth,wght].ttf")
    for n in names + ("SpaceMono-Regular.ttf",):
        p = os.path.join(STUDIO, "assets", "fonts", n)
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def fit(d, text, f, w):
    """text cut to fit w pixels."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if d.textlength(text, font=f) <= w:
        return text
    while text and d.textlength(text + "…", font=f) > w:
        text = text[:-1]
    return text + "…"


class Context:
    """What the song and the edit say about a film time: the shot, its captions and photos, bar:beat, section, line."""

    def __init__(self, pdir, video):
        self.pdir = pdir
        self.v, self.edl = edl_of(pdir, video)
        slug = (self.edl or {}).get("meta", {}).get("analysis") if self.edl else None
        try:
            self.song = Song(pdir, slug if slug and os.path.isdir(os.path.join(pdir, "song", slug)) else song_slug(pdir))
        except Exception:
            self.song = None
        self.clock = FilmClock(self.edl)
        self.caps = []
        if self.edl:
            try:
                sys.path.insert(0, HERE)
                os.environ.setdefault("AM_PROJECT", pdir)
                from am import checks
                self.caps = checks.captions(self.edl, load_project(pdir))
            except Exception:
                self.caps = []

    def shot_at(self, t):
        for s in (self.edl or {}).get("shots") or []:
            if s["t0"] - 1e-4 <= t < s["t1"]:
                return s
        return None

    def song_at(self, t):
        return at_film(self.song, self.clock, t) if self.song else None

    def lines(self, t, shot=None):
        """The margin lines for a tile at film time t."""
        out = []
        a = self.song_at(t)
        st = a.get("t") if a else None
        head = f"{mmss(t)}"
        if a and a.get("bar") is not None:
            head += f" · {a['bar']}:{a['beat']:.1f}" if isinstance(a.get("beat"), (int, float)) else f" · {a['bar']}"
        if shot:
            head = f"{shot['id']} · " + head
        out.append(("head", head))
        sec = (a.get("section") if a else None) or ""
        if st is not None and abs(st - t) > 0.05:
            sec += f" (song {mmss(st)})"
        if sec:
            out.append(("section", sec))
        if a and a.get("line"):
            ln = a["line"]
            w = a.get("word")
            if w:
                ln = re.sub(rf"\b{re.escape(w)}\b", f"[{w}]", ln, count=1)
            out.append(("lyric", f"♪ {ln}"))
        if a and a.get("moments"):
            out.append(("moment", " ".join(a["moments"])[:120]))
        if shot:
            caps = [c for c in self.caps if c.get("shot") == shot["id"]]
            if caps:
                out.append(("text", " | ".join(f"“{c['text']}” ({c.get('origin') or '?'})" for c in caps)))
            photos = sorted({x for L in shot.get("layers") or [] for x in _media(L)})
            if photos:
                out.append(("photo", ", ".join(photos)))
        return out


def _media(L):
    """The photos and clips a layer shows (am.checks.media_of, plus a grid's cells)."""
    try:
        from am import checks
        out = list(checks.media_of(L))
    except Exception:
        out = [L["src"]] if isinstance(L.get("src"), str) else [x for x in L.get("srcs") or [] if isinstance(x, str)]
    out += [c["src"] for c in L.get("cells") or [] if isinstance(c, dict) and isinstance(c.get("src"), str)]
    return out


COLORS = {"head": (255, 220, 90), "section": (255, 220, 90), "lyric": (150, 220, 255), "moment": (255, 140, 120), "text": (235, 235, 235),
          "photo": (150, 150, 150)}


def tile(img, lines, mark=False):
    from PIL import Image, ImageDraw
    t = Image.new("RGB", (TILE_W, TILE_H + MARGIN), (16, 16, 16))
    im = img.resize((TILE_W, TILE_H))
    t.paste(im, (0, 0))
    d = ImageDraw.Draw(t)
    if mark:
        d.rectangle([1, 1, TILE_W - 2, TILE_H - 2], outline=(255, 60, 60), width=4)
    y = TILE_H + 3
    for kind, text in lines:
        f = font(15 if kind == "head" else 13, mono=kind == "head")
        if y + 16 > TILE_H + MARGIN:
            break
        d.text((5, y), fit(d, text, f, TILE_W - 10), fill=COLORS.get(kind, (220, 220, 220)), font=f)
        y += 18 if kind == "head" else 15
    return t


def sheet(tiles, title, path, cols=COLS):
    from PIL import Image, ImageDraw
    rows = (len(tiles) + cols - 1) // cols
    W = cols * (TILE_W + 6) + 6
    H = rows * (TILE_H + MARGIN + 6) + 6 + 30
    s = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(s)
    d.text((8, 6), title, fill=(255, 255, 255), font=font(18))
    for k, t in enumerate(tiles):
        r, c = divmod(k, cols)
        s.paste(t, (6 + c * (TILE_W + 6), 36 + r * (TILE_H + MARGIN + 6)))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    s.save(path, quality=86)
    return path


def settled(s):
    """When a shot has settled (its intro transition and photo entrances done): the board's still time."""
    try:
        from am import checks
        return checks.settled(s)
    except Exception:
        return min(s["t1"] - 0.05, s["t0"] + min(0.6, (s["t1"] - s["t0"]) * 0.5))


def look(pdir, video, log=print):
    pv = probe(video)
    if not pv["duration"]:
        raise SystemExit(f"can't read {rel(video, pdir)}")
    d = out_dir(video, pdir)
    os.makedirs(d, exist_ok=True)
    busy = os.path.join(d, ".looking")
    open(busy, "w").write(str(os.getpid()))
    try:
        return _look(pdir, video, pv, d, log)
    finally:
        try:
            os.remove(busy)
        except OSError:
            pass


def _look(pdir, video, pv, d, log):
    for f in glob.glob(os.path.join(d, "sheet_*.jpg")) + [os.path.join(d, x) for x in ("moments.jpg", "beats.jpg")]:
        if os.path.exists(f):
            os.remove(f)
    C = Context(pdir, video)
    dur = pv["duration"]
    pics, notes = [], []
    # 1. a tile per shot (or every 2 s)
    if C.edl:
        items = [(min(settled(s), dur - 0.05), s) for s in C.edl["shots"] if s["t0"] < dur]
    else:
        items = [(t, None) for t in [x * 2.0 + 1.0 for x in range(int(dur // 2))]]
    tiles = [tile(grab(video, t), C.lines(t, s)) for t, s in items]
    for k in range(0, len(tiles), PER_SHEET):
        n = k // PER_SHEET + 1
        last = min(len(items), k + PER_SHEET) - 1
        p = sheet(tiles[k:k + PER_SHEET], f"{os.path.basename(video)} · sheet {n}: "
                  + (f"shots {items[k][1]['id']}–{items[last][1]['id']}" if C.edl else f"{mmss(items[k][0])}–{mmss(items[last][0])}")
                  + f" ({mmss(items[k][0])}–{mmss(items[last][0])})", os.path.join(d, f"sheet_{n}.jpg"))
        pics.append((f"sheet{n}", rel(p, pdir)))
    log(f"eyes: {len(tiles)} tiles on {len(pics)} sheet(s)")
    # 2. the song's big moments, in film time
    if C.song:
        ms = []
        for m in C.song.moments(2):
            ft = C.clock.film(m["t"])
            if ft is not None and 0 <= ft < dur:
                ms.append((ft, m))
        ms = sorted(ms, key=lambda x: (-x[1]["stars"], x[0]))[:12]
        ms.sort(key=lambda x: x[0])
        if ms:
            tl = [tile(grab(video, ft + 2.0 / pv["fps"]), [("moment", f"{'★' * m['stars']} {m['text']}")] + C.lines(ft, C.shot_at(ft)))
                  for ft, m in ms]
            pics.append(("moments", rel(sheet(tl, f"{os.path.basename(video)} · the song's ★★/★★★ moments (a frame just after each)",
                                              os.path.join(d, "moments.jpg")), pdir)))
        # 3. beat sheet: the loudest section's downbeats, before / on
        secs = [s for s in C.song.sections if s.get("t1", 0) > s.get("t0", 0)]
        if secs:
            loud = max(secs, key=lambda s: float(s.get("loud") if s.get("loud") is not None else -99))
            dbs = [C.clock.film(t) for t in C.song.downbeats if loud["t0"] - 0.01 <= t < loud["t1"]]
            dbs = [t for t in dbs if t is not None and 0.1 < t < dur - 0.1][:8]
            if dbs:
                tl = []
                for t in dbs:
                    tl.append(tile(grab(video, t - 1.0 / pv["fps"]), [("head", f"just before {mmss(t)}")] + C.lines(t, C.shot_at(t))[1:2]))
                    tl.append(tile(grab(video, t + 1.0 / pv["fps"]), C.lines(t, C.shot_at(t)), mark=True))
                pics.append(("beats", rel(sheet(tl, f"{os.path.basename(video)} · beat sheet: {loud.get('name')} "
                                                f"(the loudest section): the frame before each downbeat | the frame on it",
                                                os.path.join(d, "beats.jpg")), pdir)))
    # 4. what the studio measured
    if C.edl:
        shots = C.edl["shots"]
        lens = sorted(s["t1"] - s["t0"] for s in shots)
        notes.append(f"- {len(shots)} shots over {mmss(dur)}; shot length median {lens[len(lens) // 2]:.1f} s "
                     f"(shortest {lens[0]:.1f} s, longest {lens[-1]:.1f} s)")
        if C.song:
            on = 0
            for s in shots[1:]:
                st = C.clock.song(s["t0"])
                if st is not None and any(abs(st - b) < 0.05 for b in C.song.downbeats):
                    on += 1
            notes.append(f"- {on} of {len(shots) - 1} cuts on a downbeat (the rest on beats, 8ths, words or stops: see QA)")
        if C.caps:
            by = {}
            for c in C.caps:
                by[c.get("origin") or "?"] = by.get(c.get("origin") or "?", 0) + 1
            notes.append(f"- {len(C.caps)} lines of text (" + ", ".join(f"{k} {n}" for k, n in sorted(by.items())) + ")")
        qa = os.path.join(pdir, "cache", "qa", C.v, "report.md")
        if os.path.exists(qa) and os.path.getmtime(qa) >= os.path.getmtime(video) - 120:
            bold = [x.strip("* ") for x in open(qa, encoding="utf-8").read().splitlines() if x.startswith("**")]
            if bold:
                notes.append("- QA (`" + rel(qa, pdir) + "`): " + "; ".join(bold))
            cuts = sorted(glob.glob(os.path.join(os.path.dirname(qa), "cuts_*.jpg")))
            for k, c in enumerate(cuts[:3], 1):
                pics.append((f"cuts{k}", rel(c, pdir)))
    idx = [f"# Eyes: {rel(video, pdir)}", "", f"{pv['width']}×{pv['height']}, {pv['fps']:.0f} fps, {mmss(dur)}; looked at "
           f"{time.strftime('%Y-%m-%d %H:%M:%S')}" + (f"; the edit: out/{C.v}_edl.json" if C.edl else "; no EDL found for it"), "",
           "## Pictures"] + [f"- **{k}**: `{p}`" for k, p in pics] + ["", "## Measured"] + (notes or ["- (no EDL: nothing measured)"])
    open(os.path.join(d, "index.md"), "w", encoding="utf-8").write("\n".join(idx) + "\n")
    log(f"eyes: {rel(os.path.join(d, 'index.md'), pdir)}")
    return pics


def strip(pdir, video, at, n=8, log=print):
    pv = probe(video)
    C = Context(pdir, video)
    fps = pv["fps"] or 30
    f0 = int(round(at * fps)) - n // 2
    tl = []
    for k in range(n):
        t = max(0.0, (f0 + k) / fps)
        tl.append(tile(grab(video, t + 0.5 / fps), C.lines(t, C.shot_at(t)), mark=(f0 + k) == int(round(at * fps))))
    d = out_dir(video, pdir)
    p = sheet(tl, f"{os.path.basename(video)} · {n} consecutive frames around {mmss(at)}", os.path.join(d, f"strip_at{float(at):g}.jpg"))
    log(p)
    return p


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("look")
    p.add_argument("video")
    p = sp.add_parser("strip")
    p.add_argument("video")
    p.add_argument("--at", type=float, required=True)
    p.add_argument("--n", type=int, default=8)
    a = ap.parse_args()
    pdir = project_dir()
    video = a.video if os.path.isabs(a.video) else os.path.join(pdir, a.video)
    if not os.path.isfile(video):
        raise SystemExit(f"no such video: {a.video}")
    if a.cmd == "look":
        look(pdir, video)
    else:
        strip(pdir, video, a.at, a.n)


if __name__ == "__main__":
    main()
