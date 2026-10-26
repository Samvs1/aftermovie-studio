"""Aftermovie Studio: one entry point for the whole pipeline.

  python tools/studio.py new <name> [--title "..."]      create projects/<name>/ (photos/, music/, cache/, out/, project.json)
  python tools/studio.py list                            list projects
  python tools/studio.py ingest <project> [--force]      photos -> faces -> music analysis (progress in cache/status.json)
  python tools/studio.py polarsteps <project> <export.zip> [--list | --trip ID]   import a Polarsteps trip (photos, steps, route)
  python tools/studio.py songs <project>                 song suggestions: Claude looks at the photos (headless), every song verified
  python tools/studio.py moodboard <project>             just the contact sheets + context used for picking songs
  python tools/studio.py vibe <project>                  vibe read of the song + photos (cache/vibe.md) for creative directions
  python tools/studio.py gallery <project>               every look / layer / transition on the project's photos (out/style_gallery.jpg)
  python tools/studio.py cast <project>                  apply the names from cache/cast.json (after "who's who")
  python tools/studio.py sheets <project>                numbered contact sheets for logging the photos (cache/sheets/)
  python tools/studio.py shotlog <project>               merge cache/shotlog_notes.json into the shot log
  python tools/studio.py draft <project>                 automatic first draft from the template (version "draft") + preview
  python tools/studio.py build <project> [film]          run the project's builder (build.py, or build_<film>.py)
  python tools/studio.py board <project> [version]       storyboard + caption board: a still per shot, every line and its source
  python tools/studio.py preview <project> [version]     board + 960px preview + compressed share copy + QA report (one review round)
  python tools/studio.py stills <project> <version> t1,t2,...
  python tools/studio.py final <project> [version]       1080p master + share copy + QA (only after the preview is approved)
  python tools/studio.py run <project> <tool.py> [args]   run any tool inside a project (song_map.py, find_joins.py, qa.py, ...)
  python tools/studio.py serve [--port 8765]             the local web app (upload, brief, who's who, review)
  python tools/studio.py doctor                          check the install (ffmpeg, GPU, models, Claude Code)
  python tools/studio.py check [project ...] [--update]  regression check: finished films still build the same EDL and look the same

<project> is a folder name under projects/ (or a path); "elevate" = projects/elevate-2026 (the first two films).
Every step runs the existing tools with AM_PROJECT set, so they read and write inside that project.
Started with another Python (e.g. plain `python`), it re-runs itself with the studio's .venv, which has the libraries.
Projects whose folder starts with "_" are internal (e.g. _style-samples) and hidden from lists.
"""
import argparse, glob, json, os, re, shutil, subprocess, sys, time, webbrowser

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ENGINE, "tools")
PROJECTS = os.path.join(ENGINE, "projects")
# plain `python` on Windows is often the Store Python without OpenCV/librosa: hand over to the studio's own venv
_VENV_PY = os.path.join(ENGINE, ".venv", "Scripts" if os.name == "nt" else "bin", "python.exe" if os.name == "nt" else "python")
if os.path.exists(_VENV_PY) and not os.environ.get("AM_IN_VENV") and \
        os.path.normcase(os.path.abspath(sys.executable)) != os.path.normcase(os.path.abspath(_VENV_PY)):
    sys.exit(subprocess.run([_VENV_PY, os.path.abspath(__file__)] + sys.argv[1:], env=dict(os.environ, AM_IN_VENV="1")).returncode)
PY = sys.executable
IMG_IN = (".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff", ".bmp")
VID_IN = (".mp4", ".mov", ".m4v")
AUD_IN = (".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac")

DEFAULT_PROJECT = {
    "title": "", "occasion": "", "when_where": "", "group_name": "", "language": "English",
    "vibe": "", "text_amount": "medium", "length": "the whole song (or one clean cut if it's long)",
    "song": {"file": "", "artist": "", "title": ""},
    "chapters": [], "people_notes": "", "jokes": "", "avoid": "", "credits": "", "ending_note": "", "editor": "",
    "extra": "", "status": {"stage": "new"},
}


# ------------------------------------------------------------------ helpers
def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "project"


def project_dir(name):
    if name in ("elevate", "legacy"):
        name = "elevate-2026"
    p = name if os.path.isabs(name) else os.path.join(PROJECTS, name)
    if not os.path.isdir(p):
        sys.exit(f"no such project: {name} (looked in {p})")
    return os.path.abspath(p)


def env_for(pdir):
    e = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONWARNINGS="ignore", AM_TOOLS=TOOLS)
    if os.path.abspath(pdir) != ENGINE:
        e["AM_PROJECT"] = pdir
    else:
        e.pop("AM_PROJECT", None)
    return e


def run(pdir, args, log=None, check=True):
    """Run a tool (path relative to tools/) inside the project; stream output to stdout and an optional log list."""
    cmd = [PY, "-W", "ignore", os.path.join(TOOLS, args[0])] + list(args[1:])
    p = subprocess.Popen(cmd, cwd=ENGINE, env=env_for(pdir), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace")
    for line in p.stdout:
        line = line.rstrip()
        print(line, flush=True)
        if log is not None:
            log.append(line)
            del log[:-40]
    p.wait()
    if check and p.returncode:
        raise RuntimeError(f"{args[0]} failed (exit {p.returncode})")
    return p.returncode


def load_project(pdir):
    p = os.path.join(pdir, "project.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}


def save_project(pdir, d):
    json.dump(d, open(os.path.join(pdir, "project.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)


class Status:
    """cache/status.json, polled by the web app."""

    def __init__(self, pdir, job, steps):
        self.path = os.path.join(pdir, "cache", "status.json")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.d = {"job": job, "steps": steps, "i": 0, "step": steps[0], "state": "running", "log": [],
                  "started": time.time(), "updated": time.time(), "error": ""}
        self.write()

    def write(self):
        self.d["updated"] = time.time()
        tmp = self.path + ".tmp"
        json.dump(self.d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
        os.replace(tmp, self.path)

    def step(self, i):
        self.d.update(i=i, step=self.d["steps"][i])
        self.write()

    def done(self, state="done", error=""):
        self.d.update(state=state, error=error, i=len(self.d["steps"]))
        self.write()


def thumb(src, dst, size=360):
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    im.thumbnail((size, size))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    im.save(dst, quality=80)


def normalize_photos(pdir):
    """Every still becomes an upright-EXIF .jpg in photos/ (HEIC/PNG/WebP converted, originals kept in photos/_originals)."""
    from PIL import Image, ImageOps
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except Exception:
        pass
    ph = os.path.join(pdir, "photos")
    orig = os.path.join(ph, "_originals")
    n = 0
    for f in sorted(os.listdir(ph)):
        src = os.path.join(ph, f)
        ext = os.path.splitext(f)[1].lower()
        if not os.path.isfile(src):
            continue
        if ext in IMG_IN and ext not in (".jpg",):
            dst = os.path.join(ph, os.path.splitext(f)[0] + ".jpg")
            try:
                im = Image.open(src)
                exif = im.getexif()
                im = ImageOps.exif_transpose(im).convert("RGB")
                if 0x0112 in exif:
                    del exif[0x0112]                 # orientation already applied
                im.save(dst, quality=95, exif=exif.tobytes())
                os.makedirs(orig, exist_ok=True)
                shutil.move(src, os.path.join(orig, f))
                n += 1
            except Exception as e:
                print(f"  could not convert {f}: {e}")
    for f in os.listdir(ph):
        if f.lower().endswith(".jpg"):
            t = os.path.join(pdir, "cache", "thumbs", f)
            if not os.path.exists(t):
                thumb(os.path.join(ph, f), t)
    return n


def song_info(pdir):
    """(slug, file, artist, title) for the project's song."""
    out = subprocess.run([PY, "-c", "import json,sys; sys.path.insert(0, r'%s'); from analyze_audio import SONGS; print(json.dumps(SONGS))" % TOOLS],
                         cwd=ENGINE, env=env_for(pdir), capture_output=True, text=True, encoding="utf-8")
    songs = json.loads(out.stdout.strip().splitlines()[-1]) if out.stdout.strip() else {}
    pj = load_project(pdir)
    want = (pj.get("song") or {}).get("file")
    items = [(s, f) for s, f in songs.items() if os.path.exists(os.path.join(pdir, "music", f))]
    if not items:
        return None
    slug, f = next(((s, f) for s, f in items if f == want), items[0])
    artist, title = (pj.get("song") or {}).get("artist", ""), (pj.get("song") or {}).get("title", "")
    if not (artist and title):
        tags = {}
        try:
            r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags=artist,title", "-of", "json",
                                os.path.join(pdir, "music", f)], capture_output=True, text=True, encoding="utf-8")
            tags = {k.lower(): v for k, v in json.loads(r.stdout).get("format", {}).get("tags", {}).items()}
        except Exception:
            pass
        base = re.sub(r"\s*[\[(].*?[\])]", "", os.path.splitext(f)[0])
        a2, t2 = (base.split(" - ", 1) + [""])[:2] if " - " in base else ("", base)
        artist = artist or tags.get("artist") or a2.strip()
        title = title or tags.get("title") or t2.strip()
    return slug, f, artist, title


# ------------------------------------------------------------------ commands
def cmd_new(a):
    slug = slugify(a.name)
    pdir = os.path.join(PROJECTS, slug)
    if os.path.exists(pdir):
        sys.exit(f"project exists: {pdir}")
    for d in ("photos", "music", "cache", "out", "review"):
        os.makedirs(os.path.join(pdir, d))
    pj = dict(DEFAULT_PROJECT, title=a.title or a.name, created=time.strftime("%Y-%m-%d"))
    save_project(pdir, pj)
    print(pdir)
    return pdir


def cmd_list(a):
    os.makedirs(PROJECTS, exist_ok=True)
    for d in sorted(os.listdir(PROJECTS)):
        pdir = os.path.join(PROJECTS, d)
        if not d.startswith("_") and os.path.isfile(os.path.join(pdir, "project.json")):
            pj = load_project(pdir)
            n = len([f for f in os.listdir(os.path.join(pdir, "photos")) if f.lower().endswith(".jpg")])
            print(f"{d:28s} {pj.get('title', ''):30s} {n:4d} photos  stage: {pj.get('status', {}).get('stage', '?')}")


def cmd_ingest(a):
    pdir = project_dir(a.project)
    steps = ["preparing photos", "finding faces & orientation", "grouping faces", "separating the song (stems)",
             "fetching lyrics", "analysing beats & sections", "aligning sung words", "finding a clean edit point"]
    st = Status(pdir, "ingest", steps)
    log = st.d["log"]
    try:
        st.step(0)
        n = normalize_photos(pdir)
        log.append(f"converted {n} photos to jpg")
        st.step(1)
        run(pdir, ["analyze_photos.py"] + (["--force"] if a.force else []), log)
        st.step(2)
        run(pdir, ["cluster_faces.py", "0.56"], log)
        song = song_info(pdir)
        if not song:
            log.append("no song in music/ yet: skipping the music analysis")
        else:
            slug, f, artist, title = song
            st.step(3)
            run(pdir, ["separate.py", slug], log)
            st.step(4)
            lyr = False
            if artist and title:
                try:
                    run(pdir, ["fetch_lyrics.py", slug, artist, title], log)
                    lyr = True
                except Exception as e:
                    log.append(f"lyrics lookup failed ({e}); continuing without lyrics")
            else:
                log.append("no artist/title known: skipping lyrics (fill in the song on the brief page)")
            st.step(5)
            run(pdir, ["analyze_audio.py", slug], log)
            st.step(6)
            if lyr:
                run(pdir, ["align_words.py", slug], log, check=False)
            st.step(7)
            jp = os.path.join(pdir, "cache", f"joins_{slug}.txt")
            jl = []
            run(pdir, ["find_joins.py", slug, "--top", "8"], jl, check=False)
            open(jp, "w", encoding="utf-8").write("\n".join(jl))
            d = json.load(open(os.path.join(pdir, "cache", "audio", f"{slug}.json"), encoding="utf-8"))
            pj = load_project(pdir)
            pj["song"] = dict(pj.get("song") or {}, file=f, artist=artist, title=title, slug=slug)
            pj["analysis"] = {"photos": len(json.load(open(os.path.join(pdir, "cache", "photos.json")))),
                              "song_slug": slug, "tempo": d.get("tempo"), "duration": d.get("duration"),
                              "constant_grid": (d.get("grid") or {}).get("constant"),
                              "lyrics_lines": len(d.get("lyrics", [])), "lyrics_match_z": (d.get("lyrics_meta") or {}).get("match_z")}
            pj.setdefault("status", {})["stage"] = "analysed"
            save_project(pdir, pj)
        pj = load_project(pdir)
        pj.setdefault("status", {})["stage"] = pj["status"].get("stage") if song else "photos analysed"
        save_project(pdir, pj)
        st.done()
    except Exception as e:
        st.done("error", str(e))
        raise


def cmd_polarsteps(a):
    """Import a trip from a Polarsteps export zip/folder (--list shows the trips in it), then make thumbnails."""
    pdir = project_dir(a.project)
    args = ["import_polarsteps.py", a.export] + (["--list"] if a.list else []) + (["--trip", a.trip] if a.trip else [])
    run(pdir, args)
    if not a.list:
        n = normalize_photos(pdir)
        print(f"thumbnails ready ({n} converted to jpg)")
        pj = load_project(pdir)
        pj.setdefault("status", {})["stage"] = "trip imported"
        save_project(pdir, pj)


def cmd_moodboard(a):
    """Contact sheets of the photos in story order (from thumbnails, no analysis needed) + cache/moodboard/context.md
    with the brief, the trip and a target song length, for picking music."""
    from PIL import Image, ImageDraw, ImageFont
    pdir = project_dir(a.project)
    normalize_photos(pdir)                                   # thumbnails for anything new
    out = os.path.join(pdir, "cache", "moodboard")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    ph = os.path.join(pdir, "photos")
    stills = sorted(f for f in os.listdir(ph) if f.lower().endswith(".jpg"))
    clips = sorted(f for f in os.listdir(ph) if f.lower().endswith(VID_IN))
    pick = stills if len(stills) <= 60 else [stills[round(i * (len(stills) - 1) / 59)] for i in range(60)]
    tiles = [("photo", f) for f in pick] + [("clip", f) for f in clips[:6]]
    T, cols, per = 300, 6, 24
    fnt = ImageFont.truetype("arialbd.ttf", 18)
    for si in range(0, len(tiles), per):
        chunk = tiles[si:si + per]
        rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * (T + 8) + 8, rows * (T + 8) + 8), (18, 18, 18))
        d = ImageDraw.Draw(sheet)
        for k, (kind, f) in enumerate(chunk):
            x, y = 8 + (k % cols) * (T + 8), 8 + (k // cols) * (T + 8)
            if kind == "photo":
                tp = os.path.join(pdir, "cache", "thumbs", f)
                im = Image.open(tp if os.path.exists(tp) else os.path.join(ph, f)).convert("RGB")
            else:
                fr = os.path.join(out, f"_{f}.jpg")
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "2", "-i", os.path.join(ph, f), "-frames:v", "1", fr])
                im = Image.open(fr).convert("RGB") if os.path.exists(fr) else Image.new("RGB", (T, T), (40, 40, 40))
            im.thumbnail((T, T))
            sheet.paste(im, (x + (T - im.width) // 2, y + (T - im.height) // 2))
            if kind == "clip":
                d.rectangle([x, y, x + 64, y + 26], fill=(200, 30, 30))
                d.text((x + 6, y + 3), "CLIP", fill=(255, 255, 255), font=fnt)
        sheet.save(os.path.join(out, f"sheet_{si // per + 1:02d}.jpg"), quality=82)
    pj = load_project(pdir)
    lines = [f"# Moodboard context: {pj.get('title') or os.path.basename(pdir)}", "",
             f"{len(stills)} photos and {len(clips)} clips (sheets show {len(pick)} photos in story order"
             f"{', sampled evenly' if len(pick) < len(stills) else ''}; red CLIP = video).", ""]
    for k, lab in (("occasion", "What it was"), ("when_where", "When & where"), ("group_name", "Group"), ("vibe", "Vibe they want"),
                   ("people_notes", "People"), ("jokes", "Inside jokes"), ("avoid", "Never show / mention"),
                   ("music_taste", "Music taste (songs/artists they like)"), ("language", "Language of on-screen text"), ("extra", "Other")):
        if str(pj.get(k) or "").strip():
            lines.append(f"- **{lab}:** {str(pj[k]).strip()}")
    tp = os.path.join(pdir, "cache", "trip.json")
    if os.path.exists(tp):
        t = json.load(open(tp, encoding="utf-8"))
        tr, over = t["trip"], pj.get("steps") or {}
        lines += ["", f"## Trip: {tr.get('name')} ({tr.get('start')} to {tr.get('end')}, {tr.get('days')} days, "
                      f"{', '.join(tr.get('country_names', []))}, ~{tr.get('km')} km)"]
        for s in t["steps"]:
            o = over.get(s["id"], {})
            if o.get("skip"):
                continue
            note = (o.get("note") if o.get("note") is not None else s.get("note")) or ""
            lines.append(f"- {s.get('date')} {o.get('label') or s.get('label') or s.get('place')} ({s.get('place')}, {s.get('country')})"
                         + (f": {note[:160]}" if note else ""))
    n = len(stills) + 2 * len(clips)
    lines += ["", "## Length guidance",
              f"The edit shows about one photo per bar (~2 s at 110-130 BPM), so ~{n} photos want roughly "
              f"{max(45, round(n * 2.0))}-{max(70, round(n * 2.6))} s of music. Longer songs work if they can be cut once between two "
              "identical passages (chorus to chorus), or with photos held longer. Very short songs need fewer photos."]
    open(os.path.join(out, "context.md"), "w", encoding="utf-8").write("\n".join(lines))
    print(out)


SONG_PROMPT = """You are the music supervisor for a friend-group aftermovie made in Aftermovie Studio. Pick songs that fit THESE photos.

1. Read {rel}/cache/moodboard/context.md (brief, trip, photo count, length guidance).
2. Look at every image in {rel}/cache/moodboard/ named sheet_*.jpg (the photos in story order; red CLIP = video).

Then suggest 8 songs. Rules:
- Only real, released songs you are certain exist, with the exact artist and title as released. Never invent or guess titles.
- Base the vibe on what you actually see (light, colour, setting, energy, how people act) and the brief; in "why" name concrete photos or moments you saw.
- A mix: 3 strong obvious fits, 3 less obvious indie/alternative picks, 1 high-energy party option, 1 wildcard (for a trip, something from or about the place, only if you are sure it exists).
- Fit the edit: music-locked, about one photo per bar; follow the length guidance. Prefer an intro that can carry a title, a build or drop for a big reveal, and an ending that lands. Say if a song should be shortened with one clean cut.
- Respect the "never show / mention" list and the music taste if given. Avoid songs whose main hook is about drugs or that contradict the vibe.

Reply with ONLY a JSON array (no prose, no code fences). Each item:
{{"artist": "...", "title": "...", "why": "two specific sentences", "tags": ["3-5 short vibe words"], "energy": "calm|mid|high",
"structure": "how the song maps onto the film (intro / chorus / ending)", "fit": "whole song | cut to about 2:30 | ...",
"lyric_hooks": "a lyric idea that could become an on-screen gag, or empty"}}"""


def cmd_songs(a):
    """Song suggestions: moodboard -> Claude Code (headless, read-only) looks at the photos -> every song checked on LRCLIB."""
    pdir = project_dir(a.project)
    st = Status(pdir, "songs", ["making a moodboard of your photos", "Claude is looking at your photos (1-3 min)", "checking the songs exist"])
    try:
        cmd_moodboard(a)
        st.step(1)
        claude = shutil.which("claude")
        if not claude:
            raise RuntimeError("Claude Code isn't installed: https://claude.com/claude-code")
        rel = os.path.relpath(pdir, ENGINE).replace("\\", "/")
        r = subprocess.run([claude, "-p", SONG_PROMPT.format(rel=rel), "--output-format", "json", "--allowedTools", "Read"],
                           cwd=ENGINE, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1200)
        try:
            text = json.loads(r.stdout).get("result", "")
        except Exception:
            text = r.stdout
        i0, i1 = text.find("["), text.rfind("]")
        if i0 < 0 or i1 < i0:
            raise RuntimeError("Claude didn't return suggestions: " + (text or r.stderr)[-300:])
        items = json.loads(text[i0:i1 + 1])
        st.step(2)
        sys.path.insert(0, TOOLS)
        from song_check import lookup
        for it in items:
            it["check"] = lookup(it.get("artist", ""), it.get("title", ""))
            print(f"{'ok ' if it['check'].get('found') else '?? '} {it.get('artist')} - {it.get('title')}", flush=True)
            time.sleep(0.2)
        items.sort(key=lambda it: it["check"].get("found") is False)        # unverified ones last
        pj = load_project(pdir)
        pj["song_suggestions"] = {"at": time.strftime("%Y-%m-%d %H:%M"), "items": items}
        save_project(pdir, pj)
        st.done()
    except Exception as e:
        st.done("error", str(e))
        raise


def cmd_vibe(a):
    """Vibe read of the song and the photos -> cache/vibe.md (input for creative directions)."""
    run(project_dir(a.project), ["vibe.py"])


def cmd_cast(a):
    pdir = project_dir(a.project)
    run(pdir, ["cast.py"])
    pj = load_project(pdir)
    pj.setdefault("status", {})["people_named"] = True
    save_project(pdir, pj)


def cmd_sheets(a):
    """Numbered contact sheets (20 per sheet) so Claude can look at every photo and write the shot log."""
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    pdir = project_dir(a.project)
    meta = json.load(open(os.path.join(pdir, "cache", "photos.json")))
    fpp = os.path.join(pdir, "cache", "faces_people.json")
    fp = json.load(open(fpp)) if os.path.exists(fpp) else {}
    cp = os.path.join(pdir, "cache", "cast.json")
    names = {k: v.get("name") for k, v in json.load(open(cp, encoding="utf-8")).get("people", {}).items()} if os.path.exists(cp) else {}
    files = sorted(meta)
    out = os.path.join(pdir, "cache", "sheets")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    T, cols, per = 360, 5, 20
    fnt = ImageFont.truetype("arialbd.ttf", 22)
    small = ImageFont.truetype("arial.ttf", 17)
    for si in range(0, len(files), per):
        chunk = files[si:si + per]
        rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * (T + 10) + 10, rows * (T + 70) + 10), (20, 20, 20))
        d = ImageDraw.Draw(sheet)
        for k, f in enumerate(chunk):
            im = ImageOps.exif_transpose(Image.open(os.path.join(pdir, "photos", f))).convert("RGB")
            if meta[f]["rot"]:
                im = im.rotate(-90 * meta[f]["rot"], expand=True)
            im.thumbnail((T, T))
            x, y = 10 + (k % cols) * (T + 10), 10 + (k // cols) * (T + 70)
            sheet.paste(im, (x + (T - im.width) // 2, y + (T - im.height) // 2))
            who = ", ".join(sorted({names.get(p, f"#{p}") for p in fp.get(f, []) if p}))
            # long names (Polarsteps uuids) overlap the next tile: number + shortened name, full list in index.txt
            short = f if len(f) <= 24 else f[:14] + "…" + os.path.splitext(f)[0][-6:]
            d.text((x, y + T + 4), f"{si + k + 1} {short}", fill=(255, 215, 0), font=fnt)
            d.text((x, y + T + 32), (f"{meta[f]['orient'][:4]} · {meta[f]['source']} · {who}")[:44], fill=(200, 200, 200), font=small)
        p = os.path.join(out, f"sheet_{si // per + 1:02d}.jpg")
        sheet.save(p, quality=85)
        print(p)
    with open(os.path.join(out, "index.txt"), "w", encoding="utf-8") as fh:
        fh.write("".join(f"{i + 1}\t{f}\n" for i, f in enumerate(files)))
    vids = [f for f in os.listdir(os.path.join(pdir, "photos")) if f.lower().endswith(VID_IN)]
    for v in vids:
        vp = os.path.join(out, f"video_{os.path.splitext(v)[0]}.jpg")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", os.path.join(pdir, "photos", v), "-vf", "fps=1,scale=320:-2,tile=6x3",
                        "-frames:v", "1", vp])
        print(vp)


def cmd_shotlog(a):
    run(project_dir(a.project), ["shotlog.py"])


def latest_version(pdir):
    edls = sorted(glob.glob(os.path.join(pdir, "out", "*_edl.json")), key=os.path.getmtime)
    if not edls:
        sys.exit("no EDL in out/ yet: run the builder first")
    return os.path.basename(edls[-1])[:-len("_edl.json")]


def cmd_build(a):
    """Run the project's builder: build.py, or build_<name>.py when a project holds several films."""
    pdir = project_dir(a.project)
    b = os.path.join(pdir, f"build_{a.film}.py" if a.film else "build.py")
    if not os.path.exists(b):
        many = sorted(f for f in os.listdir(pdir) if re.fullmatch(r"build_.+\.py", f))
        if not a.film and len(many) == 1:
            b = os.path.join(pdir, many[0])
        else:
            sys.exit(f"no builder at {b}" + (f" (this project has: {', '.join(m[6:-3] for m in many)})" if many else
                                              " (start from tools/templates/build_template.py)"))
    subprocess.run([PY, "-W", "ignore", b], cwd=ENGINE, env=env_for(pdir), check=True)


def cmd_gallery(a):
    """Every look / layer / transition rendered on the project's own photos -> out/style_gallery.jpg."""
    pdir = project_dir(a.project)
    st = Status(pdir, "gallery", ["building the sample shots", "rendering ~30 frames", "making the sheet"])
    try:
        g = os.path.join("templates", "style_gallery.py")
        run(pdir, [g, "--edl-only"])
        st.step(1)
        stills = json.load(open(os.path.join(pdir, "cache", "style_gallery.json"), encoding="utf-8"))
        run(pdir, ["render.py", os.path.join(pdir, "out", "style_gallery_edl.json"), "--width", "960", "--stills",
                   ",".join(str(s_) for _, s_ in stills)])
        st.step(2)
        run(pdir, [g, "--sheet-only"])
        st.done()
    except Exception as e:
        st.done("error", str(e))
        raise


def cmd_draft(a):
    """Automatic first draft (no director): the template builder as version 'draft', then a preview."""
    pdir = project_dir(a.project)
    st = Status(pdir, "draft", ["building the draft edit", "rendering the preview", "QA"])
    try:
        env = dict(env_for(pdir), AM_VERSION="draft")
        subprocess.run([PY, "-W", "ignore", os.path.join(TOOLS, "templates", "build_template.py")], cwd=ENGINE, env=env, check=True)
        st.step(1)
        a.version = "draft"
        cmd_preview(a)
        st.done()
    except Exception as e:
        st.done("error", str(e))
        raise


def share_copy(src, dst, width):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-vf", f"scale={width}:-2", "-c:v", "libx264", "-crf", "27",
                    "-preset", "slow", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", dst], check=True)
    print(f"share copy: {dst} ({os.path.getsize(dst) / 1e6:.0f} MB)")


def cmd_board(a):
    pdir = project_dir(a.project)
    run(pdir, ["board.py", a.version or latest_version(pdir)])


def add_round(pdir, v, kind, video):
    """One review round per preview (and the final): project.json "rounds" {version: [{n, kind, at, video, qa}]}.
    The small video of each preview round is kept in out/rounds/ so the studio can compare rounds."""
    pj = load_project(pdir)
    rounds = pj.setdefault("rounds", {}).setdefault(v, [])
    n = len([r for r in rounds if r["kind"] == "preview"]) + (1 if kind == "preview" else 0)
    keep = ""
    if kind == "preview" and os.path.exists(video):
        os.makedirs(os.path.join(pdir, "out", "rounds"), exist_ok=True)
        keep = f"out/rounds/{v}_r{n}.mp4"
        shutil.copyfile(video, os.path.join(pdir, keep))
    qa = os.path.join(pdir, "cache", "qa", v, "report.md")
    summary = [l.strip("* ") for l in open(qa, encoding="utf-8").read().splitlines() if l.startswith("**")] if os.path.exists(qa) else []
    rounds.append({"n": n, "kind": kind, "at": time.strftime("%Y-%m-%d %H:%M"), "video": keep, "qa": summary})
    save_project(pdir, pj)
    return n


def cmd_preview(a):
    pdir = project_dir(a.project)
    v = a.version or latest_version(pdir)
    edl = os.path.join(pdir, "out", f"{v}_edl.json")
    run(pdir, ["board.py", v], check=False)              # storyboard first: reviewable while the video renders
    run(pdir, ["render.py", edl, "--preview"])
    share_copy(os.path.join(pdir, "out", f"{v}_preview.mp4"), os.path.join(pdir, "out", f"{v}_preview_share.mp4"), 960)
    run(pdir, ["qa.py", edl], check=False)
    n = add_round(pdir, v, "preview", os.path.join(pdir, "out", f"{v}_preview_share.mp4"))
    pj = load_project(pdir)
    pj.setdefault("status", {}).update(stage=f"preview ready (round {n})", preview=f"out/{v}_preview_share.mp4", version=v)
    save_project(pdir, pj)


def cmd_stills(a):
    pdir = project_dir(a.project)
    run(pdir, ["render.py", os.path.join(pdir, "out", f"{a.version}_edl.json"), "--width", "960", "--stills", a.times])


def cmd_final(a):
    pdir = project_dir(a.project)
    v = a.version or latest_version(pdir)
    edl = os.path.join(pdir, "out", f"{v}_edl.json")
    run(pdir, ["render.py", edl])
    share_copy(os.path.join(pdir, "out", f"{v}.mp4"), os.path.join(pdir, "out", f"{v}_share.mp4"), 1280)
    run(pdir, ["qa.py", edl, "--video", os.path.join(pdir, "out", f"{v}.mp4")], check=False)
    add_round(pdir, v, "final", "")
    pj = load_project(pdir)
    pj.setdefault("status", {}).update(stage="final", final=f"out/{v}.mp4", share=f"out/{v}_share.mp4")
    save_project(pdir, pj)


def cmd_run(a):
    """Run any tool inside a project, e.g.  studio.py run my-trip song_map.py my_song --segments "0,180,0.8" """
    pdir = project_dir(a.project)
    sys.exit(subprocess.run([PY, "-W", "ignore", os.path.join(TOOLS, a.tool)] + a.args, cwd=ENGINE, env=env_for(pdir)).returncode)


def cmd_serve(a):
    sys.path.insert(0, os.path.join(ENGINE, "app"))
    import server
    url = f"http://127.0.0.1:{a.port}/"
    if not a.no_browser:
        webbrowser.open(url)
    server.serve(a.port)


def cmd_check(a):
    """Rebuild every finished film's EDL (into cache/check, out/ untouched) and compare stills with the references."""
    sys.exit(subprocess.run([PY, "-W", "ignore", os.path.join(TOOLS, "check.py")] + a.args, cwd=ENGINE,
                            env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONWARNINGS="ignore")).returncode)


def cmd_doctor(a):
    ok = True

    def line(name, good, detail=""):
        nonlocal ok
        ok &= bool(good) or name.startswith("(optional)")
        print(f"  [{'ok' if good else '!!'}] {name} {detail}")
    print(f"Aftermovie Studio at {ENGINE}")
    line("python", sys.version_info >= (3, 11), sys.version.split()[0])
    ff = shutil.which("ffmpeg")
    line("ffmpeg", ff, ff or "missing: winget install Gyan.FFmpeg")
    sys.path.insert(0, TOOLS)
    from render import has_nvenc
    line("(optional) NVIDIA encoder", has_nvenc(), "(renders use the CPU without it: slower, same look)")
    for m in ("face_detection_yunet_2023mar.onnx", "face_recognition_sface_2021dec.onnx"):
        line(f"model {m}", os.path.exists(os.path.join(ENGINE, "models", m)))
    for mod in ("cv2", "librosa", "torch", "torchaudio", "demucs", "beat_this", "scipy", "PIL", "fontTools", "soundfile"):
        try:
            __import__(mod)
            line(f"module {mod}", True)
        except Exception as e:
            line(f"module {mod}", False, str(e)[:60])
    try:
        import pillow_heif  # noqa: F401
        line("(optional) HEIC photos (pillow-heif)", True)
    except Exception:
        line("(optional) HEIC photos (pillow-heif)", False, "iPhone .heic uploads need: pip install pillow-heif")
    cl = shutil.which("claude")
    line("Claude Code (the director)", cl, cl or "missing: https://claude.com/claude-code  (irm https://claude.ai/install.ps1 | iex)")
    du = shutil.disk_usage(ENGINE)
    line("free disk", du.free > 10e9, f"{du.free / 1e9:.0f} GB (stems, grading cache and renders need ~5 GB per film)")
    print("all good" if ok else "fix the !! lines above")


def main():
    ap = argparse.ArgumentParser(description="Aftermovie Studio")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("new"); p.add_argument("name"); p.add_argument("--title")
    sp.add_parser("list")
    p = sp.add_parser("ingest"); p.add_argument("project"); p.add_argument("--force", action="store_true")
    p = sp.add_parser("build"); p.add_argument("project"); p.add_argument("film", nargs="?")
    for c in ("cast", "sheets", "shotlog", "draft", "moodboard", "songs", "vibe", "gallery"):
        sp.add_parser(c).add_argument("project")
    for c in ("preview", "final", "board"):
        p = sp.add_parser(c); p.add_argument("project"); p.add_argument("version", nargs="?")
    p = sp.add_parser("stills"); p.add_argument("project"); p.add_argument("version"); p.add_argument("times")
    p = sp.add_parser("polarsteps"); p.add_argument("project"); p.add_argument("export"); p.add_argument("--trip"); p.add_argument("--list", action="store_true")
    p = sp.add_parser("run"); p.add_argument("project"); p.add_argument("tool"); p.add_argument("args", nargs=argparse.REMAINDER)
    p = sp.add_parser("serve"); p.add_argument("--port", type=int, default=8765); p.add_argument("--no-browser", action="store_true")
    sp.add_parser("doctor")
    p = sp.add_parser("check"); p.add_argument("args", nargs=argparse.REMAINDER)
    if sys.argv[1:2] == ["check"]:                          # its own flags (--update, ...) go straight to check.py
        a = argparse.Namespace(cmd="check", args=sys.argv[2:])
    else:
        a = ap.parse_args()
    globals()["cmd_" + a.cmd](a)


if __name__ == "__main__":
    main()
