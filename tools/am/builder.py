"""Small helper for authoring EDLs in Python (the EDL JSON is the real source of truth)."""
import json, os
import numpy as np

from .common import ROOT
from .music import MusicMap

MIN_PHOTO_S = 1.8           # Sam's "one photo per bar (~1.8-2 s)"; Georgia round 3: photos up 0.7-1.7 s felt rushed


def screen_time(edl, min_s=MIN_PHOTO_S):
    """Photos/clips on screen for less than min_s, from when they land (show / enter / the cut) to when they go (show end,
    or the cut, less half of a centred transition into the next shot). A layer with "quick": true is a deliberate flash.
    Returns [(shot id, src, land, seconds)]."""
    sh, out = edl["shots"], []
    for i, s in enumerate(sh):
        tin = (sh[i + 1].get("in") or {}) if i + 1 < len(sh) else {}
        centred = tin.get("type", "cut") not in ("cut", "flash") and tin.get("align", "center") == "center"
        end = s["t1"] - (tin.get("dur", 0) / 2 if centred else 0)
        for L in s["layers"]:
            if L["type"] not in ("photo", "video") or L.get("quick"):
                continue
            show = L.get("show") or [s["t0"], 99999]
            land = max(s["t0"], show[0], (L.get("enter") or {}).get("t", 0))
            dwell = min(end, show[1]) - land
            if dwell < min_s - 1e-3 and min(end, show[1]) < edl["meta"]["duration"] - 1e-3:
                out.append((s["id"], L["src"], round(land, 2), round(dwell, 2)))
    return out


class Builder:
    def __init__(self, version, title, song, analysis, segments, grade, finish, duration=None, fps=30):
        self.edl = {
            "meta": {"version": version, "title": title, "song": song, "analysis": analysis, "fps": fps},
            "audio": {"segments": [{"src": list(s[0:2]), "at": s[2]} for s in segments], "xfade": 0.04, "sfx": [], "fx": []},
            "grade": grade, "finish": finish, "flashes": [], "overlays": [], "shots": [],
        }
        self.music = MusicMap(self.edl)
        self.edl["meta"]["duration"] = round(duration or self.music.duration, 3)
        self._n = 0

    # --- musical grid in film time
    def grid(self, kind):
        return self.music.ev[kind][0]

    def snap(self, t, kind="beats", tol=0.06):
        arr = self.grid(kind)
        if kind == "beats" and t > arr[-1] + tol:
            # ring-out: extrapolate the felt pulse past the last played beat
            per = float(np.median(np.diff(arr[-16:])))
            ext = arr[-1] + per * np.arange(1, int((t - arr[-1]) / per) + 3)
            arr = np.r_[arr, ext]
        i = int(np.argmin(np.abs(arr - t)))
        if abs(arr[i] - t) > tol:
            raise ValueError(f"no {kind} within {tol}s of {t:.3f} (nearest {arr[i]:.3f})")
        return round(float(arr[i]), 4)

    def beats_from(self, t0, n, kind="beats"):
        arr = self.grid(kind)
        i = int(np.argmin(np.abs(arr - t0)))
        return [round(float(x), 4) for x in arr[i:i + n]]

    def word(self, text, near, tol=1.5):
        cands = [(abs(t - near), t) for t, w in self.music.words if w.lower().strip(",.!?'") == text.lower()]
        cands = [c for c in cands if c[0] <= tol]
        if not cands:
            raise ValueError(f"word {text!r} not found near {near}")
        return round(min(cands)[1], 4)

    # --- authoring
    def shot(self, t0, t1, layers, sync="", **kw):
        self._n += 1
        s = {"id": f"S{self._n:03d}", "t0": round(t0, 4), "t1": round(t1, 4), "sync": sync, "layers": layers}
        s.update(kw)
        self.edl["shots"].append(s)
        return s

    def sfx(self, kind, t, db=-14, **kw):
        e = {"type": kind, "t": round(t, 4), "db": db}
        e.update(kw)
        self.edl["audio"]["sfx"].append(e)

    def flash(self, t, amount=0.9, decay=0.16):
        self.edl["flashes"].append([round(t, 4), amount, decay])

    def save(self, path, notes=None):
        self.edl["shots"].sort(key=lambda s: s["t0"])
        # close gaps: each shot ends where the next begins
        sh = self.edl["shots"]
        for a, b in zip(sh[:-1], sh[1:]):
            a["t1"] = b["t0"]
        sh[-1]["t1"] = self.edl["meta"]["duration"]
        if notes:
            self.edl["meta"]["notes"] = notes
        if os.environ.get("AM_EDL_DIR"):            # studio.py check rebuilds old films without touching out/
            path = os.path.join(os.environ["AM_EDL_DIR"], os.path.basename(path))
        else:
            log_changes(path, self.edl)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        json.dump(self.edl, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        return path


def _texts(s):
    from .checks import _strings
    return sorted(t for L in s["layers"] for t in _strings(L))


def _media(s):
    from .checks import media_of
    return sorted({m for L in s["layers"] for m in media_of(L)})


def _strip(o):
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items() if not k.startswith("_")}
    if isinstance(o, list):
        return [_strip(v) for v in o]
    return round(o, 3) if isinstance(o, float) else o


def edl_changes(old, new):
    """What changed between two builds, shot by shot (shots matched by their photos, then their words):
    [{"t", "id", "what": new | changed | retimed | removed, "detail"}]."""
    def key(s):
        return tuple(_media(s)) or tuple(_texts(s)) or (s.get("sync", ""),)
    pool = {}
    for s in old["shots"]:
        pool.setdefault(key(s), []).append(s)
    by_media = {}
    for s in old["shots"]:
        for m in _media(s):
            by_media.setdefault(m, s)
    out, matched = [], set()
    for s in new["shots"]:
        cand = pool.get(key(s)) or []
        o = next((c for c in cand if id(c) not in matched), None)
        if o is None:
            o = next((by_media[m] for m in _media(s) if m in by_media and id(by_media[m]) not in matched), None)
            if o is None:
                out.append({"t": s["t0"], "id": s["id"], "what": "new", "detail": ", ".join(_texts(s))[:120] or s.get("sync", "")[:120]})
                continue
        matched.add(id(o))
        if _strip(o["layers"]) != _strip(s["layers"]) or _strip({k: v for k, v in o.items() if k not in ("id", "t0", "t1", "layers", "sync")}) != \
                _strip({k: v for k, v in s.items() if k not in ("id", "t0", "t1", "layers", "sync")}):
            gone, came = set(_texts(o)) - set(_texts(s)), set(_texts(s)) - set(_texts(o))
            ph = set(_media(o)) ^ set(_media(s))
            d = "; ".join(x for x in (f"text {', '.join(sorted(gone))!r} -> {', '.join(sorted(came))!r}" if gone or came else "",
                                       f"photos {len(ph)} swapped" if ph else "") if x) or "layout / timing inside the shot"
            out.append({"t": s["t0"], "id": s["id"], "what": "changed", "detail": d[:160]})
        elif abs(o["t0"] - s["t0"]) > 0.01 or abs(o["t1"] - s["t1"]) > 0.01:
            out.append({"t": s["t0"], "id": s["id"], "what": "retimed",
                        "detail": f"{o['t0']:.2f}-{o['t1']:.2f} -> {s['t0']:.2f}-{s['t1']:.2f}"})
    for s in old["shots"]:
        if id(s) not in matched:
            out.append({"t": s["t0"], "id": s["id"], "what": "removed", "detail": ", ".join(_media(s))[:120] or ", ".join(_texts(s))[:120]})
    return sorted(out, key=lambda c: c["t"])


def log_changes(path, edl):
    """Before overwriting out/<v>_edl.json: write out/<v>_changes.json (what this build changed), for the studio's
    review page. A rebuild that changes nothing keeps the last change log."""
    if not os.path.exists(path):
        return
    try:
        old = json.load(open(path, encoding="utf-8"))
        ch = edl_changes(old, edl)
        glob_ = [k for k in ("audio", "grade", "finish", "flashes", "overlays") if _strip(old.get(k)) != _strip(edl.get(k))]
        if not ch and not glob_:
            return
        import time
        out = {"at": time.strftime("%Y-%m-%d %H:%M"), "shots": ch, "global": glob_,
               "summary": f"{sum(c['what'] == 'new' for c in ch)} new, {sum(c['what'] == 'changed' for c in ch)} changed, "
                          f"{sum(c['what'] == 'retimed' for c in ch)} retimed, {sum(c['what'] == 'removed' for c in ch)} removed shots"
                          + (f"; {', '.join(glob_)} changed" if glob_ else "")}
        json.dump(out, open(path.replace("_edl.json", "_changes.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        print("changes since the last build:", out["summary"])
    except Exception as e:                      # the change log is a convenience; never block a save
        print("change log skipped:", e)
