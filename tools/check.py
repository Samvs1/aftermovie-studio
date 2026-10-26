"""Regression check: do the finished films still build and look the same with the current engine?

  python tools/studio.py check [project ...] [--update] [--no-stills] [--no-build]

For every project (or the ones named) and every builder in it (build.py, build_<film>.py):
  1. EDL: runs the builder with AM_EDL_DIR=cache/check/edl (out/ is never touched) and compares the new EDL with
     the one in out/. "same" = the builder still makes exactly that film; otherwise the shots that differ are listed.
  2. Look: renders a few stills (480 px) from the EDL in out/ and compares them with the reference stills in
     cache/golden/<version>/. A difference means an engine change altered how an existing film looks.
     --update (re)writes the reference stills; run it once after a change you meant to make.
Films = versions in out/ that have a rendered preview or final. Exit code 1 when anything differs or fails.
"""
import argparse, glob, json, os, subprocess, sys, time

import numpy as np

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ENGINE, "tools")
PROJECTS = os.path.join(ENGINE, "projects")
PY = sys.executable
N_STILLS = 6


def env_for(pdir, **extra):
    e = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONWARNINGS="ignore", AM_TOOLS=TOOLS, AM_PROJECT=pdir)
    e.update(extra)
    return e


def norm(o):
    """Round floats so a rebuild that differs only in float noise counts as the same EDL."""
    if isinstance(o, float):
        return round(o, 3)
    if isinstance(o, dict):
        return {k: norm(v) for k, v in o.items() if not k.startswith("_")}
    if isinstance(o, list):
        return [norm(v) for v in o]
    return o


def shot_key(s):
    media = sorted({L.get("src") for L in s["layers"] if isinstance(L.get("src"), str)})
    return ",".join(media) or s.get("sync", "")[:40]


def edl_diff(old, new):
    """Short human list of what differs between two EDLs."""
    out = []
    for k in ("meta", "audio", "grade", "finish", "flashes", "overlays"):
        if norm(old.get(k)) != norm(new.get(k)):
            out.append(f"{k} differs")
    so, sn = old["shots"], new["shots"]
    if len(so) != len(sn):
        out.append(f"{len(so)} -> {len(sn)} shots")
    bad = []
    for a, b in zip(so, sn):
        if norm(a) != norm(b):
            why = "timing" if (round(a["t0"], 3), round(a["t1"], 3)) != (round(b["t0"], 3), round(b["t1"], 3)) else \
                  "photos" if shot_key(a) != shot_key(b) else "layers"
            bad.append(f"{a['id']} @{a['t0']:.2f} ({why})")
    if bad:
        out.append(f"{len(bad)} shot(s) differ: " + ", ".join(bad[:6]) + (" ..." if len(bad) > 6 else ""))
    return out


def films(pdir):
    out = []
    for p in sorted(glob.glob(os.path.join(pdir, "out", "*_edl.json"))):
        v = os.path.basename(p)[:-len("_edl.json")]
        if any(os.path.exists(os.path.join(pdir, "out", f)) for f in (f"{v}.mp4", f"{v}_preview.mp4", f"{v}_preview_share.mp4")):
            out.append(v)
    return out


def still_times(edl, n=N_STILLS):
    sh = edl["shots"]
    pick = [sh[min(len(sh) - 1, round((k + 0.5) * len(sh) / n))] for k in range(n)]
    return sorted({round((s["t0"] + s["t1"]) / 2, 3) for s in pick})


def compare(a, b):
    """(mean abs diff, worst 16x16 block mean) in 0..255."""
    import cv2
    A, B = cv2.imread(a).astype(np.float32), cv2.imread(b).astype(np.float32)
    if A.shape != B.shape:
        return 255.0, 255.0
    d = np.abs(A - B).mean(-1)
    h, w = (d.shape[0] // 16) * 16, (d.shape[1] // 16) * 16
    blocks = d[:h, :w].reshape(h // 16, 16, w // 16, 16).mean(axis=(1, 3))
    return float(d.mean()), float(blocks.max())


def check_edls(pdir, log):
    builders = sorted(f for f in os.listdir(pdir) if f == "build.py" or (f.startswith("build_") and f.endswith(".py")))
    tmp = os.path.join(pdir, "cache", "check", "edl")
    ok = True
    for b in builders:
        os.makedirs(tmp, exist_ok=True)
        for f in glob.glob(os.path.join(tmp, "*_edl.json")):
            os.remove(f)
        t0 = time.time()
        r = subprocess.run([PY, "-W", "ignore", os.path.join(pdir, b)], cwd=ENGINE, env=env_for(pdir, AM_EDL_DIR=tmp),
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode:
            log(f"  [!!] {b}: builder failed\n" + "\n".join("       " + l for l in (r.stdout + r.stderr).strip().splitlines()[-6:]))
            ok = False
            continue
        made = glob.glob(os.path.join(tmp, "*_edl.json"))
        if not made:
            log(f"  [!!] {b}: wrote no EDL")
            ok = False
        for p in made:
            name = os.path.basename(p)
            ref = os.path.join(pdir, "out", name)
            if not os.path.exists(ref):
                log(f"  [ok] {b} -> {name}: new (nothing in out/ to compare with)")
                continue
            d = edl_diff(json.load(open(ref, encoding="utf-8")), json.load(open(p, encoding="utf-8")))
            if d:
                ok = False
                log(f"  [!!] {b} -> {name}: the rebuild differs from out/: " + "; ".join(d))
            else:
                log(f"  [ok] {b} -> {name}: same EDL ({time.time() - t0:.0f}s)")
    return ok


def check_stills(pdir, update, log):
    ok = True
    for v in films(pdir):
        edl_p = os.path.join(pdir, "out", f"{v}_edl.json")
        edl = json.load(open(edl_p, encoding="utf-8"))
        ts = still_times(edl)
        gold = os.path.join(pdir, "cache", "golden", v)
        new = os.path.join(pdir, "cache", "check", "stills", v)
        r = subprocess.run([PY, "-W", "ignore", os.path.join(TOOLS, "render.py"), edl_p, "--width", "480", "--stills",
                            ",".join(f"{t:.3f}" for t in ts), "--stills-dir", gold if update else new],
                           cwd=ENGINE, env=env_for(pdir), capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode:
            log(f"  [!!] {v}: stills failed: " + (r.stdout + r.stderr).strip().splitlines()[-1][:200])
            ok = False
            continue
        if update:
            log(f"  [ok] {v}: {len(ts)} reference stills saved")
            continue
        worst, missing = [], 0
        for t in ts:
            fn = f"{v}_{t:07.3f}.png"
            if not os.path.exists(os.path.join(gold, fn)):
                missing += 1
                continue
            m, blk = compare(os.path.join(gold, fn), os.path.join(new, fn))
            if m > 1.5 or blk > 14:
                worst.append(f"{t:.1f}s (mean {m:.1f}, patch {blk:.0f})")
        if missing == len(ts):
            log(f"  [--] {v}: no reference stills yet (run with --update)")
        elif worst:
            ok = False
            log(f"  [!!] {v}: looks different at " + ", ".join(worst) + f"  -> compare cache/check/stills/{v} with cache/golden/{v}")
        else:
            log(f"  [ok] {v}: {len(ts) - missing} stills look the same")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("projects", nargs="*")
    ap.add_argument("--update", action="store_true", help="save the current look as the reference stills")
    ap.add_argument("--no-stills", action="store_true")
    ap.add_argument("--no-build", action="store_true")
    a = ap.parse_args()
    names = a.projects or sorted(n for n in os.listdir(PROJECTS) if not n.startswith("_") and
                                 os.path.isfile(os.path.join(PROJECTS, n, "project.json")))
    ok = True
    for n in names:
        pdir = os.path.join(PROJECTS, "elevate-2026" if n == "elevate" else n)
        has_builder = any(f == "build.py" or (f.startswith("build_") and f.endswith(".py")) for f in os.listdir(pdir))
        if not has_builder and not films(pdir):
            continue
        print(f"{os.path.basename(pdir)}", flush=True)
        log = lambda s: print(s, flush=True)  # noqa: E731
        if not a.no_build and has_builder:
            ok &= check_edls(pdir, log)
        if not a.no_stills:
            ok &= check_stills(pdir, a.update, log)
    print("all films unchanged" if ok else "some films changed or failed: see the [!!] lines")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
