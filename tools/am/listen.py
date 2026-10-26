"""The song kit's ears: everything a director needs to *read* a song, computed from the mix and the Demucs stems.

  loudness()        momentary / short-term loudness (EBU R128 style, LUFS), integrated loudness and loudness range
  stem_env()        level envelope of one stem (dB and 0..1 against its own loud parts)
  pitch_track()     CREPE pitch + periodicity (torchcrepe; GPU 'full' model, CPU 'tiny')
  notes_from_f0()   a pitch track -> discrete notes (vocal melody, bass line)
  chords()          beat-level major/minor chords (chroma templates + a bar-aware Viterbi), and key()
  structure()       repetition classes per beat (Laplacian segmentation, McFee & Ellis 2014)
  label_sections()  intro / verse / pre-chorus / chorus / bridge / instrumental / break / outro from repetition + lyrics
  clap_tags()       zero-shot mood / instrument / genre hints per window (LAION CLAP); speech-vs-music for film intros

All envelopes share one frame grid: FPS frames per second (HOP samples at SR).
"""
import re
import numpy as np
import librosa
import scipy.signal as sps
import scipy.ndimage as ndi

SR = 22050
HOP = 441                    # 20 ms
FPS = SR / HOP               # 50 frames per second
PITCH = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


def frames_to_time(n):
    return np.arange(n) / FPS


def note_name(midi):
    m = int(round(midi))
    return f"{PITCH[m % 12]}{m // 12 - 1}"


# ------------------------------------------------------------------ loudness (ITU-R BS.1770 / EBU R128)
def _biquad(kind, gain_db, q, fc, rate):
    a_ = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * fc / rate
    alpha = np.sin(w0) / (2.0 * q)
    cw = np.cos(w0)
    if kind == "high_shelf":
        b = [a_ * ((a_ + 1) + (a_ - 1) * cw + 2 * np.sqrt(a_) * alpha), -2 * a_ * ((a_ - 1) + (a_ + 1) * cw),
             a_ * ((a_ + 1) + (a_ - 1) * cw - 2 * np.sqrt(a_) * alpha)]
        a = [(a_ + 1) - (a_ - 1) * cw + 2 * np.sqrt(a_) * alpha, 2 * ((a_ - 1) - (a_ + 1) * cw),
             (a_ + 1) - (a_ - 1) * cw - 2 * np.sqrt(a_) * alpha]
    else:   # high pass
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    return np.array(b) / a[0], np.array(a) / a[0]


def loudness(y, sr, nf):
    """y: (channels, n) at sr. Returns momentary (400 ms) and short-term (3 s) loudness in LUFS on the nf-frame grid,
    plus the gated mean-square blocks (for integrated loudness / LRA over any stretch)."""
    z = np.atleast_2d(y).astype(np.float64)
    for kind, g, q, fc in (("high_shelf", 4.0, 1 / np.sqrt(2), 1500.0), ("high_pass", 0.0, 0.5, 38.0)):
        b, a = _biquad(kind, g, q, fc, sr)
        z = sps.lfilter(b, a, z, axis=-1)
    p = (z ** 2).sum(axis=0)
    c = np.concatenate([[0.0], np.cumsum(p)])
    n = len(p)
    centers = (np.arange(nf) * sr / FPS).astype(np.int64)

    def window(w):
        h = int(w * sr / 2)
        lo, hi = np.clip(centers - h, 0, n), np.clip(centers + h, 0, n)
        ms = (c[hi] - c[lo]) / np.maximum(hi - lo, 1)
        return -0.691 + 10 * np.log10(ms + 1e-12)
    return {"momentary": window(0.4), "short": window(3.0), "_cum": c, "_sr": sr}


def integrated(L, t0=0.0, t1=None):
    """Gated integrated loudness (LUFS) and loudness range (LU) between t0 and t1 (seconds)."""
    c, sr = L["_cum"], L["_sr"]
    n = len(c) - 1
    a, b = int(t0 * sr), min(n, int((t1 if t1 is not None else n / sr) * sr))

    def blocks(w, step):
        bl, st = int(w * sr), int(step * sr)
        s = np.arange(a, max(a + 1, b - bl), st)
        return (c[np.minimum(s + bl, n)] - c[s]) / bl
    ms = blocks(0.4, 0.1)
    lk = -0.691 + 10 * np.log10(ms + 1e-12)
    g = lk > -70
    if not g.any():
        return -70.0, 0.0
    rel = -0.691 + 10 * np.log10(ms[g].mean()) - 10
    g &= lk > rel
    lufs = -0.691 + 10 * np.log10(ms[g].mean())
    st = -0.691 + 10 * np.log10(blocks(3.0, 1.0) + 1e-12)
    st = st[st > -70]
    if len(st) < 3:
        return float(lufs), 0.0
    rel2 = -0.691 + 10 * np.log10(np.mean(10 ** ((st + 0.691) / 10))) - 20
    st = st[st > rel2]
    return float(lufs), float(np.percentile(st, 95) - np.percentile(st, 10))


def energy_mean_db(db):
    """Mean of dB values in the energy domain (a bar's loudness, not the average of its dB numbers)."""
    db = np.asarray(db, dtype=np.float64)
    return float(10 * np.log10(np.mean(10 ** (db / 10)) + 1e-12)) if len(db) else -99.0


# ------------------------------------------------------------------ stems
def stem_env(x, nf, active=None):
    """RMS level of a stem on the frame grid: {'db', 'act' (0..1, 30 dB below its loud level -> 0), 'ref'}.
    `active` (bool per frame) limits where the loud reference level is measured (e.g. the music, not a film intro)."""
    r = librosa.feature.rms(y=x, frame_length=2048, hop_length=HOP, center=True)[0]
    r = np.pad(r, (0, max(0, nf - len(r))))[:nf]
    db = 20 * np.log10(r + 1e-7)
    sel = db[active] if active is not None and active.any() else db
    ref = float(np.percentile(sel, 95))
    return {"db": db, "act": np.clip((db - (ref - 30)) / 30, 0, 1), "ref": ref}


def bar_level(db, ref, spans, scale=30.0):
    """0..9 per bar: a stem's energy-mean level in the bar against `ref` (9 = full, 0 = absent / bleed)."""
    out = []
    for f0, f1 in spans:
        v = energy_mean_db(db[f0:max(f1, f0 + 1)])
        out.append(int(np.clip(round(9 * (v - (ref - scale)) / scale), 0, 9)))
    return out


# ------------------------------------------------------------------ pitch
def pitch_track(y16, device, fmin, fmax, hop_s=0.01):
    """CREPE on a 16 kHz mono signal -> (f0 Hz, periodicity 0..1, model name). Viterbi decoding avoids octave jumps."""
    import torch
    import torchcrepe
    model = "full" if device == "cuda" else "tiny"
    x = torch.tensor(y16, dtype=torch.float32)[None]
    with torch.inference_mode():
        f0, per = torchcrepe.predict(x, 16000, int(16000 * hop_s), fmin, fmax, model,
                                     decoder=torchcrepe.decode.viterbi, return_periodicity=True,
                                     batch_size=512, device=device, pad=True)
    f0, per = f0[0].cpu().numpy(), per[0].cpu().numpy()
    del x
    return f0, per, model


def resample_track(v, src_fps, nf):
    """Nearest-frame resample of a per-frame track to the FPS grid."""
    idx = np.minimum((np.arange(nf) / FPS * src_fps).round().astype(int), len(v) - 1)
    return v[idx]


def notes_from_f0(f0, voiced, hop_s=0.01, min_len=0.08, jump=0.75):
    """Discrete notes from a pitch track. A note breaks on an unvoiced gap > 30 ms or a pitch change of more than
    `jump` semitones that holds for 40 ms (so vibrato and scoops stay one note). Returns [{t, end, midi, name}]."""
    midi = np.where(f0 > 0, 69 + 12 * np.log2(np.maximum(f0, 1e-3) / 440.0), np.nan)
    midi = ndi.median_filter(np.nan_to_num(midi, nan=0.0), 5)
    v = voiced & (midi > 0)
    v = ndi.binary_closing(v, structure=np.ones(4)) & (midi > 0)    # bridge consonants / 30 ms dropouts
    notes, n, i = [], len(midi), 0
    while i < n:
        if not v[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and v[j + 1]:
            ref = np.median(midi[max(i, j - 9):j + 1])
            nxt = midi[j + 1:j + 5]
            if abs(midi[j + 1] - ref) > jump and len(nxt) == 4 and np.all(np.abs(nxt - midi[j + 1]) < 0.5) and v[j + 1:j + 5].all():
                break
            j += 1
        if (j - i + 1) * hop_s >= min_len:
            m = float(np.median(midi[i:j + 1]))
            notes.append({"t": round(i * hop_s, 3), "end": round((j + 1) * hop_s, 3), "midi": int(round(m)),
                          "cents": int(round((m - round(m)) * 100))})
        i = j + 1
    merged = []
    for nt in notes:      # same pitch again after a tiny gap = one held note
        if merged and merged[-1]["midi"] == nt["midi"] and nt["t"] - merged[-1]["end"] < 0.06:
            merged[-1]["end"] = nt["end"]
        else:
            merged.append(nt)
    for nt in merged:
        nt["name"] = note_name(nt["midi"])
        nt["dur"] = round(nt["end"] - nt["t"], 3)
    return merged


# ------------------------------------------------------------------ harmony
def _chord_bank():
    names, T = [], []
    for r in range(12):
        for q, iv in (("", (0, 4, 7)), ("m", (0, 3, 7))):
            t = np.zeros(12)
            t[[(r + k) % 12 for k in iv]] = [1.0, 0.8, 0.9]
            names.append(PITCH[r] + q)
            T.append(t / np.linalg.norm(t))
    return names, np.array(T)


CHORDS, _TEMPL = _chord_bank()
_KK_MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_KK_MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def harmony_chroma(harm, bass, beats, sr=SR):
    """Beat-synchronous chroma of the harmony (other [+ a little vocal]) and of the bass stem, plus the harmony level (dB)
    per beat. Each column covers [beat k, beat k+1)."""
    hop = 512
    ch = librosa.feature.chroma_cqt(y=harm, sr=sr, hop_length=hop, bins_per_octave=36)
    cb = librosa.feature.chroma_cqt(y=bass, sr=sr, hop_length=hop, fmin=librosa.note_to_hz("C1"), n_octaves=4, bins_per_octave=36)
    rms = librosa.feature.rms(y=harm + bass, frame_length=2048, hop_length=hop)[0]
    bf = librosa.time_to_frames(beats, sr=sr, hop_length=hop)
    bf = np.clip(bf, 0, ch.shape[1] - 1)
    hs = librosa.util.sync(ch, bf, aggregate=np.median, pad=False)
    bs = librosa.util.sync(cb, bf, aggregate=np.median, pad=False)
    lv = librosa.util.sync(rms[None], bf, aggregate=np.mean, pad=False)[0]
    k = len(beats) - 1
    return hs[:, :k], bs[:, :k], 20 * np.log10(lv[:k] + 1e-7)


def chords(hs, bs, level_db, beat_in_bar):
    """Viterbi chord labels per beat (24 major/minor chords + 'N'). Changes are cheap on a downbeat, plausible on the
    bar's middle, expensive elsewhere."""
    H = hs / (np.linalg.norm(hs, axis=0, keepdims=True) + 1e-9)
    Bn = bs / (bs.max(axis=0, keepdims=True) + 1e-9)
    score = _TEMPL @ H                                                  # 24 x beats
    roots = np.array([PITCH.index(re.match(r"[A-G][b#]?", c).group()) for c in CHORDS])
    score = score + 0.35 * Bn[roots]
    quiet = level_db < (np.percentile(level_db, 90) - 30)
    S = len(CHORDS) + 1
    logp = np.vstack([score * 9.0, np.full((1, score.shape[1]), 0.55 * 9.0)])      # 'N' wins only on weak fits
    logp[-1, quiet] += 6.0
    logp[:-1, quiet] -= 3.0
    logp = logp - np.logaddexp.reduce(logp, axis=0, keepdims=True)
    n = logp.shape[1]
    back = np.zeros((S, n), dtype=np.int32)
    acc = logp[:, 0].copy()
    for t in range(1, n):
        pb = beat_in_bar[t]
        stay = 0.55 if pb == 0 else 0.85 if pb == 2 else 0.97
        ls, lc = np.log(stay), np.log((1 - stay) / (S - 1))
        best_other = acc.max()
        arg_other = int(acc.argmax())
        cand_change = best_other + lc
        cand_stay = acc + ls
        back[:, t] = np.where(cand_stay >= cand_change, np.arange(S), arg_other)
        acc = np.maximum(cand_stay, cand_change) + logp[:, t]
    path = np.zeros(n, dtype=np.int32)
    path[-1] = int(acc.argmax())
    for t in range(n - 1, 0, -1):
        path[t - 1] = back[path[t], t]
    names = CHORDS + ["N"]
    return [names[p] for p in path]


def key(hs, weights=None):
    """Best key by Krumhansl-Kessler correlation on the duration/level-weighted chroma. Returns (name, score, runner_up)."""
    w = np.ones(hs.shape[1]) if weights is None else weights
    prof = (hs * w).sum(axis=1)
    res = []
    for r in range(12):
        for mode, P in (("major", _KK_MAJ), ("minor", _KK_MIN)):
            res.append((float(np.corrcoef(prof, np.roll(P, r))[0, 1]), f"{PITCH[r]} {mode}"))
    res.sort(reverse=True)
    return res[0][1], round(res[0][0], 3), res[1][1], round(res[1][0], 3)


_TONIC = {"major": ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"],
          "minor": ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "G#", "A", "Bb", "B"]}
_NAT = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def speller(key_name):
    """(spelled key name, chord -> chord spelled for that key): diatonic roots take the scale's letter (Db in Ab major,
    G# in E major); roots outside the scale keep the default name (Bb in D major stays a flat VI)."""
    root, mode = key_name.split()
    pc = PITCH.index(root)
    tonic = _TONIC[mode][pc]
    steps = [0, 2, 4, 5, 7, 9, 11] if mode == "major" else [0, 2, 3, 5, 7, 8, 10]
    letters = "CDEFGAB"
    li = letters.index(tonic[0])
    names = {}
    for k, st in enumerate(steps):
        letter = letters[(li + k) % 7]
        target = (pc + st) % 12
        acc = {0: "", 1: "#", 11: "b", 2: "##", 10: "bb"}[(target - _NAT[letter]) % 12]
        names[target] = letter + acc

    def spell(ch):
        if not ch or ch == "N":
            return ch
        out = []
        for c in ch.split(" "):
            m = re.match(r"([A-G][b#]?)(.*)", c)
            r = PITCH.index(m.group(1)) if m.group(1) in PITCH else None
            out.append((names.get(r, m.group(1)) if r is not None else m.group(1)) + m.group(2))
        return " ".join(out)
    return f"{tonic} {mode}", spell


def bar_chords(beat_chords, bar_beats):
    """One label per bar: the chord holding most of its beats, or 'X Y' when two chords split it."""
    out = []
    for idx in bar_beats:
        cs = [beat_chords[i] for i in idx if i < len(beat_chords)]
        if not cs:
            out.append("")
            continue
        seq = [c for k, c in enumerate(cs) if k == 0 or c != cs[k - 1]]
        cnt = {c: cs.count(c) for c in set(cs)}
        top = sorted(cnt.items(), key=lambda kv: -kv[1])
        if len(top) > 1 and top[1][1] >= 2 and len(seq) <= 3:
            out.append(" ".join(seq[:2]))
        else:
            out.append(top[0][0])
    return out


def loop_of(seq):
    """The shortest repeating chord loop in a list of bar chords: (loop, repeats) or (None, 0)."""
    s = [x for x in seq if x]
    for p in (1, 2, 4, 8):
        if len(s) >= 2 * p:
            m = np.mean([s[i] == s[i + p] for i in range(len(s) - p)])
            if m >= 0.74:
                return s[:p], len(s) / p
    return None, 0


# ------------------------------------------------------------------ structure
def structure(C, M, k):
    """Repetition class per beat from beat-synced harmony features C and timbre features M (Laplacian segmentation)."""
    import scipy.sparse.csgraph as csg
    from scipy.cluster.vq import kmeans2
    R = librosa.segment.recurrence_matrix(C, width=3, mode="affinity", sym=True)
    Rf = librosa.segment.timelag_filter(ndi.median_filter)(R, size=(1, 7))
    pd = np.sum(np.diff(M, axis=1) ** 2, axis=0)
    ps = np.exp(-pd / (np.median(pd) + 1e-9))
    Rp = np.diag(ps, 1) + np.diag(ps, -1)
    dp, dr = Rp.sum(1), Rf.sum(1)
    mu = dp.dot(dp + dr) / (np.sum((dp + dr) ** 2) + 1e-9)
    A = mu * Rf + (1 - mu) * Rp
    L = csg.laplacian(A, normed=True)
    _, ev = np.linalg.eigh(L)
    ev = ndi.median_filter(ev, size=(9, 1))
    cn = np.cumsum(ev ** 2, axis=1) ** 0.5
    X = ev[:, :k] / (cn[:, k - 1:k] + 1e-9)
    best = None
    for seed in range(8):
        cen, lab = kmeans2(X, k, minit="++", seed=seed)
        d = float(np.sum((X - cen[lab]) ** 2))
        if best is None or d < best[0]:
            best = (d, lab)
    return best[1]


def runs(labels):
    """[(label, start, end_exclusive)] for runs of equal values."""
    out, s = [], 0
    for i in range(1, len(labels) + 1):
        if i == len(labels) or labels[i] != labels[s]:
            out.append((labels[s], s, i))
            s = i
    return out


def norm_line(s):
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"[’']", "", s.lower())).strip()


# ------------------------------------------------------------------ CLAP tags
# The tagger only answers "what fills this stretch": music, talking, ambience or silence (music-video rips open and
# close with film). Tested on five songs: laion/larger_clap_music loads with collapsed weights under transformers 5
# (every prompt scores the same); with the music+speech checkpoint, genre ("pop punk" for The Temper Trap),
# instrument ("ukulele" for a banjo) and mood tags were too often wrong to hand to a director.
CLAP_MODEL = "laion/larger_clap_music_and_speech"
VOCAB = {"kind": ["music", "people talking", "ambient noise", "silence"]}
PROMPT = {"kind": "{}"}


class Clap:
    """LAION CLAP (music checkpoint, ~0.8 GB download, ~1 GB VRAM): audio windows and text prompts in one space."""
    SR = 48000

    def __init__(self, device):
        import torch
        from transformers import ClapModel, ClapProcessor
        self.torch, self.device = torch, device
        self.model = ClapModel.from_pretrained(CLAP_MODEL).to(device).eval()
        self.proc = ClapProcessor.from_pretrained(CLAP_MODEL)

    def _feat(self, out):
        e = getattr(out, "pooler_output", out)       # transformers 5 may return a model output, 4.x a tensor
        return self.torch.nn.functional.normalize(e, dim=-1).float().cpu().numpy()

    def audio(self, y48, starts, win, batch=8):
        """Embeddings [W x D] of win-second windows of a 48 kHz mono signal starting at `starts` (seconds)."""
        sr, embs = self.SR, []
        with self.torch.inference_mode():
            for i in range(0, len(starts), batch):
                clips = [y48[int(s * sr):int(s * sr) + int(win * sr)] for s in starts[i:i + batch]]
                clips = [np.pad(c, (0, int(win * sr) - len(c))) for c in clips]
                try:
                    inp = self.proc(audio=clips, sampling_rate=sr, return_tensors="pt")
                except TypeError:
                    inp = self.proc(audios=clips, sampling_rate=sr, return_tensors="pt")
                inp = {k: v.to(self.device) for k, v in inp.items()}
                embs.append(self._feat(self.model.get_audio_features(**inp)))
        return np.concatenate(embs) if embs else np.zeros((0, 512))

    def text(self, vocab=None):
        """{group: (tags, text embeddings [T x D])} for VOCAB."""
        out = {}
        with self.torch.inference_mode():
            for g, tags in (vocab or VOCAB).items():
                t = self.proc(text=[PROMPT[g].format(x) for x in tags], return_tensors="pt", padding=True)
                t = {k: v.to(self.device) for k, v in t.items()}
                out[g] = (tags, self._feat(self.model.get_text_features(**t)))
        return out

    def close(self):
        del self.model
