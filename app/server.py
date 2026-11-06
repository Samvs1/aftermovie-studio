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
    if not re.fullmatch(r"_?[a-z0-9][a-z0-9-]{0,60}", name or ""):          # "_name": internal, by URL only
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
            "songs": song_folders(name, d),
            "versions": versions, "notes": jload(os.path.join(d, "review", "notes.json"), []), "files": files,
            "captions": jload(os.path.join(d, "review", "captions.json"), {}),
            "job": job_state(name), "director": director_state(name, brief=False), "critiques": critiques_state(name, d),
            "story_job": (pj.get("status") or {}).get("story")}


def song_folders(name, d):
    """The song kit's folders (song/<slug>/) with the URLs the song viewer needs: data, story, the stems to solo."""
    out, sd = [], os.path.join(d, "song")
    for slug in sorted(os.listdir(sd)) if os.path.isdir(sd) else []:
        mp = os.path.join(sd, slug, "song-map.json")
        if not os.path.isfile(mp):
            continue
        v, q = int(os.path.getmtime(mp)), urllib.parse.quote(slug)
        base = f"/p/{name}/song/{q}"
        item = {"slug": slug, "map": f"{base}/song-map.json?v={v}", "env": f"{base}/envelopes.json?v={v}",
                "docs": {f: f"{base}/{f}" for f in ("song-map.md", "lyrics.md", "song-story.md", "overview.png", "report.json")
                         if os.path.exists(os.path.join(sd, slug, f))},
                "stems": {k: f"/p/{name}/cache/stems/{q}/{k}.wav" for k in ("vocals", "drums", "bass", "other")
                          if os.path.exists(os.path.join(d, "cache", "stems", slug, f"{k}.wav"))}}
        sp = os.path.join(sd, slug, "song-story.md")
        item["story_written"] = os.path.exists(sp) and "_2–4 sentences" not in open(sp, encoding="utf-8").read()
        out.append(item)
    return out


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
        pj["song"] = dict(pj.get("song") or {}, **{k: str(v)[:200] for k, v in body["song"].items()
                                                   if k in ("artist", "title", "file", "language")})
        if "lyrics" in body["song"]:                    # the user's own lyrics for the project's song (align_lyrics.py)
            set_lyrics(d, pj["song"], body["song"]["lyrics"])
    studio.save_project(d, pj)
    return pj


# ------------------------------------------------------------------ the user's own lyrics (tools/align_lyrics.py)
SLUG = re.compile(r"[a-z0-9_]{1,60}")


def set_lyrics(d, entry, text, keep_old=True):
    """The lyrics of one song (entry = project.json "song" or "songs"[slug]): plain text, LRC or word-timed LRC. Other
    lyrics than before are no longer the ones timed on this song in the editor (lyrics_synced, lyrics_set dropped);
    the text they replace is kept in cache/lyrics/."""
    import align_lyrics as AL
    text = str(text or "").replace("\r\n", "\n").lstrip("\ufeff")[:60000]
    old = AL.lyrics_text(entry)
    if text.strip() == old.strip():
        return False
    if keep_old and old.strip():
        os.makedirs(os.path.join(d, "cache", "lyrics"), exist_ok=True)
        open(os.path.join(d, "cache", "lyrics", f"lyrics_{time.strftime('%Y%m%d-%H%M%S')}.txt"), "w",
             encoding="utf-8").write(old)
    entry.pop("lyrics_synced", None)
    entry.pop("lyrics_set", None)
    if text.strip():
        entry["lyrics"] = text
    else:
        entry.pop("lyrics", None)
    return True


def song_of(d, slug):
    """(slug, file) of an analysed song in the project (cache/audio/<slug>.json), for the lyric timing editor."""
    if not SLUG.fullmatch(str(slug or "")):
        raise ValueError("bad song slug")
    A = jload(os.path.join(d, "cache", "audio", f"{slug}.json"), None)
    if not A or not A.get("file"):
        raise ValueError(f"the song {slug} isn't analysed yet")
    return slug, A["file"]


def lrc_time(t):
    m, s_ = divmod(max(0.0, float(t)), 60)
    return f"{int(m):02d}:{s_:05.2f}"


def lyric_structure(rows):
    """The LRC lines (rows of (t, line, set, part, stanza) in time order) with the lyric's tags and stanza breaks put
    back: "[Chorus]" above a line whose part differs from the one above it, a blank line between two stanzas. A line
    with neither (a repeat Whisper heard, a line added in the editor) goes on in the part above it; a repeat that has a
    part but sits inside another part (the parts above and below it agree) stays in that part."""
    out, cur, cur_st = [], None, None
    for k, (_, line, _, part, st) in enumerate(rows):
        if part and st is None:
            nxt = next((r[3] for r in rows[k + 1:] if r[4] is not None), None)
            if cur and nxt == cur:
                part = cur
        if part and part != cur:
            out += ([""] if out else []) + [f"[{part}]"]
            cur, cur_st = part, st
        elif st is not None:
            if cur_st is not None and st != cur_st:
                out.append("")
            cur_st = st
        out.append(line)
    return out


def save_lyric_timing(name, body):
    """The lyric timing editor (The song page): body {slug, lines: [{t, end?, text, words?, set, part?, stanza?}]}.
    Every line with its start, its end where the user set one (a time tag after the last word: "[00:12.00] hold the
    light <00:14.10>") and its words' times where the user's LRC had them, becomes LRC in that song's lyrics
    (project.json song.lyrics, or songs.<slug>.lyrics), marked as timed on this very song file ("lyrics_synced": no
    offset search). The lyric's own structure stays in it ([Chorus] tags above each part, blank lines between stanzas),
    so the analysis still names the sections from the tags. The lines the user set by hand are listed in "lyrics_set"
    (their start times): the analysis keeps those exactly and places every other line where Whisper heard it. The
    lyrics it replaces are kept in cache/lyrics/. Then the song is analysed again (ingest --song-only: stems reused)."""
    import align_lyrics as AL
    d = pdir(name)
    slug, file = song_of(d, body.get("slug"))
    out = []
    for x in body.get("lines") or []:
        text = re.sub(r"\s+", " ", str(x.get("text") or "")).strip()[:400]
        t = float(x.get("t"))
        if not text:
            continue
        if not 0 <= t < 6 * 3600:
            raise ValueError(f"a line starts at {t} s: that's not in the song")
        ws = x.get("words") or []
        if ws and " ".join(str(w[0]) for w in ws) == text:            # word-timed (enhanced LRC): keep the word times
            text = " ".join(f"<{lrc_time(float(wt))}> {w}" for w, wt in ws)
        end = x.get("end")
        if end is not None and t + 0.05 < float(end) < 6 * 3600:      # when the line stops
            text += f" <{lrc_time(float(end))}>"
        part = re.sub(r"[\[\]\s]+", " ", str(x.get("part") or "")).strip()[:80] or None
        st = x.get("stanza")
        out.append((t, f"[{lrc_time(t)}] {text}", bool(x.get("set")), part, st if isinstance(st, int) else None))
    if len(out) < 3:
        raise ValueError("at least 3 lyric lines are needed")
    if job_state(name).get("running"):
        raise RuntimeError("something is running on this project: wait for it to finish, then save again")
    pj = jload(os.path.join(d, "project.json"), {})
    entry = AL.lyrics_entry(pj, slug, file, create=True)
    set_lyrics(d, entry, "\n".join(lyric_structure(sorted(out, key=lambda z: z[0]))) + "\n")
    entry["lyrics_synced"] = True
    entry["lyrics_set"] = [round(int(m) * 60 + float(s_), 2) for t, _, mine, _, _ in out if mine
                           for m, s_ in [lrc_time(t).split(":")]]        # as the LRC reads back
    studio.save_project(d, pj)
    if body.get("analyse", True):
        start_job(name, "ingest", ["ingest", name, "--song-only", "--slug", slug])
    return {"ok": True, "lines": len(out)}


def align_lyrics(name, body):
    """The timing editor's "Align with Whisper": body {slug, lines: [{text}]} goes to studio.py align-lyrics (Whisper
    transcribes the vocal stem once per song, then align_lyrics.py matches the lines to what it heard) as a background
    job "align"; the editor reads cache/lyrics/<slug>_aligned.json when the job is done."""
    d = pdir(name)
    slug, _ = song_of(d, body.get("slug"))
    lines = [{"text": re.sub(r"\s+", " ", str(x.get("text") or "")).strip()[:400]} for x in body.get("lines") or []]
    if len([x for x in lines if x["text"]]) < 2:
        raise ValueError("at least 2 lyric lines are needed")
    cd = os.path.join(d, "cache", "lyrics")
    os.makedirs(cd, exist_ok=True)
    if os.path.exists(os.path.join(cd, f"{slug}_aligned.json")):
        os.remove(os.path.join(cd, f"{slug}_aligned.json"))
    inp = os.path.join(cd, f"{slug}_align_in.json")
    json.dump(lines, open(inp, "w", encoding="utf-8"), ensure_ascii=False)
    start_job(name, "align", ["align-lyrics", name, slug, "--in", inp])
    return {"ok": True}


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
    """A note at a moment of a version. Written through am/notes.py (a lock, a re-read, an atomic replace): a running
    director's runner forwards notes and the director marks them done (`studio.py note-done`) in the same file."""
    from am.notes import update_notes
    d = pdir(name)
    v = str(body.get("version", ""))[:80]
    rounds = [r for r in (jload(os.path.join(d, "project.json"), {}).get("rounds") or {}).get(v, []) if r.get("kind") == "preview"]
    n = {"id": int(time.time() * 1000), "version": v, "t": round(float(body.get("t", 0)), 2),
         "text": str(body.get("text", ""))[:2000], "done": False, "at": time.strftime("%Y-%m-%d %H:%M"),
         "round": rounds[-1]["n"] if rounds else None}
    return update_notes(d, lambda notes: notes.append(n))


def edit_note(name, body):
    from am.notes import update_notes
    d = pdir(name)

    def fn(notes):
        if body.get("delete"):
            return [n for n in notes if n.get("id") != body.get("id")]
        for n in notes:
            if n.get("id") == body.get("id"):
                n["done"] = bool(body.get("done"))
    return update_notes(d, fn)


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


# ------------------------------------------------------------------ the autonomous director, the critic, the story draft
DIRECTOR_KEYS = ("model", "effort", "budget", "critic_model", "critic_effort", "ultracode", "max_usd", "auto_continue")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
MODEL_RE = re.compile(r"[A-Za-z0-9._\[\]-]{1,60}")


def director_state(name, brief=True):
    """The latest director run (cache/director/current.json + its status.json) for the Direct page: its state, the
    clock, the live log, the agents, the costs per model with the total, the critiques; and "continuable" (Continue
    the last run) once it's over."""
    import director
    d = pdir(name)
    cur = jload(os.path.join(d, "cache", "director", "current.json"), None)
    if not cur:
        return None
    st = jload(os.path.join(d, cur["dir"], "status.json"), {}) or {}
    out = {k: st.get(k, cur.get(k)) for k in ("run", "state", "kind", "model", "model_used", "effort", "budget", "budget_s",
                                               "started", "deadline", "elapsed_s", "wall_s", "cost_usd", "turns", "version",
                                               "preview", "stop_reason", "result", "messages_sent", "claude_version",
                                               "critic_model", "critic_cost_usd", "version_critique", "version_scores",
                                               "ultracode", "max_usd", "budget_hit", "agents", "model_usage", "background",
                                               "working", "auto_continue", "paused", "pauses", "paused_s", "active_s", "left_s",
                                               "cut_off", "continues", "waiting_until", "resets_at", "seed_notes")}
    out["critiques"] = [dict(c, url=f"/p/{name}/{c['file']}") for c in st.get("critiques") or [] if c.get("file")]
    out["costs"], out["total_usd"] = director.cost_rows(out), director.total_cost(out)
    out["events"] = st.get("events", [])[-200:]
    out["now"] = time.time()
    out["active"] = bool(director.run_active(d))
    c = director.continuable(d)
    out["continuable"] = {k: c.get(k) for k in ("run", "kind", "why", "ended", "left_s", "budget_s", "resets_at", "limit", "cut",
                                                "resumable", "version")} if c else None
    if brief and os.path.exists(os.path.join(d, cur["dir"], "brief.md")):
        out["brief"] = f"/p/{name}/{cur['dir']}/brief.md"
    if os.path.exists(os.path.join(d, cur["dir"], "messages.md")):
        out["messages"] = f"/p/{name}/{cur['dir']}/messages.md"
    return out


def critiques_state(name, d):
    """The critic's notes in this project (review/critic/*.json), newest first, with their reports' URLs; and which
    renders it is looking at right now."""
    try:
        import critic
        cs = critic.critiques(d)
        busy = critic.any_pending(d)
    except Exception:
        return {"items": [], "pending": []}
    out = []
    for c in reversed(cs[-80:]):
        f = c.get("file")
        if f and os.path.exists(os.path.join(d, f)):
            out.append({k: c.get(k) for k in ("video", "version", "scores", "verdict", "model", "cost_usd", "at", "problems", "keep", "safe")}
                       | {"file": f, "url": f"/p/{name}/{f}?v={int(os.path.getmtime(os.path.join(d, f)))}"})
    return {"items": out, "pending": busy}


def busy_elsewhere(name):
    """A director run going on in this project that this web app didn't start (`studio.py direct` from a terminal):
    said, so a second one isn't started over it."""
    import director
    j = JOBS.get(name)
    if j and j["proc"].poll() is None:
        return None
    if director.run_active(pdir(name)):
        return "a director run is going on in this project (not started here): let it finish, or stop it first"
    return None


def budget_of(x, default):
    budget = str(x or default).strip()
    return budget + "m" if re.fullmatch(r"\d+", budget) else budget


def cap_of(x):
    try:
        cap = float(str(x or "").strip().lstrip("$") or 0)
    except ValueError:
        cap = 0
    return cap if 0 < cap <= 10000 else 0


def on(x):
    return x is True or str(x).lower() in ("1", "true", "on")


def direct_args(name, body):
    """The Direct page's form -> `studio.py direct`: one director (effort default max), the critic, ultracode, an
    optional cost cap in dollars; auto_continue; revise (a review round); continue (Continue the last run: without a
    budget, what it had left). Anything out of range is left to the defaults."""
    cont = on(body.get("continue"))
    args = ["direct", name] + ([] if cont and not str(body.get("budget") or "").strip() else
                               ["--budget", budget_of(body.get("budget"), "90m")])
    args += ["--effort", body.get("effort") if body.get("effort") in EFFORTS else "max"]
    for key, flag in (("model", "--model"), ("critic_model", "--critic-model")):
        if MODEL_RE.fullmatch(str(body.get(key) or "")):
            args += [flag, str(body[key])]
    if on(body.get("ultracode")):
        args.append("--ultracode")
    if cap_of(body.get("max_usd")):
        args += ["--max-usd", f"{cap_of(body['max_usd']):g}"]
    if str(body.get("seed_notes") or "").strip():
        args += ["--seed-notes", str(body["seed_notes"])[:4000]]
    if on(body.get("revise")) and not cont:
        args.append("--revise")
    if cont:
        args.append("--continue")
    if "auto_continue" in body:
        args.append("--auto-continue" if on(body.get("auto_continue")) else "--no-auto-continue")
    if body.get("nudge") is False:
        args.append("--no-nudge")
    return args


def save_director(name, body):
    """The Direct form's settings, kept as they change (project.json "director")."""
    d = pdir(name)
    pj = jload(os.path.join(d, "project.json"), {})
    cur = dict(pj.get("director") or {})
    for k in DIRECTOR_KEYS:
        if k in body:
            v = body[k]
            if k in ("ultracode", "auto_continue"):
                cur[k] = on(v)
            elif k == "max_usd":
                cur[k] = cap_of(v) or None
            elif k == "effort":
                cur[k] = v if v in EFFORTS else "max"
            elif k in ("model", "critic_model", "critic_effort"):
                if MODEL_RE.fullmatch(str(v or "")):
                    cur[k] = str(v)
            else:
                cur[k] = str(v or "")[:20]
    pj["director"] = cur
    studio.save_project(d, pj)
    return pj


def start_direct(name, body):
    why = busy_elsewhere(name)
    if why:
        raise RuntimeError(why)
    if any(k in body for k in DIRECTOR_KEYS):
        save_director(name, body)
    start_job(name, "direct", direct_args(name, body))
    return {"ok": True}


def start_critique(name, body):
    """The Review page's "Ask the critic": a render in the project (or a version: its newest render), as the job
    "critique"."""
    d = pdir(name)
    target = str(body.get("video") or body.get("version") or "").replace("\\", "/").strip("/")
    if target.endswith(".mp4"):
        full = os.path.abspath(os.path.join(d, target))
        if not full.startswith(os.path.abspath(d) + os.sep) or not os.path.isfile(full):
            raise ValueError("no such video in this project")
    elif not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", target):
        raise ValueError("no such version")
    args = ["critique", name, target]
    if MODEL_RE.fullmatch(str(body.get("model") or "")):
        args += ["--model", str(body["model"])]
    if str(body.get("focus") or "").strip():
        args += ["--focus", str(body["focus"])[:600]]
    start_job(name, "critique", args)
    return {"ok": True}


def stop_job(name):
    """Stop the project's job: a director run wraps up cleanly (asked through cache/director/STOP; forced after 3 min
    if it hangs), the critic is ended with what it started, anything else terminated. A run started from the command
    line is asked the same way."""
    import director
    from am.claude import kill_tree
    d = pdir(name)
    j = JOBS.get(name)
    if not j or j["proc"].poll() is not None:
        if director.run_active(d):
            director.request_stop(d)
            return {"ok": True, "stopping": "asked it to stop (it was started from the command line): it wraps up cleanly"}
        return {"ok": True, "running": False}
    if j["job"] == "direct":
        director.request_stop(d)

        def force():
            time.sleep(180)
            if j["proc"].poll() is None:
                kill_tree(j["proc"])
        threading.Thread(target=force, daemon=True).start()
        return {"ok": True, "stopping": "the director wraps up within a minute or two"}
    if j["job"] in ("critique", "story", "songs"):    # with the claude call they started: they'd keep spending
        kill_tree(j["proc"])
        return {"ok": True}
    j["proc"].terminate()
    return {"ok": True}



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
            if parts[0] == "api" and parts[1] == "p" and len(parts) == 4 and parts[3] == "director":
                return self.send_json(director_state(parts[2]))
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
                elif ext in (".lrc", ".txt"):                # a lyrics file: the song's lyrics (project.json)
                    n = int(self.headers.get("Content-Length") or 0)
                    if n > 400000:
                        return self.send_json({"error": "that lyrics file is too big"}, 400)
                    raw = self.rfile.read(n)
                    try:
                        text = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        text = raw.decode("cp1252", errors="replace")
                    pj = jload(os.path.join(d, "project.json"), {})
                    slug = q.get("song", [""])[0]
                    import align_lyrics as AL
                    if slug:
                        slug, file = song_of(d, slug)
                        entry = AL.lyrics_entry(pj, slug, file, create=True)
                    else:
                        entry = pj.setdefault("song", {})
                    set_lyrics(d, entry, text)
                    studio.save_project(d, pj)
                    return self.send_json({"ok": True, "kind": "lyrics", "name": fn})
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
                if act == "lyrics-timing":                       # the lyric timing editor: LRC, then analyse again
                    return self.send_json(save_lyric_timing(name, body))
                if act == "lyrics-align":                        # ... "Align with Whisper": job "align"
                    return self.send_json(align_lyrics(name, body))
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
                if act == "song":                                  # remake the song folder (song kit)
                    start_job(name, "song", ["song", name])
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
                    return self.send_json(stop_job(name))
                if act == "direct":                                # the autonomous director (tools/director.py)
                    return self.send_json(start_direct(name, body))
                if act == "director-settings":
                    return self.send_json(save_director(name, body))
                if act == "critique":
                    return self.send_json(start_critique(name, body))
                if act == "story-draft":                           # Claude drafts the song story (headless)
                    start_job(name, "story", ["story", name])
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
