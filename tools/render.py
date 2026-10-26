"""Render an aftermovie from its EDL.

  python tools/studio.py run <project> render.py <edl> --preview          # 960x540 quick preview
  python tools/studio.py run <project> render.py <edl>                    # final 1920x1080
  python tools/studio.py run <project> render.py <edl> --stills 9.6,21.5  # PNG frames for checking
  python tools/studio.py run <project> render.py <edl> --preview --start 30 --end 50
  ... --full                                                               # ignore the chunk cache
(studio.py preview / final / stills wrap these.)

Everything (cuts, layers, effects, captions, audio edit) comes from the EDL JSON.

Chunk cache (a render-time saving, never an editing rule): the film is encoded in chunks of whole shots
(cache/render/chunks/). When the next render has exactly the same timeline (every shot boundary, transition, the
audio edit, length, fps), only the chunks whose shots or inputs changed are rendered again: a caption reworded, a
photo swapped, a colour fixed. When ANY timing changed (a shot held longer, a cut moved, the song edit changed),
everything downstream plays differently, so the whole film is rendered fresh.
"""
import argparse, glob, hashlib, json, os, subprocess, sys, time
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from am.common import ROOT  # noqa: E402

_ctx = None


def _init(edl_path, out_w):
    global _ctx
    import cv2
    cv2.setNumThreads(1)
    from am.frame import Ctx
    _ctx = Ctx(json.load(open(edl_path, encoding="utf-8")), out_w)


def _frame(args):
    fidx, t = args
    from am.frame import render_frame
    img = render_frame(_ctx, t, fidx)
    return (img * 255 + 0.5).astype(np.uint8).tobytes()


def free_ram_gb():
    """Available physical memory in GB (Windows API; None elsewhere or on failure)."""
    try:
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = MS()
        m.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.ullAvailPhys / 1e9
    except Exception:
        return None


def default_workers():
    """CPU-scaled, but never more workers than free memory allows (~0.7 GB each: photo + clip caches, canvases)."""
    n = min(8, max(2, (os.cpu_count() or 4) - 2))
    ram = free_ram_gb()
    if ram:
        n = max(2, min(n, int((ram - 1.0) / 0.7)))
    return n


def has_nvenc():
    """True when ffmpeg can actually encode with an NVIDIA GPU (the encoder can be listed without a GPU)."""
    try:
        r = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=256x144:d=0.1",
                            "-c:v", "h264_nvenc", "-f", "null", "-"], capture_output=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False


CHUNK_S = 4.0          # a chunk = consecutive whole shots, at least this long


def _strip(o):
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items() if not k.startswith("_")}
    if isinstance(o, list):
        return [_strip(v) for v in o]
    return o


def _sha(o):
    return hashlib.sha1(json.dumps(o, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()[:20]


def timeline(edl):
    """Fingerprint of everything that decides *when* things happen. Any change here = render the whole film."""
    return _sha({"shots": [[round(s["t0"], 4), round(s["t1"], 4), _strip(s.get("in"))] for s in edl["shots"]],
                 "audio": edl["audio"]["segments"], "dur": edl["meta"]["duration"], "fps": edl["meta"].get("fps", 30)})


def engine_hash():
    """The renderer's own code: an engine change renders everything again."""
    h = hashlib.sha1()
    tools = os.path.dirname(os.path.abspath(__file__))
    for f in sorted(glob.glob(os.path.join(tools, "am", "*.py"))) + [os.path.abspath(__file__)]:
        h.update(open(f, "rb").read())
    return h.hexdigest()[:20]


def chunks(edl, fps):
    """[(frame0, frame1, shot index0, shot index1)]: consecutive whole shots of at least CHUNK_S."""
    sh, out, i0 = edl["shots"], [], 0
    n = int(round(edl["meta"]["duration"] * fps))
    for i, s in enumerate(sh):
        last = i == len(sh) - 1
        if last or sh[i + 1]["t0"] - sh[i0]["t0"] >= CHUNK_S:
            f0 = int(round(sh[i0]["t0"] * fps)) if i0 else 0
            f1 = n if last else int(round(sh[i + 1]["t0"] * fps))
            if f1 > f0:
                out.append((f0, f1, i0, i))
            i0 = i + 1
    return out


def chunk_key(edl, c, fps, out_w, venc, common):
    """Everything that can change the pixels of a chunk: its shots and their neighbours (transitions reach across the
    cut), flashes near it, the photos' files, plus the film-wide look, the encoder and the engine (in common)."""
    f0, f1, i0, i1 = c
    sh = edl["shots"][max(0, i0 - 1):i1 + 2]
    t0, t1 = f0 / fps - 1.0, f1 / fps + 1.0
    from am.common import PHOTOS
    srcs = sorted({x for s in sh for L in s["layers"] for x in ([L["src"]] if isinstance(L.get("src"), str) else L.get("srcs") or [])
                   if isinstance(x, str)})
    mt = {x: os.path.getmtime(os.path.join(PHOTOS, x)) for x in srcs if os.path.exists(os.path.join(PHOTOS, x))}
    return _sha({"shots": _strip(sh), "flashes": [f for f in edl.get("flashes", []) if t0 <= f[0] <= t1], "f": [f0, f1],
                 "photos": mt, "w": out_w, "venc": venc, "common": common})


def render_chunked(edl, edl_path, fps, out_w, out_h, venc, wav, out, workers, mode):
    """Render through the chunk cache (see the module docstring); returns how many chunks were rendered."""
    from am.common import ROOT as PROOT, CACHE
    cdir = os.path.join(CACHE, "render", "chunks", f"{edl['meta']['version']}_{mode}_{out_w}")
    os.makedirs(cdir, exist_ok=True)
    man_p = os.path.join(cdir, "manifest.json")
    try:
        man = json.load(open(man_p, encoding="utf-8"))
    except Exception:
        man = {}
    tl = timeline(edl)
    common = {"grade": edl.get("grade"), "finish": edl.get("finish"), "overlays": edl.get("overlays"),
              "engine": engine_hash(), "analysis": edl["meta"].get("analysis"),
              "audio_json": os.path.getmtime(os.path.join(CACHE, "audio", f"{edl['meta']['analysis']}.json"))}
    plan = chunks(edl, fps)
    keys = [chunk_key(edl, c, fps, out_w, venc, common) for c in plan]
    same_tl = man.get("timeline") == tl
    todo = [k for k, key in enumerate(keys) if not (same_tl and os.path.exists(os.path.join(cdir, key + ".mp4")))]
    if not same_tl and man:
        print("the timeline changed (shot timing, transitions or the song edit): rendering the whole film", flush=True)
    elif todo and len(todo) < len(plan):
        sh = edl["shots"]
        print(f"same timeline: re-rendering {len(todo)}/{len(plan)} chunks (" +
              ", ".join(f"{sh[plan[k][2]]['id']}-{sh[plan[k][3]]['id']}" for k in todo[:8]) + (" ..." if len(todo) > 8 else "") + ")", flush=True)
    elif not todo:
        print("same timeline, nothing changed: reusing every chunk", flush=True)
    frames = [(i, i / fps) for k in todo for i in range(plan[k][0], plan[k][1])]
    t0 = time.time()
    if frames:
        with Pool(workers, initializer=_init, initargs=(edl_path, out_w)) as pool:
            it = pool.imap(_frame, frames, chunksize=4)
            done = 0
            for k in todo:
                f0, f1 = plan[k][:2]
                part = os.path.join(cdir, keys[k] + ".part.mp4")
                ff = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{out_w}x{out_h}",
                                       "-r", str(fps), "-i", "-", *venc, "-bf", "0", "-pix_fmt", "yuv420p",
                                       "-an", "-video_track_timescale", str(fps * 512), part], stdin=subprocess.PIPE)
                for _ in range(f1 - f0):
                    ff.stdin.write(next(it))
                    done += 1
                    if done % 150 == 0:
                        el = time.time() - t0
                        print(f"  frame {done}/{len(frames)}  {el:.0f}s elapsed  ({done / max(el, 1e-3):.1f} fps)", flush=True)
                ff.stdin.close()
                if ff.wait():
                    raise RuntimeError("ffmpeg failed on a chunk")
                os.replace(part, os.path.join(cdir, keys[k] + ".mp4"))
    # chunks are encoded without B-frames (no reordering, no edit lists), so they join frame-exact at the seams
    lst = os.path.join(cdir, "list.txt")
    with open(lst, "w", encoding="utf-8") as fh:
        fh.write("".join(f"file '{key}.mp4'\n" for key in keys))
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-i", wav, "-map", "0:v", "-map", "1:a",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "320k", "-video_track_timescale", str(fps * 512),
                        "-movflags", "+faststart", "-shortest", out])
    if r.returncode:
        raise RuntimeError("ffmpeg could not join the chunks")
    for f in glob.glob(os.path.join(cdir, "*.mp4")):   # chunks no longer used
        if os.path.splitext(os.path.basename(f))[0] not in keys:
            os.remove(f)
    json.dump({"timeline": tl, "chunks": [[*c, key] for c, key in zip(plan, keys)], "at": time.strftime("%Y-%m-%d %H:%M")},
              open(man_p, "w", encoding="utf-8"), indent=1)
    print(f"done in {time.time() - t0:.0f}s ({len(todo)}/{len(plan)} chunks rendered) -> {out}")
    return len(todo)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("edl")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--width", type=int)
    ap.add_argument("--start", type=float, default=0)
    ap.add_argument("--end", type=float)
    ap.add_argument("--stills")
    ap.add_argument("--stills-dir", help="where --stills writes its PNGs (default cache/render)")
    ap.add_argument("--workers", type=int, default=default_workers())
    ap.add_argument("--out")
    ap.add_argument("--full", action="store_true", help="render every frame, ignoring the chunk cache")
    a = ap.parse_args()

    edl_path = os.path.abspath(a.edl)
    edl = json.load(open(edl_path, encoding="utf-8"))
    meta = edl["meta"]
    fps = meta.get("fps", 30)
    out_w = a.width or (960 if a.preview else 1920)
    out_h = out_w * 9 // 16
    name = meta["version"]
    render_dir = os.path.join(ROOT, "cache", "render")
    os.makedirs(render_dir, exist_ok=True)

    # grade every referenced photo up front (single process, cached on disk)
    from am.grade import ensure_graded, photos_in
    g = edl.get("grade", {})
    for ph in sorted(photos_in(edl["shots"])):
        ensure_graded(g.get("preset", "consumer_film"), ph, (g.get("overrides") or {}).get(ph))

    if a.stills:
        _init(edl_path, out_w)
        import cv2
        sdir = a.stills_dir or render_dir
        os.makedirs(sdir, exist_ok=True)
        for t in [float(x) for x in a.stills.split(",")]:
            img = _frame((int(t * fps), t))
            arr = np.frombuffer(img, np.uint8).reshape(out_h, out_w, 3)
            p = os.path.join(sdir, f"{name}_{t:07.3f}.png")
            cv2.imwrite(p, cv2.cvtColor(arr, cv2.COLOR_RGB2BGR))
            print(p)
        return

    from am.audio import build
    t0 = time.time()
    wav = build(edl, os.path.join(render_dir, f"{name}_audio.wav"))
    print(f"audio built in {time.time() - t0:.1f}s -> {wav}")

    dur = meta["duration"]
    end = min(a.end or dur, dur)
    frames = [(i, i / fps) for i in range(int(round(a.start * fps)), int(round(end * fps)))]
    out = a.out or (os.path.join(ROOT, "out", f"{name}_preview.mp4") if a.preview else os.path.join(ROOT, "out", f"{name}.mp4"))
    if has_nvenc():
        if a.preview:
            venc = ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "26", "-b:v", "0"]
        else:
            venc = ["-c:v", "h264_nvenc", "-preset", "p7", "-tune", "hq", "-rc", "vbr", "-cq", "16", "-b:v", "0",
                    "-maxrate", "45M", "-bufsize", "90M", "-profile:v", "high", "-spatial-aq", "1", "-temporal-aq", "1"]
    else:   # no NVIDIA GPU: x264 on the CPU (slower, same look)
        venc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"] if a.preview else \
               ["-c:v", "libx264", "-preset", "slow", "-crf", "17", "-profile:v", "high"]
    if a.preview and not a.full and a.start == 0 and a.end is None and not a.out:     # finals: one fresh pass
        render_chunked(edl, edl_path, fps, out_w, out_h, venc, wav, out, a.workers, "preview" if a.preview else "final")
        return
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{out_w}x{out_h}", "-r", str(fps),
           "-i", "-", "-ss", f"{a.start:.4f}", "-t", f"{end - a.start:.4f}", "-i", wav,
           *venc, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "320k", "-movflags", "+faststart", "-shortest", out]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    t0 = time.time()
    with Pool(a.workers, initializer=_init, initargs=(edl_path, out_w)) as pool:
        for k, buf in enumerate(pool.imap(_frame, frames, chunksize=4)):
            ff.stdin.write(buf)
            if k % 150 == 0:
                el = time.time() - t0
                print(f"  frame {k}/{len(frames)}  {el:.0f}s elapsed  ({(k + 1) / max(el, 1e-3):.1f} fps)", flush=True)
    ff.stdin.close()
    ff.wait()
    print(f"done in {time.time() - t0:.0f}s -> {out}")


if __name__ == "__main__":
    main()
