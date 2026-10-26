"""Split each song into drums / bass / other / vocals stems with Demucs (htdemucs, CPU).

Stems are analysis-only (cleaner kicks, bass hits and vocal timing); the films use the
original mix. Writes cache/stems/<slug>/<stem>.wav (44.1 kHz stereo).

usage: python tools/separate.py [slug ...]
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

OUT = os.path.join(ROOT, "cache", "stems")


def main():
    torch.set_num_threads(max(1, os.cpu_count() - 2))
    model = get_model("htdemucs")
    model.eval()
    for slug in (sys.argv[1:] or list(SONGS)):
        dst = os.path.join(OUT, slug)
        if os.path.exists(os.path.join(dst, "vocals.wav")):
            print(f"{slug}: stems exist, skipping")
            continue
        os.makedirs(dst, exist_ok=True)
        y, sr = librosa.load(os.path.join(MUSIC, SONGS[slug]), sr=model.samplerate, mono=False)
        if y.ndim == 1:
            y = np.stack([y, y])
        wav = torch.tensor(y, dtype=torch.float32)
        ref = wav.mean(0)
        wav = (wav - ref.mean()) / (ref.std() + 1e-8)
        with torch.no_grad():
            sources = apply_model(model, wav[None], device="cpu", shifts=1, split=True, overlap=0.25, progress=False)[0]
        sources = sources * ref.std() + ref.mean()
        for name, src in zip(model.sources, sources):
            sf.write(os.path.join(dst, f"{name}.wav"), src.numpy().T, model.samplerate, subtype="PCM_16")
        print(f"{slug}: wrote {', '.join(model.sources)}")


if __name__ == "__main__":
    main()
