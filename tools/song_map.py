"""Per-bar map of a song for planning an edit: bar times, loudness, drums, vocal activity per quarter-bar,
the aligned sung words with their beat position, and section starts.

  python tools/song_map.py <slug> [--segments "in,out,at;in,out,at"]

With --segments the film time of every bar is printed too (bars that are cut out are marked).
Vocal per quarter: '#' singing, '+' some, '.' faint, ' ' none (synths can leak into the vocal stem).
"""
import argparse, json, os, sys
import numpy as np
import librosa

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from am.common import CACHE  # noqa: E402

SR = 22050


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--segments", default="")
    a = ap.parse_args()
    d = json.load(open(os.path.join(CACHE, "audio", f"{a.slug}.json"), encoding="utf-8"))
    segs = [tuple(float(x) for x in s.split(",")) for s in a.segments.split(";") if s.strip()]

    def film(t):
        for s0, s1, at in segs:
            if s0 <= t < s1:
                return t - s0 + at
        return None
    db = np.array(d["downbeats"])
    bp = d["beat_period"]
    stems = os.path.join(CACHE, "stems", a.slug)
    voc, _ = librosa.load(os.path.join(stems, "vocals.wav"), sr=SR)
    drm, _ = librosa.load(os.path.join(stems, "drums.wav"), sr=SR)

    def rms(x, t0, t1):
        s = x[int(t0 * SR):int(t1 * SR)]
        return 20 * np.log10(np.sqrt(np.mean(s ** 2)) + 1e-9) if len(s) else -99
    words = [(w["t"], w["w"]) for L in d.get("lyrics", []) for w in L.get("words", [])]
    sec = {round(s["start"], 2): s for s in d.get("sections", [])}
    ends = list(db[1:]) + [d["duration"]]
    print(f"{a.slug}: {d['tempo']:.2f} BPM, beat {bp:.4f}s, {len(db)} bars, constant grid: {d['grid'].get('constant')}, "
          f"lyrics match_z {(d.get('lyrics_meta') or {}).get('match_z')}")
    print("bar  song_t   " + ("film_t   " if segs else "") + "drums vocal/quarter  words (beat position in the bar)")
    for i, (t0, t1) in enumerate(zip(db, ends)):
        if round(t0, 2) in sec:
            s = sec[round(t0, 2)]
            print(f"---- section: {s['bars']} bars, energy {s['energy']:.2f}, vocal {s['vocal']:.2f}")
        q = [rms(voc, t0 + k * (t1 - t0) / 4, t0 + (k + 1) * (t1 - t0) / 4) for k in range(4)]
        qs = "".join("#" if v > -18 else "+" if v > -25 else "." if v > -35 else " " for v in q)
        dr = rms(drm, t0, t1)
        ws = " ".join(f"{w}@{(t - t0) / bp:.1f}" for t, w in words if t0 <= t < t1)
        ft = film(t0)
        fcol = (f"{ft:7.2f}  " if ft is not None else "  (cut)  ") if segs else ""
        print(f"{i:3d}  {t0:7.2f}  {fcol}{'DRUMS' if dr > -25 else '  .  '}  [{qs}]  {ws}")
    jp = os.path.join(CACHE, f"joins_{a.slug}.txt")
    if os.path.exists(jp):
        print("\nbest single joins (tools/find_joins.py):")
        print("\n".join(open(jp, encoding="utf-8").read().splitlines()[:6]))


if __name__ == "__main__":
    main()
