"""QA for a rendered aftermovie.

  python tools/studio.py run <project> qa.py <edl> [--video <rendered.mp4>]   (studio.py preview runs it)

Writes cache/qa/<version>/report.md + contact sheets:
  1. Sync: every visual event detected in the *rendered video* (frame-difference peaks) is matched
     to the nearest musical event (beat / 8th / kick / snare / vocal word / stop). Also checks every
     EDL shot boundary against the grid.
  2. Adjacent shots: layout/motion/transition signature + image similarity of neighbouring shots.
  3. Faces: no photo crop cuts through a face at the start or end of its move.
  4. Text: luminance contrast of every caption against what is behind it + minimum size.
  4b. Reading time: every caption stays up long enough to read before it goes or the shot cuts.
  4c. Screen time: every photo stays up >= 1.8 s (MIN_PHOTO_S) from landing to the cut (layers marked "quick" are skipped).
  4d. Photo visibility: each photo, once its shot has settled, keeps at least VISIBLE of its own contrast (a faint
      pencil sketch or a washed-out blend is "hard to see").
  4e. Treatments: no photo stays a pencil drawing, and no slow look is still changing when its shot cuts.
  2c. Near-duplicates: no two photos of the same view (a burst, or reframed) land close together.
  6. Must-haves: starred photos (project.json must_use) are in, story-order rules (order) hold.
  7. Caption board: every line, where it came from, and what the user ticked or vetoed in the studio.
  5. Audio: level continuity and click check at every segment joint.
"""
import argparse, json, os, subprocess, sys
import numpy as np
import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from am.common import ROOT  # noqa: E402
from am.music import MusicMap  # noqa: E402
from am.photo import plan_crop, cut_faces  # noqa: E402
from am.builder import MIN_PHOTO_S, screen_time  # noqa: E402
from am import checks  # noqa: E402
from am.common import project  # noqa: E402

VISIBLE = 0.45       # rendered contrast / the photo's own contrast below this = hard to see (calibrated on the finished films)


def read_video_small(path, w=192, h=108):
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    n = len(raw) // (w * h * 3)
    return np.frombuffer(raw[:n * w * h * 3], np.uint8).reshape(n, h, w, 3).astype(np.float32) / 255


def frame_at(path, t, w=640):
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{max(0, t):.3f}", "-i", path, "-frames:v", "1", "-vf", f"scale={w}:-2",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    h = len(raw) // (w * 3)
    return np.frombuffer(raw, np.uint8).reshape(h, w, 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("edl")
    ap.add_argument("--video")
    a = ap.parse_args()
    edl = json.load(open(a.edl, encoding="utf-8"))
    name = edl["meta"]["version"]
    fps = edl["meta"].get("fps", 30)
    video = a.video or os.path.join(ROOT, "out", f"{name}_preview.mp4")
    qdir = os.path.join(ROOT, "cache", "qa", name)
    os.makedirs(qdir, exist_ok=True)
    mm = MusicMap(edl)
    rep = [f"# QA report: {name}", "", f"video: `{os.path.relpath(video, ROOT)}`", ""]

    # musical grid (film time)
    beats = mm.ev["beats"][0]
    per = float(np.median(np.diff(beats)))
    fill = []
    for a_, b_ in zip(beats[:-1], beats[1:]):          # felt pulse continues through ring-outs / silences
        k_ = 1
        while b_ - a_ > 1.6 * per and a_ + k_ * per < b_ - 0.5 * per and k_ <= 12:
            fill.append(a_ + k_ * per)
            k_ += 1
    per_end = float(np.median(np.diff(beats[-16:])))       # felt pulse after the song: the closing tempo (= Builder.snap)
    beats = np.sort(np.r_[beats, fill, beats[-1] + per_end * np.arange(1, 41)])
    eighths = np.sort(np.r_[beats, (beats[:-1] + beats[1:]) / 2])
    sixteenths = np.sort(np.r_[eighths, (eighths[:-1] + eighths[1:]) / 2])
    words = np.array([w[0] for w in mm.words])
    events = {"beat": beats, "8th": eighths, "16th": sixteenths, "kick": mm.ev["kicks"][0], "snare": mm.ev["snares"][0],
              "word": words, "onset": mm.ev["onsets"][0]}

    def nearest_event(t):
        best = (9, None, None)
        for k in ["beat", "8th", "word", "kick", "snare", "16th", "onset"]:
            arr = events[k]
            if len(arr):
                i = int(np.argmin(np.abs(arr - t)))
                d = t - arr[i]
                if abs(d) < abs(best[0]) - 0.004:  # prefer earlier kinds on ties
                    best = (d, k, float(arr[i]))
        return best

    # ---------------------------------------------------------------- 1a. EDL boundaries
    rep += ["## 1. Sync", "", "### EDL shot boundaries vs music", "", "| shot | t0 | nearest event | offset ms | sync note |", "|---|---|---|---|---|"]
    bad = 0
    for s in edl["shots"][1:]:
        d, k, te = nearest_event(s["t0"])
        flag = "" if abs(d) <= 1 / fps else " ⚠"
        bad += abs(d) > 1 / fps
        rep.append(f"| {s['id']} | {s['t0']:.3f} | {k} {te:.3f} | {d * 1000:+.0f}{flag} | {s.get('sync', '')} |")
    rep += ["", f"**{len(edl['shots']) - 1 - bad}/{len(edl['shots']) - 1} shot boundaries within one frame ({1000 / fps:.0f} ms) of a musical event.**", ""]

    # ---------------------------------------------------------------- 1b. detected visual events in the video
    V = read_video_small(video)
    n = len(V)
    diff = np.r_[0, np.abs(np.diff(V, axis=0)).mean(axis=(1, 2, 3))]
    base = cv2.GaussianBlur(diff.reshape(-1, 1), (1, 31), 8).ravel()
    from scipy.signal import find_peaks
    pk, _ = find_peaks(diff, height=np.maximum(0.06, base * 2.2), distance=3)
    rows, unsynced = [], 0
    windows = []
    for s_ in edl["shots"][1:]:
        tr = s_.get("in") or {}
        if tr.get("type", "cut") not in ("cut", "flash") and tr.get("align", "center") == "center":
            d_ = tr.get("dur", 0.3)
            windows.append((s_["t0"] - d_ / 2 - 1 / fps, s_["t0"] + d_ / 2, s_["t0"]))
    for p in pk:
        q = p
        while q > 0 and diff[q - 1] > 0.35 * diff[p] and p - q < 6:
            q -= 1
        t = q / fps
        win = [w_ for w_ in windows if w_[0] <= t <= w_[1]]
        d, k, te = nearest_event(win[0][2] if win else t)
        if win:
            k = "centred transition @ " + k
        # a cut at frame p shows at time p/fps; allow one frame either way
        ok = abs(d) <= 1.0 / fps + 0.004
        unsynced += not ok
        rows.append(f"| {t:.3f} | {diff[p]:.3f} | {k} {te:.3f} | {d * 1000:+.0f}{'' if ok else ' ⚠'} |")
    rep += ["### Visual events detected in the rendered video", "",
            f"{len(pk)} hard visual changes (cuts, flashes, drops, stamps) found by frame differencing; "
            f"**{len(pk) - unsynced} land within one frame of a musical event**.", "",
            "| t (s) | strength | nearest musical event | offset ms |", "|---|---|---|---|"] + rows + [""]

    # ---------------------------------------------------------------- 2. adjacent shots
    def signature(s):
        # decoration (shapes, stickers) is not the layout; but a collage film varies its full-frame backdrops and tile
        # frames from shot to shot, so those join the signature (pattern fills with a "hole" are frames)
        deco = ("text", "seven", "marker", "flag", "stamp", "fill", "shape", "sticker")
        lay = [L["type"] for L in s["layers"] if L["type"] not in deco]
        main = lay[0] if lay else "other"
        photo_layers = [L for L in s["layers"] if L["type"] == "photo"]
        media = [L for L in s["layers"] if L["type"] in ("photo", "video", "type_mask", "slices", "polaroid")]
        if main == "photo" and len(photo_layers) > 1:
            main = "split"
        shapes = [L for L in s["layers"] if L["type"] == "shape"]
        bg = next((f"{L.get('motif', L['kind'])}:{(L.get('colors') or [L.get('color', '')])[0]}" for L in shapes
                   if L.get("w", 0) >= 1900 and L.get("h", 0) >= 1060 and not L.get("hole")), "")
        frames = sorted({f"{L.get('motif')}:{(L.get('colors') or [''])[0]}" for L in shapes if L.get("hole")})
        if frames:
            main = f"framed x{len(media)}" if len(media) <= 3 else "collage"
        if bg or frames:
            main += f" | bg {bg or '-'} | {','.join(frames) or '-'}"
        mv = "-"
        if photo_layers:
            z = photo_layers[0].get("zoom", [1, 1])
            z = z if isinstance(z, list) else [z, z]
            dr = photo_layers[0].get("drift", [[0, 0], [0, 0]])
            mv = "push" if z[1] > z[0] + 0.02 else ("pull" if z[0] > z[1] + 0.02 else "hold")
            if abs(dr[1][0] - dr[0][0]) > 0.04:
                mv += "+pan"
            if photo_layers[0].get("pulse"):
                mv += "+pulse"
        tr = (s.get("in") or {}).get("type", "cut")
        return main, mv, tr
    rep += ["## 2. Adjacent shots", "", "| shot | layout | motion | transition in | image similarity to previous | flag |", "|---|---|---|---|---|---|"]
    prev_sig, prev_img = None, None
    same = 0
    for s in edl["shots"]:
        sig = signature(s)
        mid = (s["t0"] + s["t1"]) / 2
        fi = min(n - 1, int(mid * fps))
        img = cv2.resize(V[fi], (48, 27))
        hsv = cv2.cvtColor((img * 255).astype(np.uint8), cv2.COLOR_RGB2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [12, 6], [0, 180, 0, 256]).ravel()
        hist /= hist.sum() + 1e-9
        sim = None
        flag = ""
        if prev_img is not None:
            sim = float(np.minimum(hist, prev_img).sum())
            if sig == prev_sig:
                flag = "⚠ same treatment"
                same += 1
            elif sim > 0.85 and sig[0] == prev_sig[0]:
                flag = "⚠ looks alike"
                same += 1
        rep.append(f"| {s['id']} | {sig[0]} | {sig[1]} | {sig[2]} | {'' if sim is None else f'{sim:.2f}'} | {flag} |")
        prev_sig, prev_img = sig, hist
    rep += ["", f"**{same} adjacent pairs flagged.**", ""]

    # ---------------------------------------------------------------- 2b. photo reuse
    counts = {}

    def walk(o):
        if isinstance(o, dict):
            for k_, v_ in o.items():
                if k_ == "src" and isinstance(v_, str) and v_.lower().endswith(".jpg"):
                    counts[v_] = counts.get(v_, 0) + 1
                elif k_ == "srcs" and isinstance(v_, list):
                    for x_ in v_:
                        counts[x_] = counts.get(x_, 0) + 1
                else:
                    walk(v_)
        elif isinstance(o, list):
            for v_ in o:
                walk(v_)
    walk(edl["shots"])
    dups = {k_: v_ for k_, v_ in counts.items() if v_ > 1}
    rep += ["## 2b. Photo reuse", "", f"{len(counts)} distinct photos; **{len(dups)} used more than once**."] + \
           [f"- {k_}: {v_}x" for k_, v_ in dups.items()] + [""]

    # ---------------------------------------------------------------- 2c. near-duplicates (Sam: "very similar shot side by side")
    nd = checks.near_dupes(edl)
    rep += ["## 2c. Near-duplicate photos", "",
            f"Different photos of the same view (a burst, or the same spot reframed) within {checks.DUPE_WINDOW:g} s or in one shot. "
            "Skipped: pairs with different named people (one of each of you), grids of 4+, layers marked `twin`.", ""] + \
           [f"- {ta:.2f}s {a_} ~ {tb:.2f}s {b_} ({why}) ⚠" for a_, b_, ta, tb, why in nd] + \
           ["", f"**{len(nd)} near-duplicate pairs close together.**", ""]

    # ---------------------------------------------------------------- 3. faces
    rep += ["## 3. Faces cut by crops", ""]
    fcount, fbad = 0, []
    for s in edl["shots"]:
        for L in s["layers"]:
            if L["type"] != "photo":
                continue
            box = L.get("box", [0, 0, 1920, 1080])
            z = L.get("zoom", [1, 1.08])
            z = z if isinstance(z, list) else [z, z]
            dr = L.get("drift", [[0, 0], [0, 0]])
            for zi, di in zip(z, dr):
                c = plan_crop(L["src"], box[2] / box[3], zi, L.get("focus", "faces"), di)
                fcount += 1
                k = cut_faces(L["src"], c)
                if k:
                    fbad.append(f"{s['id']} {L['src']} zoom {zi}: {k} face(s) cut")
    rep += [f"{fcount} crop keyframes checked, **{len(fbad)} cut a face**."] + [f"- {x}" for x in fbad] + [""]

    # ---------------------------------------------------------------- 4. text readability
    from am.frame import Ctx, render_shot
    from am import draw as D
    ctx = Ctx(edl, 960)
    rep += ["## 4. Text readability (rendered at 960 px, contrast = WCAG luminance ratio text vs surroundings)", "",
            "| shot | text | size @1080p | contrast | verdict |", "|---|---|---|---|---|"]
    low = 0

    def lum(rgb):
        c = np.where(rgb <= 0.03928, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
        return 0.2126 * c[..., 0] + 0.7152 * c[..., 1] + 0.0722 * c[..., 2]
    for s in edl["shots"]:
        for L in s["layers"]:
            if L["type"] != "text":
                continue
            t0_, t1_ = L.get("t0", s["t0"]), L.get("t1", s["t1"])
            t = t0_ + (t1_ - t0_) * 0.6
            t = max(t, t0_ + L.get("dur", 0.22) + 0.03)
            t = min(t, t1_ - L.get("fade_out", 0.15) - 0.02)
            with_txt = render_shot(ctx, s, t)
            col = L.get("color", "#ffffff")
            L["color"] = "#00ff00" if col.lower() != "#00ff00" else "#ff00ff"
            swapped = render_shot(ctx, s, t)
            L["color"] = col
            m = np.abs(with_txt - swapped).max(-1) > 0.2          # exactly the glyph pixels
            if m.sum() < 20:
                continue
            core = cv2.erode(m.astype(np.uint8), np.ones((2, 2), np.uint8)).astype(bool)
            core = core if core.sum() > 10 else m
            m8 = m.astype(np.uint8)
            ring = cv2.dilate(m8, np.ones((9, 9), np.uint8)).astype(bool) & ~cv2.dilate(m8, np.ones((3, 3), np.uint8)).astype(bool)
            lt = lum(with_txt[core]).mean()
            lb = lum(with_txt[ring]).mean()
            cr = (max(lt, lb) + 0.05) / (min(lt, lb) + 0.05)
            size = L.get("size", 64)
            ok = cr >= 3.0 and size >= 34
            low += not ok
            txt = L["text"].replace("\n", " / ")[:40]
            rep.append(f"| {s['id']} | {txt} | {size} | {cr:.1f}:1 | {'ok' if ok else '⚠ low'} |")
    rep += ["", f"**{low} captions below 3:1 contrast or 34 px.**", ""]

    # ---------------------------------------------------------------- 4b. reading time (Sam: "you cannot read it in time")
    rt = checks.reading_time(edl)
    rep += ["## 4b. Reading time", "",
            "Each caption must stay fully visible for ~0.8 s + 55 ms per character (1.4-3.0 s) before it disappears or the shot cuts.", "",
            "| shot | t0 | text | visible s | needed s |", "|---|---|---|---|---|"] + \
           [f"| {sid} | {t0_:.2f} | {tx[:40].replace(chr(10), ' / ')} | {shown_:.2f} ⚠ | {need_:.2f} |" for sid, t0_, tx, shown_, need_ in rt] + \
           ["", f"**{len(rt)} captions shown too briefly to read.**", ""]

    # ---------------------------------------------------------------- 4c. screen time (Sam: "some go past too quickly")
    quick = screen_time(edl)
    rep += ["## 4c. Photo screen time", "",
            f"Each photo or clip stays up at least {MIN_PHOTO_S:.1f} s from when it lands until it goes or the shot cuts "
            "(a layer marked `quick` is a deliberate flash and is skipped).", "",
            "| shot | lands | photo | on screen s |", "|---|---|---|---|"] + \
           [f"| {sid} | {land:.2f} | {src[:40]} | {d:.2f} ⚠ |" for sid, src, land, d in quick] + \
           ["", f"**{len(quick)} photos on screen under {MIN_PHOTO_S:.1f} s.**", ""]

    # ---------------------------------------------------------------- 4d. photo visibility (Sam: "the image on the left is hard to see")
    from am.common import photo_meta
    meta = photo_meta()
    rep += ["## 4d. Photo visibility", "",
            f"Each photo once its shot has settled (the storyboard moment): contrast on screen / the photo's own contrast. "
            f"Under {VISIBLE:.2f} reads as faint (a light pencil sketch, a washed-out blend).", "",
            "| shot | t | photo | visible | |", "|---|---|---|---|---|"]
    faint = 0
    for s in edl["shots"]:
        t = checks.settled(s)
        layers = [L for L in s["layers"] if L["type"] == "photo" and not L.get("quick") and L["src"] in meta
                  and checks.window(s, L)[0] <= t < checks.window(s, L)[1]]
        if not layers:
            continue
        img = render_shot(ctx, s, t)
        g = img @ np.array([0.299, 0.587, 0.114], np.float32)
        for L in layers:
            x, y, w, h = L.get("box", [0, 0, 1920, 1080])
            k = ctx.W / 1920
            x0, y0 = int(max(0, (x + 0.1 * w) * k)), int(max(0, (y + 0.1 * h) * k))
            x1, y1 = int(min(ctx.W, (x + 0.9 * w) * k)), int(min(ctx.H, (y + 0.9 * h) * k))
            if x1 - x0 < 8 or y1 - y0 < 8:
                continue
            own = max(meta[L["src"]].get("contrast", 0.2), 0.05)
            ratio = float(g[y0:y1, x0:x1].std()) / own
            if ratio < VISIBLE:
                faint += 1
                rep.append(f"| {s['id']} | {t:.2f} | {L['src'][:40]} | {ratio:.2f} | ⚠ faint |")
    rep += ["", f"**{faint} photos too faint to see.**", ""]

    # ---------------------------------------------------------------- 4e. treatments that never arrive
    rs = checks.resolve(edl)
    rep += ["## 4e. Treatments", "", "A look that changes over time (sketch, bloom, fade) has to arrive while the photo is up.", ""] + \
           [f"- {sid} {land:.2f}s {src[:40]}: {why} ⚠" for sid, src, land, why in rs] + \
           ["", f"**{len(rs)} photos whose treatment never arrives.**", ""]

    # ---------------------------------------------------------------- 6. must-haves
    pj = project()
    mu = checks.musts(edl, pj)
    rep += ["## 6. Must-haves", "", f"{len(pj.get('must_use') or [])} starred photos, {len(pj.get('order') or [])} story-order rules "
            "(project.json `must_use` / `order`).", ""] + \
           [f"- missing: {m_} ⚠" for m_ in mu["missing"]] + [f"- {r_}: {why} ⚠" for r_, why in mu["order"]] + \
           ["", f"**{len(mu['missing'])} starred photos missing, {len(mu['order'])} story-order rules broken.**", ""]

    # ---------------------------------------------------------------- 7. caption board
    caps = checks.captions(edl, pj)
    rv = checks.caption_review(caps)
    rep += ["## 7. Caption board", "",
            "Every line on screen, the photos it sits on and where it came from. Lines from the song or the user's own words "
            "are trusted; the rest the user ticks or vetoes on the studio's Storyboard tab.", "",
            "| shot | t | text | source | basis | user |", "|---|---|---|---|---|---|"]
    for c in caps:
        d_ = rv["decisions"].get(c["key"], {})
        verdict = "vetoed ⚠ " + d_.get("comment", "") if d_.get("ok") is False else "ok" if d_.get("ok") else ("to check" if c["check"] else "")
        rep.append(f"| {c['shot']} | {c['t0']:.2f} | {c['text'][:40].replace(chr(10), ' / ')} | {c['origin']} | {c['basis'][:40]} | {verdict} |")
    rep += ["", f"**{len(rv['vetoed'])} captions vetoed, {len(rv['unreviewed'])} not reviewed yet, "
            f"{sum(c['origin'] == '?' for c in caps)} with no source.**", ""]

    # ---------------------------------------------------------------- 5. audio joints
    import soundfile as sf
    wav = os.path.join(ROOT, "cache", "render", f"{name}_audio.wav")
    y, sr = sf.read(wav)
    y = y.mean(1) if y.ndim > 1 else y
    rep += ["## 5. Audio joints", "", "| joint (film s) | level before dB | level after dB | step dB | click (HF jump) |", "|---|---|---|---|---|"]
    for seg in edl["audio"]["segments"][1:]:
        t = seg["at"]
        i = int(t * sr)
        w = int(0.25 * sr)
        lb = 20 * np.log10(np.sqrt(np.mean(y[i - w:i] ** 2)) + 1e-9)
        la = 20 * np.log10(np.sqrt(np.mean(y[i:i + w] ** 2)) + 1e-9)
        if lb < -90:
            rep.append(f"| {t:.3f} | silence | {la:.1f} | (starts after silence: epilogue) | - |")
            continue
        hp = np.diff(y[i - int(0.02 * sr):i + int(0.02 * sr)])
        ref = np.diff(y[i - int(0.3 * sr):i - int(0.1 * sr)])
        click = np.abs(hp).max() / (np.abs(ref).max() + 1e-9)
        rep.append(f"| {t:.3f} | {lb:.1f} | {la:.1f} | {la - lb:+.1f} | {click:.2f}{' ⚠' if click > 2.0 else ''} |")
    rep.append("")

    # ---------------------------------------------------------------- contact sheets at cuts
    tiles = []
    for s in edl["shots"]:
        for dt, tag in [(-1.0 / fps, "before"), (2.0 / fps, "after")]:
            t = s["t0"] + dt
            if 0 <= t < edl["meta"]["duration"]:
                tiles.append((s["id"], tag, t, frame_at(video, t, 320)))
    W, H = 320, 180
    cols = 8
    per = 48
    for si in range(0, len(tiles), per):
        chunk = tiles[si:si + per]
        rows_ = (len(chunk) + cols - 1) // cols
        sheet = np.zeros((rows_ * (H + 18), cols * W, 3), np.uint8)
        for k, (sid, tag, t, im) in enumerate(chunk):
            r, c = divmod(k, cols)
            im = cv2.resize(im, (W, H))
            sheet[r * (H + 18):r * (H + 18) + H, c * W:(c + 1) * W] = im
            cv2.putText(sheet, f"{sid} {tag} {t:.2f}", (c * W + 4, r * (H + 18) + H + 13), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 230, 0), 1, cv2.LINE_AA)
        cv2.imwrite(os.path.join(qdir, f"cuts_{si // per + 1}.jpg"), cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
    open(os.path.join(qdir, "report.md"), "w", encoding="utf-8").write("\n".join(rep))
    print("\n".join(l for l in rep if l.startswith("**") or l.startswith("#")))
    print("report:", os.path.join(qdir, "report.md"))


if __name__ == "__main__":
    main()
