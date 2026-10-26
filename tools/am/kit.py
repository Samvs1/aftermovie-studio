"""Builder kit: the helpers every film builder needs, distilled from the Time to Pretend v2 builder
(projects/elevate-2026/build_time_to_pretend.py).

    from am.kit import Film
    F = Film("my_film", "My Film", song_file="music/song.mp3", slug="song", segments=[(0.3, 180.0, 1.0)])
    F.shot(F.bar(4), F.bar(5), [F.wall(F.YEL)] + F.pr("a.jpg", "why", 960, 540, (700, 900), -3, F.bar(4)) +
           [F.note("caption", 1450, 300, F.cue(F.sung("love", 42.1)), F.bar(5))], sync="bar 4: ...")
    F.save()            # writes out/<version>_edl.json, prints the reading-time lint

Rules baked in (Sam's notes on the Elevate films):
  * every photo once: use() raises on reuse
  * lyric captions on the sung onset: cue(sung(word, near)) = the 8th at or just before the aligned onset
  * reading time: save() lints every caption (~0.8 s + 55 ms/char, 1.4..3 s, before it goes or the shot cuts)
  * portraits are shown whole: pr() lays any photo out as a bordered print at its own aspect ratio
  * screen time: page() lands every print so it stays up >= 1.8 s, and save() lints every photo
  * every line is true: said(...) records where a caption came from (lyric, credit, note, answer, invented...) for the
    caption board in the studio; save() lists the lines the user vetoed or hasn't checked yet
  * must-haves: save() lints the photos starred in the studio (project.json "must_use") and the story-order rules
    ("order"), near-identical photos close together, and treatments that never arrive (am/checks.py)
"""
import json, math, os
import numpy as np

from . import checks
from .builder import Builder, MIN_PHOTO_S, screen_time
from .common import CACHE, OUT, font as _font, project

W, H = 1920, 1080


class Film:
    INK, RED, RED_DK = "#1f2a44", "#c8371f", "#9e2410"
    YEL, PINK, TEAL, BLACK, NEWS, KRAFT, BLUE, CREAM = ("#ffd400", "#ff5c9d", "#22b8c9", "#141414", "#f1ead9", "#cdb38f",
                                                       "#1d3bd1", "#f3eee2")
    VHS = {"type": "vhs", "amount": 1.0}
    VHS_SOFT = {"type": "vhs", "amount": 0.55, "band": False}
    SPLIT = {"type": "rgb_split", "on": "snares", "amount": 12}
    CYM = {"type": "flash_on", "on": "cymbals", "amount": 0.28, "min": 0.8}
    PUNCH = {"on": "kicks", "amount": 0.035, "decay": 0.11, "min": 0.45}

    def __init__(self, version, title, song_file, slug, segments, grade=None, finish=None, tail=14.0, duration=None):
        """segments: [(song_in, song_out, film_at), ...]  (at most ONE join between identical passages).
        tail: seconds of silence after the song for the thank-you; or give duration explicitly."""
        self.version, self.slug, self.segments = version, slug, segments
        self.a = json.load(open(os.path.join(CACHE, "audio", f"{slug}.json"), encoding="utf-8"))
        self.beat_len = float(self.a["beat_period"])
        song_end = max(at + b - a for a, b, at in segments)
        self.B = Builder(version, title, song_file, slug, segments,
                         grade=grade or {"preset": "consumer_film", "overrides": {}},
                         finish=finish or {"grain": 0.012, "vignette": 0.26, "halation": 0.06, "flicker": 0.005, "weave": 0.3},
                         duration=duration or song_end + tail)
        self.song_end = song_end
        self.duration = self.B.edl["meta"]["duration"]
        b = self.B.grid("beats")
        self.EIGHTHS = np.sort(np.r_[b, (b[:-1] + b[1:]) / 2])
        self.used = {}
        self.META = json.load(open(os.path.join(CACHE, "photos.json")))
        sl = os.path.join(CACHE, "shotlog.json")
        self.shotlog = {e["file"]: e for e in json.load(open(sl, encoding="utf-8"))} if os.path.exists(sl) else {}
        cp = os.path.join(CACHE, "cast.json")
        self.cast = json.load(open(cp, encoding="utf-8")).get("people", {}) if os.path.exists(cp) else {}
        self.project = project()
        self.shot = self.B.shot
        self.sfx = self.B.sfx

    # ------------------------------------------------------------ time
    def song2film(self, s):
        for a, b, at in self.segments:
            if a - 1e-4 <= s < b:
                return s - a + at
        return None

    def bar(self, n):
        """Film time of song bar n (n indexes the song's downbeats)."""
        t = self.song2film(self.a["downbeats"][n])
        if t is None:
            raise ValueError(f"bar {n} is cut out of the edit")
        return self.B.snap(t, "beats", 0.03)

    def beat(self, n, k):
        """Beat k of bar n; fractional k in 8ths (2.5 = the 'and' of beat 3). Counted on the song's own beat grid,
        so it follows a live band's drift and half-time sections (where the tracked beat is twice beat_len)."""
        g = self.B.grid("beats")
        i = int(np.argmin(np.abs(g - self.bar(n)))) + int(k)
        if i + 1 < len(g):
            return round(float(g[i] + (k - int(k)) * (g[i + 1] - g[i])), 4)
        t = self.B.snap(self.bar(n) + int(k) * self.beat_len, "beats", 0.05)       # past the last beat: felt pulse
        return round(t + (k - int(k)) * self.beat_len, 4)

    def b(self, t):
        """Snap to the nearest beat (the felt pulse continues past the song's end)."""
        return self.B.snap(t, "beats")

    def near(self, t):
        """The felt beat nearest to t, however far (for boundaries derived from arbitrary times like the song's end)."""
        return self.B.snap(t, "beats", self.beat_len / 2 + 0.01)

    def sung(self, word, near, tol=0.4):
        """Aligned sung onset (film time) of a lyric word near a film time (run tools/align_words.py first)."""
        return self.B.word(word, near, tol=tol)

    def cue(self, onset):
        """The 8th-note grid point at or just before a sung onset: captions land with the voice, never after it."""
        g = self.EIGHTHS[self.EIGHTHS <= onset + 0.05]
        return round(float(g[-1]), 4)

    def at(self, word, song_t, tol=0.4):
        """Caption time for a lyric word given its time in the *song* (as song_map.py prints it): cue(sung(...))."""
        t = self.song2film(song_t)
        if t is None:
            raise ValueError(f"song time {song_t} is cut out of the edit")
        return self.cue(self.sung(word, t, tol))

    # ------------------------------------------------------------ people + photos
    def use(self, src, where):
        if src in self.used:
            raise SystemExit(f"photo {src} used twice: {self.used[src]!r} and {where!r}")
        self.used[src] = where
        return src

    def person(self, name):
        """Person id for a name from the who's-who page (for focus='person:<id>' and circles)."""
        for pid, p in self.cast.items():
            if p.get("name", "").lower() == name.lower() or p.get("nick", "").lower() == name.lower():
                return pid
        raise KeyError(name)

    def portrait(self, src):
        return self.META[src]["h"] > self.META[src]["w"] * 1.05

    def ph(self, n):
        """Photo file for its number on the contact sheets (studio.py sheets: cache/sheets/index.txt), the numbers
        the shot log and the user's notes use."""
        if not hasattr(self, "_idx"):
            p = os.path.join(CACHE, "sheets", "index.txt")
            self._idx = dict(l.rstrip("\n").split("\t") for l in open(p, encoding="utf-8") if "\t" in l) if os.path.exists(p) else {}
        if str(n) not in self._idx:
            raise KeyError(f"photo #{n} is not on the contact sheets (run studio.py sheets)")
        return self._idx[str(n)]

    def face_uv(self, src, person=None, i=None):
        """Centre (u, v) of a face in a photo, normalised to the photo: a named person's ('Alex' or a cast id), face i,
        or the biggest face. For arrows and bubbles that point at who they name."""
        from .common import faces
        fs = faces(src, min_score=0.5, min_size=0.0)
        if not fs:
            raise ValueError(f"no face found in {src}")
        if person is not None:
            pid = str(person) if str(person).isdigit() else self.person(person)
            fs = [f for f in fs if str(f["person"]) == pid]
            if not fs:
                raise ValueError(f"{person} is not recognised in {src}")
        f = fs[i] if i is not None else max(fs, key=lambda f: f["box"][2] * f["box"][3])
        x, y, w, h = f["box"]
        return x + w / 2, y + h / 2

    # ------------------------------------------------------------ layers
    def photo(self, src, where, zoom=(1.0, 1.08), focus="faces", drift=None, **kw):
        L = {"type": "photo", "src": self.use(src, where), "zoom": list(zoom), "focus": focus,
             "drift": [list(d) for d in (drift or ((0, 0), (0, 0)))]}
        L.update(kw)
        return L

    def text(self, t, x, y, t0, t1, size=72, fnt="caveat", color="#ffffff", **kw):
        L = {"type": "text", "text": t, "x": x, "y": y, "t0": round(t0, 4), "t1": round(t1, 4), "size": size, "font": fnt,
             "color": color}
        L.update(kw)
        return L

    def note(self, t, x, y, t0, t1, size=72, color=None, seed=0, tape=True, **kw):
        """Handwritten caption on a taped paper note: readable on any photo (house style)."""
        return self.text(t, x, y, t0, t1, size, "caveat", color or self.INK, panel={"seed": seed, "tape": tape, "pady": 16}, **kw)

    def slam(self, t, x, y, t0, t1, size=200, color="#111111", fnt="anton", **kw):
        return self.text(t, x, y, t0, t1, size, fnt, color, anim="pop", dur=0.14, fade_out=0.06, **kw)

    @staticmethod
    def text_w(t, fnt, size, stroke=0):
        pad = size * 0.35 + stroke * 2
        return max(_font(fnt, size).getlength(line) for line in t.split("\n")) + 2 * pad

    def vcr(self, t, t0, t1, y=1000, size=48, cx=W / 2):
        """Typed closed caption (white mono on a black box), centred. Returns two layers: use *F.vcr(...)."""
        w_ = self.text_w(t, "mono", size, 2)
        box = {"type": "rect", "x": cx - w_ / 2 + 4, "y": y - size * 0.78, "w": w_ - 8, "h": size * 1.5, "color": "#000000",
               "alpha": 0.82, "show": [round(t0, 4), round(t1, 4)]}
        return [box, self.text(t, cx - w_ / 2, y, t0, t1, size, "mono", "#ffffff", anim="type", dur=min(0.3, 0.012 * len(t)),
                               stroke=2, stroke_color="#000000", fade_out=0.0)]

    @staticmethod
    def wall(color, paper=False):
        return {"type": "fill", "color": color, "paper": paper}

    @staticmethod
    def tape(x, y, rot, t, dark=True):
        w_, h_ = 150, 42
        return {"type": "rect", "x": x - w_ / 2, "y": y - h_ / 2, "w": w_, "h": h_, "rot": rot,
                "color": "#2c2c2c" if dark else "#b9b7b0", "alpha": 0.94, "enter": {"t": round(t, 4), "dur": 0.1, "type": "pop"}}

    def print_size(self, src, fit):
        a = self.META[src]["w"] / self.META[src]["h"]
        ww, hh = fit[0], fit[0] / a
        if hh > fit[1]:
            hh, ww = fit[1], fit[1] * a
        return ww, hh

    def on_print(self, cx, cy, src, fit, rot, u, v):
        """Screen position of the normalised point (u, v) of a print laid out by pr() with zoom 1.0 (arrows that hit)."""
        ww, hh = self.print_size(src, fit)
        dx, dy = (u - 0.5) * ww, (v - 0.5) * hh
        th = math.radians(rot)
        return cx + dx * math.cos(th) - dy * math.sin(th), cy + dx * math.sin(th) + dy * math.cos(th)

    def pr(self, src, where, cx, cy, fit, rot, t_land, zoom=(1.0, 1.04), focus="faces", tapes="dark", border="#fbfaf4",
           enter="thump", sfx=True, **kw):
        """A bordered print, whole photo visible, landing at t_land (thump / drop), optionally gaffer-taped."""
        ww, hh = self.print_size(src, fit)
        # the thump starts 20 ms (< 1 frame) early: on a cut the first frame already shows the print, not an empty wall
        anim = {"t": round(t_land - 0.02, 4), "dur": 0.12, "type": "thump"} if enter == "thump" else \
               {"t": round(t_land - 0.14, 4), "dur": 0.22, "type": "drop", "from": [0, -900], "spin": 8}
        L = self.photo(src, where, zoom, focus, box=[round(cx - ww / 2, 1), round(cy - hh / 2, 1), round(ww, 1), round(hh, 1)],
                       border={"color": border, "px": 16}, shadow=True, rot=rot, enter=anim, **kw)
        out = [L]
        if tapes:
            th = math.radians(rot)
            for sx in (-1, 1):
                dx, dy = sx * (ww / 2 - 6), -hh / 2 - 6
                out.append(self.tape(cx + dx * math.cos(th) - dy * math.sin(th), cy + dx * math.sin(th) + dy * math.cos(th),
                                     rot + sx * 38, t_land + 0.05, tapes == "dark"))
        if sfx:
            self.sfx("drop", t_land, db=-21)
        return out

    def full(self, src, where, zoom=(1.0, 1.08), focus="faces", drift=None, **kw):
        """A full-frame photo with a slow move; for landscapes. Portraits should go through pr()."""
        return self.photo(src, where, zoom, focus, drift, **kw)

    @staticmethod
    def idx(layers, src):
        return next(i for i, L in enumerate(layers) if L.get("src") == src)

    def circle(self, layers, src, pid, t0, color=None, seed=1, width=8):
        """Hand-drawn circle around a person's face in a photo layer of this shot."""
        return {"type": "marker", "kind": "circle", "follow": {"layer": self.idx(layers, src), "face": f"person:{pid}"},
                "t0": round(t0, 4), "dur": 0.3, "color": color or self.RED, "width": width, "seed": seed}

    @staticmethod
    def doodles(times, spots, kind="star", color="#ffe066", size=36, seed=0):
        return [{"type": "doodle", "kind": kind, "x": x, "y": y, "size": size, "t": round(t, 4), "dur": 0.16, "color": color,
                 "width": 6, "seed": seed + i} for i, (t, (x, y)) in enumerate(zip(times, spots))]

    def check(self, x, y, t, s=1.0):
        return {"type": "marker", "kind": "line", "points": [[x, y], [x + 18 * s, y + 26 * s], [x + 62 * s, y - 38 * s]],
                "t0": round(t, 4), "dur": 0.16, "color": self.RED, "width": 9}

    @staticmethod
    def tr(kind, dur=None):
        return {"in": {"type": kind, "dur": dur or {"whip": 0.22, "glitch": 0.2, "dissolve": 0.3}.get(kind, 0.25)}}

    def arrow(self, x0, y0, x1, y1, t0, color=None, width=8, bend=0.16, seed=1):
        """A hand-drawn arrow from (x0, y0) to (x1, y1), drawn on t0. Aim it with on_print(..., *face_uv(...))."""
        return {"type": "marker", "kind": "arrow", "x0": round(x0), "y0": round(y0), "x1": round(x1), "y1": round(y1),
                "t0": round(t0, 4), "dur": 0.25, "color": color or self.RED, "width": width, "seed": seed, "bend": bend}

    @staticmethod
    def said(layers, origin, basis="", joke=""):
        """Record where the words in these layers came from, for the caption board (the user ticks or vetoes each line):
          origin  lyric | credit | brief | name | place  (the song or the user's own words, verbatim: trusted)
                  answer | note | fact | invented        (the user checks these: reworded, data, or Claude's joke)
          basis   what it rests on, short: "the user in chat: Alex did the driving", "step ps011 note", "trip.json km"
          joke    one id for every line of one joke, so its setup and payoff are reviewed together ("hike")
        Takes a layer or a list and returns it: [*F.said(F.tag("TOM: PRO DRIVER", ...), "answer", "...")]."""
        if origin not in checks.ORIGINS:
            raise ValueError(f"origin must be one of {', '.join(checks.ORIGINS)}")
        for L in (layers if isinstance(layers, list) else [layers]):
            if checks._strings(L):
                L["origin"] = origin
                if basis:
                    L["basis"] = basis
                if joke:
                    L["joke"] = joke
        return layers

    def page(self, srcs, where, t0, t1, wall=None, land=None, fit=None, rots=None, y=545, **kw):
        """One to three photos as whole prints side by side (portraits never cropped), each staying up >= MIN_PHOTO_S.
        land: landing time per photo (default: all on the cut t0; a later one needs MIN_PHOTO_S before t1).
        fit: (max w, max h), or one per photo (default: shares of the frame). Returns layers; **kw goes to pr()."""
        n = len(srcs)
        if not 1 <= n <= 3:
            raise ValueError("page() takes 1-3 photos (use a grid or a filmstrip for more)")
        land = list(land or [t0] * n)
        for src, tl in zip(srcs, land):
            if t1 - tl < MIN_PHOTO_S - 1e-3:
                raise ValueError(f"{src} would be up {t1 - tl:.2f}s (< {MIN_PHOTO_S}s): land it earlier or hold the page longer")
        cols = {1: [960], 2: [520, 1400], 3: [345, 960, 1575]}[n]
        fit = fit or {1: (1500, 900), 2: (800, 860), 3: (560, 820)}[n]
        fit = fit if isinstance(fit[0], (list, tuple)) else [fit] * n
        rots = rots or {1: [-1.5], 2: [-3, 3], 3: [-3, 2, -2]}[n]
        lay = [wall] if wall else []
        kw.setdefault("sfx", False)
        for src, cx, f, r, tl in zip(srcs, cols, fit, rots, land):
            lay += self.pr(src, where, cx, y, f, r, tl, **kw)
        for tl in sorted(set(land)):
            self.sfx("drop", tl, db=-23)
        return lay

    # ------------------------------------------------------------ the broader vocabulary (am/graphic.py, am/looks.py)
    def lyric_words(self, t0, t1, case=None):
        """Sung words between two film times, each cued on the 8th at/before its aligned onset -> lyric_type words."""
        out = []
        for ft, w in self.B.music.words:
            if t0 - 1e-3 <= ft < t1:
                ww = w.strip(",.!?;:\"")
                out.append({"w": ww.upper() if case == "upper" else ww.lower() if case == "lower" else ww, "t": self.cue(ft)})
        return out

    def lyric_type(self, words, x=W / 2, y=H / 2, mode="replace", font="anton", size=160, color="#ffffff", **kw):
        """Kinetic typography on the voice: replace (one big word at a time) | stack (lines build up) | line (karaoke)."""
        L = {"type": "lyric_type", "words": words, "mode": mode, "font": font, "size": size, "color": color, "x": x, "y": y}
        L.update(kw)
        return L

    def type_mask(self, src, where, text, t0=None, t1=None, size=520, x=W / 2, y=H / 2, font="anton", scale=None, **kw):
        """A photo seen through giant letters. scale=[[t, 1.0], [t2, 25]] zooms through them to reveal the photo."""
        L = {"type": "type_mask", "src": self.use(src, where), "text": text, "font": font, "size": size, "x": x, "y": y,
             "zoom": kw.pop("zoom", [1.0, 1.06]), "focus": kw.pop("focus", "faces")}
        if t0 is not None:
            L["t0"] = round(t0, 4)
        if t1 is not None:
            L["t1"] = round(t1, 4)
        if scale:
            L["scale"] = [[round(a, 4), b] for a, b in scale]
        L.update(kw)
        return L

    @staticmethod
    def shape(kind, x, y, w, h=None, color="#e85d2a", **kw):
        """circle | ring | rect | stripes | triangle | line; grow={"t", "dur"}, spin, blend (multiply/screen/overlay)."""
        L = {"type": "shape", "kind": kind, "x": x, "y": y, "w": w, "h": h if h is not None else w, "color": color}
        L.update(kw)
        return L

    def slices(self, src, where, t, n=7, stagger=None, dur=0.35, **kw):
        """A photo arriving as N strips, one after another (stagger defaults to a 16th note)."""
        L = {"type": "slices", "src": self.use(src, where), "n": n, "t": round(t, 4), "stagger": stagger or round(self.beat_len / 4, 4),
             "dur": dur, "zoom": kw.pop("zoom", [1.0, 1.04]), "focus": kw.pop("focus", "faces")}
        L.update(kw)
        return L

    def filmstrip(self, srcs, where, y=540, h=380, advance=None, speed=None, **kw):
        """A strip of frames with sprocket bands; advance=[beat times] steps a frame per beat, or speed=px/s scrolls."""
        L = {"type": "filmstrip", "srcs": [self.use(s, where) for s in srcs], "y": y, "h": h}
        if advance:
            L["advance"] = [round(a, 4) for a in advance]
        else:
            L["speed"] = speed or 140
        L.update(kw)
        return L

    # ------------------------------------------------------------ souq pop (Hajjaj-style pop collage; Oman)
    def tag(self, text, x, y, t0, t1, size=36, rot=-4, bg="#ffffff", fg="#141414", fnt="mono"):
        """A price tag (label with a punched hole) carrying a fact, slapped on at t0; "\\n" breaks long facts onto two
        short lines (they read faster than one wide plate). Returns layers: use *F.tag(...)."""
        lines = text.split("\n")
        w_ = max(_font(fnt, size).getlength(l_) for l_ in lines) + size * 2.6
        h_ = size * (2.0 + 1.15 * (len(lines) - 1))
        k = min(w_ * 0.16, h_ * 0.5)
        th = math.radians(rot)
        an = {"t": round(t0 - 0.02, 4), "dur": 0.12, "type": "thump"}
        return [self.shape("tag", x, y, w_, h_, bg, rot=rot, t0=round(t0, 4), t1=round(t1, 4), enter=an),
                self.text(text, x + k * 0.45 * math.cos(th), y + k * 0.45 * math.sin(th), t0, t1, size, fnt, fg, rot=rot,
                          anim="fade", dur=0.06, fade_out=0.06)]

    def block(self, text, x, y, t0, t1, color="#d7261e", fg="#fbf6ea", fnt="anton", size=120, pad=(44, 22), rot=0,
              enter="pop", **kw):
        """A flat colour block with a word on it (Anton slam, or Arabic: pass arabic(...) text with an arabic font)."""
        w_ = _font(fnt, size).getlength(text.split("\n")[0]) + 2 * pad[0]
        asc, desc = _font(fnt, size).getmetrics()
        h_ = (asc + desc) * 0.92 + 2 * pad[1]
        an = {"t": round(t0 - 0.02, 4), "dur": 0.14, "type": enter} if enter else None
        rect = self.shape("rect", x, y, w_, h_, color, rot=rot, t0=round(t0, 4), t1=round(t1, 4))
        if an:
            rect["enter"] = an
        return [rect, self.text(text, x, y, t0, t1, size, fnt, fg, rot=rot, anim="pop", dur=0.14, fade_out=0.06, **kw)]

    def frame(self, src, where, cx, cy, fit, t, motif="star8", colors=("#d7261e", "#fbf6ea", "#0f8a4a"), border=64,
              rim=18, rim_color="#141414", cell=None, zoom=(1.0, 1.04), focus="faces", enter="thump", scroll=None, rot=0,
              **kw):
        """A Hajjaj-style framed print: the whole photo at its own aspect inside a tiled pattern border and a dark rim.
        fit = (max w, max h) of the photo itself. Returns layers (use F.frame(...) + [...])."""
        ww, hh = self.print_size(src, fit)
        an = ({"t": round(t - 0.02, 4), "dur": 0.12, "type": "thump"} if enter == "thump" else
              {"t": round(t - 0.14, 4), "dur": 0.22, "type": "drop", "from": [0, -900], "spin": 6} if enter == "drop" else None)
        bw_, bh_ = ww + 2 * border, hh + 2 * border
        L = [self.shape("rect", cx, cy, bw_ + 2 * rim, bh_ + 2 * rim, rim_color, rot=rot),
             self.shape("pattern", cx, cy, bw_, bh_, motif=motif, cell=cell or border * 1.3, colors=list(colors),
                        hole=[border, border, ww, hh], rot=rot, **({"scroll": scroll} if scroll else {})),
             self.photo(src, where, zoom, focus, box=[round(cx - ww / 2, 1), round(cy - hh / 2, 1), round(ww, 1), round(hh, 1)],
                        rot=rot, **kw)]
        if an:
            for l_ in L:
                l_["enter"] = dict(an)
        return L

    def clip_size(self, name):
        """Display size (w, h) of a clip in photos/, after its rotation metadata (vertical phone clips are tall)."""
        if not hasattr(self, "_clip_sizes"):
            self._clip_sizes = {}
        if name not in self._clip_sizes:
            import cv2
            from .common import PHOTOS
            cap = cv2.VideoCapture(os.path.join(PHOTOS, name))
            ok, img = cap.read()
            self._clip_sizes[name] = (img.shape[1], img.shape[0]) if ok else (1920, 1080)
            self._clip_sizes[name + "#dur"] = cap.get(cv2.CAP_PROP_FRAME_COUNT) / max(cap.get(cv2.CAP_PROP_FPS) or 30, 1)
        return self._clip_sizes[name]

    def clip_dur(self, name):
        self.clip_size(name)
        return self._clip_sizes[name + "#dur"]

    def vframe(self, src, where, cx, cy, fit, t, start=0.0, motif="star8", colors=("#d7261e", "#fbf6ea", "#0f8a4a"),
               border=64, rim=18, rim_color="#141414", cell=None, zoom=(1.0, 1.0), focus=(0.5, 0.5), enter="thump",
               scroll=None, rot=0, **kw):
        """frame() for a video clip: the whole clip at its own aspect (tall for vertical phone clips) in a tiled border.
        start = the clip's source second shown at the shot start."""
        cw, ch = self.clip_size(src)
        a = cw / ch
        ww, hh = fit[0], fit[0] / a
        if hh > fit[1]:
            hh, ww = fit[1], fit[1] * a
        an = ({"t": round(t - 0.02, 4), "dur": 0.12, "type": "thump"} if enter == "thump" else
              {"t": round(t - 0.14, 4), "dur": 0.22, "type": "drop", "from": [0, -900], "spin": 6} if enter == "drop" else None)
        bw_, bh_ = ww + 2 * border, hh + 2 * border
        V = {"type": "video", "src": self.use(src, where), "start": round(start, 3), "zoom": list(zoom), "focus": list(focus),
             "box": [round(cx - ww / 2, 1), round(cy - hh / 2, 1), round(ww, 1), round(hh, 1)], "rot": rot}
        V.update(kw)
        L = [self.shape("rect", cx, cy, bw_ + 2 * rim, bh_ + 2 * rim, rim_color, rot=rot),
             self.shape("pattern", cx, cy, bw_, bh_, motif=motif, cell=cell or border * 1.3, colors=list(colors),
                        hole=[border, border, ww, hh], rot=rot, **({"scroll": scroll} if scroll else {})), V]
        if an:
            for l_ in L:
                l_["enter"] = dict(an)
        return L

    @staticmethod
    def sticker(t, x, y, size=180, text=None, img=None, rot=0, font="emoji", t1=None, **kw):
        """A die-cut sticker slapped on at t: an emoji/word (text) or a photo cut-out (img = 'cutouts/<name>.png')."""
        L = {"type": "sticker", "t": round(t, 4), "x": x, "y": y, "size": size, "rot": rot}
        if img:
            L["img"] = img
        else:
            L.update(text=text, font=font)
        if t1 is not None:
            L["t1"] = round(t1, 4)
        L.update(kw)
        return L

    # ------------------------------------------------------------ trips (Polarsteps import: tools/import_polarsteps.py)
    def trip(self):
        """cache/trip.json merged with the user's per-step context from project.json ("steps": {id: {label, note, skip}}),
        or None when the project has no imported trip."""
        p = os.path.join(CACHE, "trip.json")
        if not os.path.exists(p):
            return None
        d = json.load(open(p, encoding="utf-8"))
        over = self.project.get("steps") or {}
        for s in d["steps"]:
            o = over.get(s["id"], {})
            s["label"] = (o.get("label") or s.get("label") or s.get("place") or "").strip()
            s["note"] = (o.get("note", s.get("note", "")) or "").strip()
            s["skip"] = bool(o.get("skip", s.get("skip", False)))
        d["photo_step"] = {p: s for s in d["steps"] for p in s.get("photos", [])}
        return d

    @staticmethod
    def map_bounds(lonlats, pad=0.32, min_span=4.0, aspect=16 / 9):
        """lon/lat box around the points, padded and widened to the frame's aspect (cos-latitude corrected)."""
        lons, lats = [p[0] for p in lonlats], [p[1] for p in lonlats]
        cx, cy = (min(lons) + max(lons)) / 2, (min(lats) + max(lats)) / 2
        k = math.cos(math.radians(cy))
        w = max((max(lons) - min(lons)) * k, min_span * k) * (1 + 2 * pad)
        h = max(max(lats) - min(lats), min_span * 0.6) * (1 + 2 * pad)
        if w / h < aspect:
            w = h * aspect
        else:
            h = w / aspect
        return [round(cx - w / k / 2, 4), round(cx + w / k / 2, 4), round(cy - h / 2, 4), round(cy + h / 2, 4)]

    def route_map(self, trip, pin_times, zoom=(1.0, 1.06), color=None, label_size=46, labels=None, car=None, bounds=None):
        """A map layer for the trip: route drawn through every (non-skipped) step, reaching each stop at its
        pin time (put those on beats), dots + labels popping in as it arrives. Countries visited get a wash.
        Fewer pin_times than steps draws the trip so far. labels: {step id: on-screen name, "" hides it};
        car: an emoji (e.g. "🚗") that drives the route head. Route points far from every stop (the flights
        there and back) are left out, so the map frames the trip itself."""
        steps = [s for s in trip["steps"] if not s["skip"] and s.get("lon") is not None]
        lons, lats = [s["lon"] for s in steps], [s["lat"] for s in steps]
        pad = max(max(lons) - min(lons), max(lats) - min(lats), 1.0) * 0.5
        near = lambda p: min(lons) - pad <= p[0] <= max(lons) + pad and min(lats) - pad <= p[1] <= max(lats) + pad  # noqa: E731
        route = [[p[0], p[1]] for p in trip.get("route", []) if p[0] is not None and near(p)] or [[s["lon"], s["lat"]] for s in steps]
        pts, keys, j = [], [], 0
        for s, tp in zip(steps, pin_times):            # anchor each stop to the nearest later route point
            best = min(range(j, len(route)), key=lambda i: (route[i][0] - s["lon"]) ** 2 + (route[i][1] - s["lat"]) ** 2) if j < len(route) else None
            seg = route[j:best + 1] if best is not None else []
            pts += seg + [[s["lon"], s["lat"]]]
            keys.append([len(pts) - 1, round(tp, 4)])
            j = (best + 1) if best is not None else j
        bounds = bounds or self.map_bounds([[s["lon"], s["lat"]] for s in steps] + route)
        labels = labels or {}
        # labels: alternate above / below, and leave out labels that would sit on top of an earlier one
        from .props import MapProj
        proj = MapProj(1920, 1080, *bounds)
        placed, pins = [], []
        for n, (s, tp) in enumerate(zip(steps, pin_times)):
            x, y = proj(s["lon"], s["lat"])
            off = (0, -52) if n % 2 == 0 else (0, 56)
            lx, ly = x + off[0], y + off[1]
            name = labels.get(s["id"], s["label"])[:26]
            clash = bool(name) and any(abs(lx - a) < 230 and abs(ly - b) < 60 for a, b in placed)
            if name and not clash:
                placed.append((lx, ly))
            pins.append({"lon": s["lon"], "lat": s["lat"], "t": round(tp, 4), "label": "" if clash else name,
                         "off": list(off), "size": label_size, "rot": -3 if n % 2 == 0 else 2})
        route_l = {"points": pts, "keys": keys, "color": color or self.RED, "width": 6}
        if car:
            route_l["car"] = car
        return {"type": "map", "bounds": bounds, "highlight": trip["trip"].get("countries", []), "zoom": list(zoom),
                "focus_px": [960, 540], "route": route_l, "pins": pins}

    # ------------------------------------------------------------ save + lint
    need = staticmethod(checks.need)

    def lint(self):
        return [f"  {sid} {t0:7.2f}  {text[:38]!r:42s} visible {shown:.2f}s < {nd:.2f}s"
                for sid, t0, text, shown, nd in checks.reading_time(self.B.edl)]

    def save(self, path=None):
        p = self.B.save(path or os.path.join(OUT, f"{self.version}_edl.json"))
        edl = self.B.edl
        bad = self.lint()
        print("wrote", p, "| shots:", len(edl["shots"]), "| photos:", len(self.used), "| duration:", self.duration,
              "| song ends:", round(self.song_end, 3))
        print(f"reading-time lint: {len(bad)} caption(s) too short" + ("" if not bad else ":\n" + "\n".join(bad)))
        quick = screen_time(edl)
        print(f"screen-time lint: {len(quick)} photo(s) up < {MIN_PHOTO_S:.1f} s" +
              "".join(f"\n  {sid} {land:7.2f}  {src[:40]}  {d:.2f}s" for sid, src, land, d in quick))
        m = checks.musts(edl, self.project)
        print(f"must-haves lint: {len(m['missing'])} starred photo(s) missing, {len(m['order'])} story-order rule(s) broken" +
              "".join(f"\n  missing {x}" for x in m["missing"]) + "".join(f"\n  {r}: {why}" for r, why in m["order"]))
        res = checks.resolve(edl, self.beat_len)
        print(f"treatment lint: {len(res)} photo(s) whose look never arrives" +
              "".join(f"\n  {sid} {land:7.2f}  {src[:40]}  {why}" for sid, src, land, why in res))
        dup = checks.near_dupes(edl)
        print(f"near-duplicate lint: {len(dup)} pair(s) of look-alike photos close together" +
              "".join(f"\n  {ta:7.2f} {a[:34]}  ~  {tb:7.2f} {b[:34]}  ({why})" for a, b, ta, tb, why in dup))
        caps = checks.captions(edl, self.project)
        rv = checks.caption_review(caps)
        print(f"caption board: {len(caps)} lines, {sum(c['check'] for c in caps)} to check "
              f"({sum(c['origin'] == '?' for c in caps)} with no source), {rv['approved']} approved, "
              f"{len(rv['unreviewed'])} not reviewed yet, {len(rv['vetoed'])} vetoed" +
              "".join(f"\n  VETOED {c['shot']} {c['t0']:7.2f}  {c['text'][:40]!r}  {rv['decisions'][c['key']].get('comment', '')}"
                      for c in rv["vetoed"]))
        return p
