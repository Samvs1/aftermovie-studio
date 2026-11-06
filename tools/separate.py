"""Split each song into drums / bass / other / vocals stems with Demucs.

On an NVIDIA GPU this uses htdemucs_ft (the fine-tuned bag of four models: cleaner vocals, less synth bleed; ~1.5 GB
VRAM in 8 s segments, ~30 s per song on an RTX 4060); on the CPU the single htdemucs model (a few minutes).
Stems are analysis-only (cleaner kicks, bass hits, vocal timing and pitch); the films use the original mix.
Writes cache/stems/<slug>/<stem>.wav (44.1 kHz stereo) + model.txt (which model made them).

usage: python tools/separate.py [slug ...] [--force] [--fallback]

Offline fallback (from Music Video Studio): when Demucs or its weights can't be loaded (first use downloads them from
dl.fbaipublicfiles.com: htdemucs ~80 MB, htdemucs_ft ~320 MB) or --fallback is given, the stems are *estimated* with
librosa: harmonic/percussive separation, a low band for the bass and the centre of the stereo image for the voice.
They are rough (bleed everywhere) but keep the pipeline running; model.txt says "fallback ..." and the song kit says
so (report.json, the song map, the web app) and lowers its confidence. While a song's stems are estimates, every run
(analysing again) tries Demucs again; real stems are kept (--force remakes them).
"""
import os, sys
import numpy as np
import soundfile as sf
import librosa

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze_audio import SONGS, MUSIC, ROOT  # noqa: E402
from am import device as D  # noqa: E402

OUT = os.path.join(ROOT, "cache", "stems")
NAMES = ("vocals", "drums", "bass", "other")


class Demucs:
    """The Demucs model, loaded once for all the songs of a run."""

    def __init__(self):
        import torch
        from demucs.pretrained import get_model
        self.torch = torch
        self.dev = D.pick(2.0)
        self.name = "htdemucs_ft" if self.dev == "cuda" else "htdemucs"
        torch.set_num_threads(max(1, (os.cpu_count() or 2) - 2))
        print(f"   loading {self.name} (first use downloads the weights: htdemucs ~80 MB, htdemucs_ft ~320 MB)", flush=True)
        self.model = get_model(self.name)
        self.model.eval()

    def stems(self, path):
        """({name: (2, n) float32}, sr, label)."""
        from demucs.apply import apply_model
        torch, model = self.torch, self.model
        y, sr = librosa.load(path, sr=model.samplerate, mono=False)
        if y.ndim == 1:
            y = np.stack([y, y])
        wav = torch.tensor(y, dtype=torch.float32)
        ref = wav.mean(0)
        wav = (wav - ref.mean()) / (ref.std() + 1e-8)
        with torch.no_grad():
            sources = apply_model(model, wav[None], device=self.dev, shifts=1, split=True, overlap=0.25, progress=False)[0]
        sources = sources.cpu() * ref.std() + ref.mean()
        out = {stem: src.numpy() for stem, src in zip(model.sources, sources)}
        label = f"{self.name} ({self.dev})"
        del sources, wav
        D.release()
        return out, model.samplerate, label


def fallback_stems(path):
    """Rough stems without a model: HPSS + bands + the stereo centre. Returns ({name: (2, n)}, sr, label)."""
    sr = 44100
    y, _ = librosa.load(path, sr=sr, mono=False)
    if y.ndim == 1:
        y = np.stack([y, y])
    n = y.shape[1]
    mid, side = (y[0] + y[1]) / 2, (y[0] - y[1]) / 2
    nfft, hop = 4096, 1024
    M = librosa.stft(mid, n_fft=nfft, hop_length=hop)
    Sd = librosa.stft(side, n_fft=nfft, hop_length=hop)
    mh, mp = librosa.decompose.hpss(np.abs(M), mask=True, margin=(1.0, 1.5))
    f = librosa.fft_frequencies(sr=sr, n_fft=nfft)[:, None]
    low = 1 / (1 + (f / 180.0) ** 6)                                     # soft low-pass: the bass
    band = (1 / (1 + (150.0 / np.maximum(f, 1)) ** 6)) * (1 / (1 + (f / 6000.0) ** 4))   # the voice's band
    centre = np.clip(1 - np.abs(Sd) / (np.abs(M) + 1e-6), 0, 1) ** 2      # what sits in the middle of the image
    masks = {"drums": mp, "bass": mh * low}
    masks["vocals"] = mh * (1 - low) * band * centre
    masks["other"] = np.clip(mh - masks["bass"] - masks["vocals"], 0, 1)
    out = {}
    for k, m in masks.items():
        x = librosa.istft(M * m, hop_length=hop, length=n)
        if k == "other":                                                   # keep the stereo spread of the band
            xs = librosa.istft(Sd * mh * (1 - low), hop_length=hop, length=n)
            out[k] = np.stack([x + xs, x - xs]).astype(np.float32)
        else:
            out[k] = np.stack([x, x]).astype(np.float32)
    return out, sr, "fallback (librosa HPSS + bands + stereo centre: estimated, not a real separation)"


def estimated(dst):
    mt = os.path.join(dst, "model.txt")
    return os.path.exists(mt) and open(mt, encoding="utf-8", errors="replace").read().startswith("fallback")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force, fallback = "--force" in sys.argv, "--fallback" in sys.argv
    model, failed = None, fallback
    for slug in (args or list(SONGS)):
        dst = os.path.join(OUT, slug)
        have = os.path.exists(os.path.join(dst, "vocals.wav"))
        est = have and estimated(dst)
        if have and not force and (fallback or not est):
            print(f"{slug}: stems exist, skipping (--force to remake)")
            continue
        if est and not force:                      # Demucs wasn't there last time: a real separation if it is now
            print(f"{slug}: the stems are estimates (no Demucs last time): trying Demucs again", flush=True)
        os.makedirs(dst, exist_ok=True)
        path = os.path.join(MUSIC, SONGS[slug])
        stems = None
        if not failed:
            try:
                if model is None:
                    model = Demucs()
                stems, sr, label = model.stems(path)
            except Exception as ex:
                failed = True
                print(f"   Demucs unavailable ({type(ex).__name__}: {str(ex)[:160]})", flush=True)
                print("   WARNING: estimating the stems without a model; the stem lanes, notes and chords will be rough", flush=True)
        if stems is None:
            if est and not force:
                print(f"{slug}: keeping the estimated stems")
                continue
            stems, sr, label = fallback_stems(path)
        for k in NAMES:
            sf.write(os.path.join(dst, f"{k}.wav"), stems[k].T, sr, subtype="PCM_16")
        open(os.path.join(dst, "model.txt"), "w", encoding="utf-8").write(label + "\n")
        print(f"{slug}: wrote {', '.join(NAMES)} with {label}" +
              (f" (peak VRAM {D.peak_gb()} GB)" if "cuda" in label else ""))


if __name__ == "__main__":
    main()
