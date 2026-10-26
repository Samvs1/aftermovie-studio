"""Per-song repairs to the aligned lyric timing, kept as data in project.json so they survive every re-ingest.

  python tools/studio.py run <project> fix_lyrics.py            (align_words.py runs it by itself after aligning)

project.json "lyrics_fix" (write it when a song's aligned words are wrong in a way you checked by ear):
  "held_lines": ["I, I did it all", "Oh, whoa"]
      Lines that open on a long held note the forced aligner (a speech model) skips: the first word goes back to the
      LRC line start (snapped to a beat within 0.15 s); later words keep their times only while they stay in order.
  "words": [{"w": "saw", "near": 87.0, "t": 86.62, "why": "the aligner puts it late"}]
      Exact song times for single words: the word w aligned nearest to song time `near` gets time t.
Running it twice changes nothing.
"""
import json, os, sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from am.common import CACHE, project  # noqa: E402


def apply(path, rules):
    """Apply the rules to cache/audio/<slug>.json in place; returns a list of what changed."""
    if not rules:
        return []
    a = json.load(open(path, encoding="utf-8"))
    beats = np.array(a["beats"])
    done = []
    held = tuple(rules.get("held_lines") or [])
    for L in a.get("lyrics", []):
        ws = L.get("words") or []
        if not held or not ws or "t_lrc" not in ws[0] or not L.get("text", "").startswith(held):
            continue
        if abs(ws[0]["t"] - ws[0]["t_lrc"]) <= 0.35:
            continue
        t0 = ws[0]["t_lrc"]
        j = int(np.argmin(np.abs(beats - t0)))
        if abs(beats[j] - t0) <= 0.15:
            t0 = float(beats[j])
        ws[0]["t"], ws[0]["t_end"], ws[0]["fixed"] = round(t0, 3), round(t0 + 0.8, 3), "held note: LRC line start"
        prev = t0
        for w in ws[1:]:
            if w["t"] <= prev + 0.05:                  # out of order after the repair: fall back to the LRC time
                w["t"], w["fixed"] = round(max(w.get("t_lrc", w["t"]), prev + 0.1), 3), "order"
            prev = w["t"]
        done.append(f"{t0:7.2f}  held line: {L['text']}")
    for r in rules.get("words") or []:
        cands = [(abs(w["t"] - r["near"]), w) for L in a.get("lyrics", []) for w in L.get("words") or []
                 if w["w"].lower().strip(",.!?'\"") == r["w"].lower()]
        if not cands:
            done.append(f"  !! word {r['w']!r} not found near {r['near']}")
            continue
        d, w = min(cands, key=lambda c: c[0])
        if d > 2.0:
            done.append(f"  !! word {r['w']!r}: nearest is {d:.1f}s from {r['near']}, left alone")
            continue
        if abs(w["t"] - r["t"]) > 1e-3:
            w["t"], w["fixed"] = round(r["t"], 3), r.get("why", "lyrics_fix")
            w["t_end"] = max(w.get("t_end", r["t"]), round(r["t"] + 0.2, 3))
            done.append(f"{r['t']:7.2f}  word {r['w']!r}")
    json.dump(a, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return done


def main():
    pj = project()
    slug = (pj.get("song") or {}).get("slug") or (sys.argv[1] if len(sys.argv) > 1 else None)
    if not slug:
        sys.exit("no song slug in project.json")
    rules = pj.get("lyrics_fix")
    if not rules:
        print("no lyrics_fix rules in project.json: nothing to do")
        return
    done = apply(os.path.join(CACHE, "audio", f"{slug}.json"), rules)
    print(f"lyrics_fix: {len(done)} repair(s)" + "".join("\n" + d for d in done))


if __name__ == "__main__":
    main()
