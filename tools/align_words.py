"""Forced-align the lyric words on the Demucs vocal stem (torchaudio MMS_FA) for accurate sung onsets.

  python tools/align_words.py <slug> [--dry]

LRC word times are interpolated inside each line and can run a few hundred ms late, so captions keyed
to them pop up after the word is sung. This aligns every line separately on the isolated vocals, in a
window from just before the line to just after the next line starts. '*' wildcards at both ends absorb
neighbouring singing. It then writes the result back into cache/audio/<slug>.json:
  words[i]["t"]     = aligned onset (what the builders use)
  words[i]["t_end"] = aligned end
  words[i]["t_lrc"] = the original LRC time
  words[i]["fa"]    = alignment score (0..1)
Words with a near-zero score (< MIN_SCORE) or out of order keep the LRC time. (Line starts agree with LRC
to ~0.1 s; inside a line, LRC spreads words evenly over held notes and runs up to several seconds late.)
"""
import argparse, json, os, re, sys
import numpy as np
import torch
import torchaudio
import librosa

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from am.common import CACHE  # noqa: E402

SR = 16000
MIN_SCORE = 0.02


def norm(w):
    return re.sub(r"[^a-z']", "", w.lower().replace("’", "'"))


def chunk_align(voc, lines, model, tok, aligner, max_span=30.0, gap=5.5):
    """Align runs of consecutive lines together ('*' between lines absorbs ad-libs and breaths), so a word can never
    jump into a neighbouring line's window (the per-line windows overlap the next line). Returns {(line, word): (ts, te,
    score)} for words that land inside their own line's window."""
    starts = [L["words"][0].get("t_lrc", L["words"][0]["t"]) if L.get("words") else None for L in lines]
    idx = [i for i, s in enumerate(starts) if s is not None]
    chunks, cur = [], []
    for i in idx:
        if cur and (starts[i] - starts[cur[0]] > max_span or starts[i] - starts[cur[-1]] > gap):
            chunks.append(cur)
            cur = []
        cur.append(i)
    if cur:
        chunks.append(cur)
    out = {}
    for ci, ch in enumerate(chunks):
        t0 = max(0.0, starts[ch[0]] - 1.5)
        nxt = chunks[ci + 1][0] if ci + 1 < len(chunks) else None
        last = lines[ch[-1]]["words"][-1]
        t1 = (starts[nxt] - 0.25) if nxt is not None else last.get("t_lrc", last["t"]) + 4.0
        t1 = max(t1, last.get("t_lrc", last["t"]) + 1.0)
        trans, owners = ["*"], []
        for i in ch:
            for k, w in enumerate(lines[i]["words"]):
                n = norm(w["w"])
                if n:
                    trans.append(n)
                    owners.append((i, k))
            trans.append("*")
        seg = torch.tensor(voc[int(t0 * SR):int(t1 * SR)])[None]
        with torch.inference_mode():
            em, _ = model(seg)
            spans = aligner(em[0], tok(trans))
        ratio = seg.size(1) / em.size(1) / SR
        j = 0
        for ti, tk in enumerate(trans):
            if tk == "*":
                continue
            i, k = owners[j]
            j += 1
            sp = spans[ti]
            ts, te = t0 + sp[0].start * ratio, t0 + sp[-1].end * ratio
            lo = starts[i] - 1.2
            nx = next((starts[q] for q in range(i + 1, len(lines)) if starts[q] is not None), starts[i] + 8.0)
            if lo <= ts <= nx + 0.6:
                out[(i, k)] = (ts, te, float(np.mean([s.score for s in sp])))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--mode", choices=["auto", "line"], default="auto",
                    help="auto: whole runs of lines first (robust), per-line where that fails; line: the old per-line pass")
    a = ap.parse_args()
    path = os.path.join(CACHE, "audio", f"{a.slug}.json")
    d = json.load(open(path, encoding="utf-8"))
    voc, _ = librosa.load(os.path.join(CACHE, "stems", a.slug, "vocals.wav"), sr=SR, mono=True)
    bundle = torchaudio.pipelines.MMS_FA
    model = bundle.get_model(with_star=True)
    tok = bundle.get_tokenizer()
    aligner = bundle.get_aligner()
    lines = d.get("lyrics") or []
    if not lines:
        print("no lyrics in the analysis: nothing to align")
        return
    for L in lines:                          # re-runs start from the LRC times, not from an earlier alignment
        for w in L.get("words", []):
            if "t_lrc" in w:
                w["t"] = w["t_lrc"]
    chunked = chunk_align(voc, lines, model, tok, aligner) if a.mode == "auto" else {}
    report = []
    for li, L in enumerate(lines):
        ws = L.get("words", [])
        if not ws:
            continue
        lrc = [w.get("t_lrc", w["t"]) for w in ws]
        t0 = lrc[0] - 1.2
        nxt = lines[li + 1]["words"][0].get("t_lrc", lines[li + 1]["words"][0]["t"]) if li + 1 < len(lines) and lines[li + 1].get("words") else lrc[-1] + 3
        t1 = max(nxt + 0.35, lrc[-1] + 1.0)
        seg = torch.tensor(voc[max(0, int(t0 * SR)):int(t1 * SR)])[None]
        words = [norm(w["w"]) for w in ws]
        keep = [i for i, w in enumerate(words) if w]
        transcript = ["*"] + [words[i] for i in keep] + ["*"]
        with torch.inference_mode():
            em, _ = model(seg)
            spans = aligner(em[0], tok(transcript))
        ratio = seg.size(1) / em.size(1) / SR
        prev = -1.0
        for k, i in enumerate(keep):
            sp = spans[k + 1]
            ts = t0 + sp[0].start * ratio
            te = t0 + sp[-1].end * ratio
            score = float(np.mean([s.score for s in sp]))
            old = lrc[i]
            c = chunked.get((li, i))
            if c and c[2] >= MIN_SCORE and c[0] > prev:      # the whole-run alignment wins when it is usable
                ts, te, score = c
            # singing scores low against a speech model; line starts agree with LRC to ~0.1 s, so trust the
            # acoustic times unless the score is near zero or the order breaks
            ok = score >= MIN_SCORE and ts > prev and lrc[0] - 1.0 <= ts <= t1
            if ok:
                prev = ts
            report.append((ts - old, score, ws[i]["w"], old, ts, ok))
            if not a.dry:
                ws[i]["t_lrc"] = round(old, 3)
                ws[i]["t"] = round(ts if ok else old, 3)
                ws[i]["t_end"] = round(te if ok else old + 0.3, 3)
                ws[i]["fa"] = round(score, 3)
    for dt, sc, w, old, new, ok in report:
        print(f"{w:>14s}  lrc {old:7.2f}  sung {new:7.2f}  ({dt:+.2f}s)  score {sc:.2f}{'' if ok else '  -> kept LRC'}")
    dts = np.array([r[0] for r in report if r[5]])
    print(f"\n{len(dts)}/{len(report)} words aligned; median shift {np.median(dts):+.3f}s, "
          f"{np.mean(dts < -0.1) * 100:.0f}% of words sung >0.1 s before their LRC time")
    if not a.dry:
        json.dump(d, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        print("updated", path)
        from am.common import project
        from fix_lyrics import apply                     # this song's own repairs (project.json lyrics_fix)
        for line in apply(path, project().get("lyrics_fix")):
            print("lyrics_fix:", line)


if __name__ == "__main__":
    main()
