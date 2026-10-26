"""Where the audio models run: the NVIDIA GPU when there is one with room, else the CPU.

Sized for an 8 GB card + 16 GB RAM: the models run one at a time (stems ~1.5 GB, beats ~0.5 GB, lyric aligner
~1.3 GB, pitch ~0.2 GB, music tagger ~1 GB, Whisper turbo ~2 GB of VRAM) and every stage calls release() before the
next loads. AM_DEVICE=cpu forces the CPU (e.g. while the GPU renders a final).
"""
import gc, os

_INFO = None


def pick(min_free_gb=1.0):
    """'cuda' when a CUDA GPU has at least min_free_gb free VRAM, otherwise 'cpu'."""
    if os.environ.get("AM_DEVICE", "").lower() == "cpu":
        return "cpu"
    try:
        import torch
        if torch.cuda.is_available():
            free, _ = torch.cuda.mem_get_info()
            if free / 2 ** 30 >= min_free_gb:
                return "cuda"
            print(f"   GPU has only {free / 2 ** 30:.1f} GB free: running on the CPU")
    except Exception:
        pass
    return "cpu"


def info():
    """{'device', 'gpu', 'vram_gb'} for reports."""
    global _INFO
    if _INFO is None:
        _INFO = {"device": "cpu", "gpu": None, "vram_gb": None}
        try:
            import torch
            if torch.cuda.is_available():
                p = torch.cuda.get_device_properties(0)
                _INFO = {"device": "cuda", "gpu": p.name, "vram_gb": round(p.total_memory / 2 ** 30, 1)}
        except Exception:
            pass
    return dict(_INFO)


def peak_gb():
    """Peak VRAM allocated by torch so far (GB), or None on the CPU."""
    try:
        import torch
        if torch.cuda.is_available():
            return round(torch.cuda.max_memory_allocated() / 2 ** 30, 2)
    except Exception:
        pass
    return None


def release():
    """Free VRAM and RAM between model stages (drop your own references first)."""
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
