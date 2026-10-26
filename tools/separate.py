"""Split each song into drums / bass / other / vocals stems with Demucs.

On an NVIDIA GPU this uses htdemucs_ft (the fine-tuned bag of four models: cleaner vocals, less synth bleed; ~1.5 GB
VRAM in 8 s segments, ~30 s per song on an RTX 4060); on the CPU the single htdemucs model (a few minutes).
Stems are analysis-only (cleaner kicks, bass hits, vocal timing and pitch); the films use the original mix.
Writes cache/stems/<slug>/<stem>.wav (44.1 kHz stereo) + model.txt (which model made them).

usage: python tools/separate.py [slug ...] [--force]
"""
import os, sys
import numpy as np
import soundfile as sf
import librosa
import torch
from demucs.pretrained import get_model
from demucs.apply import apply_model

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze_audio import SONGS, MUSIC, ROOT  # noqa: E402
from am import device as D  # noqa: E402

OUT = os.path.join(ROOT, "cache", "stems")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    dev = D.pick(2.0)
    name = "htdemucs_ft" if dev == "cuda" else "htdemucs"
    torch.set_num_threads(max(1, os.cpu_count() - 2))
    model = None
    for slug in (args or list(SONGS)):
        dst = os.path.join(OUT, slug)
        if os.path.exists(os.path.join(dst, "vocals.wav")) and not force:
            print(f"{slug}: stems exist, skipping (--force to remake)")
            continue
        if model is None:
            model = get_model(name)
            model.eval()
        os.makedirs(dst, exist_ok=True)
        y, sr = librosa.load(os.path.join(MUSIC, SONGS[slug]), sr=model.samplerate, mono=False)
        if y.ndim == 1:
            y = np.stack([y, y])
        wav = torch.tensor(y, dtype=torch.float32)
        ref = wav.mean(0)
        wav = (wav - ref.mean()) / (ref.std() + 1e-8)
        with torch.no_grad():
            sources = apply_model(model, wav[None], device=dev, shifts=1, split=True, overlap=0.25, progress=False)[0]
        sources = sources.cpu() * ref.std() + ref.mean()
        for stem, src in zip(model.sources, sources):
            sf.write(os.path.join(dst, f"{stem}.wav"), src.numpy().T, model.samplerate, subtype="PCM_16")
        open(os.path.join(dst, "model.txt"), "w").write(f"{name} ({dev})\n")
        print(f"{slug}: wrote {', '.join(model.sources)} with {name} on {dev}" +
              (f" (peak VRAM {D.peak_gb()} GB)" if dev == "cuda" else ""))
        del sources, wav
        D.release()


if __name__ == "__main__":
    main()
