"""Transcribe the lyric from the vocal stem with Whisper, for songs LRCLIB has no synced lyrics for (local or
non-English songs often). analyze_audio.py uses the result when there is no LRC; align_words.py then aligns it.

  python tools/transcribe_lyrics.py <slug> [--language nl] [--model openai/whisper-large-v3-turbo]

Only stretches where the vocal stem is clearly singing are transcribed (Whisper invents text over instrumentals),
in pieces of up to 28 s. Writes cache/lyrics/<slug>_transcribed.json: {"model", "language", "lines": [{t, end, text,
words: [{w, t, end}]}]}. Transcriptions mishear: show the text to the user and fix it before captions use it.
GPU: Whisper large-v3-turbo in fp16 (~2 GB of VRAM, ~20 s per song on an RTX 4060); on the CPU it takes minutes.
"""
import argparse, json, os, re, sys
import numpy as np
import librosa

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from am.common import CACHE  # noqa: E402
from am import device as D  # noqa: E402

SR = 16000
JUNK = re.compile(r"(thank(s| you) for watching|subtitles? by|amara\.org|transcribed by|♪|\[music\]|^\s*(thank you|thanks)\.?\s*$)", re.I)


def sung_regions(v, max_len=28.0, gap=1.2):
    """[(t0, t1)] where the vocal stem is within 25 dB of its loud level, gaps under `gap` s bridged."""
    hop = 160
    r = librosa.feature.rms(y=v, frame_length=1024, hop_length=hop)[0]
    db = 20 * np.log10(r + 1e-7)
    on = db > np.percentile(db, 95) - 25
    t = np.arange(len(on)) * hop / SR
    regs, start, last = [], None, None
    for i, o in enumerate(on):
        if o:
            if start is None:
                start = t[i]
            elif t[i] - last > gap:
                regs.append((start, last))
                start = t[i]
            last = t[i]
    if start is not None:
        regs.append((start, last))
    out = []
    for a, b in regs:
        a, b = max(0.0, a - 0.3), b + 0.4
        if b - a < 0.6:
            continue
        while b - a > max_len:                 # split long stretches at their quietest point
            lo, hi = int((a + max_len * 0.6) * SR / hop), int((a + max_len) * SR / hop)
            k = lo + int(np.argmin(db[lo:hi]))
            out.append((a, k * hop / SR))
            a = k * hop / SR
        out.append((a, b))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--language", default=None, help="ISO code (en, nl, fr, ...); default: Whisper detects it")
    ap.add_argument("--model", default="openai/whisper-large-v3-turbo")
    a = ap.parse_args()
    import torch
    from transformers import pipeline
    dev = D.pick(2.5)
    v, _ = librosa.load(os.path.join(CACHE, "stems", a.slug, "vocals.wav"), sr=SR, mono=True)
    regs = sung_regions(v)
    print(f"{a.slug}: {len(regs)} sung stretches, {sum(b - x for x, b in regs):.0f} s of singing; {a.model} on {dev}")
    asr = pipeline("automatic-speech-recognition", model=a.model, device=dev,
                   dtype=torch.float16 if dev == "cuda" else torch.float32)
    gk = {"task": "transcribe"}
    if a.language:
        gk["language"] = a.language
    words = []
    for t0, t1 in regs:
        out = asr(v[int(t0 * SR):int(t1 * SR)].copy(), return_timestamps="word", generate_kwargs=gk)
        text = out.get("text", "")
        ws = out.get("chunks") or []
        toks = [w["text"].strip().lower() for w in ws]
        if JUNK.search(text) or (len(toks) >= 8 and max(toks.count(x) for x in set(toks)) > 0.5 * len(toks)):
            print(f"   {t0:6.1f}-{t1:6.1f}  (skipped: looks invented) {text[:60]}")
            continue
        for w in ws:
            s, e = w["timestamp"]
            if not w["text"].strip():
                continue
            s = t0 + (s or 0.0)
            e = t0 + (e if e is not None else (s - t0) + 0.3)
            words.append({"w": w["text"].strip(), "t": round(s, 3), "end": round(max(e, s + 0.05), 3)})
        print(f"   {t0:6.1f}-{t1:6.1f}  {text.strip()[:90]}")
    del asr
    D.release()
    # words -> lines: break on a pause, after sentence punctuation, or at 10 words
    lines, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt is None or nxt["t"] - w["end"] > 0.6 or re.search(r"[.!?]$", w["w"]) or len(cur) >= 10:
            lines.append({"t": cur[0]["t"], "end": cur[-1]["end"], "text": " ".join(x["w"] for x in cur).strip(" ,"),
                          "words": [dict(x, w=x["w"].strip(",.!?")) for x in cur if x["w"].strip(",.!?")]})
            cur = []
    lines = [x for x in lines if x["words"]]
    p = os.path.join(CACHE, "lyrics", f"{a.slug}_transcribed.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump({"model": a.model, "language": a.language or "auto", "lines": lines}, open(p, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"{len(lines)} lines, {len(words)} words -> {p}")


if __name__ == "__main__":
    main()
