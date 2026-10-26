"""Import a trip from a Polarsteps data export into a studio project.

  python tools/studio.py run <project> import_polarsteps.py <export.zip|folder> --list
  python tools/studio.py run <project> import_polarsteps.py <export.zip|folder> [--trip <id or name>]
  python tools/studio.py run <project> import_polarsteps.py - --rechapter     (rebuild chapters, no export needed)

Get the export in a desktop browser: Polarsteps -> Account settings -> "Download my data" (emailed as a zip).
Expected layout (tolerant): .../trip/<trip folder>/trip.json + locations.json, media in step sub-folders
(photos/, videos/). Media is matched to steps by folder name (step id / slug), else by capture time.

Writes:
  photos/ps<step>_<name>      the trip's photos + clips, in story order (originals untouched)
  cache/trip.json             trip, steps (place, country, date, coords, text, weather, photos), route, stats
  cache/photo_sources.json    marks imported photos as phone shots (upright; no auto-rotation)
  project.json                fills ONLY empty fields: title, when_where, occasion, chapters, and per-step
                              context in "steps" (label / note / skip) that the user can edit in the studio
"""
import argparse, datetime as dt, io, json, math, os, re, shutil, sys, zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from am.common import ROOT, PHOTOS, CACHE  # noqa: E402

MEDIA = (".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".mp4", ".mov", ".m4v")


# ------------------------------------------------------------------ reading the export (zip or folder)
class Source:
    def __init__(self, path):
        self.path = path
        self.zip = zipfile.ZipFile(path) if zipfile.is_zipfile(path) else None
        if self.zip:
            self.names = [n for n in self.zip.namelist() if not n.endswith("/")]
        else:
            self.names = [os.path.relpath(os.path.join(r, f), path).replace("\\", "/") for r, _, fs in os.walk(path) for f in fs]

    def read(self, name):
        if self.zip:
            return self.zip.read(name)
        return open(os.path.join(self.path, name), "rb").read()

    def copy(self, name, dst):
        if self.zip:
            with self.zip.open(name) as s, open(dst, "wb") as d:
                shutil.copyfileobj(s, d, 1 << 20)
        else:
            shutil.copy2(os.path.join(self.path, name), dst)


def ts(v):
    """Polarsteps times: unix seconds (float) or ISO strings -> datetime (UTC)."""
    if v in (None, ""):
        return None
    try:
        return dt.datetime.fromtimestamp(float(v), dt.timezone.utc)
    except (TypeError, ValueError):
        try:
            return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except ValueError:
            return None


def find_trips(src):
    trips = []
    for n in src.names:
        if n.lower().endswith("trip.json") and os.path.basename(n).lower() == "trip.json":
            try:
                t = json.loads(src.read(n).decode("utf-8"))
            except Exception:
                continue
            folder = n[: -len("trip.json")]
            media = [m for m in src.names if m.startswith(folder) and m.lower().endswith(MEDIA)]
            steps = t.get("all_steps") or t.get("steps") or []
            s, e = ts(t.get("start_date")), ts(t.get("end_date"))
            trips.append({"folder": folder, "id": str(t.get("id", "")), "name": t.get("name") or os.path.basename(folder.rstrip("/")),
                          "start": s.date().isoformat() if s else "", "end": e.date().isoformat() if e else "",
                          "steps": len(steps), "media": len(media), "json": t})
    return sorted(trips, key=lambda x: x["start"] or "")


def step_text(st):
    return (st.get("description") or "").strip()


def place_of(st):
    loc = st.get("location") or {}
    return (loc.get("name") or st.get("name") or "").strip(), (loc.get("detail") or "").strip(), (loc.get("country_code") or "").upper()


def country_names():
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from am.props import countries
        return {iso: name for iso, name, _ in countries() if iso}
    except Exception:
        return {}


def read_route(src, folder):
    for n in src.names:
        if n.startswith(folder) and os.path.basename(n).lower() == "locations.json":
            try:
                d = json.loads(src.read(n).decode("utf-8"))
            except Exception:
                return []
            pts = d.get("locations", d) if isinstance(d, dict) else d
            out = []
            for p in pts if isinstance(pts, list) else []:
                if not isinstance(p, dict):
                    continue
                lat = p.get("lat", p.get("latitude"))
                lon = p.get("lon", p.get("lng", p.get("longitude")))
                if lat is None or lon is None:
                    continue
                t = ts(p.get("time", p.get("timestamp")))
                out.append([round(float(lon), 5), round(float(lat), 5), t.timestamp() if t else None])
            out.sort(key=lambda p: (p[2] is None, p[2] or 0))
            return out
    return []


def media_time(src, name):
    """Capture time from EXIF (photos), else None."""
    if not name.lower().endswith((".jpg", ".jpeg")):
        return None
    try:
        from PIL import Image
        ex = Image.open(io.BytesIO(src.read(name))).getexif()
        v = ex.get_ifd(0x8769).get(0x9003) or ex.get(0x0132)
        return dt.datetime.strptime(v, "%Y:%m:%d %H:%M:%S").replace(tzinfo=dt.timezone.utc) if v else None
    except Exception:
        return None


def km(a, b):
    (lo1, la1), (lo2, la2) = a, b
    p = math.pi / 180
    h = math.sin((la2 - la1) * p / 2) ** 2 + math.cos(la1 * p) * math.cos(la2 * p) * math.sin((lo2 - lo1) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def make_chapters(steps):
    """One chapter per step for short trips; otherwise runs of the same place (or country), max ~10."""
    live = [s for s in steps if not s["skip"]]

    def runs(key):
        out = []
        for s in live:
            if out and key(out[-1][-1]) == key(s):
                out[-1].append(s)
            else:
                out.append([s])
        return out
    if len(live) <= 10:
        groups = [[s] for s in live]
    else:
        groups = runs(lambda s: s["place"])
        if len(groups) > 10:                      # several countries: one chapter each, if that gives a sensible count
            by_country = runs(lambda s: s["country_code"] or s["place"])
            if 3 <= len(by_country) <= 10:
                groups = by_country

    def weight(g):                                # chapters of similar size on screen: count photos, not stops
        return sum(len(x.get("photos", [])) for x in g) + 1
    while len(groups) > 10:                       # merge the lightest neighbouring pair (empty travel days fold in)
        i = min(range(len(groups) - 1), key=lambda j: weight(groups[j]) + weight(groups[j + 1]))
        groups[i:i + 2] = [groups[i] + groups[i + 1]]
    chapters = []
    for g in groups:
        first, last = g[0], g[-1]
        label = first["label"] if len(g) == 1 else (first["place"] if first["place"] == last["place"] else f"{first['place']} → {last['place']}")
        when = first["date_label"] if first["date"] == last["date"] else f"{first['date_label']}–{last['date_label']}"
        cid = re.sub(r"[^a-z0-9]+", "_", f"s{first['i']:02d} {label}".lower()).strip("_")[:28]
        chapters.append({"id": cid, "label": label, "when": when, "steps": [s["id"] for s in g]})
    return chapters


def rechapter():
    """Recompute project.json chapters from cache/trip.json + the user's per-step context (labels / skips)."""
    pj_path = os.path.join(ROOT, "project.json")
    pj = json.load(open(pj_path, encoding="utf-8"))
    t = json.load(open(os.path.join(CACHE, "trip.json"), encoding="utf-8"))
    over = pj.get("steps") or {}
    for st in t["steps"]:
        o = over.get(st["id"], {})
        st["label"] = o.get("label") or st.get("label") or st["place"]
        st["skip"] = bool(o.get("skip", st.get("skip", False)))
    pj["chapters"] = make_chapters(t["steps"])
    json.dump(pj, open(pj_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    for c in pj["chapters"]:
        print(f"  {c['when']:>12s}  {c['label']}  ({len(c['steps'])} stop{'s' if len(c['steps']) != 1 else ''})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("export")
    ap.add_argument("--trip")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--rechapter", action="store_true", help="rebuild the chapters from the imported trip (export not needed)")
    a = ap.parse_args()
    if a.rechapter:
        return rechapter()
    src = Source(a.export)
    trips = find_trips(src)
    if not trips:
        raise SystemExit("no trip.json found: is this a Polarsteps 'Download my data' export?")
    if a.list or (len(trips) > 1 and not a.trip):
        print(json.dumps([{k: t[k] for k in ("id", "name", "start", "end", "steps", "media")} for t in trips], ensure_ascii=False))
        if not a.list:
            raise SystemExit("several trips: pass --trip <id or name>")
        return
    trip = trips[0] if not a.trip else next((t for t in trips if a.trip in (t["id"], t["name"])), None)
    if trip is None:
        raise SystemExit(f"no trip {a.trip!r}")
    T, folder = trip["json"], trip["folder"]
    raw_steps = [s for s in (T.get("all_steps") or T.get("steps") or []) if not s.get("is_deleted")]
    raw_steps.sort(key=lambda s: ts(s.get("start_time")) or dt.datetime.max.replace(tzinfo=dt.timezone.utc))
    cn = country_names()
    pj_path = os.path.join(ROOT, "project.json")
    pj = json.load(open(pj_path, encoding="utf-8")) if os.path.exists(pj_path) else {}
    over = pj.get("steps") or {}

    steps = []
    for i, st in enumerate(raw_steps, 1):
        place, detail, cc = place_of(st)
        t0 = ts(st.get("start_time"))
        sid = str(st.get("id") or st.get("uuid") or i)
        o = over.get(sid, {})
        loc = st.get("location") or {}
        steps.append({
            "i": i, "id": sid, "slug": st.get("slug") or "", "name": (st.get("name") or "").strip(), "place": place or detail,
            "detail": detail, "country_code": cc, "country": cn.get(cc, detail if cc else ""),
            "lat": loc.get("lat"), "lon": loc.get("lon"),
            "time": t0.timestamp() if t0 else None, "date": t0.date().isoformat() if t0 else "",
            "date_label": f"{t0.day} {t0.strftime('%b')}" if t0 else "",
            "text": step_text(st), "weather_temp": st.get("weather_temperature"), "weather": st.get("weather_condition") or "",
            "label": o.get("label") or (st.get("name") or "").strip() or place, "note": o.get("note", step_text(st)),
            "skip": bool(o.get("skip", False)), "photos": [],
        })
    by_key = {}
    for s in steps:
        for k in (s["id"], s["slug"]):
            if k:
                by_key[k.lower()] = s

    # ---- media -> steps (folder name, else nearest step in time)
    media = sorted(m for m in src.names if m.startswith(folder) and m.lower().endswith(MEDIA))
    os.makedirs(PHOTOS, exist_ok=True)
    sources_path = os.path.join(CACHE, "photo_sources.json")
    os.makedirs(CACHE, exist_ok=True)
    sources = json.load(open(sources_path)) if os.path.exists(sources_path) else {}
    unmatched, copied = 0, 0
    for m in media:
        rel = m[len(folder):]
        parts = [p.lower() for p in rel.split("/")[:-1]]
        s = None
        for p in parts:
            for k, cand in by_key.items():
                if p == k or p.endswith("_" + k) or p.startswith(k + "_") or (len(k) > 6 and k in p):
                    s = cand
                    break
            if s:
                break
        if s is None:
            mt = media_time(src, m)
            timed = [x for x in steps if x["time"]]
            if mt and timed:
                s = min(timed, key=lambda x: abs(x["time"] - mt.timestamp()) if x["time"] <= mt.timestamp() + 3600 else 1e12)
        if s is None:
            unmatched += 1
        idx = s["i"] if s else 999
        base = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(m))
        dst_name = f"ps{idx:03d}_{base}"
        dst = os.path.join(PHOTOS, dst_name)
        if not os.path.exists(dst):
            src.copy(m, dst)
            copied += 1
        jpg_name = os.path.splitext(dst_name)[0] + ".jpg" if dst_name.lower().endswith((".png", ".heic", ".heif", ".webp", ".jpeg")) else dst_name
        if s:
            s["photos"].append(jpg_name)
        if not jpg_name.lower().endswith((".mp4", ".mov", ".m4v")):
            sources[jpg_name] = "phone"
    json.dump(sources, open(sources_path, "w"), indent=0)

    # ---- route + stats
    route = read_route(src, folder)
    if len(route) < 2:
        route = [[s["lon"], s["lat"], s["time"]] for s in steps if s["lon"] is not None]
    dist = T.get("total_km") or sum(km(route[i][:2], route[i + 1][:2]) for i in range(len(route) - 1))
    t_s, t_e = ts(T.get("start_date")), ts(T.get("end_date"))
    if not t_s and steps and steps[0]["time"]:
        t_s = dt.datetime.fromtimestamp(steps[0]["time"], dt.timezone.utc)
    if not t_e and steps and steps[-1]["time"]:
        t_e = dt.datetime.fromtimestamp(steps[-1]["time"], dt.timezone.utc)
    countries = []
    for s in steps:
        if s["country_code"] and s["country_code"] not in countries and not s["skip"]:
            countries.append(s["country_code"])
    days = (t_e.date() - t_s.date()).days + 1 if (t_s and t_e) else None
    trip_out = {"source": "polarsteps", "id": trip["id"], "name": T.get("name") or trip["name"], "summary": (T.get("summary") or "").strip(),
                "start": t_s.date().isoformat() if t_s else "", "end": t_e.date().isoformat() if t_e else "",
                "days": days, "km": round(float(dist)) if dist else None, "countries": countries,
                "country_names": [cn.get(c, c) for c in countries], "steps": len(steps),
                "photos": sum(len(s["photos"]) for s in steps)}
    json.dump({"trip": trip_out, "steps": steps, "route": route}, open(os.path.join(CACHE, "trip.json"), "w", encoding="utf-8"),
              indent=1, ensure_ascii=False)

    # ---- project.json: fill only what the user hasn't written
    def empty(k):
        v = str(pj.get(k) or "").strip()
        return not v or (k == "title" and re.sub(r"[^a-z0-9]+", "-", v.lower()).strip("-") == os.path.basename(ROOT.rstrip("/\\")))
    if empty("title"):
        pj["title"] = trip_out["name"]
    if empty("occasion"):
        pj["occasion"] = trip_out["summary"] or "a trip"
    if empty("when_where") and t_s:
        when = t_s.strftime("%B %Y") if (not t_e or t_s.month == t_e.month) else f"{t_s.strftime('%b')}–{t_e.strftime('%b %Y')}"
        pj["when_where"] = f"{', '.join(trip_out['country_names'][:4])} · {when}"
    if not pj.get("chapters"):
        pj["chapters"] = make_chapters(steps)
    pj["steps"] = {s["id"]: {"label": s["label"], "note": s["note"], "skip": s["skip"]} for s in steps}
    pj["trip"] = {"source": "polarsteps", "id": trip_out["id"], "name": trip_out["name"], "imported": dt.date.today().isoformat()}
    json.dump(pj, open(pj_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)

    print(f"imported '{trip_out['name']}': {len(steps)} steps, {copied} new media files"
          f" ({unmatched} not matched to a step), {trip_out['days']} days, {len(countries)} countries, ~{trip_out['km']} km")
    for s in steps:
        print(f"  {s['i']:3d} {s['date']} {s['place'][:28]:28s} {s['country_code']:3s} {len(s['photos']):3d} media"
              f"{'  [has text]' if s['text'] else ''}")


if __name__ == "__main__":
    main()
