"""The song folder (song/<slug>/song-map.json) as a Python object, for the studio's own side: the critic's eyes, the
director runner's note context, the web app. Standard library only.

    from am.song import Song, FilmClock
    song = Song("projects/my-trip", "my_song")   # or the song/<slug>/ folder itself
    song.t(17, 2.5)                          # song seconds of bar 17, 2.5 beats after its downbeat
    song.pos(83.2)                           # (bar, beat) -> (37, 1.98)
    song.at(83.2)                            # {'t', 'bar', 'beat', 'section', 'chord', 'line', 'word', 'moments'}
    song.cue(t)                              # the beat or 8th at or just before t (where lyric text appears)
    song.moments(3)                          # the ★★★ moments
    song.section("chorus 2")                 # {'name', 't0', 't1', 'bar0', 'bar1', ...}
    clock = FilmClock(edl)                   # film time <-> song time through the EDL's audio segments (a join)
    clock.song(t_film), clock.film(t_song)

Times in the song folder are song seconds. A film's edit can have one join (house rule 1), so film time and song time
differ after it: FilmClock maps them (the same rule as am/music.py's MusicMap, without numpy).
"""
import bisect, json, math, os


class Song:
    def __init__(self, where, slug=None):
        where = os.path.abspath(where)
        if os.path.exists(os.path.join(where, "song-map.json")):
            self.dir = where
        else:
            if not slug:
                import sys
                sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                from am.util import song_slug
                slug = song_slug(where)
            if not slug:
                raise FileNotFoundError(f"no song folder in {where} (run Analyse first)")
            self.dir = os.path.join(where, "song", slug)
        self.slug = os.path.basename(self.dir)
        self.m = self._load("song-map.json")
        self.duration = float(self.m["duration"])
        self.beats = [float(b) for b in self.m["beats"]]
        self.bars = self.m["bars"]
        self.downbeats = [float(b["t"]) for b in self.bars]
        self.beat_s = float(self.m["tempo"]["beat_s"])
        self.bpm = float(self.m["tempo"]["bpm"])
        self.sections = self.m["sections"]
        self.lines = self.m.get("lyrics") or []
        self.words = sorted(((float(w["t"]), w["w"], x.get("i", k)) for k, x in enumerate(self.lines)
                             for w in x.get("words") or []))
        self._dbi = [self._nearest_beat(d) for d in self.downbeats]

    def _load(self, name):
        with open(os.path.join(self.dir, name), encoding="utf-8") as f:
            return json.load(f)

    # ------------------------------------------------------------------ time <-> bar:beat
    def _nearest_beat(self, t):
        i = bisect.bisect_left(self.beats, t)
        if i > 0 and (i == len(self.beats) or t - self.beats[i - 1] < self.beats[i] - t):
            i -= 1
        return i

    def _beat_time(self, x):
        """Time of fractional beat index x (extrapolated with the beat length outside the grid)."""
        B = self.beats
        if x <= 0:
            return B[0] + x * self.beat_s
        if x >= len(B) - 1:
            return B[-1] + (x - (len(B) - 1)) * self.beat_s
        i = int(math.floor(x))
        return B[i] + (x - i) * (B[i + 1] - B[i])

    def t(self, bar, beat=0.0):
        """Song time of bar:beat (bar 0 = the first downbeat, beat 0 = the downbeat, 2.5 = the 8th after beat 2)."""
        if bar < 0 or bar >= len(self._dbi):
            base = (bar - (len(self._dbi) - 1)) * 4 + self._dbi[-1] if bar >= 0 else bar * 4 + self._dbi[0]
            return self._beat_time(base + beat)
        return self._beat_time(self._dbi[bar] + beat)

    def pos(self, t):
        """(bar, beat) of song time t, or None outside the beat grid."""
        if not self.beats or t < self.beats[0] - 2 * self.beat_s or t > self.beats[-1] + 4 * self.beat_s:
            return None
        bar = max(0, bisect.bisect_right(self.downbeats, t + 1e-6) - 1)
        j = bisect.bisect_right(self.beats, t + 1e-6) - 1
        if j < 0:
            frac = (t - self.beats[0]) / self.beat_s
            j = 0
        else:
            nxt = self.beats[j + 1] if j + 1 < len(self.beats) else self.beats[j] + self.beat_s
            frac = (t - self.beats[j]) / (nxt - self.beats[j])
        return bar, round(j - self._dbi[bar] + frac, 3)

    def cue(self, t):
        """The beat or 8th at or just before t: where lyric text for a word sung at t appears."""
        grid = []
        for i, b in enumerate(self.beats):
            grid.append(b)
            nxt = self.beats[i + 1] if i + 1 < len(self.beats) else b + self.beat_s
            grid.append((b + nxt) / 2)
        i = bisect.bisect_right(grid, t + 1e-4) - 1
        return grid[i] if i >= 0 else t

    def snap(self, t, step="beat"):
        """Nearest beat ('beat'), 8th ('8th') or downbeat ('bar') to t."""
        arr = self.downbeats if step == "bar" else self.beats
        if step == "8th":
            arr = sorted(self.beats + [(a + b) / 2 for a, b in zip(self.beats, self.beats[1:])])
        i = bisect.bisect_left(arr, t)
        cands = arr[max(0, i - 1):i + 1]
        return min(cands, key=lambda x: abs(x - t)) if cands else t

    # ------------------------------------------------------------------ what happens when
    def section_at(self, t):
        for s in self.sections:
            if s["t0"] <= t < s["t1"]:
                return s
        return None

    def section(self, name):
        for s in self.sections:
            if s["name"] == name:
                return s
        raise KeyError(f"no section {name!r}: {', '.join(s['name'] for s in self.sections)}")

    def chord_at(self, t):
        for c in self.m.get("chords") or []:
            if c["t"] <= t < (c["end"] or 1e9):
                return c["chord"]
        return None

    def line_at(self, t, hold=0.3):
        for x in self.lines:
            if x["t"] - 0.05 <= t <= float(x.get("end") or x["t"] + 2) + hold:
                return x
        return None

    def word_at(self, t):
        i = bisect.bisect_right([w[0] for w in self.words], t + 1e-4) - 1
        if i < 0:
            return None
        w = self.words[i]
        line = self.line_at(t)
        return w[1] if line is not None and line.get("i", self.lines.index(line)) == w[2] else None

    def moments(self, stars=1):
        return [m for m in self.m.get("moments") or [] if m["stars"] >= stars]

    def at(self, t):
        p = self.pos(t)
        s = self.section_at(t)
        line = self.line_at(t)
        near = [m for m in self.m.get("moments") or [] if abs(m["t"] - t) < 0.25]
        return {"t": round(t, 3), "bar": p[0] if p else None, "beat": p[1] if p else None, "section": s["name"] if s else None,
                "chord": self.chord_at(t), "line": line["text"] if line else None, "word": self.word_at(t),
                "moments": [f"{'★' * m['stars']} {m['text']}" for m in near]}


class FilmClock:
    """Film time <-> song time through an EDL's audio segments ({"src": [song_in, song_out], "at": film_t}). Without
    an EDL (or segments) film time is song time."""

    def __init__(self, edl=None):
        segs = ((edl or {}).get("audio") or {}).get("segments") or []
        self.segs = [(float(s["at"]), float(s["src"][0]), float(s["src"][1])) for s in segs if s.get("src")]

    def song(self, t):
        """The song time playing at film time t, or None (silence after the song, or before it)."""
        if not self.segs:
            return t
        for at, a, b in self.segs:
            if at - 1e-4 <= t < at + (b - a):
                return a + (t - at)
        return None

    def film(self, t):
        """The film time where song time t plays, or None (cut out by the join)."""
        if not self.segs:
            return t
        for at, a, b in self.segs:
            if a - 1e-4 <= t < b:
                return at + (t - a)
        return None


def at_film(song, clock, t):
    """song.at() for a film time (the song time it plays; None fields in the silence after the song), with "film"."""
    st = clock.song(t) if clock else t
    if st is None:
        before = bool(clock and clock.segs) and t < min(at for at, _, _ in clock.segs)
        return {"t": None, "film": round(t, 3), "bar": None, "beat": None,
                "section": "before the song" if before else "after the song", "chord": None,
                "line": None, "word": None, "moments": []}
    return dict(song.at(st), film=round(t, 3))
