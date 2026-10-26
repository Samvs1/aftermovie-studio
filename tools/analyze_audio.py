"""Deep music analysis for one or all songs in the project's music/ folder (v2: stems + neural downbeats).

Inputs: the mix in music/, Demucs stems in cache/stems/<slug>/ (tools/separate.py), beat_this
beats/downbeats (computed and cached here), synced lyrics from cache/lyrics/<slug>_search.json.

Writes cache/audio/<slug>.json + cache/audio/<slug>.png with:
  - beats: constant grid for click-steady songs (fit to the drum stem, phase checked against the
    kick drum and beat_this), otherwise beat_this beats snapped to drum onsets and smoothed
  - downbeats/bars (beat_this downbeat votes)
  - kick / snare / cymbal / bass-hit / generic onset events with strengths
  - energy curve (per 0.1 s, per beat, per bar), sections (bar-level novelty)
  - vocal activity + vocal onsets from the vocal stem
  - lyric lines aligned to this exact file, with estimated word times

usage: python tools/analyze_audio.py [slug ...]
"""
import json, os, re, sys
import numpy as np
import librosa
import scipy.signal as sps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from am.common import ROOT, MUSIC, CACHE  # noqa: E402  (project-aware: AM_PROJECT)
OUTDIR = os.path.join(CACHE, "audio")
STEMS = os.path.join(CACHE, "stems")
os.makedirs(OUTDIR, exist_ok=True)

SONGS_FIXED = {
    "cool_kids": "Echosmith - Cool Kids [Official Music Video].mp3",
    "time_to_pretend": "MGMT - Time to Pretend (Official HD Video).mp3",
    "sweet_disposition": "The Temper Trap - Sweet Disposition (Official Video).mp3",
}


def _discover():
    """Fixed slugs for the original three songs; any other audio file in music/ gets an automatic slug."""
    out = dict(SONGS_FIXED)
    if os.path.isdir(MUSIC):
        for f in sorted(os.listdir(MUSIC)):
            if f.lower().endswith((".mp3", ".wav", ".m4a", ".flac", ".ogg")) and f not in out.values():
                stem = re.sub(r"\s*[\[(].*?[\])]", "", os.path.splitext(f)[0])   # drop "(Official Video)" etc.
                slug = re.sub(r"[^a-z0-9]+", "_", stem.lower()).strip("_")[:40]
                out[slug] = f
    return out


SONGS = _discover()
SR = 22050
HOP = 128  # 5.8 ms frames
DT = HOP / SR


def norm(x):
    return x / (np.percentile(x, 99.7) + 1e-9)


def flux(S, freqs, lo, hi):
    band = S[(freqs >= lo) & (freqs < hi)]
    lg = np.log1p(band * 20)
    f = np.maximum(0, np.diff(lg, axis=1, prepend=lg[:, :1])).sum(axis=0)
    return norm(f)


def peaks(env, height, distance_s, prominence=0.08):
    pk, _ = sps.find_peaks(env, height=height, distance=max(1, int(distance_s / DT)), prominence=prominence)
    return [{"t": round(float(p * DT), 3), "s": round(float(min(env[p], 1.5)), 3)} for p in pk]


def fold(env, period, nb=600, mask=None):
    t = np.arange(len(env)) * DT
    w = env ** 2 if mask is None else (env ** 2) * mask
    h = np.bincount(((t % period) / period * nb).astype(int) % nb, weights=w, minlength=nb)
    h = np.convolve(np.r_[h[-4:], h, h[:4]], np.ones(7) / 7, "same")[4:-4]
    k = int(np.argmax(h))
    return k / nb * period, float(h[k] / (h.mean() + 1e-9))


def fit_constant_grid(env, bpm0):
    best = None
    for bpm in np.arange(bpm0 * 0.985, bpm0 * 1.015, 0.002):
        ph, sc = fold(env, 60 / bpm)
        if best is None or sc > best[0]:
            best = (sc, bpm, ph)
    sc, bpm, ph = best
    P = 60 / bpm
    t = np.arange(len(env)) * DT
    devs = []
    for a in np.arange(0, t[-1] - 20, 10):
        m = ((t >= a) & (t < a + 20)).astype(float)
        p2, s2 = fold(env, P, mask=m)
        dv = (p2 - ph + P / 2) % P - P / 2
        if s2 > 6.5:  # ignore windows without a clear drum pulse (e.g. drumless intros)
            devs.append(dv)
    drift = float(np.max(np.abs(devs))) if devs else 1.0
    return bpm, ph, drift


def syllables(word):
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    groups = re.findall(r"[aeiouy]+", w)
    n = len(groups)
    if w.endswith("e") and n > 1 and not w.endswith(("le", "ee")):
        n -= 1
    return max(1, n)


def parse_lrc(text):
    out = []
    for line in text.splitlines():
        m = re.match(r"\[(\d+):(\d+(?:\.\d+)?)\]\s*(.*)", line)
        if m:
            out.append((int(m.group(1)) * 60 + float(m.group(2)), m.group(3).strip()))
    return out


def beat_this_cached(slug, y):
    path = os.path.join(OUTDIR, "beat_this.json")
    cache = json.load(open(path)) if os.path.exists(path) else {}
    if slug not in cache:
        from beat_this.inference import Audio2Beats
        a2b = Audio2Beats(checkpoint_path="final0", device="cpu", dbn=False)
        b, d = a2b(y, SR)
        cache[slug] = {"beats": np.round(b, 4).tolist(), "downbeats": np.round(d, 4).tolist()}
        json.dump(cache, open(path, "w"))
    return np.array(cache[slug]["beats"]), np.array(cache[slug]["downbeats"])


def load_stem(slug, name, n):
    p = os.path.join(STEMS, slug, f"{name}.wav")
    s, _ = librosa.load(p, sr=SR, mono=True)
    return np.pad(s, (0, max(0, n - len(s))))[:n]


def analyze(slug):
    print(f"== {slug}")
    y, _ = librosa.load(os.path.join(MUSIC, SONGS[slug]), sr=SR, mono=True)
    n = len(y)
    dur = n / SR
    drums, bass, vocals, other = (load_stem(slug, s, n) for s in ("drums", "bass", "vocals", "other"))
    freqs = librosa.fft_frequencies(sr=SR, n_fft=2048)

    def spec(sig):
        return np.abs(librosa.stft(sig, n_fft=2048, hop_length=HOP))

    Sd, Sb, Sv, Sm = spec(drums), spec(bass), spec(vocals), spec(y)
    nf = Sm.shape[1]
    times = np.arange(nf) * DT

    kick = flux(Sd, freqs, 25, 150)
    snare = flux(Sd, freqs, 180, 2500) * 0.5 + flux(Sd, freqs, 2500, 6000) * 0.5
    snare = norm(snare)
    cym = flux(Sd, freqs, 7000, 11000)
    drum_env = norm(kick + snare)
    bass_env = flux(Sb, freqs, 30, 400)
    mix_env = norm(librosa.onset.onset_strength(S=librosa.amplitude_to_db(Sm, ref=np.max), sr=SR, hop_length=HOP))

    # ---------------- beats
    bt_b, bt_d = beat_this_cached(slug, y)
    bpm0 = 60 / np.median(np.diff(bt_b))
    bpm, ph, drift = fit_constant_grid(drum_env, bpm0)
    P = 60 / bpm
    constant = drift < 0.022
    print(f"   grid fit {bpm:.3f} bpm, max window drift {drift*1000:.0f} ms -> {'constant grid' if constant else 'tempo-following'}")
    if constant:
        # the fold peak can sit on the off-beat; pick the phase the kick drum and beat_this agree with
        kph, _ = fold(kick, P)
        cands = [ph, (ph + P / 2) % P]
        bt_phase = float(np.angle(np.mean(np.exp(2j * np.pi * (bt_b % P) / P))) / (2 * np.pi) * P) % P

        def cdist(a, b):
            return abs((a - b + P / 2) % P - P / 2)
        score = [cdist(c, kph) + cdist(c, bt_phase) for c in cands]
        ph = cands[int(np.argmin(score))]
        print(f"   phase: fold {cands[0]:.3f}/{cands[1]:.3f}, kick {kph:.3f}, beat_this {bt_phase:.3f} -> {ph:.3f}")
        first = bt_b[0] - 0.1
        last = min(bt_b[-1] + 0.1, dur)
        k0 = int(np.ceil((first - ph) / P))
        k1 = int(np.floor((last - ph) / P))
        beats = np.array([ph + k * P for k in range(k0, k1 + 1)])
    else:
        # snap each neural beat to the strongest drum onset within +-35 ms, then smooth jitter
        snapped = []
        for b in bt_b:
            f = int(round(b / DT))
            w = int(0.035 / DT)
            seg = drum_env[max(0, f - w):f + w + 1]
            if len(seg) and seg.max() > 0.2:
                snapped.append((max(0, f - w) + int(np.argmax(seg))) * DT)
            else:
                snapped.append(b)
        snapped = np.array(snapped)
        resid = snapped - sps.savgol_filter(snapped, 9, 2)
        beats = np.where(np.abs(resid) < 0.03, snapped, sps.savgol_filter(snapped, 9, 2))
    # downbeats: follow beat_this bar positions (handles irregular bars), fill gaps in 4-beat steps
    bi = np.array([int(np.argmin(np.abs(beats - d))) for d in bt_d])
    ok = np.abs(beats[bi] - bt_d) < 0.09
    votes = np.bincount(bi[ok] % 4, minlength=4)
    dphase = int(np.argmax(votes))
    anchors = sorted(set(bi[ok].tolist()))
    # drop isolated anchors that disagree with both neighbours (1-beat 'bars' are tracker noise)
    clean = []
    for j, a in enumerate(anchors):
        prev_ok = j > 0 and (a - anchors[j - 1]) % 4 == 0
        next_ok = j + 1 < len(anchors) and (anchors[j + 1] - a) % 4 == 0
        if prev_ok or next_ok or len(anchors) < 3:
            clean.append(a)
    db_idx = []
    for j, a in enumerate(clean):
        db_idx.append(a)
        nxt = clean[j + 1] if j + 1 < len(clean) else len(beats)
        k = a + 4
        while k <= nxt - 3:
            db_idx.append(k)
            k += 4
    k = clean[0] - 4 if clean else dphase
    while k >= 0:
        db_idx.insert(0, k)
        k -= 4
    db_idx = sorted(set(db_idx))
    downbeats = beats[db_idx]
    irregular = [round(float(beats[a]), 3) for a, b in zip(db_idx[:-1], db_idx[1:]) if b - a != 4]
    print(f"   downbeat votes {votes.tolist()}; irregular bars at {irregular}")

    # ---------------- energy
    rms = librosa.feature.rms(S=Sm, frame_length=2048, hop_length=HOP)[0]
    e = np.clip((librosa.amplitude_to_db(rms, ref=np.max) + 40) / 40, 0, 1)
    e_s = sps.savgol_filter(e, 201, 2)
    bfr = (beats / DT).astype(int)
    beat_energy = [round(float(e[max(0, f - 10):f + 60].mean()), 3) for f in bfr]
    dfr = (downbeats / DT).astype(int)
    bar_energy = [round(float(e[a:b].mean()), 3) for a, b in zip(dfr, list(dfr[1:]) + [nf])]

    def at(env, f, w=6):
        return float(env[max(0, f - w):f + w + 1].max())
    beat_kick = [round(at(kick, f), 3) for f in bfr]
    beat_snare = [round(at(snare, f), 3) for f in bfr]
    beat_bass = [round(at(bass_env, f), 3) for f in bfr]

    # ---------------- sections (bar novelty on chroma + mfcc + energy)
    chroma = librosa.feature.chroma_stft(S=Sm ** 2, sr=SR)
    mfcc = librosa.feature.mfcc(S=librosa.power_to_db(librosa.feature.melspectrogram(S=Sm ** 2, sr=SR)), n_mfcc=13)
    voc_rms = librosa.feature.rms(S=Sv, frame_length=2048, hop_length=HOP)[0]
    voc_act = np.clip((librosa.amplitude_to_db(voc_rms, ref=np.max) + 35) / 35, 0, 1)
    feat = np.vstack([librosa.util.normalize(chroma, axis=0), mfcc / 50.0, e[None] * 3, voc_act[None] * 2])
    bars = librosa.util.sync(feat, dfr, aggregate=np.mean)[:, 1:][:, :len(bar_energy)]
    R = librosa.segment.recurrence_matrix(bars, mode="affinity", sym=True, width=2)
    R = librosa.segment.path_enhance(R, 3)
    nb = R.shape[0]
    K = 4
    ker = np.kron(np.array([[1, -1], [-1, 1]]), np.ones((K, K)))
    g = sps.windows.gaussian(2 * K, K / 1.5)
    ker *= np.outer(g, g)
    pad = np.pad(R, K)
    nov = np.array([np.sum(pad[i:i + 2 * K, i:i + 2 * K] * ker) for i in range(nb)])
    be = np.array(bar_energy[:nb])
    ej = np.abs(np.r_[0, np.diff(be)])
    nov2 = nov / (np.abs(nov).max() + 1e-9) + 1.5 * ej / (ej.max() + 1e-9)
    pk, _ = sps.find_peaks(nov2, distance=4, height=np.percentile(nov2, 60))
    bounds = sorted(set([0] + pk.tolist() + [nb]))
    sections = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        en = float(downbeats[b]) if b < len(downbeats) else dur
        sections.append({"start": round(float(downbeats[a]), 3), "end": round(en, 3), "bars": b - a,
                         "energy": round(float(be[a:b].mean()), 3),
                         "vocal": round(float(voc_act[dfr[a]:(dfr[b] if b < len(dfr) else nf)].mean()), 3)})

    # ---------------- vocals
    v_on = flux(Sv, freqs, 150, 4000)
    v_on = v_on * (voc_act > 0.35)
    vocal_onsets = peaks(v_on, 0.18, 0.09, 0.08)

    # ---------------- lyrics
    lyrics, meta = [], None
    lp = os.path.join(CACHE, "lyrics", f"{slug}_search.json")
    if os.path.exists(lp):
        cands = [c for c in json.load(open(lp, encoding="utf-8")) if c.get("syncedLyrics")]
        on_frames = np.zeros(nf)
        for v in vocal_onsets:
            on_frames[int(v["t"] / DT)] = v["s"]
        on_s = np.convolve(on_frames, np.ones(int(0.12 / DT)), "same")
        best = None
        for c in cands[:15]:
            lines = [(t, s) for t, s in parse_lrc(c["syncedLyrics"]) if s]
            if len(lines) < 6:
                continue
            lt = np.array([t for t, _ in lines])

            def score(o):
                fr = ((lt + o) / DT).astype(int)
                okf = (fr > 80) & (fr < nf - 200)
                if okf.sum() < 0.8 * len(fr):
                    return -1.0
                # onset at the timestamp, singing right after, (relative) silence just before
                return float(np.mean([on_s[f - 10:f + 25].max() + 0.6 * voc_act[f:f + 120].mean() - 0.3 * voc_act[f - 60:f - 15].mean()
                                      for f in fr[okf]]))
            # music videos open with up to a minute of film before the song: search wide (coarse), then refine
            coarse = np.arange(-60, 60, 0.05)
            csc = np.nan_to_num(np.array([score(o) for o in coarse]), nan=-1.0)
            tops = coarse[np.argsort(csc)[::-1][:3]]
            offs = np.unique(np.round(np.concatenate([np.arange(o - 0.1, o + 0.1, 0.01) for o in tops]), 2))
            sc = np.nan_to_num(np.array([score(o) for o in offs]), nan=-1.0)
            j = int(np.argmax(sc))
            allsc = np.r_[csc, sc]                               # z-score against the whole search
            pos = allsc[allsc > 0]
            z = (sc[j] - np.median(pos)) / (np.std(pos) + 1e-9)
            if best is None or z > best[0]:
                best = (z, float(offs[j]), c, lines)
        z, off, c, lines = best
        meta = {"source": "lrclib", "id": c["id"], "album": c.get("albumName"), "offset": round(off, 3), "match_z": round(float(z), 2)}
        print(f"   lyrics: lrclib {c['id']} '{c.get('albumName')}' offset {off:+.2f}s z={z:.1f}")
        on_t = np.array([v["t"] for v in vocal_onsets])
        on_sv = np.array([v["s"] for v in vocal_onsets])
        for i, (t, s) in enumerate(lines):
            t0 = t + off
            near = np.where(np.abs(on_t - t0) < 0.3)[0]
            if len(near):
                t0 = float(on_t[near[np.argmax(on_sv[near] - np.abs(on_t[near] - t0))]])
            t1 = lines[i + 1][0] + off if i + 1 < len(lines) else min(dur, t0 + 5)
            words = s.split()
            syl = [syllables(w) for w in words]
            cand = on_t[(on_t >= t0 - 0.01) & (on_t < t1 - 0.15)]
            wt = []
            if len(cand) >= len(words):
                # walk syllables through the onsets in order; word time = onset of its first syllable
                k = 0
                total = sum(syl)
                scale = len(cand) / max(total, 1)
                for w, sy in zip(words, syl):
                    wt.append(round(float(cand[min(int(round(k * scale)), len(cand) - 1)]), 3))
                    k += sy
            else:
                # not enough onsets: spread words by syllables over the sung part of the line
                vend = t0 + max(0.4, min(t1 - t0, 0.32 * sum(syl) + 0.3))
                acc = 0
                for sy in syl:
                    wt.append(round(t0 + (vend - t0) * acc / max(sum(syl), 1), 3))
                    acc += sy
            lyrics.append({"t": round(t0, 3), "end": round(float(t1), 3), "text": s,
                           "words": [{"w": w, "t": tt} for w, tt in zip(words, wt)]})

    # ---------------- events
    kicks = peaks(kick, 0.3, 0.15)
    snares = peaks(snare, 0.3, 0.15)
    cymbals = peaks(cym, 0.45, 0.4, 0.2)
    bass_hits = peaks(bass_env, 0.35, 0.2)
    onsets = peaks(mix_env, 0.2, 0.08)
    step = int(round(0.1 / DT))
    data = {
        "slug": slug, "file": SONGS[slug], "duration": round(dur, 3),
        "tempo": round(bpm if constant else 60 / np.median(np.diff(beats)), 3),
        "beat_period": round(P if constant else float(np.median(np.diff(beats))), 5),
        "grid": {"constant": bool(constant), "drift_ms": round(drift * 1000, 1)},
        "downbeat_votes": votes.tolist(), "irregular_bars": irregular,
        "beats": [round(float(b), 3) for b in beats],
        "beat_energy": beat_energy, "beat_kick": beat_kick, "beat_snare": beat_snare, "beat_bass": beat_bass,
        "downbeats": [round(float(d), 3) for d in downbeats], "bar_energy": bar_energy,
        "sections": sections,
        "kicks": kicks, "snares": snares, "cymbals": cymbals, "bass_hits": bass_hits, "onsets": onsets,
        "vocal_onsets": vocal_onsets,
        "curve": {"t": [round(float(t), 2) for t in times[::step]], "energy": [round(float(v), 3) for v in e_s[::step]],
                  "vocal": [round(float(v), 3) for v in sps.savgol_filter(voc_act, 41, 2)[::step]]},
        "lyrics_meta": meta, "lyrics": lyrics,
    }
    json.dump(data, open(os.path.join(OUTDIR, f"{slug}.json"), "w"), indent=0)
    plot(data, slug)
    print(f"   {len(beats)} beats, {len(downbeats)} bars, {len(sections)} sections, {len(lyrics)} lyric lines, "
          f"{len(kicks)} kicks, {len(snares)} snares, {len(cymbals)} cymbals, {len(bass_hits)} bass hits")


def plot(d, slug, span=60):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    dur = d["duration"]
    rows = int(np.ceil(dur / span))
    fig, axes = plt.subplots(rows, 1, figsize=(28, 4.6 * rows), squeeze=False)
    t = np.array(d["curve"]["t"])
    for r in range(rows):
        ax = axes[r][0]
        a, b = r * span, (r + 1) * span
        m = (t >= a) & (t <= b)
        ax.fill_between(t[m], 0, np.array(d["curve"]["energy"])[m], color="#4a90d9", alpha=0.45)
        ax.plot(t[m], np.array(d["curve"]["vocal"])[m] * 0.9, color="#e94f37", lw=1.1)
        for s in d["sections"]:
            if a <= s["start"] <= b:
                ax.axvline(s["start"], color="k", lw=2.5)
                ax.text(s["start"] + 0.15, 1.13, f"{s['start']:.2f}s e{s['energy']:.2f}", fontsize=9, fontweight="bold")
        for x in d["downbeats"]:
            if a <= x <= b:
                ax.axvline(x, color="#888", lw=0.9)
        for x in d["beats"]:
            if a <= x <= b:
                ax.plot([x, x], [-0.1, -0.03], color="#222", lw=0.9)
        for k in d["kicks"]:
            if a <= k["t"] <= b:
                ax.plot(k["t"], -0.17, "v", color="#2a9d8f", ms=2 + 5 * min(k["s"], 1))
        for k in d["snares"]:
            if a <= k["t"] <= b:
                ax.plot(k["t"], -0.25, "^", color="#f4a261", ms=2 + 5 * min(k["s"], 1))
        for k in d["cymbals"]:
            if a <= k["t"] <= b:
                ax.plot(k["t"], -0.32, "*", color="#8338ec", ms=4 + 6 * min(k["s"], 1))
        for ly in d["lyrics"]:
            if a <= ly["t"] <= b:
                ax.axvline(ly["t"], color="#e94f37", lw=1, ls="--")
                for wi, w in enumerate(ly["words"]):
                    ax.text(w["t"], 1.02 - 0.07 * (wi % 3), w["w"], fontsize=7, color="#b0302a")
        ax.set_xlim(a, b)
        ax.set_ylim(-0.38, 1.2)
        ax.set_xticks(np.arange(a, b + 1, 2))
        ax.tick_params(labelsize=8)
    fig.suptitle(f"{slug}  {d['tempo']:.2f} bpm  constant grid={d['grid']['constant']}", fontsize=14)
    fig.tight_layout()
    fig.savefig(os.path.join(OUTDIR, f"{slug}.png"), dpi=55)
    plt.close(fig)


if __name__ == "__main__":
    for s in (sys.argv[1:] or list(SONGS)):
        analyze(s)
