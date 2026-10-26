"""Aftermovie Studio local web app (standard library only; listens on 127.0.0.1).

  python tools/studio.py serve            -> http://127.0.0.1:8765/

Upload photos + a song, fill in the brief, run the analysis, name the faces, make a quick draft,
and review previews with timestamped notes. The creative direction itself happens in Claude Code
(/aftermovie <project>), which reads the same project folder.
"""
import json, mimetypes, os, re, subprocess, sys, threading, time, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

APP = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(APP)
TOOLS = os.path.join(ENGINE, "tools")
sys.path.insert(0, TOOLS)
import studio  # noqa: E402

PY = sys.executable
JOBS = {}            # project -> {"proc", "job", "log", "started"}
LOCK = threading.Lock()


# ------------------------------------------------------------------ project data
def pdir(name):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,60}", name or ""):
        raise ValueError("bad project name")
    d = os.path.join(studio.PROJECTS, name)
    if not os.path.isfile(os.path.join(d, "project.json")):
        raise FileNotFoundError(name)
    return d


def jload(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def safe_name(fn):
    base, ext = os.path.splitext(os.path.basename(fn))
    base = re.sub(r"[^A-Za-z0-9._ ()'&,-]+", "_", base).strip(" .")[:80] or "file"
    return base + ext.lower()


def list_projects():
    os.makedirs(studio.PROJECTS, exist_ok=True)
    out = []
    for n in sorted(os.listdir(studio.PROJECTS)):
        d = os.path.join(studio.PROJECTS, n)
        pj = jload(os.path.join(d, "project.json"), None) if not n.startswith("_") else None   # "_" = internal
        if pj is None:
            continue
        ph = [f for f in os.listdir(os.path.join(d, "photos")) if f.lower().endswith((".jpg", ".jpeg"))] if os.path.isdir(os.path.join(d, "photos")) else []
        cover = f"/p/{n}/cache/thumbs/{ph[0]}" if ph and os.path.exists(os.path.join(d, "cache", "thumbs", ph[0])) else ""
        out.append({"name": n, "title": pj.get("title") or n, "stage": (pj.get("status") or {}).get("stage", "new"),
                    "photos": len(ph), "song": (pj.get("song") or {}).get("title") or (pj.get("song") or {}).get("file") or "",
                    "cover": cover, "updated": os.path.getmtime(os.path.join(d, "project.json"))})
    return sorted(out, key=lambda p: -p["updated"])


def project_state(name):
    d = pdir(name)
    pj = jload(os.path.join(d, "project.json"), {})
    meta = jload(os.path.join(d, "cache", "photos.json"), {})
    photos, videos = [], []
    for f in sorted(os.listdir(os.path.join(d, "photos"))):
        fp = os.path.join(d, "photos", f)
        if not os.path.isfile(fp):
            continue
        low = f.lower()
        if low.endswith(studio.VID_IN):
            videos.append({"name": f, "url": f"/p/{name}/photos/{urllib.parse.quote(f)}"})
        elif low.endswith(studio.IMG_IN):
            t = os.path.join(d, "cache", "thumbs", os.path.splitext(f)[0] + ".jpg")
            m = meta.get(f, {})
            photos.append({"name": f, "thumb": f"/p/{name}/cache/thumbs/{urllib.parse.quote(os.path.basename(t))}" if os.path.exists(t) else "",
                           "faces": len(m.get("faces", [])), "orient": m.get("orient", ""), "analysed": f in meta})
    music = [f for f in sorted(os.listdir(os.path.join(d, "music"))) if f.lower().endswith(studio.AUD_IN)]
    cast = jload(os.path.join(d, "cache", "cast.json"), {"people": {}})
    names = {}
    for pid, p in cast.get("people", {}).items():
        for c in p.get("clusters", []):
            names[c] = {k: p.get(k, "") for k in ("name", "nick", "from", "city", "role", "credit")}
    for c in cast.get("exclude_clusters", []):
        names[c] = {"role": "ignore"}
    clusters = jload(os.path.join(d, "cache", "face_clusters_ui.json"), [])
    for c in clusters:
        c["crops"] = [f"/p/{name}/{x}" for x in c["crops"]]
        c.update(names.get(c["cluster"], {}))
    versions = []
    for f in sorted(os.listdir(os.path.join(d, "out")), key=lambda f: -os.path.getmtime(os.path.join(d, "out", f))):
        if f.endswith("_edl.json"):
            v = f[:-len("_edl.json")]
            item = {"version": v}
            for key, fn in (("preview", f"{v}_preview_share.mp4"), ("preview_full", f"{v}_preview.mp4"), ("final", f"{v}.mp4"),
                            ("final_share", f"{v}_share.mp4"), ("notes", f"{v}_notes.md")):
                if os.path.exists(os.path.join(d, "out", fn)):
                    item[key] = f"/p/{name}/out/{fn}"
            qa = os.path.join(d, "cache", "qa", v, "report.md")
            if os.path.exists(qa):
                item["qa"] = [l.strip("* ") for l in open(qa, encoding="utf-8").read().splitlines() if l.startswith("**")]
            bp = os.path.join(d, "out", f"{v}_board.json")
            if os.path.exists(bp):
                item["board"] = f"/p/{name}/out/{v}_board.json?v={int(os.path.getmtime(bp))}"
            ch = jload(os.path.join(d, "out", f"{v}_changes.json"), None)
            if ch:
                item["changes"] = ch
            item["rounds"] = [dict(r, video=f"/p/{name}/{r['video']}" if r.get("video") else "")
                              for r in (pj.get("rounds") or {}).get(v, [])]
            # play the newest render: a new preview round must not hide behind an older final
            vids = [(os.path.getmtime(os.path.join(d, "out", fn)), item[key]) for key, fn in
                    (("final_share", f"{v}_share.mp4"), ("final", f"{v}.mp4"), ("preview", f"{v}_preview_share.mp4"),
                     ("preview_full", f"{v}_preview.mp4")) if key in item]
            if vids:
                newest = max(vids)[1]
                item["play"] = newest
                item["play_kind"] = "final" if newest in (item.get("final_share"), item.get("final")) else "preview"
            versions.append(item)
    files = {k: f"/p/{name}/{v}" for k, v in (("treatment", "out/treatment.md"), ("shotlog", "out/shot_log.html"),
                                              ("cast_sheet", "cache/cast_sheet.jpg")) if os.path.exists(os.path.join(d, v))}
    trip = None
    tp = jload(os.path.join(d, "cache", "trip.json"), None)
    if tp:
        over = pj.get("steps") or {}
        steps = []
        for st in tp["steps"]:
            o = over.get(st["id"], {})
            stills = [x for x in st.get("photos", []) if not x.lower().endswith(studio.VID_IN)]
            thumbs = [f"/p/{name}/cache/thumbs/{urllib.parse.quote(os.path.splitext(x)[0] + '.jpg')}" for x in stills[:6]
                      if os.path.exists(os.path.join(d, "cache", "thumbs", os.path.splitext(x)[0] + ".jpg"))]
            item = {k: st.get(k) for k in ("id", "i", "date", "date_label", "place", "country", "country_code", "text", "weather_temp", "name")}
            item.update(label=o.get("label", st.get("label", "")), note=o.get("note", st.get("note", "")), who=o.get("who", ""),
                        skip=bool(o.get("skip", False)), photos=len(st.get("photos", [])), thumbs=thumbs)
            steps.append(item)
        trip = {"trip": tp["trip"], "steps": steps}
    directions = []
    for dr in jload(os.path.join(d, "out", "directions.json"), []) or []:
        if isinstance(dr, dict) and dr.get("id"):
            dr = dict(dr)
            dr["frames"] = [f"/p/{name}/{urllib.parse.quote(f)}" for f in dr.get("frames", []) if os.path.exists(os.path.join(d, f))]
            directions.append(dr)
    gp = os.path.join(d, "out", "style_gallery.jpg")
    gallery = f"/p/{name}/out/style_gallery.jpg?v={int(os.path.getmtime(gp))}" if os.path.exists(gp) else ""
    return {"name": name, "engine": ENGINE, "project": pj, "trip": trip, "directions": directions, "gallery": gallery, "photos": photos, "videos": videos, "music": music, "clusters": clusters,
            "versions": versions, "notes": jload(os.path.join(d, "review", "notes.json"), []), "files": files,
            "captions": jload(os.path.join(d, "review", "captions.json"), {}),
            "job": job_state(name)}


# ------------------------------------------------------------------ background jobs (one per project)
def start_job(name, job, args):
    with LOCK:
        j = JOBS.get(name)
        if j and j["proc"].poll() is None:
            raise RuntimeError(f"already running: {j['job']}")
        d = pdir(name)
        logp = os.path.join(d, "cache", "job.log")
        os.makedirs(os.path.dirname(logp), exist_ok=True)
        lf = open(logp, "w", encoding="utf-8")
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONWARNINGS="ignore")
        proc = subprocess.Popen([PY, "-W", "ignore", os.path.join(TOOLS, "studio.py")] + args, cwd=ENGINE, env=env,
                                stdout=lf, stderr=subprocess.STDOUT,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        JOBS[name] = {"proc": proc, "job": job, "log": logp, "started": time.time()}


def job_state(name):
    j = JOBS.get(name)
    d = os.path.join(studio.PROJECTS, name)
    st = jload(os.path.join(d, "cache", "status.json"), {})
    if not j:
        return {"running": False, "job": st.get("job"), "steps": st.get("steps"), "i": st.get("i"), "state": st.get("state")}
    rc = j["proc"].poll()
    try:
        tail = open(j["log"], encoding="utf-8", errors="replace").read().splitlines()[-14:]
    except Exception:
        tail = []
    out = {"running": rc is None, "job": j["job"], "returncode": rc, "log": tail, "elapsed": round(time.time() - j["started"])}
    if st.get("job") == j["job"]:
        out.update(steps=st.get("steps"), i=st.get("i"), state=st.get("state"), error=st.get("error"))
    return out


# ------------------------------------------------------------------ writes
BRIEF_KEYS = {"title", "occasion", "when_where", "group_name", "language", "vibe", "text_amount", "length", "people_notes",
              "jokes", "avoid", "credits", "ending_note", "editor", "extra", "grade", "music_taste",
              "adventurous", "style_leanings", "references", "musts"}


def save_brief(name, body):
    d = pdir(name)
    pj = jload(os.path.join(d, "project.json"), {})
    for k in BRIEF_KEYS & set(body):
        pj[k] = str(body[k])[:6000]
    if "chapters" in body:
        old = {c.get("label", ""): c for c in pj.get("chapters", [])}
        chs = []
        for line in str(body["chapters"]).splitlines():
            line = line.strip(" -\u2022\t")
            if line:
                chs.append(old.get(line[:60]) or {"id": re.sub(r"[^a-z0-9]+", "_", line.lower()).strip("_")[:24] or f"ch{len(chs) + 1}",
                                                  "label": line[:60]})
        pj["chapters"] = chs
    if "song" in body and isinstance(body["song"], dict):
        pj["song"] = dict(pj.get("song") or {}, **{k: str(v)[:200] for k, v in body["song"].items() if k in ("artist", "title", "file")})
    studio.save_project(d, pj)
    return pj


def save_cast(name, body):
    """body: {cluster_id: {name, nick, from, city, role (core|extra|ignore), credit}} -> cache/cast.json + cast.py."""
    d = pdir(name)
    people, by_name, exclude = {}, {}, []
    for cid, v in sorted(body.items(), key=lambda kv: int(kv[0])):
        role = v.get("role", "core")
        nm = (v.get("name") or "").strip()
        if role == "ignore" or not nm:
            if role == "ignore":
                exclude.append(cid)
            continue
        key = nm.lower()
        if key not in by_name:
            pid = str(len(people) + 1)
            by_name[key] = pid
            people[pid] = {"clusters": [], "name": nm, "nick": v.get("nick", ""), "from": v.get("from", ""),
                           "city": v.get("city", ""), "credit": v.get("credit", ""), "role": role, "core": role == "core"}
        p = people[by_name[key]]
        p["clusters"].append(cid)
        for k in ("nick", "from", "city", "credit"):
            p[k] = p[k] or v.get(k, "")
        if role == "core":
            p["core"], p["role"] = True, "core"
    json.dump({"_note": "written by the studio's who's-who page", "people": people, "exclude_clusters": exclude},
              open(os.path.join(d, "cache", "cast.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    r = subprocess.run([PY, "-W", "ignore", os.path.join(TOOLS, "studio.py"), "cast", name], cwd=ENGINE,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return {"people": len(people), "log": (r.stdout + r.stderr)[-1500:]}


def save_steps(name, body):
    """body: {step id: {label, note, who, skip}} -> project.json "steps"; single-step chapters follow their step's label.
    who = who is in it / who did what ("Tom drove; Sam cooked"): captions attribute actions only from here."""
    d = pdir(name)
    pj = jload(os.path.join(d, "project.json"), {})
    steps = pj.get("steps") or {}
    for sid, v in body.items():
        cur = steps.get(str(sid), {})
        cur.update(label=str(v.get("label", cur.get("label", "")))[:80], note=str(v.get("note", cur.get("note", "")))[:1500],
                   who=str(v.get("who", cur.get("who", "")))[:400], skip=bool(v.get("skip", cur.get("skip", False))))
        steps[str(sid)] = cur
    pj["steps"] = steps
    for c in pj.get("chapters", []):
        if len(c.get("steps", [])) == 1 and c["steps"][0] in steps and steps[c["steps"][0]].get("label"):
            c["label"] = steps[c["steps"][0]]["label"]
    studio.save_project(d, pj)
    return pj


def polarsteps_list(name, zpath):
    r = subprocess.run([PY, "-W", "ignore", os.path.join(TOOLS, "studio.py"), "polarsteps", name, zpath, "--list"], cwd=ENGINE,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    for line in reversed(r.stdout.splitlines()):
        if line.startswith("["):
            return json.loads(line)
    out = (r.stdout + r.stderr).strip().splitlines()
    raise RuntimeError(out[-1] if out else "could not read the export")


def add_note(name, body):
    d = pdir(name)
    p = os.path.join(d, "review", "notes.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    notes = jload(p, [])
    v = str(body.get("version", ""))[:80]
    rounds = [r for r in (jload(os.path.join(d, "project.json"), {}).get("rounds") or {}).get(v, []) if r.get("kind") == "preview"]
    notes.append({"id": int(time.time() * 1000), "version": v, "t": round(float(body.get("t", 0)), 2),
                  "text": str(body.get("text", ""))[:2000], "done": False, "at": time.strftime("%Y-%m-%d %H:%M"),
                  "round": rounds[-1]["n"] if rounds else None})
    json.dump(notes, open(p, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return notes


def edit_note(name, body):
    d = pdir(name)
    p = os.path.join(d, "review", "notes.json")
    notes = jload(p, [])
    if body.get("delete"):
        notes = [n for n in notes if n["id"] != body["id"]]
    else:
        for n in notes:
            if n["id"] == body.get("id"):
                n["done"] = bool(body.get("done"))
    json.dump(notes, open(p, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return notes


def caption(name, body):
    """The caption board: {key, ok: true | false | null (undecided), comment, text, version} -> review/captions.json.
    Keyed by the line and the photos it sits on, so a decision survives rebuilds and retiming."""
    d = pdir(name)
    p = os.path.join(d, "review", "captions.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    dec = jload(p, {})
    key = str(body.get("key", ""))[:2000]
    if not key:
        raise ValueError("no caption key")
    if body.get("ok") is None:
        dec.pop(key, None)
    else:
        dec[key] = {"ok": bool(body["ok"]), "comment": str(body.get("comment", ""))[:600], "text": str(body.get("text", ""))[:300],
                    "version": str(body.get("version", ""))[:80], "at": time.strftime("%Y-%m-%d %H:%M")}
    json.dump(dec, open(p, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return dec


def must(name, body):
    """Star a photo or clip as must-use: project.json "must_use" (the builder lint and QA check it is in the film)."""
    d = pdir(name)
    pj = jload(os.path.join(d, "project.json"), {})
    fn = safe_name(body.get("name", ""))
    cur = [x for x in pj.get("must_use") or [] if x != fn]
    if body.get("on"):
        cur.append(fn)
    pj["must_use"] = cur
    studio.save_project(d, pj)
    return {"must_use": cur}


def approve(name, body):
    d = pdir(name)
    pj = jload(os.path.join(d, "project.json"), {})
    pj.setdefault("status", {}).update(approved=str(body.get("version", "")), approved_at=time.strftime("%Y-%m-%d %H:%M"),
                                       stage="approved: ready for the final render")
    studio.save_project(d, pj)
    return pj


# ------------------------------------------------------------------ HTTP
class H(BaseHTTPRequestHandler):
    server_version = "AftermovieStudio/1.0"

    def log_message(self, fmt, *args):
        pass

    def send_json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def body_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n).decode("utf-8") or "{}") if n else {}

    def send_file(self, path):
        if not os.path.isfile(path):
            return self.send_json({"error": "not found"}, 404)
        size = os.path.getsize(path)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if path.endswith(".md"):
            ctype = "text/plain; charset=utf-8"
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            start = int(a) if a else max(0, size - int(b))
            end = int(b) if (a and b) else size - 1
            end = min(end, size - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(1 << 20, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
                    return
                left -= len(chunk)

    def route(self):
        u = urllib.parse.urlparse(self.path)
        return [urllib.parse.unquote(x) for x in u.path.strip("/").split("/") if x], urllib.parse.parse_qs(u.query)

    def do_GET(self):
        parts, q = self.route()
        try:
            if not parts:
                return self.send_file(os.path.join(APP, "static", "index.html"))
            if parts[0] == "static":
                return self.send_file(os.path.join(APP, "static", *[safe_name(p) for p in parts[1:]]))
            if parts[0] == "fonts" and len(parts) == 2:
                return self.send_file(os.path.join(ENGINE, "assets", "fonts", os.path.basename(parts[1])))
            if parts[0] == "p" and len(parts) >= 3:              # files inside a project
                base = pdir(parts[1])
                full = os.path.abspath(os.path.join(base, *parts[2:]))
                if not full.startswith(os.path.abspath(base) + os.sep):
                    return self.send_json({"error": "forbidden"}, 403)
                return self.send_file(full)
            if parts[:2] == ["api", "projects"]:
                return self.send_json(list_projects())
            if parts[0] == "api" and parts[1] == "p" and len(parts) == 3:
                return self.send_json(project_state(parts[2]))
            if parts[0] == "api" and parts[1] == "p" and len(parts) == 4 and parts[3] == "job":
                return self.send_json(job_state(parts[2]))
            if parts[:2] == ["api", "doctor"]:
                r = subprocess.run([PY, os.path.join(TOOLS, "studio.py"), "doctor"], capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", cwd=ENGINE, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
                return self.send_json({"text": r.stdout + r.stderr})
            self.send_json({"error": "not found"}, 404)
        except FileNotFoundError:
            self.send_json({"error": "no such project"}, 404)
        except Exception as e:
            self.send_json({"error": str(e)}, 400)

    def do_PUT(self):
        parts, q = self.route()
        try:
            if parts[0] == "api" and parts[1] == "p" and len(parts) == 4 and parts[3] == "polarsteps-upload":
                d = pdir(parts[2])
                os.makedirs(os.path.join(d, "import"), exist_ok=True)
                fn = safe_name(q.get("filename", ["polarsteps.zip"])[0])
                if not fn.lower().endswith(".zip"):
                    return self.send_json({"error": "that's not a .zip: use the file from Polarsteps' 'Download my data' email"}, 400)
                dst = os.path.join(d, "import", fn)
                n = int(self.headers.get("Content-Length") or 0)
                with open(dst + ".part", "wb") as f:
                    left = n
                    while left > 0:
                        chunk = self.rfile.read(min(1 << 20, left))
                        if not chunk:
                            break
                        f.write(chunk)
                        left -= len(chunk)
                os.replace(dst + ".part", dst)
                return self.send_json({"zip": "import/" + fn, "trips": polarsteps_list(parts[2], dst)})
            if parts[0] == "api" and parts[1] == "p" and len(parts) == 4 and parts[3] == "upload":
                d = pdir(parts[2])
                fn = safe_name(q.get("filename", ["file"])[0])
                ext = os.path.splitext(fn)[1]
                if ext in studio.AUD_IN:
                    sub = "music"
                elif ext in studio.IMG_IN or ext in studio.VID_IN:
                    sub = "photos"
                else:
                    return self.send_json({"error": f"unsupported file type {ext}"}, 400)
                dst = os.path.join(d, sub, fn)
                n = int(self.headers.get("Content-Length") or 0)
                with open(dst + ".part", "wb") as f:
                    left = n
                    while left > 0:
                        chunk = self.rfile.read(min(1 << 20, left))
                        if not chunk:
                            break
                        f.write(chunk)
                        left -= len(chunk)
                os.replace(dst + ".part", dst)
                if sub == "photos" and ext in studio.IMG_IN:
                    try:
                        try:
                            import pillow_heif
                            pillow_heif.register_heif_opener()
                        except Exception:
                            pass
                        studio.thumb(dst, os.path.join(d, "cache", "thumbs", os.path.splitext(fn)[0] + ".jpg"))
                    except Exception as e:
                        print("thumb failed", fn, e)
                if sub == "music":
                    pj = jload(os.path.join(d, "project.json"), {})
                    pj["song"] = dict(pj.get("song") or {}, file=fn)
                    studio.save_project(d, pj)
                return self.send_json({"ok": True, "kind": sub, "name": fn})
            self.send_json({"error": "not found"}, 404)
        except Exception as e:
            self.send_json({"error": str(e)}, 400)

    def do_POST(self):
        parts, q = self.route()
        try:
            body = self.body_json()
            if parts[:2] == ["api", "projects"]:
                name = studio.slugify(body.get("name") or body.get("title") or "aftermovie")
                if os.path.exists(os.path.join(studio.PROJECTS, name)):
                    name = f"{name}-{int(time.time()) % 10000}"
                class A:  # noqa: E701
                    pass
                a = A()
                a.name, a.title = name, body.get("title") or body.get("name") or name
                studio.cmd_new(a)
                return self.send_json({"name": name})
            if parts[0] == "api" and parts[1] == "p" and len(parts) == 4:
                name, act = parts[2], parts[3]
                if act == "brief":
                    return self.send_json(save_brief(name, body))
                if act == "delete":
                    d = pdir(name)
                    fn = safe_name(body.get("name", ""))
                    trash = os.path.join(d, "trash")          # recoverable: files are moved, never destroyed
                    os.makedirs(trash, exist_ok=True)
                    for sub in ("photos", "music"):
                        p = os.path.join(d, sub, fn)
                        if os.path.isfile(p):
                            os.replace(p, os.path.join(trash, fn))
                    t = os.path.join(d, "cache", "thumbs", os.path.splitext(fn)[0] + ".jpg")
                    if os.path.isfile(t):
                        os.remove(t)
                    return self.send_json({"ok": True})
                if act == "ingest":
                    start_job(name, "ingest", ["ingest", name])
                    return self.send_json({"ok": True})
                if act == "songs":
                    start_job(name, "songs", ["songs", name])
                    return self.send_json({"ok": True})
                if act == "gallery":
                    start_job(name, "gallery", ["gallery", name])
                    return self.send_json({"ok": True})
                if act == "draft":
                    start_job(name, "draft", ["draft", name])
                    return self.send_json({"ok": True})
                if act == "cast":
                    return self.send_json(save_cast(name, body))
                if act == "direction":
                    d = pdir(name)
                    pj = jload(os.path.join(d, "project.json"), {})
                    pj["direction"] = {"id": str(body.get("id", ""))[:20], "note": str(body.get("note", ""))[:1500],
                                       "at": time.strftime("%Y-%m-%d %H:%M")}
                    studio.save_project(d, pj)
                    return self.send_json(pj)
                if act == "steps":
                    return self.send_json(save_steps(name, body))
                if act == "polarsteps-import":
                    d = pdir(name)
                    zp = os.path.abspath(os.path.join(d, body.get("zip", "")))
                    if not zp.startswith(os.path.join(d, "import")) or not os.path.isfile(zp):
                        return self.send_json({"error": "upload the export first"}, 400)
                    start_job(name, "trip", ["polarsteps", name, zp, "--trip", str(body.get("trip", ""))])
                    return self.send_json({"ok": True})
                if act == "note":
                    return self.send_json(add_note(name, body))
                if act == "note-edit":
                    return self.send_json(edit_note(name, body))
                if act == "approve":
                    return self.send_json(approve(name, body))
                if act == "caption":
                    return self.send_json(caption(name, body))
                if act == "must":
                    return self.send_json(must(name, body))
                if act == "stop":
                    j = JOBS.get(name)
                    if j and j["proc"].poll() is None:
                        j["proc"].terminate()
                    return self.send_json({"ok": True})
            self.send_json({"error": "not found"}, 404)
        except FileNotFoundError:
            self.send_json({"error": "no such project"}, 404)
        except Exception as e:
            self.send_json({"error": str(e)}, 400)


def serve(port=8765):
    os.makedirs(studio.PROJECTS, exist_ok=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), H)
    print(f"Aftermovie Studio running at http://127.0.0.1:{port}/  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 8765)
