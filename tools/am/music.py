"""Film-time musical events: song analysis mapped through the EDL's audio segments."""
import json, math, os
import numpy as np

from .common import CACHE

KINDS = ["beats", "downbeats", "kicks", "snares", "cymbals", "bass_hits", "onsets", "vocal_onsets"]


class MusicMap:
    def __init__(self, edl):
        slug = edl["meta"]["analysis"]
        self.a = json.load(open(os.path.join(CACHE, "audio", f"{slug}.json")))
        self.segments = edl["audio"]["segments"]
        self.ev = {}
        for kind in KINDS:
            src = self.a[kind]
            if src and isinstance(src[0], dict):
                pairs = [(e["t"], e.get("s", 1.0)) for e in src]
            else:
                pairs = [(t, 1.0) for t in src]
            out = []
            for seg in self.segments:
                a, b = seg["src"]
                for t, s in pairs:
                    if a - 1e-4 <= t < b - 1e-4:
                        out.append((seg["at"] + (t - a), s))
            out.sort()
            self.ev[kind] = (np.array([o[0] for o in out]), np.array([o[1] for o in out]))
        # lyric words in film time
        self.words = []
        for line in self.a.get("lyrics", []):
            for w in line.get("words", []):
                ft = self.to_film(w["t"])
                if ft is not None:
                    self.words.append((ft, w["w"]))
        self.duration = max(s["at"] + s["src"][1] - s["src"][0] for s in self.segments)

    def to_film(self, song_t):
        for seg in self.segments:
            a, b = seg["src"]
            if a - 1e-4 <= song_t < b:
                return seg["at"] + song_t - a
        return None

    def events(self, kind, t0, t1, min_s=0.0):
        t, s = self.ev[kind]
        m = (t >= t0) & (t < t1) & (s >= min_s)
        return list(zip(t[m].tolist(), s[m].tolist()))

    def pulse(self, kind, t, decay=0.12, min_s=0.3, window=None):
        """Sum of exponentially decaying impulses from events at or before t."""
        tt, ss = self.ev[kind]
        lo = np.searchsorted(tt, t - 6 * decay)
        hi = np.searchsorted(tt, t, side="right")
        v = 0.0
        for i in range(lo, hi):
            if ss[i] >= min_s and (window is None or window[0] <= tt[i] < window[1]):
                v += min(ss[i], 1.2) * math.exp(-(t - tt[i]) / decay)
        return min(v, 1.5)

    def nearest(self, kind, t):
        tt, _ = self.ev[kind]
        if not len(tt):
            return None
        i = int(np.argmin(np.abs(tt - t)))
        return float(tt[i])
