"""Checks on an EDL that need no render, shared by the builder kit's lint (F.save) and tools/qa.py.

Each one is a lesson from real review rounds:
  reading_time   "you cannot read the text in time"
  screen_time    "visible for maybe 0.2 s" (lives in builder.py)
  captions       every on-screen line, the photos it sits on and where it came from, for the caption board:
                 a fact on the wrong photo ("why?"), "it wasn't a highway", the wrong friend credited with the driving
  musts          must-use photos (the stars in the studio) and story-order rules ("NO ENTRY before the ruins")
  resolve        a treatment that changes over time has to arrive fast ("I don't see what we are trying to achieve")
  near_dupes     two near-identical photos in one place ("very similar shot side by side")
"""
import json, os, re

import numpy as np

from .builder import MIN_PHOTO_S, screen_time  # noqa: F401  (re-exported)
from .common import CACHE, ROOT

MAX_RESOLVE_BEATS = 2.0          # a look that sketches / fades / blooms in must settle within this many beats of landing
DUPE_BITS = 12                   # perceptual-hash distance (of 64) under which two photos read as the same picture
DUPE_WINDOW = 12.0               # ... and they are flagged when they land this close together (s) or share a shot
TEXT_KEYS = {"text": ("text",), "bubble": ("text",), "type_mask": ("text",), "sticker": ("text",), "osd": ("text",),
             "vinyl": ("text",), "polaroid": ("caption",), "stamp": ("top", "mid", "bottom"), "label": ("title", "sub")}
# where a line came from (layer key "origin"); the first five are the user's own words or the song, the rest get checked
ORIGINS = {"lyric": "sung in the song", "credit": "credit line, verbatim", "brief": "from the brief, verbatim",
           "name": "a name", "place": "a place / step name", "answer": "the user's answer in chat",
           "note": "from a step note / the brief, reworded", "fact": "a fact (date, count, data)", "invented": "a joke Claude wrote",
           "?": "no source given"}
TRUSTED = {"lyric", "credit", "brief", "name", "place"}


def need(text):
    """Reading time for a caption: ~0.8 s + 55 ms per character, 1.4..3 s."""
    n = len(text.replace("\n", " "))
    return min(3.0, max(1.4, 0.8 + 0.055 * n))


def reading_time(edl):
    """Captions shown too briefly: [(shot id, t0, text, shown s, needed s)]."""
    out, dur = [], edl["meta"]["duration"]
    for s in edl["shots"]:
        for L in s["layers"]:
            if L["type"] not in ("text", "bubble"):
                continue
            t0, t1 = L.get("t0", s["t0"]), min(L.get("t1", s["t1"]), s["t1"])
            if t1 >= dur - 1e-3:
                continue                                       # stays up until the end of the film
            shown = t1 - t0 - (L.get("dur", 0.2) if L.get("anim") in ("write", "type") else 0.1)
            if shown < need(L["text"]) - 1e-3:
                out.append((s["id"], round(t0, 2), L["text"], round(shown, 2), round(need(L["text"]), 2)))
    return out


# ------------------------------------------------------------------ media on screen
def media_of(L):
    """Photo / clip names a layer shows."""
    if isinstance(L.get("src"), str) and L["type"] not in ("sticker",):
        return [L["src"]]
    if isinstance(L.get("srcs"), list):
        return [x for x in L["srcs"] if isinstance(x, str)]
    if L["type"] == "contact":
        return [f["src"] for f in L.get("frames", []) if isinstance(f, dict) and f.get("src")]
    return []


def window(s, L):
    """[t0, t1) a layer is on screen within its shot."""
    sh = L.get("show") or [s["t0"], 99999]
    t0 = max(s["t0"], sh[0], L.get("t0", L.get("t", s["t0"])), (L.get("enter") or {}).get("t", s["t0"]))
    return t0, min(s["t1"], sh[1], L.get("t1", 99999))


def first_seen(edl):
    """{photo: film time it first lands}."""
    out = {}
    for s in edl["shots"]:
        for L in s["layers"]:
            for m in media_of(L):
                t = window(s, L)[0]
                out[m] = min(out.get(m, 1e9), t)
    return out


def settled(s):
    """A moment when the shot has settled: every element landed, handwriting written out, colour bloomed in
    (but before the cut)."""
    ends = []
    for L in s["layers"]:
        t = window(s, L)[0]
        e = t + (L.get("dur", 0.2) if L.get("anim") else 0.0)
        if L.get("enter"):
            e = max(e, L["enter"].get("t", t) + L["enter"].get("dur", 0.2))
        look_end = _settle(L.get("look"))[0]
        if look_end:
            e = max(e, look_end)
        if t < s["t1"] - 0.3:
            ends.append(min(e, s["t1"] - 0.12))
    t = max(ends + [s["t0"]]) + 0.12
    return round(min(max(t, s["t0"] + 0.25), s["t1"] - 0.12), 3)


# ------------------------------------------------------------------ captions + where they came from
def _norm(t):
    return re.sub(r"[\W_]+", " ", str(t).lower()).strip()


def caption_key(text, photos):
    return _norm(text) + "|" + ",".join(sorted(photos))


def _strings(L):
    if L["type"] == "lyric_type":
        return [" ".join(w["w"] for w in L.get("words", []))]
    if L["type"] == "map":
        return [p["label"] for p in L.get("pins", []) if p.get("label")] + \
               [a["label"] for a in L.get("labels", []) + L.get("annotations", []) if isinstance(a, dict) and a.get("label")]
    if L["type"] == "contact":
        return [f"{f.get('name', '')}: {f.get('role', '')}".strip(": ") for f in L.get("frames", []) if isinstance(f, dict)]
    keys = TEXT_KEYS.get(L["type"])
    if not keys:
        return []
    v = " / ".join(str(L[k]) for k in keys if L.get(k))
    return [v] if v else []


_MONTHS = {"jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"}


class Sources:
    """What the project knows, to guess where an unlabelled line came from (lyrics, credits, the brief, steps)."""

    def __init__(self, edl, project):
        self.lyrics = ""
        try:
            a = json.load(open(os.path.join(CACHE, "audio", f"{edl['meta']['analysis']}.json"), encoding="utf-8"))
            self.lyrics = " " + " ".join(_norm(l.get("text", "")) for l in a.get("lyrics", [])) + " "
        except Exception:
            pass
        cast = {}
        try:
            cast = json.load(open(os.path.join(CACHE, "cast.json"), encoding="utf-8")).get("people", {})
        except Exception:
            pass
        self.names = {_norm(x) for p in cast.values() for x in (p.get("name"), p.get("nick")) if x}
        self.credits = {_norm(p.get("credit")) for p in cast.values() if p.get("credit")}
        self.brief = set()
        for k in ("credits", "ending_note", "jokes", "title", "group_name", "editor"):
            for line in str(project.get(k) or "").splitlines():
                for part in re.split(r":\s+", line, maxsplit=1):
                    if _norm(part):
                        self.brief.add(_norm(part))
        self.places, self.notes = set(), []
        steps = project.get("steps") or {}
        try:
            trip = json.load(open(os.path.join(CACHE, "trip.json"), encoding="utf-8"))
            for st in trip.get("steps", []):
                o = steps.get(st["id"], {})
                for x in (o.get("label"), st.get("label"), st.get("place"), st.get("name"), st.get("country")):
                    if x:
                        self.places.add(_norm(x))
                for x in (o.get("note"), st.get("text")):
                    if x:
                        self.notes.append(_norm(x))
        except Exception:
            pass

    def guess(self, text, kind):
        n = _norm(text)
        if not n:
            return "?"
        if kind == "lyric_type" or ((len(n) >= 6 or (" " in n and len(n) >= 4)) and f" {n} " in self.lyrics):
            return "lyric"
        if n in self.credits:
            return "credit"
        if n in self.names:
            return "name"
        if n in self.brief or any(n == b or (len(n) >= 12 and n in b) for b in self.brief):
            return "brief"
        if kind == "map" or n in self.places:
            return "place"
        rest = n
        for pl in sorted(self.places, key=len, reverse=True):          # "Tbilisi · 12–13 Oct": a place name + a date
            if len(pl) >= 4 and (rest.startswith(pl + " ") or rest.endswith(" " + pl)):
                rest = rest.replace(pl, " ").strip()
                break
        if rest != n and (not rest or re.fullmatch(r"[\d\s]+[a-z]{0,4}[\d\s]*", rest) or rest in _MONTHS):
            return "place"
        if len(n) <= 24 and sum(ch.isdigit() for ch in n) >= max(1, len(n.replace(" ", "")) // 3):   # "km 0", dates, counts
            return "fact"
        if len(n) >= 8 and any(n in x for x in self.notes):
            return "note"
        return "?"


def captions(edl, project=None):
    """Every line of text on screen: [{key, shot, t0, t1, text, layer, origin, basis, joke, photos, check}]."""
    src = Sources(edl, project or {})
    out = []
    for s in edl["shots"]:
        media = [(window(s, L), media_of(L)) for L in s["layers"] if media_of(L)]
        for L in s["layers"]:
            for text in _strings(L):
                if not re.search(r"[^\W_]", text):              # emoji / symbols only
                    continue
                t0, t1 = window(s, L)
                if L["type"] == "lyric_type" and L.get("words"):
                    t0 = max(t0, L["words"][0]["t"])
                photos = sorted({m for (a, b), ms in media for m in ms if a < max(t1, t0 + 0.05) and b > t0})
                origin = L.get("origin") or src.guess(text, L["type"])
                out.append({"key": caption_key(text, photos), "shot": s["id"], "t0": round(t0, 2), "t1": round(min(t1, s["t1"]), 2),
                            "text": text, "layer": L["type"], "origin": origin, "basis": L.get("basis", ""),
                            "joke": L.get("joke", ""), "photos": photos, "check": origin not in TRUSTED})
    return out


def caption_decisions():
    p = os.path.join(ROOT, "review", "captions.json")
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}


def caption_review(caps, decisions=None):
    """{'vetoed': [...], 'unreviewed': [...], 'approved': n} over the lines that need the user's eye."""
    d = caption_decisions() if decisions is None else decisions
    vetoed = [c for c in caps if d.get(c["key"], {}).get("ok") is False]
    unrev = [c for c in caps if c["check"] and c["key"] not in d]
    return {"vetoed": vetoed, "unreviewed": unrev, "approved": sum(1 for c in caps if d.get(c["key"], {}).get("ok") is True),
            "decisions": d}


# ------------------------------------------------------------------ must-haves + story order
def musts(edl, project):
    """project.json "must_use": [photo, ...] (the stars in the studio) and "order": [{"first", "then": [...], "why"}].
    Returns {"missing": [photo], "order": [(rule text, problem)]}."""
    seen = first_seen(edl)
    missing = [m for m in project.get("must_use") or [] if m not in seen]
    bad = []
    for r in project.get("order") or []:
        a, then = r.get("first"), r.get("then") or []
        then = [then] if isinstance(then, str) else then
        label = r.get("why") or f"{a} before {', '.join(then)}"
        if a not in seen:
            if any(b in seen for b in then):
                bad.append((label, f"{a} is not in the film"))
            continue
        late = [b for b in then if b in seen and seen[b] < seen[a] - 1e-3]
        if late:
            bad.append((label, f"{a} lands at {seen[a]:.1f}s, after " + ", ".join(f"{b} ({seen[b]:.1f}s)" for b in late[:3])))
    return {"missing": missing, "order": bad}


# ------------------------------------------------------------------ treatments that have to arrive
def _settle(spec):
    """Last time a look spec still changes, and its final colour amount for sketch (None if it never changes)."""
    if not isinstance(spec, dict):
        return None, None
    ts = []
    if "t" in spec:
        ts.append(spec["t"] + spec.get("dur", 0.3))
    for k in ("keys", "draw", "color"):
        v = spec.get(k)
        if isinstance(v, list) and v and isinstance(v[0], (list, tuple)):
            ts.append(v[-1][0])
    col = None
    if spec.get("name") == "sketch":
        c = spec.get("color", 0.0)
        col = c[-1][1] if isinstance(c, list) and c else float(c)
    return (max(ts) if ts else None), col


def beat_period(edl):
    from .music import MusicMap
    b = MusicMap(edl).ev["beats"][0]
    return float(np.median(np.diff(b))) if len(b) > 1 else 0.5


def resolve(edl, beat=None):
    """Treatments that never arrive: a photo that stays a pencil drawing, or a slow look (longer than
    MAX_RESOLVE_BEATS) still changing when the shot cuts, so its point is never seen. A slow bloom that completes on
    screen is a device, not a fault. Returns [(shot, photo, land, problem)]."""
    beat = beat or beat_period(edl)
    out = []
    for s in edl["shots"]:
        shot_looks = [fx.get("look") for fx in s.get("fx", []) if fx.get("type") == "look"]
        for L in s["layers"]:
            ms = media_of(L)
            if not ms or L.get("quick"):
                continue
            land, gone = window(s, L)
            for spec in [L.get("look")] + shot_looks:
                end, col = _settle(spec)
                if col is not None and col < 0.35 and gone - land > 1.0:
                    out.append((s["id"], ms[0], round(land, 2), "stays a pencil drawing (the photo never comes back in colour)"))
                if end is not None and end - land > MAX_RESOLVE_BEATS * beat + 0.05 and end > gone + 0.05:
                    out.append((s["id"], ms[0], round(land, 2), f"its {spec.get('name', 'look')} is still changing when the shot "
                                                                 f"cuts ({end - gone:.1f}s short): the payoff is never seen"))
    return out


# ------------------------------------------------------------------ near-duplicates
def phash(name):
    """64-bit perceptual hash (DCT of a 32x32 grey thumbnail) of an upright photo, cached in cache/phash.json."""
    p = os.path.join(CACHE, "phash.json")
    if not hasattr(phash, "db"):
        try:
            phash.db = json.load(open(p))
        except Exception:
            phash.db = {}
    if name not in phash.db:
        import cv2
        from .common import load_upright
        g = np.asarray(load_upright(name, 256).convert("L"), np.float32)
        d = cv2.dct(cv2.resize(g, (32, 32), interpolation=cv2.INTER_AREA))[:8, :8].ravel()[1:]
        phash.db[name] = "".join("1" if x > np.median(d) else "0" for x in d)
        phash.dirty = True
    return phash.db[name]


def _save_hashes():
    if getattr(phash, "dirty", False):
        json.dump(phash.db, open(os.path.join(CACHE, "phash.json"), "w"))
        phash.dirty = False


SAME_SCENE = 40                  # ORB matches that survive a RANSAC homography: same scene, even reframed (calibrated on
                                 # a trip film: the look-alike pair a reviewer flagged = 152, same-spot pairs 50-540, different photos < 25)


def same_scene(a, b, _f={}):
    """How many local features of two photos agree under one homography (same place, same moment, any framing)."""
    import cv2
    from .common import load_upright
    for n in (a, b):
        if n not in _f:
            g = np.asarray(load_upright(n, 640).convert("L"))
            _f[n] = cv2.ORB_create(1500).detectAndCompute(g, None)
    (ka, da), (kb, db) = _f[a], _f[b]
    if da is None or db is None or len(ka) < 20 or len(kb) < 20:
        return 0
    m = [x[0] for x in cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(da, db, k=2) if len(x) == 2 and x[0].distance < 0.75 * x[1].distance]
    if len(m) < 12:
        return 0
    pa = np.float32([ka[x.queryIdx].pt for x in m])
    pb = np.float32([kb[x.trainIdx].pt for x in m])
    _, mask = cv2.findHomography(pa, pb, cv2.RANSAC, 6.0)
    return int(mask.sum()) if mask is not None else 0


def near_dupes(edl):
    """Pairs of different photos that read as the same picture (a burst, or the same view reframed) and land close
    together: [(a, b, ta, tb, why)]. Deliberate pairs are skipped: different named people in each ("one of each of us"
    at the same spot), both in one grid / collage of 4+ photos, or a layer marked "twin": true."""
    from .common import faces_people
    seen = first_seen(edl)
    shots, twins, sets = {}, set(), set()
    for s in edl["shots"]:
        ms = {m for L in s["layers"] for m in media_of(L)}
        if len(ms) >= 4:
            sets.add(s["id"])                                    # a grid / collage reads as a set: repeats are its point
        for L in s["layers"]:
            for m in media_of(L):
                shots.setdefault(m, set()).add(s["id"])
                if L.get("twin"):
                    twins.add(m)
    stills = sorted((t, m) for m, t in seen.items() if m.lower().endswith((".jpg", ".jpeg")))
    cp = os.path.join(CACHE, "dupes.json")
    try:
        db = json.load(open(cp))
    except Exception:
        db = {}
    people = faces_people()
    out, dirty = [], False
    try:
        for i, (ta, a) in enumerate(stills):
            for tb, b in stills[i + 1:]:
                if tb - ta > DUPE_WINDOW and not (shots[a] & shots[b]):
                    break
                if a in twins or b in twins or (shots[a] & shots[b] & sets):
                    continue
                pa, pb = {p for p in people.get(a, []) if p}, {p for p in people.get(b, []) if p}
                if pa and pb and pa != pb:
                    continue
                bits = sum(x != y for x, y in zip(phash(a), phash(b)))
                k = "|".join(sorted((a, b)))
                if k not in db:
                    db[k], dirty = same_scene(a, b), True
                if bits <= DUPE_BITS or db[k] >= SAME_SCENE:
                    out.append((a, b, round(ta, 2), round(tb, 2), f"{db[k]} matching features" if db[k] >= SAME_SCENE else f"hash {bits}/64"))
    except Exception as e:                                   # never break a build over this check
        print("near-duplicate check skipped:", e)
    _save_hashes()
    if dirty:
        json.dump(db, open(cp, "w"))
    return out
