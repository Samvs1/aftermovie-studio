"""Find the cleanest single join in a song (for a shorter edit that still sounds continuous).

  python tools/find_joins.py <slug> [--min-skip 16] [--top 10]

Compares every pair of downbeats (bar i -> bar j, skipping >= min-skip bars) on the Demucs stems:
harmony (other+bass chroma), drum pattern, vocal envelope, two bars AFTER and two bars BEFORE the
join. High scores mean the listener hears the same music either side. For the best candidates it then
refines the destination offset (mel correlation) and suggests a cut point inside a vocal gap.

Rule (from Sam): the song must sound continuous; use at most ONE join, only between identical passages.
"""
import argparse, json, os, sys
import numpy as np
import librosa

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze_audio import SONGS, MUSIC, ROOT  # noqa: E402

SR, HOP = 22050, 512


def bar_features(sig_feats, bars, n=24):
    """Per-bar feature vectors, each bar resampled to n frames."""
    out = []
    for a, b in zip(bars[:-1], bars[1:]):
        f0, f1 = librosa.time_to_frames([a, b], sr=SR, hop_length=HOP)
        vecs = []
        for F in sig_feats:
            seg = F[:, f0:max(f1, f0 + 2)]
            idx = np.linspace(0, seg.shape[1] - 1, n).astype(int)
            v = seg[:, idx].ravel()
            vecs.append((v - v.mean()) / (v.std() + 1e-9))
        out.append(vecs)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--min-skip", type=int, default=16)
    ap.add_argument("--top", type=int, default=10)
    a = ap.parse_args()
    d = json.load(open(os.path.join(ROOT, "cache", "audio", f"{a.slug}.json")))
    bars = np.array(d["downbeats"] + [d["duration"]])
    st = {k: librosa.load(os.path.join(ROOT, "cache", "stems", a.slug, f"{k}.wav"), sr=SR)[0] for k in ["drums", "bass", "vocals", "other"]}
    harm = librosa.feature.chroma_stft(y=st["other"] + st["bass"], sr=SR, hop_length=HOP)
    drum = librosa.onset.onset_strength(y=st["drums"], sr=SR, hop_length=HOP)[None, :]
    voc = librosa.feature.rms(y=st["vocals"], hop_length=HOP)
    BF = bar_features([harm, drum, voc], bars)
    nb = len(BF)

    def s(i, j):  # mean correlation of one bar pair across harmony / drums / vocals
        return float(np.mean([np.dot(BF[i][k], BF[j][k]) / len(BF[i][k]) for k in range(3)]))
    cands = []
    for i in range(3, nb - 3):
        for j in range(i + a.min_skip, nb - 3):
            score = np.mean([s(i, j), s(i + 1, j + 1), s(i - 1, j - 1), s(i - 2, j - 2)])
            cands.append((score, i, j))
    cands.sort(reverse=True)
    print(f"{a.slug}: {nb} bars; top joins (bar i -> bar j). Result length = t_i + (song_end - t_j)")
    y, _ = librosa.load(os.path.join(MUSIC, SONGS[a.slug]), sr=SR)
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=256))
    M = librosa.amplitude_to_db(librosa.feature.melspectrogram(S=S ** 2, sr=SR, n_mels=64))
    shown = 0
    for score, i, j in cands:
        if shown >= a.top:
            break
        ti, tj = bars[i], bars[j]
        # refine destination offset on the mel spectrum
        f0 = librosa.time_to_frames(ti, sr=SR, hop_length=256)
        A = M[:, f0:f0 + int(1.5 * SR / 256)]
        best = (-1, 0.0)
        for off in np.arange(-0.3, 0.31, 0.01):
            g0 = librosa.time_to_frames(tj + off, sr=SR, hop_length=256)
            B = M[:, g0:g0 + A.shape[1]]
            if B.shape[1] == A.shape[1]:
                c = np.corrcoef(A.ravel(), B.ravel())[0, 1]
                best = max(best, (c, off))
        # vocal gap: quietest 0.1 s in the 1.2 s before the bar on both sides together
        v = st["vocals"]
        gap = None
        for back in np.arange(0.05, 1.2, 0.05):
            e1 = np.sqrt(np.mean(v[int((ti - back) * SR):int((ti - back + 0.1) * SR)] ** 2) + 1e-12)
            e2 = np.sqrt(np.mean(v[int((tj + best[1] - back) * SR):int((tj + best[1] - back + 0.1) * SR)] ** 2) + 1e-12)
            db_ = 20 * np.log10(max(e1, e2))
            if gap is None or db_ < gap[0]:
                gap = (db_, back)
        cut_src = ti - gap[1]
        cut_dst = tj + best[1] - gap[1]
        length = cut_src + (d["duration"] - cut_dst)
        print(f"  {score:.2f}  bar {i:3d} -> {j:3d}  ({ti:7.2f} -> {tj:7.2f})  mel corr {best[0]:.3f} @ {best[1]:+.2f}s  "
              f"| cut in vocal gap: {cut_src:.3f} -> {cut_dst:.3f} ({gap[0]:.0f} dB)  | edit length ~{length:.0f}s")
        shown += 1


if __name__ == "__main__":
    main()
