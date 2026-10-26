"""Builds the film soundtrack from the EDL: bar-aligned song segments + crossfades + synthesized SFX + fx.

All SFX are synthesized here (no samples, no voices):
  shutter  - disposable camera shutter (two mechanical clicks)
  wind     - thumbwheel film advance ratchet
  runout   - film flapping off the reel at the end
  projector- quiet projector rattle
  clunk    - VCR swallowing / ejecting a tape
  static   - tape snow hiss
  tape_stop - processed from the song itself (an audio fx, not an sfx)
"""
import math, os
import numpy as np
import librosa
import soundfile as sf
import scipy.signal as sps

from .common import ROOT

SR = 44100


def _bp(x, lo, hi, order=2):
    sos = sps.butter(order, [lo, hi], btype="band", fs=SR, output="sos")
    return sps.sosfilt(sos, x)


def _hp(x, f, order=2):
    return sps.sosfilt(sps.butter(order, f, btype="high", fs=SR, output="sos"), x)


def synth(kind, dur=None, seed=0):
    rng = np.random.default_rng(seed)
    if kind == "shutter":
        n = int(0.16 * SR)
        out = np.zeros(n)
        c1 = _hp(rng.normal(0, 1, int(0.006 * SR)), 2500) * np.exp(-np.arange(int(0.006 * SR)) / (0.0012 * SR))
        out[:len(c1)] += c1
        o2 = int(0.052 * SR)
        c2n = int(0.03 * SR)
        c2 = _bp(rng.normal(0, 1, c2n), 900, 5200) * np.exp(-np.arange(c2n) / (0.006 * SR))
        out[o2:o2 + c2n] += 0.8 * c2
        thump = np.sin(2 * np.pi * 90 * np.arange(int(0.02 * SR)) / SR) * np.exp(-np.arange(int(0.02 * SR)) / (0.004 * SR))
        out[:len(thump)] += 0.25 * thump
        return out / (np.abs(out).max() + 1e-9)
    if kind == "wind":
        dur = dur or 0.55
        n = int(dur * SR)
        out = np.zeros(n)
        k = 11
        times = np.cumsum(np.linspace(0.055, 0.035, k))
        times = times / times[-1] * (dur - 0.06)
        for i, tc in enumerate(times):
            s = int(tc * SR)
            m = int(0.012 * SR)
            ring = np.sin(2 * np.pi * rng.uniform(3800, 4600) * np.arange(m) / SR) * np.exp(-np.arange(m) / (0.0025 * SR))
            burst = _hp(rng.normal(0, 1, m), 2000) * np.exp(-np.arange(m) / (0.0012 * SR))
            out[s:s + m] += (0.6 * ring + burst) * (0.5 + 0.5 * i / k)
        # final latch click
        s = int((dur - 0.05) * SR)
        m = int(0.02 * SR)
        out[s:s + m] += 1.4 * _bp(rng.normal(0, 1, m), 1200, 6000) * np.exp(-np.arange(m) / (0.003 * SR))
        return out / (np.abs(out).max() + 1e-9)
    if kind == "runout":
        dur = dur or 2.0
        n = int(dur * SR)
        t = np.arange(n) / SR
        out = np.zeros(n)
        rate = 22 * np.exp(-t / (dur * 0.8))
        ph = np.cumsum(rate) / SR
        idx = np.where(np.diff(np.floor(ph)) > 0)[0]
        for s in idx:
            m = int(0.01 * SR)
            if s + m < n:
                out[s:s + m] += _bp(rng.normal(0, 1, m), 600, 4000) * np.exp(-np.arange(m) / (0.002 * SR)) * math.exp(-s / n * 2)
        out += _bp(rng.normal(0, 1, n), 2000, 9000) * 0.05 * np.exp(-t / dur * 3)
        return out / (np.abs(out).max() + 1e-9)
    if kind == "stamp":  # rubber stamp on paper: low thud + paper slap
        n = int(0.18 * SR)
        t = np.arange(n) / SR
        thud = np.sin(2 * np.pi * (120 - 50 * t / 0.18) * t) * np.exp(-t / 0.025)
        slap = _bp(rng.normal(0, 1, n), 300, 3500) * np.exp(-t / 0.012)
        out = 0.9 * thud + 0.7 * slap
        return out / (np.abs(out).max() + 1e-9)
    if kind == "page":  # a sketchbook page turning: paper swish rising and falling, a soft flap as it lands
        dur = dur or 0.42
        n = int(dur * SR)
        t = np.arange(n) / SR
        env = np.sin(np.pi * np.clip(t / (dur * 0.85), 0, 1)) ** 1.5
        swish = _bp(rng.normal(0, 1, n), 700, 7000) * env * (0.6 + 0.4 * np.sin(2 * np.pi * 9 * t + seed))
        m = int(0.03 * SR)
        s = n - m - int(0.01 * SR)
        swish[s:s + m] += 0.8 * _bp(rng.normal(0, 1, m), 200, 2500) * np.exp(-np.arange(m) / (0.006 * SR))
        return swish / (np.abs(swish).max() + 1e-9)
    if kind == "pencil":  # a few quick pencil strokes on paper
        dur = dur or 0.3
        n = int(dur * SR)
        out = np.zeros(n)
        for i in range(3):
            s = int(i * n / 3.2)
            m = int(n / 3.6)
            e = np.sin(np.pi * np.arange(m) / m)
            out[s:s + m] += _bp(rng.normal(0, 1, m), 2500, 9000) * e * (1 - 0.2 * i)
        return out / (np.abs(out).max() + 1e-9)
    if kind == "drop":  # polaroid landing on a table
        n = int(0.12 * SR)
        t = np.arange(n) / SR
        out = _bp(rng.normal(0, 1, n), 500, 6000) * np.exp(-t / 0.018) + 0.3 * np.sin(2 * np.pi * 180 * t) * np.exp(-t / 0.01)
        return out / (np.abs(out).max() + 1e-9)
    if kind == "charge":  # disposable flash charging whine
        dur = dur or 1.0
        n = int(dur * SR)
        t = np.arange(n) / SR
        f = 1800 * (9200 / 1800) ** (t / dur) ** 0.6
        ph = 2 * np.pi * np.cumsum(f) / SR
        env = np.clip(t / 0.08, 0, 1) * (0.55 + 0.45 * t / dur)
        out = (np.sin(ph) + 0.25 * np.sin(2 * ph)) * env * (1 + 0.04 * np.sin(2 * np.pi * 37 * t))
        return out / (np.abs(out).max() + 1e-9)
    if kind == "rewind":  # camera rewinding the roll
        dur = dur or 0.9
        n = int(dur * SR)
        t = np.arange(n) / SR
        motor = np.sin(2 * np.pi * np.cumsum(260 + 900 * t / dur) / SR) * 0.4
        clicks = np.zeros(n)
        for k in range(int(dur * 40)):
            s = int(k / 40 * SR)
            m = int(0.004 * SR)
            if s + m < n:
                clicks[s:s + m] += _hp(rng.normal(0, 1, m), 3000)
        out = (motor + 0.5 * clicks) * np.clip(t / 0.05, 0, 1) * np.clip((dur - t) / 0.08, 0, 1)
        return out / (np.abs(out).max() + 1e-9)
    if kind == "clunk":  # VCR swallowing a tape: latch click, low thunk, short motor whirr
        dur = dur or 0.6
        n = int(dur * SR)
        t = np.arange(n) / SR
        out = np.zeros(n)
        m = int(0.015 * SR)
        out[:m] += _bp(rng.normal(0, 1, m), 1500, 7000) * np.exp(-np.arange(m) / (0.002 * SR))
        o = int(0.06 * SR)
        k = int(0.12 * SR)
        tk = np.arange(k) / SR
        out[o:o + k] += 1.3 * np.sin(2 * np.pi * (95 - 40 * tk / 0.12) * tk) * np.exp(-tk / 0.03)
        out[o:o + k] += 0.4 * _bp(rng.normal(0, 1, k), 200, 1200) * np.exp(-tk / 0.02)
        w0 = int(0.18 * SR)
        motor = np.sin(2 * np.pi * np.cumsum(140 + 60 * np.clip((t[w0:] - 0.18) / 0.15, 0, 1)) / SR)
        env = np.clip((t[w0:] - 0.18) / 0.05, 0, 1) * np.clip((dur - t[w0:]) / 0.12, 0, 1)
        out[w0:] += 0.18 * (motor + 0.3 * _bp(rng.normal(0, 1, n - w0), 300, 2500)) * env
        return out / (np.abs(out).max() + 1e-9)
    if kind == "static":  # tape snow / tracking hiss
        dur = dur or 0.3
        n = int(dur * SR)
        t = np.arange(n) / SR
        out = _bp(rng.normal(0, 1, n), 800, 9000) * np.clip(t / 0.01, 0, 1) * np.clip((dur - t) / 0.03, 0, 1)
        return out / (np.abs(out).max() + 1e-9)
    if kind == "projector":
        dur = dur or 2.0
        n = int(dur * SR)
        t = np.arange(n) / SR
        out = 0.3 * np.sin(2 * np.pi * 50 * t) + 0.15 * np.sin(2 * np.pi * 100 * t)
        for k in range(int(dur * 24)):
            s = int(k / 24 * SR)
            m = int(0.008 * SR)
            if s + m < n:
                out[s:s + m] += _bp(rng.normal(0, 1, m), 500, 3000) * np.exp(-np.arange(m) / (0.0015 * SR))
        return out / (np.abs(out).max() + 1e-9)
    raise ValueError(kind)


def lowpass_sweep(x, t0, t1, f0, f1, order=2):
    """Time-varying low-pass between t0 and t1 (cutoff log-interpolated f0 -> f1). x: (2, n)."""
    n_fft, hop = 2048, 512
    out = []
    for ch in x:
        Z = librosa.stft(ch, n_fft=n_fft, hop_length=hop)
        freqs = librosa.fft_frequencies(sr=SR, n_fft=n_fft)[:, None]
        times = librosa.frames_to_time(np.arange(Z.shape[1]), sr=SR, hop_length=hop)
        u = np.clip((times - t0) / max(t1 - t0, 1e-3), 0, 1)
        fc = np.exp(np.log(f0) + (np.log(f1) - np.log(f0)) * u)
        fc = np.where(times < t0, f0, np.where(times > t1, 1e9, fc))[None, :]
        mask = 1 / np.sqrt(1 + (freqs / fc) ** (2 * order))
        out.append(librosa.istft(Z * mask, hop_length=hop, length=len(ch)))
    return np.stack(out)


def tape_stop(x, t0, dur):
    """Slow the audio from t0 to a halt over dur (pitch drops), then silence."""
    s0 = int(t0 * SR)
    n = int(dur * SR)
    seg = x[:, s0:s0 + int(dur * SR * 1.0) + 10]
    tt = np.arange(n) / n
    speed = (1 - tt) ** 1.6
    pos = np.cumsum(speed)
    pos = np.clip(pos, 0, seg.shape[1] - 2)
    i = pos.astype(int)
    fr = pos - i
    y = seg[:, i] * (1 - fr) + seg[:, i + 1] * fr
    y *= np.linspace(1, 0.0, n) ** 0.5
    x[:, s0:s0 + n] = y
    x[:, s0 + n:] = 0
    return x


def build(edl, out_path):
    meta = edl["meta"]
    A = edl["audio"]
    y, _ = librosa.load(os.path.join(ROOT, meta["song"]), sr=SR, mono=False)
    if y.ndim == 1:
        y = np.stack([y, y])
    segs = A["segments"]
    total = meta.get("duration") or max(s["at"] + s["src"][1] - s["src"][0] for s in segs)
    out = np.zeros((2, int(total * SR) + SR))
    xf0 = A.get("xfade", 0.03)
    for i, s in enumerate(segs):
        a, b = s["src"]
        xf = s.get("xfade", xf0)                      # crossfade into this segment
        xf_out = segs[i + 1].get("xfade", xf0) if i + 1 < len(segs) else xf0
        pre = xf / 2 if i > 0 else 0
        post = xf_out / 2 if i + 1 < len(segs) else 0
        i0, i1 = int((a - pre) * SR), int((b + post) * SR)
        chunk = y[:, max(0, i0):i1].copy()
        nf = int(xf * SR)
        nfo = int(xf_out * SR)
        if i > 0 and nf > 0:
            chunk[:, :nf] *= np.sin(np.linspace(0, np.pi / 2, nf))
        else:
            fi = int(s.get("fade_in", 0.01) * SR)
            if fi > 0:
                chunk[:, :fi] *= np.linspace(0, 1, fi)
        if i + 1 < len(segs) and nfo > 0:
            chunk[:, -nfo:] *= np.cos(np.linspace(0, np.pi / 2, nfo))
        p = int((s["at"] - pre) * SR)
        p0 = max(0, p)
        chunk = chunk[:, p0 - p:]
        out[:, p0:p0 + chunk.shape[1]] += chunk[:, :out.shape[1] - p0]
    for fx in A.get("fx", []):
        if fx["type"] == "lowpass":
            out = lowpass_sweep(out, fx["t0"], fx["t1"], fx["f0"], fx["f1"])
        elif fx["type"] == "tape_stop":
            out = tape_stop(out, fx["t"], fx.get("dur", 0.8))
        elif fx["type"] == "duck":  # dip the music (e.g. under a freeze)
            s0, s1 = int(fx["t0"] * SR), int(fx["t1"] * SR)
            g = 10 ** (fx.get("db", -6) / 20)
            ramp = int(0.02 * SR)
            env = np.ones(out.shape[1])
            env[s0:s1] = g
            env[s0:s0 + ramp] = np.linspace(1, g, ramp)
            env[s1 - ramp:s1] = np.linspace(g, 1, ramp)
            out *= env
    for k, e in enumerate(A.get("sfx", [])):
        snd = synth(e["type"], e.get("dur"), seed=k)
        g = 10 ** (e.get("db", -14) / 20)
        s = int(e["t"] * SR)
        pan = e.get("pan", 0.0)
        L, R = math.cos((pan + 1) * math.pi / 4), math.sin((pan + 1) * math.pi / 4)
        n = min(len(snd), out.shape[1] - s)
        if n > 0 and s >= 0:
            out[0, s:s + n] += snd[:n] * g * L * 1.41
            out[1, s:s + n] += snd[:n] * g * R * 1.41
    fo = A.get("fade_out")
    if fo:
        s0, s1 = int(fo[0] * SR), int(fo[1] * SR)
        out[:, s0:s1] *= np.linspace(1, 0, s1 - s0) ** 1.5
        out[:, s1:] = 0
    out = out[:, :int(total * SR)]
    peak = np.abs(out).max()
    if peak > 0.98:
        out *= 0.98 / peak
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    sf.write(out_path, out.T.astype(np.float32), SR, subtype="PCM_24")
    return out_path
