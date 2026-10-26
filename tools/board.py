"""Storyboard + caption board: one still per shot with its time, bar, lyric, photos and every line of text, straight
from the EDL (no video render), so the user can check story order and every caption before (or while) the preview renders.

  python tools/studio.py board <project> [version]

Writes out/<version>_board.json and out/board/<version>/<shot>.jpg (480 px). The studio's Review page shows it as
the Storyboard tab, where the user ticks or vetoes each line (review/captions.json; read by F.save() and qa.py).
"""
import argparse, json, os, shutil, sys, time
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from am import checks  # noqa: E402
from am.common import CACHE, OUT, ROOT, project  # noqa: E402
from am.music import MusicMap  # noqa: E402
from render import _frame, _init, default_workers  # noqa: E402

WIDTH = 480


def song_bar(edl, a, t):
    """Song bar number (index into the song's downbeats, as F.bar(n) counts) at film time t."""
    for seg in edl["audio"]["segments"]:
        x, y = seg["src"]
        if seg["at"] <= t < seg["at"] + y - x:
            st = x + t - seg["at"]
            db = np.array(a["downbeats"])
            n = int(np.searchsorted(db, st + 0.02, side="right") - 1)
            return n if n >= 0 else None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("version")
    ap.add_argument("--workers", type=int, default=default_workers())
    a = ap.parse_args()
    edl_p = os.path.join(OUT, f"{a.version}_edl.json")
    edl = json.load(open(edl_p, encoding="utf-8"))
    fps = edl["meta"].get("fps", 30)
    pj = project()
    mm = MusicMap(edl)
    audio = json.load(open(os.path.join(CACHE, "audio", f"{edl['meta']['analysis']}.json"), encoding="utf-8"))

    from am.grade import ensure_graded, photos_in
    g = edl.get("grade", {})
    for ph in sorted(photos_in(edl["shots"])):
        ensure_graded(g.get("preset", "consumer_film"), ph, (g.get("overrides") or {}).get(ph))

    sdir = os.path.join(OUT, "board", a.version)
    shutil.rmtree(sdir, ignore_errors=True)
    os.makedirs(sdir)
    times = [checks.settled(s) for s in edl["shots"]]
    t0 = time.time()
    import cv2
    h = WIDTH * 9 // 16
    with Pool(a.workers, initializer=_init, initargs=(edl_p, WIDTH)) as pool:
        for s, buf in zip(edl["shots"], pool.imap(_frame, [(int(t * fps), t) for t in times])):
            img = np.frombuffer(buf, np.uint8).reshape(h, WIDTH, 3)
            cv2.imwrite(os.path.join(sdir, f"{s['id']}.jpg"), cv2.cvtColor(img, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 82])

    caps = checks.captions(edl, pj)
    flags = {}
    for sid, t, text, shown, nd in checks.reading_time(edl):
        flags.setdefault(sid, []).append(f"'{text[:30]}' up {shown:.1f}s, needs {nd:.1f}s to read")
    for sid, src, land, d in checks.screen_time(edl):
        flags.setdefault(sid, []).append(f"a photo is up only {d:.1f}s")
    for sid, src, land, why in checks.resolve(edl):
        flags.setdefault(sid, []).append(why)
    first = {}
    for s in edl["shots"]:
        for L in s["layers"]:
            for m in checks.media_of(L):
                first.setdefault(m, s["id"])
    for x, y, ta, tb, why in checks.near_dupes(edl):
        flags.setdefault(first[y], []).append(f"looks like the photo at {ta:.1f}s ({why})")
    m = checks.musts(edl, pj)
    starred = set(pj.get("must_use") or [])
    shots = []
    for s, t in zip(edl["shots"], times):
        media = sorted({x for L in s["layers"] for x in checks.media_of(L)})
        words = [w for ft, w in mm.words if s["t0"] - 1e-3 <= ft < s["t1"]]
        shots.append({"id": s["id"], "t0": s["t0"], "t1": s["t1"], "t_still": t, "still": f"out/board/{a.version}/{s['id']}.jpg",
                      "bar": song_bar(edl, audio, s["t0"]), "lyric": " ".join(words), "sync": s.get("sync", ""),
                      "photos": media, "starred": sorted(starred & set(media)),
                      "captions": [c for c in caps if c["shot"] == s["id"]], "flags": flags.get(s["id"], [])})
    out = {"version": a.version, "at": time.strftime("%Y-%m-%d %H:%M"), "duration": edl["meta"]["duration"],
           "origins": checks.ORIGINS, "trusted": sorted(checks.TRUSTED), "musts": m, "shots": shots}
    p = os.path.join(OUT, f"{a.version}_board.json")
    json.dump(out, open(p, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    rv = checks.caption_review(caps)
    print(f"board: {len(shots)} shots in {time.time() - t0:.0f}s, {len(caps)} lines ({sum(c['check'] for c in caps)} to check, "
          f"{len(rv['vetoed'])} vetoed) -> {os.path.relpath(p, ROOT)}")


if __name__ == "__main__":
    main()
