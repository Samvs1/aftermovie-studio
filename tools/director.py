"""The director, run headless: the story step and the autonomous run with a time budget.

  studio.py story <p>                     Claude drafts song/<slug>/song-story.md (read-only tools; the text comes back here)
  studio.py direct <p> --budget 90m ...   the autonomous run: one director (templates/director-brief.md) with full
                                          reign: it makes the film itself, or deploys agents where it wants to, and
                                          delivers a preview round (never the final: that waits for the user's approval)
  studio.py direct <p> --revise ...       the review round: templates/revise-brief.md with the user's notes and vetoes
  studio.py direct <p> --continue ...     carry on the last run in its own conversation (claude --resume), with the
                                          budget it had left (after the usage limit that stopped it has reset)
  studio.py direct <p> --auto-continue    when Claude's usage limit stops the director, wait for the reset (the clock
                                          stopped) and carry on; without, the run ends there
  studio.py clock <p>                     time left in the running budget
  studio.py stop <p>                      ask the running director to stop cleanly

The autonomous run (checked against `claude --help` of Claude Code 2.1.x):
  claude -p --input-format stream-json --output-format stream-json --verbose --model M --effort E (default max)
         --permission-mode dontAsk --allowedTools Read Write Edit Glob Grep Bash TaskCreate TaskUpdate TaskList TaskGet
         Agent TaskStop [Workflow: --ultracode] --disallowedTools WebFetch WebSearch --settings <deny network commands,
         the studio's folders, photos/, music/, the user's review files, the other projects> --add-dir <studio tools,
         assets, skills, templates, the reference builders> --append-system-prompt <the studio's ground rules>
         [--max-budget-usd N]
  cwd = the project folder. The brief goes in as the first stream-json user message; the runner reads every event,
  keeps cache/director/run-N/events.jsonl (raw) and status.json (summarised, polled by the web app), and sends more
  user messages: time warnings (half way, the last preview's time, 5 minutes left, time's up), a nudge when the
  director stops early with time left (use it to improve the film), a reminder when no preview exists yet. At the
  deadline plus a grace period (or when cache/director/STOP appears, or the cost cap was reached) it ends the session.
  Afterwards: the run settings (models and their costs, the agents, ultracode, the cap, effort, budget, wall time) go
  into out/<version>_notes.md and project.json "runs", and the critic's notes on the delivered preview.
  Agents are the director's choice: the Agent tool runs them (in the background with run_in_background), sharing the
  director's sandbox (`studio.py permtest` checks it). While they run the session is working even when its own turn
  has ended (am/session.py), so the runner sends no nudge or reminder and never closes the session then.
  The critic (tools/critic.py, a cheaper model with fresh eyes) looks at every new preview in out/ while the director
  works; its notes go to the director as messages, and the early-finish nudge carries its notes on the newest preview.
  The user's notes (the studio's Review page: they watch a preview with sound) made during the run reach the director
  within seconds, as a message with the song and shot context, and are marked forwarded in review/notes.json.
  Claude's usage limit stopping the director mid-run (am/session.py reads it from Claude Code's own messages): with
  --auto-continue the run pauses, its clock stopped and nothing sent, and once the limit has reset it carries on (a
  message to the same session, or a resumed process of its conversation); without, the run ends there and
  status.json's cut_off says what it had left. `direct --continue` (continuable(): the last run that started) carries
  it on later: claude --resume <its session id> with the studio's "carry on" first, or, when Claude Code can't resume
  it, a fresh session whose brief says where the work is. tools/INTERNALS.md has the details.
"""
import glob, json, os, re, shutil, subprocess, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STUDIO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from am.util import jload, jsave, load_project as load_pj, update_project, song_slug, PROJECTS  # noqa: E402
from am.claude import claude_bin, claude_print, kill_tree  # noqa: E402
from am.session import Session, LIMIT_RE, NOT_LIMIT_RE, reset_at, when  # noqa: E402

TEMPLATES = os.path.join(STUDIO, "templates")
SKILL = os.path.join(STUDIO, ".claude", "skills", "aftermovie", "SKILL.md")
STYLEBOOK = os.path.join(os.path.dirname(SKILL), "stylebook.md")
# reference builders the director may read (the studio's first films), when this install has them
REFERENCE = ("elevate-2026",)
# TaskCreate/Update/List/Get: its own to-do list. The agent tool is "Agent" in --allowedTools (the init event lists it as
# Task); TaskStop stops one; Workflow (multi-agent workflows) only with --ultracode. SendMessage and ListAgents aren't
# allowed: SendMessage can address the user's other Claude sessions on this machine by name.
ALLOWED = ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "TaskCreate", "TaskUpdate", "TaskList", "TaskGet", "Agent",
           "TaskStop"]
ULTRACODE = ["Workflow"]
DISALLOWED = ["WebFetch", "WebSearch"]
DENY_BASH = ["curl", "wget", "Invoke-WebRequest", "iwr", "Invoke-RestMethod", "irm", "pip install", "pip3 install",
             "python -m pip", "npm install", "npm i", "npx", "yarn", "pnpm", "git push", "git clone", "ssh", "scp",
             "winget", "apt", "apt-get", "brew", "choco"]
STUDIO_DIRS = ("tools", "assets", ".claude", "templates", "app", "models")       # read-only to a director run
PROJECT_RO = ("photos", "music")                                                  # the user's material: never changed
USER_FILES = (("review", "notes.json"), ("review", "captions.json"))               # written by the web app (and note-done)
SYSTEM_APPEND = ("You are running unattended inside Aftermovie Studio as the director of one aftermovie. Nobody "
                 "answers questions: decide and keep going, and never invent facts about the people or what happened. "
                 "Stay inside this project folder (the studio tools may be read and run, not edited). No network: "
                 "everything you need is installed. Deliver previews only: never render the final. Watch the clock.")
PREVIEW_TIME = "about 1-2 minutes with an NVIDIA GPU (longer on the CPU; a re-render with an unchanged timeline only redoes the changed chunks)"


def parse_budget(s):
    """'90m', '1h30m', '2h', '45' (minutes), '5400s' -> seconds."""
    s = str(s).strip().lower()
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return int(float(s) * 60)
    tot, ok = 0.0, False
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([hms])", s):
        tot += float(num) * {"h": 3600, "m": 60, "s": 1}[unit]
        ok = True
    if not ok:
        raise ValueError(f"can't read the budget {s!r}: use e.g. 90m, 1h30m, 45")
    return int(tot)


def fmt_dur(sec):
    sec = int(max(0, sec))
    h, m = divmod(sec // 60, 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


def hm(t):
    return time.strftime("%H:%M", time.localtime(t))


def mmss(t):
    m, s = divmod(max(0.0, float(t)), 60)
    return f"{int(m)}:{s:05.2f}"


def rel(p, start):
    return os.path.relpath(p, start).replace("\\", "/")


def venv_python(pdir):
    py = os.path.join(STUDIO, ".venv", "Scripts" if os.name == "nt" else "bin", "python.exe" if os.name == "nt" else "python")
    return rel(py if os.path.exists(py) else sys.executable, pdir)


def fill(text, values):
    return re.sub(r"\{\{(\w+)\}\}", lambda m: str(values.get(m.group(1), "")), text)


def ddir_of(pdir):
    return os.path.join(pdir, "cache", "director")


BRIEF_LABELS = (("title", "Title"), ("occasion", "What it was"), ("when_where", "When & where"), ("group_name", "The group"),
                ("editor", "Who I am (the editor)"), ("vibe", "The vibe"), ("adventurous", "How adventurous"),
                ("style_leanings", "Styles I lean to"), ("references", "References"), ("text_amount", "How much text"),
                ("length", "Length"), ("people_notes", "The people"), ("jokes", "Inside jokes"),
                ("musts", "Must-haves"), ("avoid", "Never show / mention (a hard rule)"),
                ("credits", "Credit lines (verbatim)"), ("ending_note", "The ending"),
                ("language", "Language of the on-screen text"), ("extra", "Other"))


def user_notes(pj, seed=""):
    """The user's brief in their own words, for a brief or the story step."""
    out = []
    for k, lab in BRIEF_LABELS:
        v = pj.get(k)
        v = ", ".join(map(str, v)) if isinstance(v, list) else str(v or "").strip()
        if v:
            out.append(f"- {lab}: {v}")
    chs = [c.get("label") for c in pj.get("chapters") or [] if isinstance(c, dict) and c.get("label")]
    if chs:
        out.append(f"- The story in chapters: {' → '.join(chs)}")
    if seed.strip():
        out.append(f"- Also, for this run: {seed.strip()}")
    return "\n".join(out)


def song_of(pdir, pj):
    """(slug, the song file relative to the project, the song map) or (None, None, {})."""
    slug = song_slug(pdir, pj)
    if not slug:
        return None, None, {}
    sm = jload(os.path.join(pdir, "song", slug, "song-map.json"), {}) or {}
    f = (pj.get("song") or {}).get("file") or sm.get("file") or ""
    return slug, (f"music/{os.path.basename(f)}" if f else "the song in music/"), sm


# ------------------------------------------------------------------ the story step
def story(pdir, model=None, log=print):
    from studio import Status
    st = Status(pdir, "story", ["Claude reads the song folder and your brief", "writing the song story"])
    try:
        if not claude_bin():
            raise RuntimeError("Claude Code isn't installed (https://claude.com/claude-code)")
        pj = load_pj(pdir)
        slug, _, sm = song_of(pdir, pj)
        if not sm:
            raise RuntimeError("no song folder yet: run Analyse (ingest) first")
        title = f"{sm.get('artist')} – {sm.get('title')}" if sm.get("artist") else sm.get("title") or sm.get("file") or slug
        vibe = "4. cache/vibe.md (the vibe read of the song and the photos)\n" if os.path.exists(os.path.join(pdir, "cache", "vibe.md")) else ""
        prompt = fill(open(os.path.join(TEMPLATES, "story-prompt.md"), encoding="utf-8").read(),
                      {"notes": user_notes(pj) or "(no brief given)", "title": title, "date": time.strftime("%Y-%m-%d"),
                       "slug": slug, "vibe": vibe})
        log("Claude is reading the song folder (1-3 min)...")
        r = claude_print(prompt, pdir, model=model or (pj.get("director") or {}).get("story_model") or "sonnet",
                         tools=["Read"], timeout=1200)
        res, text = r["json"], r["text"]
        st.step(1)
        text = re.sub(r"^```(?:markdown)?\s*|\s*```\s*$", "", text.strip())
        if "# Song story" not in text or "## What it's about" not in text:
            raise RuntimeError("Claude didn't return a song story: " + (text or r["stderr"])[-400:])
        sp = os.path.join(pdir, "song", slug, "song-story.md")
        if os.path.exists(sp) and "_2–4 sentences" not in open(sp, encoding="utf-8").read():   # (keep the one before)
            os.makedirs(os.path.join(pdir, "cache", "story"), exist_ok=True)
            shutil.copyfile(sp, os.path.join(pdir, "cache", "story", f"song-story_{time.strftime('%Y%m%d-%H%M%S')}.md"))
        open(sp, "w", encoding="utf-8").write(text.strip() + "\n")
        update_project(pdir, lambda p: p.setdefault("status", {}).__setitem__(
            "story", {"by": "claude", "at": time.strftime("%Y-%m-%d %H:%M"), "cost_usd": res.get("total_cost_usd")}))
        log(f"-> {sp}")
        st.done()
    except Exception as e:
        st.done("error", str(e))
        raise


# ------------------------------------------------------------------ the clock
def current(pdir):
    return jload(os.path.join(ddir_of(pdir), "current.json"), None)


RUN_FRESH_S = 180                # a runner writes current.json every second: quiet this long, it was cut off
# a run at work: "paused" waits for Claude's usage limit to reset (its clock stopped), "waiting" is a continuing run
# that waits for it before its clock starts
ACTIVE = ("running", "finishing", "paused", "waiting")


def run_active(pdir):
    """The autonomous run going on in this project (its current.json), or None. A run whose runner stopped writing
    (its console closed, the machine slept or restarted, the process killed) is over, whatever its file says."""
    c = current(pdir)
    if not c or c.get("state") not in ACTIVE:
        return None
    try:
        fresh = time.time() - float(c.get("updated") or 0) < RUN_FRESH_S
    except (TypeError, ValueError):
        fresh = False
    return c if fresh else None


def clock(pdir):
    now = time.time()
    c = run_active(pdir)
    if not c:
        c = current(pdir)
        print("no autonomous run is going on (no time budget). " + (f"Last run: {c.get('state')}" if c else "")
              + (" (its runner stopped writing: it was cut off)" if c and c.get("state") in ACTIVE else ""))
        return
    if c.get("state") == "waiting":
        print(f"{time.strftime('%H:%M:%S')}  run {c.get('run')} waits for Claude's usage limit to reset: it starts at "
              f"{hm(c.get('waiting_until') or now)} with {fmt_dur(c.get('budget_s') or 0)}")
        return
    if c.get("state") == "paused":
        p = c.get("paused") or {}
        print(f"{time.strftime('%H:%M:%S')}  PAUSED: Claude's usage limit stopped the director at {hm(p.get('since') or now)}; "
              f"the clock is stopped at {fmt_dur(p.get('left_s') or 0)} left; it carries on at {hm(p.get('until') or now)}")
        return
    left = c["deadline"] - now
    agents = [a for a in c.get("agents") or [] if a.get("state") == "running"]
    active = now - c["started"] - float(c.get("paused_s") or 0)
    print(f"{time.strftime('%H:%M:%S')}  elapsed {fmt_dur(active)} of {fmt_dur(c['budget_s'])}; "
          f"{'LEFT ' + fmt_dur(left) if left > 0 else 'TIME IS UP: finish now'} (deadline {hm(c['deadline'])})"
          + (f"; {len(agents)} agent{'s' * (len(agents) != 1)} running" if agents else ""))


def request_stop(pdir):
    """Ask the running director to stop cleanly."""
    os.makedirs(ddir_of(pdir), exist_ok=True)
    open(os.path.join(ddir_of(pdir), "STOP"), "w").write(time.strftime("%Y-%m-%d %H:%M:%S"))


# ------------------------------------------------------------------ the cut: previews in out/
def latest_version(pdir, pj=None):
    """The version the user reviews now: project.json status.version (the last preview), else the newest EDL."""
    pj = pj if pj is not None else load_pj(pdir)
    v = (pj.get("status") or {}).get("version")
    if v and os.path.exists(os.path.join(pdir, "out", f"{v}_edl.json")):
        return v
    edls = sorted(glob.glob(os.path.join(pdir, "out", "*_edl.json")), key=os.path.getmtime)
    edls = [e for e in edls if not os.path.basename(e).startswith(("style_gallery", "sd_", "style_samples"))]
    return os.path.basename(edls[-1])[:-len("_edl.json")] if edls else None


def previews(pdir, since=0.0):
    """The previews in out/ (out/<v>_preview.mp4) changed since a time, oldest first."""
    out = []
    for f in glob.glob(os.path.join(pdir, "out", "*_preview.mp4")):
        b = os.path.basename(f)
        if b.startswith(("style_gallery", "sd_")):
            continue
        try:
            if os.path.getmtime(f) > since and os.path.getsize(f) > 0:
                out.append(f)
        except OSError:
            pass
    return sorted(out, key=os.path.getmtime)


def version_of(path):
    return re.sub(r"_preview$", "", os.path.splitext(os.path.basename(path))[0])


# ------------------------------------------------------------------ the brief
def critic_brief(critic, project, python, tools):
    """The brief's bullet on the studio's critic, after the bullet that ends in {{critic}}; "" when it is off.
    critic = (model, most critiques this run) or None."""
    if not critic:
        return ""
    return (f"\n- The studio's critic: a cheaper model ({critic[0]}) with fresh eyes looks at every preview you render "
            f"(out/<version>_preview.mp4; up to {critic[1]} critiques this run). It sees only the frames (a tile per shot "
            f"with the song and its captions), out/treatment.md, the brief, the song, QA and the caption board, not your "
            f"reasoning, and its notes arrive as a message from the studio a few minutes after the preview (ambition "
            f"first, then craft). It does the looking so your own tokens go into the film: after a preview, don't open "
            f"every sheet and still yourself; carry on with the next thing until its notes arrive, then open only the "
            f"pictures it names that you need to judge yourself (`board` and `stills` for one specific question are fine). "
            f"You're the director: take what's right, push harder where it says you played safe, ignore what's wrong, "
            f"and log what you took. For a second look at one part: `{python} {tools}/studio.py critique {project} "
            f"out/<version>_preview.mp4 --focus \"...\"` (2-4 min).")


ULTRACODE_LINE = ("\n- Ultracode is on for this run: you may orchestrate multi-agent workflows with the Workflow tool, by "
                  "the same rules (each agent its model and a narrow brief; the looking isn't theirs).")


def looking(critic, project, python, tools):
    """Who does the looking at renders, for the briefs' agents part: the critic when it's on, else the director."""
    if critic:
        return (f"The looking at previews is the critic's (`{python} {tools}/studio.py critique {project} <video>`), not the "
                f"agents': they don't open frames to judge the film.", "the looking stays the critic's")
    return ("The critic is off for this run, so the looking is yours (board, stills, the QA sheets, one question at a "
            "time), not the agents'.", "the looking stays yours")


def note_done_cmd(pdir):
    """The command a director marks a note done with (studio.py note-done: the web app writes review/notes.json too)."""
    return (f"{venv_python(pdir)} {rel(os.path.join(STUDIO, 'tools'), pdir)}/studio.py note-done {os.path.basename(pdir)} "
            f"<id> \"<what you changed>\"")


def clock_cmd(pdir):
    return f"{venv_python(pdir)} {rel(os.path.join(STUDIO, 'tools'), pdir)}/studio.py clock {os.path.basename(pdir)}"


def references(pdir):
    """The reference builders the director may read (another project's folder, read-only), as a line for the brief."""
    out = []
    for r in REFERENCE:
        d = os.path.join(PROJECTS, r)
        if os.path.isdir(d) and os.path.abspath(d) != os.path.abspath(pdir):
            for b in sorted(glob.glob(os.path.join(d, "build_*.py"))):
                out.append(rel(b, pdir))
    return (f"The studio's most complete reference builders (read-only, another project): {', '.join(out)}." if out else "")


def context_rows(pdir, notes, version=None):
    """The user's notes as lines with the context: film time · bar:beat · section · what is sung there · the shot
    there (its id, its photos, its text) · the note (and its id)."""
    from am.song import Song, FilmClock, at_film
    v = version
    edls = {}

    def edl_for(x):
        vv = str(x.get("version") or v or "")
        if vv not in edls:
            edls[vv] = jload(os.path.join(pdir, "out", f"{vv}_edl.json"), None)
        return edls[vv]
    try:
        S = Song(pdir)
    except Exception:
        S = None
    rows = []
    for nt in sorted(notes, key=lambda x: (str(x.get("version") or ""), float(x.get("t") or 0))):
        t = float(nt.get("t") or 0)
        e = edl_for(nt)
        parts = [mmss(t)]
        if S:
            try:
                s2 = Song(pdir, (e or {}).get("meta", {}).get("analysis")) if e and (e.get("meta") or {}).get("analysis") != S.slug else S
            except Exception:
                s2 = S
            a = at_film(s2, FilmClock(e), t)
            parts += [f"{a['bar']}:{a['beat']:.1f}" if a.get("bar") is not None and isinstance(a.get("beat"), (int, float)) else "-",
                      a.get("section") or "-", f"“{a['line']}”" if a.get("line") else "(no singing)"]
        sh = next((s for s in (e or {}).get("shots") or [] if s["t0"] - 1e-4 <= t < s["t1"]), None)
        if sh:
            ph = sorted({L.get("src") for L in sh.get("layers") or [] if isinstance(L.get("src"), str)})
            txt = [str(L.get("text"))[:40] for L in sh.get("layers") or [] if isinstance(L.get("text"), str)]
            parts.append(f"shot {sh['id']}" + (f" ({', '.join(ph[:3])})" if ph else "") + (f" text “{' / '.join(txt[:2])}”" if txt else ""))
        if nt.get("version") and nt.get("version") != v:
            parts.append(f"on {nt['version']}")
        rows.append("- " + " · ".join(parts) + f" · **{str(nt.get('text') or '').strip()}** (id {nt.get('id')})")
    return rows


def vetoed_lines(pdir, version):
    """The lines the user vetoed on the caption board (review/captions.json ok: false), for a review round's brief."""
    dec = jload(os.path.join(pdir, "review", "captions.json"), {}) or {}
    rows = []
    for key, d in dec.items():
        if isinstance(d, dict) and d.get("ok") is False:
            rows.append(f"- “{d.get('text') or key.split('|')[0]}”" + (f" (on {d['version']})" if d.get("version") else "")
                        + (f": {d['comment']}" if d.get("comment") else ""))
    return rows


def open_notes(pdir, version):
    """The user's review notes on this version that are still open."""
    from am.notes import read_notes
    try:
        ns = read_notes(pdir)
    except RuntimeError:
        ns = []
    return [n for n in ns if isinstance(n, dict) and not n.get("done") and str(n.get("text") or "").strip()
            and str(n.get("version") or "") == str(version)]


def build_brief(pdir, budget_s, seed_notes="", revise=False, started=None, deadline=None, critic=None, ultracode=False,
                cont_text=""):
    """The run's brief (templates/director-brief.md, or revise-brief.md for a review round). cont_text: a run that
    carries on earlier work in a fresh session (CONT_BRIEF: where the work is), after the user's brief."""
    pj = load_pj(pdir)
    slug, song_file, sm = song_of(pdir, pj)
    tools = rel(os.path.join(STUDIO, "tools"), pdir)
    name = os.path.basename(pdir)
    ph = os.path.join(pdir, "photos")
    stills = [f for f in os.listdir(ph) if f.lower().endswith((".jpg", ".jpeg"))] if os.path.isdir(ph) else []
    clips = [f for f in os.listdir(ph) if f.lower().endswith((".mp4", ".mov", ".m4v"))] if os.path.isdir(ph) else []
    cast = jload(os.path.join(pdir, "cache", "cast.json"), {}) or {}
    core = [p.get("name") for p in (cast.get("people") or {}).values() if isinstance(p, dict) and p.get("core") and p.get("name")]
    people = (f"The main cast (named on the studio's who's-who page, cache/cast.json): {', '.join(core)}." if core else
              "The faces aren't named yet (cache/cast.json): never put a name on a face you can't tell from the brief.")
    trip = ", and a Polarsteps trip in cache/trip.json (the steps, the route; my own words per step in project.json \"steps\" win)" \
        if os.path.exists(os.path.join(pdir, "cache", "trip.json")) else ""
    dr = pj.get("direction") or {}
    if dr.get("id"):
        rule = (f"I picked direction {dr['id']} in the studio (out/directions.json)" + (f", with this note: {dr['note']}" if dr.get("note") else "")
                + ": build that one, and go further with it.")
    else:
        rule = ("I haven't picked a direction: make the skill's three contrasting directions with their style frames "
                "(out/directions.json, so I can see them in the studio), then build the one you believe in most, and say "
                "which and why in the notes.")
    vals = {"song_file": song_file or "music/", "slug": slug or "<slug>", "duration": f"{float(sm.get('duration') or 0):.1f}",
            "photos": f"{len(stills)} photos" + (f" and {len(clips)} clips" if clips else ""), "trip": trip, "people": people,
            "budget": fmt_dur(budget_s), "tools": tools, "project": name, "python": venv_python(pdir),
            "started": hm(started or time.time()), "deadline": hm(deadline or time.time() + budget_s) + f" (in {fmt_dur(budget_s)})",
            "skill": rel(SKILL, pdir), "stylebook": rel(STYLEBOOK, pdir), "refs": references(pdir),
            "ultracode": ULTRACODE_LINE if ultracode else "", "direction_rule": rule, "render_time": PREVIEW_TIME,
            "note_done": note_done_cmd(pdir)}
    vals["critic"] = critic_brief(critic, name, vals["python"], tools)
    vals["looking"], vals["looking_short"] = looking(critic, name, vals["python"], tools)
    vals["previews"] = "get the studio's critic's notes on them (below)" if critic else "look at them (board, stills, the QA sheets)"
    notes = user_notes(pj, seed_notes)
    if revise:
        v = latest_version(pdir, pj)
        if not v:
            raise SystemExit("no version to review yet: make a first preview (a first run) before a review round")
        nts = open_notes(pdir, v)
        vet = vetoed_lines(pdir, v)
        if not nts and not vet:
            raise SystemExit(f"no open notes on {v}: leave notes on the Review page (press N) first, or veto lines on the "
                             f"caption board")
        vid = next((f"out/{v}{s}.mp4" for s in ("_preview", "") if os.path.exists(os.path.join(pdir, "out", f"{v}{s}.mp4"))), f"out/{v}_preview.mp4")
        vals.update(version=v, video=vid, notes="\n".join(context_rows(pdir, nts, v)) or "(none: only vetoed lines this round)",
                    captions_part=" and on the caption board" if vet else "",
                    vetoed=("\nThe lines I vetoed on the caption board (they must go, or be fixed at their source):\n" + "\n".join(vet) + "\n") if vet else "",
                    direction=(("\nMy brief (as before):\n" + notes + "\n") if notes else "") + cont_text)
        return fill(open(os.path.join(TEMPLATES, "revise-brief.md"), encoding="utf-8").read(), vals)
    vals["direction"] = (("\nMy brief:\n" + notes + "\n") if notes else "\n(I left the brief empty: it's all yours.)\n") + cont_text
    return fill(open(os.path.join(TEMPLATES, "director-brief.md"), encoding="utf-8").read(), vals)


def rule_path(p):
    """An absolute path in Claude Code's permission-rule form: //home/me/x, and on Windows //c/Users/me/x (paths are
    matched in POSIX form there). A relative rule (../../tools/**) does not match: tested with Claude Code 2.1.311."""
    q = os.path.abspath(p).replace("\\", "/")
    if re.match(r"^[A-Za-z]:", q):
        q = "/" + q[0].lower() + q[2:]
    return "/" + q


def deny_rules(pdir):
    """What a director run may not change: the studio itself, the user's photos and song, the user's review files
    (the web app writes them; the director answers notes with `studio.py note-done`), and the other projects."""
    deny = [f"Bash({c}:*)" for c in DENY_BASH]
    for d in STUDIO_DIRS:
        rp = rule_path(os.path.join(STUDIO, d))
        deny += [f"Edit({rp}/**)", f"Write({rp}/**)"]
    for d in PROJECT_RO:
        rp = rule_path(os.path.join(pdir, d))
        deny += [f"Edit({rp}/**)", f"Write({rp}/**)"]
    for parts in USER_FILES:
        rp = rule_path(os.path.join(pdir, *parts))
        deny += [f"Edit({rp})", f"Write({rp})"]
    if os.path.isdir(PROJECTS):
        for d in sorted(os.listdir(PROJECTS)):
            full = os.path.join(PROJECTS, d)
            if os.path.isdir(full) and os.path.normcase(os.path.abspath(full)) != os.path.normcase(os.path.abspath(pdir)):
                rp = rule_path(full)
                deny += [f"Edit({rp}/**)", f"Write({rp}/**)"]
    return deny


def claude_args(pdir, model, effort, ultracode=False, max_usd=None, settings_path=None, system=None, resume=None):
    """The stream-json session's command with the director's sandbox (its agents share it): the project is the
    director's (its photos, song and the user's review files aside), the studio's own folders and the other projects
    are read-only, no network. ultracode adds the Workflow tool; max_usd is a hard cap on the session's spending
    (--max-budget-usd). resume: Claude Code's session id of a conversation to carry on (--resume; the cwd must be the
    same)."""
    cl = claude_bin()
    if not cl:
        raise SystemExit("Claude Code isn't installed: https://claude.com/claude-code (or set AM_CLAUDE)")
    settings_d = {"permissions": {"deny": deny_rules(pdir) + ["WebFetch", "WebSearch"]}}
    sp = settings_path or os.path.join(ddir_of(pdir), "settings.json")      # a file, not inline JSON (cmd.exe-safe)
    os.makedirs(os.path.dirname(sp), exist_ok=True)
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(settings_d, f, indent=1)
    dirs = [os.path.join(STUDIO, "tools"), os.path.join(STUDIO, "assets"), os.path.join(STUDIO, ".claude", "skills"),
            os.path.join(STUDIO, "templates")]
    dirs += [os.path.join(PROJECTS, r) for r in REFERENCE if os.path.isdir(os.path.join(PROJECTS, r))
             and os.path.abspath(os.path.join(PROJECTS, r)) != os.path.abspath(pdir)]
    cmd = [*cl, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
           "--permission-mode", "dontAsk", "--allowedTools", *ALLOWED, *(ULTRACODE if ultracode else []),
           "--disallowedTools", *DISALLOWED, "--settings", sp, "--add-dir", *dirs,
           "--strict-mcp-config", "--append-system-prompt", system or SYSTEM_APPEND]
    if model:
        cmd += ["--model", model]
    if effort:
        cmd += ["--effort", effort]
    if max_usd:
        cmd += ["--max-budget-usd", f"{float(max_usd):g}"]
    if resume:
        cmd += ["--resume", str(resume)]
    return cmd


# ------------------------------------------------------------------ the critic during a run
CRITIC_INTRO = ("The studio's critic ({model}, fresh eyes: it saw only the frames, your treatment, the brief and the song, "
                "not your reasoning) looked at {video}. You're the director: take what's right, push harder where it says "
                "you played safe, ignore what's wrong, and note in out/director_log.md what you took and why.")


def since(at, started):
    """A critique's "at" (local time, "%Y-%m-%d %H:%M:%S") in seconds from the run's start, or None."""
    try:
        return round(time.mktime(time.strptime(str(at), "%Y-%m-%d %H:%M:%S")) - started)
    except (TypeError, ValueError, OverflowError):
        return None


class CriticWatcher:
    """The studio's critic during an autonomous run. Every ~5 s it looks at the previews in out/ (out/<v>_preview.mp4)
    changed since the run started; one is ready when its size held still over two looks and its QA report
    (cache/qa/<v>/report.md, which `studio.py preview` writes right after the render) is newer than it, or it has held
    still for QA_WAIT_S. A cut that has a critique already (critic.find: the path, size and mtime) or one being made
    (critic.is_pending: the director ran `studio.py critique` itself) isn't critiqued again (a finished one is handed
    to the runner all the same, marked "seen", for the run's record). One critique at a time, in a background thread
    (critic.py with this Python): the newest ready preview; older ones are passed over. At most `most` critiques per
    run; none when its notes couldn't reach the director in time (`min_left`), and nothing new once the run is
    stopping. Finished critiques wait in take() for the runner; the first preview passed over because the critiques
    are used up waits in passed() (the director is told once). A critique Claude's usage limit refused (the critic and
    the director share the user's plan) gives its slot back and its cut is looked at again once the limit has reset."""
    QA_WAIT_S = 240

    def __init__(self, pdir, started, model, effort, most=6, min_left=6 * 60):
        self.pdir, self.started, self.model, self.effort, self.most = pdir, started, model, effort, most
        self.min_left = min_left
        self.seen, self.handled, self.finished, self.still = {}, set(), [], {}
        self.job, self.n, self.last = None, 0, 0.0
        self.hold_until = 0.0
        self.done_at = 0.0                      # the newest cut critiqued elsewhere (its mtime)
        self.skipped, self.told = [], False
        self.lock = threading.Lock()

    @staticmethod
    def key(path):
        try:
            st = os.stat(path)
        except OSError:
            return None
        return (os.path.normcase(os.path.abspath(path)), st.st_size, st.st_mtime)

    def qa_ready(self, f, k, now):
        qa = os.path.join(self.pdir, "cache", "qa", version_of(f), "report.md")
        if os.path.exists(qa) and os.path.getmtime(qa) >= k[2]:
            return True
        return now - self.still.get(k, now) > self.QA_WAIT_S

    def elsewhere(self, f, k):
        import critic
        v = rel(f, self.pdir)
        return critic.find(self.pdir, v, k[1], k[2]) or ("coming" if critic.is_pending(self.pdir, v, k[1], k[2]) else None)

    def poll(self, now, left=None, stopping=False):
        if now - self.last < 5:
            return
        self.last = now
        ready, coming = [], [0.0]
        for f in previews(self.pdir, self.started):
            k = self.key(f)
            if not k or not k[1] or re.search(r"\.(part|tmp)\b", os.path.basename(f)):
                continue
            was, self.seen[f] = self.seen.get(f), k
            if was != k:
                self.still[k] = now
                continue
            if k in self.handled:
                continue
            there = self.elsewhere(f, k)
            if isinstance(there, dict):             # the director had it critiqued itself: it has the report
                self.handled.add(k)
                self.done_at = max(self.done_at, k[2])
                with self.lock:
                    self.finished.append(dict(there, key=k, t=since(there.get("at"), self.started), seen=True))
            elif there:
                coming.append(k[2])
            elif self.qa_ready(f, k, now):
                ready.append(k)
        if stopping or not ready or now < self.hold_until:
            return
        with self.lock:
            if self.job:
                return
            ready.sort(key=lambda k: k[2])
            cut = max(self.done_at, max(coming))
            self.handled.update(ready[:-1])          # only the newest counts
            newest = [k for k in ready[-1:] if k[2] > cut]
            self.handled.update(k for k in ready[-1:] if k[2] <= cut)
            if newest and (self.n >= self.most or (left is not None and left < self.min_left)):
                if self.n >= self.most and not self.told:
                    self.told = True
                    self.skipped.append(rel(newest[-1][0], self.pdir))
                self.handled.update(newest)
                newest = []
            if not newest:
                return
            k = newest[-1]
            self.handled.add(k)
            self.n += 1
            self.job = {"key": k, "video": rel(k[0], self.pdir), "proc": None}
            threading.Thread(target=self._run, args=(self.job,), daemon=True).start()

    def _run(self, job):
        import critic
        cmd, env = critic.command(self.pdir, job["video"], self.model, self.effort)
        out, c = "", None
        try:
            job["proc"] = subprocess.Popen(cmd, cwd=STUDIO, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                           encoding="utf-8", errors="replace",
                                           creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            if job.get("superseded"):
                kill_tree(job["proc"])
            out = job["proc"].communicate(timeout=1500)[0]
            c = critic.from_output(self.pdir, out)
        except Exception as ex:
            out += f"\n({ex})"
            if job["proc"]:
                kill_tree(job["proc"])
        tail = [x for x in out.strip().splitlines() if x.strip()][-1:] or ["no output"]
        limit = not c and is_limit(tail[0])
        with self.lock:
            if limit and not job.get("superseded"):     # its slot back; its cut again after the reset
                self.n -= 1
                self.handled.discard(job["key"])
                r = reset_at(tail[0])
                self.hold_until = max(time.time() + 60, (r + RESET_MARGIN_S) if r else time.time() + RETRY_S)
            if not job.get("superseded"):
                self.finished.append(dict(c, key=job["key"], t=round(time.time() - self.started)) if c else
                                     {"video": job["video"], "error": tail[0][:300], "cost_usd": critic.spent(out), "limit": limit})
            if self.job is job:
                self.job = None

    def take(self):
        """The critiques finished since the last call (an {"video", "error", "cost_usd"} for one that couldn't run;
        "seen": True on one the director had made itself)."""
        with self.lock:
            out, self.finished = self.finished, []
        return out

    def passed(self):
        with self.lock:
            out, self.skipped = self.skipped, []
        return out

    def pending_latest(self):
        """A critique of the newest preview of this run is running or will start (it hasn't been handled yet)."""
        ps = previews(self.pdir, self.started)
        k = self.key(ps[-1]) if ps else None
        with self.lock:
            if not k:
                return False
            if self.job and self.job["key"] == k:
                return True
            return k not in self.handled and self.n < self.most

    def stop(self, wait_key=None, timeout=900, abort=None):
        """At the end of the run: a critique of wait_key (the delivered preview) still running may finish, unless
        abort() says the user stopped; any other is stopped (with what it started)."""
        with self.lock:
            job = self.job
        if not job:
            return
        if wait_key and job["key"] == wait_key:
            t0 = time.time()
            while time.time() - t0 < timeout and self.job is job and not (abort and abort()):
                time.sleep(1)
        if self.job is job:
            for _ in range(20):
                if job["proc"]:
                    break
                time.sleep(0.5)
            if job["proc"]:
                kill_tree(job["proc"])
            t0 = time.time()
            while time.time() - t0 < 20 and self.job is job:
                time.sleep(0.5)


def critic_pictures(c, most=12):
    ps = c.get("pictures") or []
    return (f"The pictures it looked at (made already: open only the ones you need to judge yourself): "
            + ", ".join(ps[:most]) + (f" (+{len(ps) - most} more)" if len(ps) > most else "") + ".") if ps else ""


def critic_message(c, most=6000):
    rep = (c.get("report") or "").strip()
    if len(rep) > most:
        rep = rep[:most].rsplit("\n", 1)[0] + "\n[... the rest is in the file]"
    pics = critic_pictures(c)
    return CRITIC_INTRO.format(model=c.get("model") or "the critic", video=c["video"]) + \
        f" (Its report is also in {c.get('file')}.)" + (f"\n{pics}" if pics else "") + "\n\n" + rep


CRITIC_USED_UP = ("The studio's critic has used this run's critiques ({n}), so it won't look at {video} or a later "
                  "preview by itself. When you need eyes on one: `{python} {tools}/studio.py critique {project} <video> "
                  "--focus \"...\"` (2-4 min), or board / stills yourself, one question at a time.")
NUDGE_HEAD = ("You delivered a preview with {left} still on the clock: spend it making the film better, and bolder. Start "
              "where the critic says you played safe and with what it says the boldest version of your concept would do, "
              "not with polish; then its worst problems. ")
NUDGE_TAIL = ("\n\nThen build, preview (QA clean) and update the notes again. Keep the version name unless you want me to "
              "compare (the studio keeps every preview round). Never the final: it waits for my approval.")


def critic_nudge(c, left, seen=False):
    """The early-finish nudge with the critic's notes on the newest preview: its whole report, or, when the director
    has had the report already, the gist again: the ambition push, where it plays safe, the worst problems."""
    import critic
    head = NUDGE_HEAD.format(left=fmt_dur(left))
    if not seen:
        return head + "\n\n" + critic_message(c) + NUDGE_TAIL
    amb = re.sub(r"^## [^\n]*\n", "", critic.section(c.get("report") or "", "Ambition")).strip()
    safe = "\n".join(f"- {x}" for x in (c.get("safe") or [])[:5])
    probs = critic.problems_text(c, 4)
    return (head + f"You had the critic's notes on this cut ({c.get('file')}); the gist again:\n\n"
            f"Its verdict: {c.get('verdict') or '-'} ({critic.score_line(c.get('scores'))})\n"
            + (f"\nAmbition: {amb[:1500]}\n" if amb else "") + (f"\nWhere it plays safe:\n{safe}\n" if safe else "")
            + (f"\nIts worst problems:\n{probs}\n" if probs else "") + NUDGE_TAIL)


def plain_nudge(left, pdir, critic_on=False, coming=False):
    """The early-finish nudge without the critic's notes on this cut."""
    if not critic_on:
        return (f"You delivered a preview with {fmt_dur(left)} still on the clock. Spend it making the film better: look at "
                f"it again (the storyboard, stills at the signature moments, the QA cut sheets), pick the weakest parts and "
                f"improve them, then build, preview (QA clean) and update the notes again." + NUDGE_TAIL)
    tools = rel(os.path.join(STUDIO, "tools"), pdir)
    look = ("The critic's notes on this cut are on their way (they come as a message): start on what you already know is "
            "weakest meanwhile." if coming else
            f"For fresh eyes on it, ask the critic rather than opening every still yourself: `{venv_python(pdir)} {tools}/"
            f"studio.py critique {os.path.basename(pdir)} <the preview> --focus \"...\"` (2-4 min).")
    return (f"You delivered a preview with {fmt_dur(left)} still on the clock. Spend it making the film better, and bolder: "
            f"where does it play safe, which ★★★ moment doesn't change the picture's rules, what would the boldest version "
            f"of your concept do? {look}" + NUDGE_TAIL)


def run_streamed(cmd, env, log, timeout=2400, abort=None):
    """A studio tool with each line of its output passed to log as it comes, stopped with what it started at the
    timeout or when abort() says so. Returns (exit code, None when it was stopped; the output)."""
    p = subprocess.Popen(cmd, cwd=STUDIO, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace")
    t0, stopped, out = time.time(), [], []

    def guard():
        while p.poll() is None:
            if time.time() - t0 > timeout or (abort and abort()):
                stopped.append(1)
                kill_tree(p)
                return
            time.sleep(1)
    threading.Thread(target=guard, daemon=True).start()
    try:
        for line in p.stdout:
            out.append(line)
            log(line.rstrip())
        p.wait()
    except BaseException:
        kill_tree(p)
        raise
    return (None if stopped else p.returncode), "".join(out)


def logged_critiques(pdir, since_t):
    """The critic's log lines (review/critic/log.jsonl) written since a time: every critic.py run, the director's own
    ones and the ones that couldn't answer included (those with their cost)."""
    t0 = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(since_t))
    out = []
    try:
        for ln in open(os.path.join(pdir, "review", "critic", "log.jsonl"), encoding="utf-8").read().splitlines():
            try:
                d = json.loads(ln)
            except Exception:
                continue
            if isinstance(d, dict) and str(d.get("at") or "") >= t0:
                out.append(d)
    except OSError:
        pass
    return out


# ------------------------------------------------------------------ the user's notes during a run
NOTES_MSG = ("The user watched a preview in the studio (with sound: they can hear; you can't) and left {what} (film time "
             "· bar:beat · section · what is sung there · the shot there · the note):\n{rows}\n"
             "Treat {them}: find the root cause and fix the film, not the frame. Where a note asks for more, go further "
             "than it asks; never answer one by making the film safer. Mark each one done with a one-line fix, what you "
             "changed: `{done}` (not by editing review/notes.json: the user may be adding notes to it right now). Then "
             "carry on; the next preview shows them your fix.")


class UserNotes:
    """The user's notes from the studio's Review page during a run (review/notes.json): the ones made after the run
    started, not done and not forwarded yet. Every ~5 s the runner sends them to the director when a message can go,
    with the song and shot context, and marks them "forwarded_run": n (am/notes.update_notes)."""

    def __init__(self, pdir, n, started):
        self.pdir, self.n, self.started = pdir, n, started
        self.t = 0.0
        from am.notes import read_notes
        try:                                     # the notes there when the run starts: its brief has them already
            self.before = {x.get("id") for x in read_notes(pdir) if isinstance(x, dict)}
        except RuntimeError:
            self.before = set()

    def made_in_run(self, x):
        try:
            return float(x.get("id") or 0) / 1000 >= self.started - 1          # (its id is when it was made, in ms)
        except (TypeError, ValueError):
            return False

    def pending(self):
        from am.notes import read_notes
        try:
            notes = read_notes(self.pdir)
        except RuntimeError:                     # being written, or broken: next time
            return []
        return [x for x in notes if isinstance(x, dict) and not x.get("done") and not x.get("forwarded_run")
                and str(x.get("text") or "").strip() and x.get("id") not in self.before and self.made_in_run(x)]

    def mark(self, notes, undo=False):
        from am.notes import update_notes
        ids, at = {x.get("id") for x in notes}, time.strftime("%Y-%m-%d %H:%M:%S")

        def fn(ns):
            for x in ns:
                if isinstance(x, dict) and x.get("id") in ids:
                    if undo:
                        x.pop("forwarded_run", None)
                        x.pop("forwarded_at", None)
                    else:
                        x.update(forwarded_run=self.n, forwarded_at=at)
        update_notes(self.pdir, fn)


# ------------------------------------------------------------------ the autonomous run
HUNG_S = 25 * 60                 # working with no events this long: said in the live log (a long command makes none either)
STOP_MSG = ("The user stopped this run. Stop now: don't start anything new, and stop any agent of yours that is still "
            "running (TaskStop). If a preview exists, make sure out/<version>_notes.md is written (a few lines are fine) "
            "and end.")
MAX_WAIT_S = 24 * 3600           # a reset further off than this isn't waited for: the run ends (continue it then)
RESET_MARGIN_S = 60              # carry on this long after the reset it gives (the message says it to the minute)
RETRY_S = 15 * 60                # it gives no reset (or the limit still holds past it): try again this often
RESUME_WAIT_S = 60               # claude --resume: a process that ends before its first turn couldn't resume it
CONTINUE_MIN_S = 15 * 60         # a continuing run gets at least this much by default
RESUME_MSG = ("Claude's usage limit stopped you at {at}; it has reset now ({waited} later): carry on where you were. The "
              "run's clock was stopped while you waited, so you still have {left}, and the deadline is now **{dl}** "
              "(`{clock}` prints the time left). An agent of yours that was running then was stopped by the limit, and a "
              "background command may have finished meanwhile: check what each left before you start it again, and "
              "don't redo what's done.")
CONTINUE_MSG = ("The studio again. Your run {prev} ended at {at}: {why}. This is run {n}, and it carries on from there in "
                "this same conversation, so what you knew then is still yours. Anything that was running when it ended "
                "(an agent of yours, a render, a background command) was stopped: check what each left on disk before you "
                "start it again, and don't redo what's done.\n\n"
                "The new clock: you have {budget}; the deadline is **{deadline}** (`{clock}` prints the time left). The "
                "studio messages you as time runs down, as before, and stops the session a few minutes after the "
                "deadline. {critic}\n{notes}\nCarry on where you were: say in one line where you pick up, then deliver "
                "a preview (`studio.py preview`, QA clean) and its notes before the deadline. Never the final.")
CONT_BRIEF = ("\nThis carries on {what}. Everything made so far is in this folder: your log (out/director_log.md), the "
              "treatment, the builder, the EDLs, the previews and their notes, the critic's notes (review/critic/). Don't "
              "start over: read out/director_log.md first and look at what's there, then carry on from where it stopped "
              "(say in one line where you pick up). Keep its direction unless it really doesn't work. Anything that was "
              "running then (an agent, a render) was stopped.\n")


def is_limit(text):
    """Claude Code's own words for its usage limit (am/session.py LIMIT_RE), not a temporary server throttle."""
    return bool(LIMIT_RE.search(str(text or "")) and not NOT_LIMIT_RE.search(str(text or "")))


class Runner:
    """One autonomous run around one Claude Code session (am/session.py): the director, with full reign. It makes the
    film, and deploys agents if it wants to (they run in its session, in the background); the critic watcher looks at
    its previews. cache/director/run-N/ has brief.md, command.json, events.jsonl, stderr.log, messages.md and
    status.json (cache/director/current.json for `clock` and `stop`). The runner keeps the time warnings, STOP, the
    deadline + grace, the cost cap, the early-finish nudge and the "no preview yet" reminder (only when the director's
    turn is over and none of its agents is running), and the end: the run settings in the notes and project.json, the
    critic's notes on the delivered preview.
    Claude's usage limit: with auto_continue the run pauses ("paused": its clock stopped, nothing sent, the critic and
    the user's notes held) until the limit has reset, then carries on: a message to the same session, or, when that
    session ended meanwhile, a new process of its conversation (claude --resume, through new_session; when that can't
    be resumed, a fresh session with fallback(why), a brief that says where the work is). A reset more than MAX_WAIT_S
    away isn't waited for. Without auto_continue (or too far) the run ends there, and cut_off says when, why and how
    much of the budget was left (`direct --continue` carries it on)."""

    def __init__(self, pdir, n, rdir, status, session, budget_s, started, nudge=True, critic=None, st=None, log=print,
                 auto_continue=False, new_session=None, fallback=None):
        self.pdir, self.n, self.rdir, self.status, self.s = pdir, n, rdir, status, session
        self.ddir = ddir_of(pdir)
        self.budget_s, self.started, self.deadline = budget_s, started, started + budget_s
        self.nudge, self.st, self.log = nudge, st, log
        self.lock = session.lock if session else threading.RLock()
        self.auto, self.new_session, self.fallback = bool(auto_continue), new_session, fallback
        self.pause = None
        self.paused_s = 0.0
        self.limits_seen = 0
        self.cut = None
        status.setdefault("pauses", [])
        self.use_critic = bool(critic)
        self.critic_model = critic["model"] if critic else "off"
        self.critic_effort = critic.get("effort") if critic else None
        self.critic_max = critic.get("max", 6) if critic else 0
        self.critics = CriticWatcher(pdir, started, self.critic_model, self.critic_effort, self.critic_max) if critic else None
        self.warned = set()
        self.nudges = self.reminders = 0
        self.grace = min(600, max(180, int(0.1 * budget_s)))
        self.stop_reason = None
        self.unsent = []
        self.wait_t0 = None
        self.hung_said = False
        self.capped = False
        self.end_reason = "the director ended the session"
        self.notes = UserNotes(pdir, n, started)

    def newest(self):
        """The newest preview of this run (out/<v>_preview.mp4), or None."""
        ps = previews(self.pdir, self.started)
        return ps[-1] if ps else None

    # ------------------------------------------------------------------ bookkeeping
    def save(self):
        status = self.status
        now = time.time()
        status["updated"] = now
        status["elapsed_s"] = round(now - self.started)
        status["active_s"] = round(self.active(now))
        nw = self.newest()
        status["preview"] = rel(nw, self.pdir) if nw else None
        jsave(os.path.join(self.rdir, "status.json"), status)
        jsave(os.path.join(self.ddir, "current.json"), {k: v for k, v in status.items() if k != "events"} | {"dir": rel(self.rdir, self.pdir)})

    def note(self, line):
        if self.s is not None:
            self.s.note(line)
        else:
            self.status.setdefault("events", []).append({"t": round(time.time() - self.started), "text": line})

    def send(self, text, why):
        return self.s.send(text, why)

    def active(self, now):
        return now - self.started - self.paused_s - (now - self.pause["since"] if self.pause else 0)

    def left(self, now):
        return self.deadline - (self.pause["since"] if self.pause else now)

    def record(self, c, used="waiting"):
        import critic as crit
        with self.lock:
            self.status["critic_cost_usd"] = round(self.status["critic_cost_usd"] + (c.get("cost_usd") or 0), 4)
            if c.get("error"):
                self.status["critic_failed"] = self.status.get("critic_failed", 0) + 1
                self.note(f"🔍 the critic couldn't look at {c['video']}: {c['error']}"
                          + (" (Claude's usage limit: it looks again once the limit has reset)" if c.get("limit") else ""))
                return
            self.status["critiques"].append({k: c.get(k) for k in ("t", "video", "version", "scores", "verdict", "file", "cost_usd", "model")}
                                            | {"used": used})
            self.note(f"🔍 critic on {c['video']}: {crit.score_line(c.get('scores'))}")

    def used(self, c, how):
        with self.lock:
            for x in self.status["critiques"]:
                if x.get("file") == c.get("file"):
                    x["used"] = how

    # ------------------------------------------------------------------ the loop
    def loop(self):
        while True:
            time.sleep(1)
            now = time.time()
            try:
                with self.lock:
                    self.save()
            except Exception as ex:
                self.trouble("saving the run's status", ex)
            try:
                self.notes_step(now)
            except Exception as ex:
                self.trouble("passing on the user's notes", ex)
            try:
                if not self.step(now):
                    break
            except Exception as ex:
                self.trouble("a step of the run", ex)
                if now > self.deadline + self.grace + (now - self.pause["since"] if self.pause else 0):
                    self.stop_reason = self.stop_reason or "budget ran out (deadline + grace)"
                    break

    def trouble(self, what, ex):
        import traceback
        try:
            with open(os.path.join(self.rdir, "runner_errors.log"), "a", encoding="utf-8") as f:
                f.write(f"\n{time.strftime('%H:%M:%S')} {what}:\n{traceback.format_exc()}")
        except OSError:
            pass
        if time.time() - getattr(self, "t_trouble", 0) > 60:
            self.t_trouble = time.time()
            self.note(f"⚠ the studio hit an error in {what}: {type(ex).__name__}: {ex} (cache/director/run-{self.n}/runner_errors.log); "
                      f"it carries on")

    # ------------------------------------------------------------------ the user's notes
    def notes_step(self, now):
        U = self.notes
        if now - U.t < 5:
            return
        U.t = now
        notes = U.pending()
        if not notes or not self.may_send(now):
            return
        many = len(notes) > 1
        U.mark(notes)                            # first: the director may read the file as soon as the message is in
        if not self.send(self.notes_message(notes), f"the user's note{'s' if many else ''} ({len(notes)})"):
            U.mark(notes, undo=True)
        else:
            self.note(f"📝 the user's note{'s' if many else ''} to the {self.s.name}: " + "; ".join(
                f"{mmss(float(x.get('t') or 0))} {str(x.get('text') or '')[:70]}" for x in notes))

    def may_send(self, now):
        s = self.s
        return s.alive() and not s.closed and self.stop_reason is None and self.pause is None and self.deadline - now > 120

    def notes_message(self, notes):
        n = len(notes)
        return NOTES_MSG.format(what="a note" if n == 1 else f"{n} notes", rows="\n".join(context_rows(self.pdir, notes)),
                                them="it like a review note" if n == 1 else "them like review notes", done=note_done_cmd(self.pdir))

    # ------------------------------------------------------------------ every second
    def check_stop(self, now):
        if self.stop_reason is None and os.path.exists(os.path.join(self.ddir, "STOP")):
            self.stop_reason = "stopped by the user"
            self.cut = self.cut or {"why": "stopped", "at": now, "left_s": round(self.left(now))}
            if not self.pause:
                self.send(STOP_MSG, "stop")
            self.deadline = min(self.deadline, now)
            self.grace = 60

    def check_cap(self, now):
        if not self.capped and self.status.get("budget_hit"):
            self.capped = True
            self.stop_reason = self.stop_reason or f"the cost cap (${float(self.status.get('max_usd') or 0):g}) was reached"
            self.cut = self.cut or {"why": "cost cap", "at": now, "left_s": round(self.left(now))}
            self.deadline = min(self.deadline, now)
            self.grace = 60
            self.warned.add("up")

    # ------------------------------------------------------------------ Claude's usage limit
    def check_limit(self, now):
        hits = int(self.status.get("limit_hits") or 0)
        if hits <= self.limits_seen:
            return
        self.limits_seen = hits
        lim = dict(self.status.get("limit") or {})
        r = lim.get("resets_at")
        if self.pause:
            if r and r > (self.pause.get("resets_at") or 0):
                self.pause.update(resets_at=r, retry_at=max(self.pause["retry_at"], r + RESET_MARGIN_S))
                self.status["paused"].update(resets_at=r, until=self.pause["retry_at"])
            return
        left = self.deadline - now
        if self.stop_reason is not None or left <= 60:
            return
        far = r is not None and r - now > MAX_WAIT_S
        if self.auto and not far:
            return self.start_pause(now, lim)
        self.stop_reason = ("Claude's usage limit was reached" + (f" (it resets {when(r, now)})" if r else "")
                            + ("; the reset is more than a day away, too far to wait for" if self.auto else ""))
        self.cut = {"why": "limit", "at": now, "left_s": round(left), "resets_at": r, "text": lim.get("text")}
        self.deadline, self.grace = now, 60
        self.warned.add("up")
        self.status["state"] = "finishing"
        self.note(f"⛔ the run ends here with {fmt_dur(left)} of its budget left: Claude can't work until the limit "
                  f"resets. Continue the last run (the Direct page, or `studio.py direct {os.path.basename(self.pdir)} "
                  f"--continue`) carries it on from where it stopped, in the same conversation")

    def start_pause(self, now, lim):
        r = lim.get("resets_at")
        retry = r + RESET_MARGIN_S if r and r + RESET_MARGIN_S > now else now + (RETRY_S if not r else RETRY_S // 3)
        left = self.deadline - now
        self.pause = {"since": now, "resets_at": r, "retry_at": retry, "text": lim.get("text"), "left_s": round(left), "tries": 1}
        self.status["state"] = "paused"
        self.status["paused"] = {"since": now, "resets_at": r, "until": retry, "left_s": round(left), "text": lim.get("text")}
        self.note(f"⏸ the run waits for the limit to reset, its clock stopped at {fmt_dur(left)} left; it carries on by "
                  f"itself at {when(retry, now)}" + ("" if r else f" (no reset time given: it tries every {RETRY_S // 60} min)"))

    def paused_step(self, now):
        p = self.pause
        if self.stop_reason is not None:
            self.unpause(now, "stopped")
            return False
        if self.critics:
            for c in self.critics.take():
                self.record(c, "the director ran it" if c.get("seen") else "waiting")
                if not c.get("error") and not c.get("seen"):
                    self.unsent.append(c)
        if now - p["since"] > MAX_WAIT_S + 3600:
            self.cut = {"why": "limit", "at": p["since"], "left_s": p["left_s"], "resets_at": None, "text": p["text"]}
            self.unpause(now, "gave up")
            self.stop_reason = "Claude's usage limit still held after a day of waiting"
            self.deadline, self.grace = now, 60
            self.warned.add("up")
            return self.s.alive()
        if now < p["retry_at"]:
            return True
        self.unpause(now, "carried on")
        self.carry_on(now, p)
        return True

    def unpause(self, now, how):
        p, waited = self.pause, now - self.pause["since"]
        self.pause = None
        self.paused_s += waited
        if how == "carried on":
            self.deadline += waited
        with self.lock:
            self.status.update(state="running" if how == "carried on" else "finishing", deadline=self.deadline,
                               paused_s=round(self.paused_s))
            self.status.pop("paused", None)
            self.status["pauses"].append({"t": round(p["since"] - self.started), "s": round(waited), "resets_at": p["resets_at"],
                                          "text": p["text"], "end": how})

    def carry_on(self, now, p):
        left = self.deadline - now
        msg = RESUME_MSG.format(at=hm(p["since"]), waited=fmt_dur(now - p["since"]), left=fmt_dur(left),
                                dl=hm(self.deadline), clock=clock_cmd(self.pdir))
        why = "the usage limit reset: carry on"
        s = self.s
        if s.alive() and not s.closed:
            s.ack()
            if self.send(msg, why):
                self.note(f"▶ the usage limit has reset: the director carries on ({fmt_dur(left)} left, deadline now {hm(self.deadline)})")
                return
        sid = self.status.get("session_id")
        fb = (lambda: self.fallback(f"this run (run {self.n}): Claude's usage limit stopped its director at "
                                    f"{hm(p['since'])}, and its conversation couldn't be brought back",
                                    self.deadline - time.time(), self.deadline)) if self.fallback else None
        self.note("▶ the usage limit has reset; the director's session had ended meanwhile: the studio "
                  + ("resumes its conversation" if sid else "starts a fresh one, told where the work is"))
        ok = self.launch(msg, why, resume=sid, fallback=fb) if sid else \
            bool(fb) and self.launch(fb(), "the brief (a fresh session: there was no conversation to resume)")
        if not ok:
            self.stop_reason = self.stop_reason or "the director's session couldn't be started again after the usage limit"

    def launch(self, text, why, resume=None, fallback=None):
        """A new director session for this run (new_session), `text` its first message: with resume, a new process of
        that conversation (claude --resume <id>). One that ends before its first turn couldn't be resumed: then a
        fresh session with fallback() (a brief that says where the work is), if there is one."""
        if not self.new_session:
            return False
        for rid in ([resume] if resume else []) + [None]:
            first = text if rid or not resume else (fallback() if fallback else None)
            if first is None:
                return False
            s = self.new_session(rid)
            try:
                s.start()
            except Exception as ex:
                self.note(f"⚠ Claude Code couldn't start: {type(ex).__name__}: {ex}")
                return False
            old, self.s, self.lock = self.s, s, s.lock
            if old is not None and old is not s:
                try:
                    old.finish()
                except Exception:
                    pass
            if rid is None and resume:
                open(os.path.join(self.rdir, "brief.md"), "w", encoding="utf-8").write(first)
            s.send(first, why if rid or not resume else "the brief (a fresh session: the conversation couldn't be resumed)")
            if not rid:
                return True
            t0 = time.time()
            while time.time() - t0 < RESUME_WAIT_S and s.alive() and not s.inits:
                time.sleep(0.5)
                try:
                    with self.lock:
                        self.save()
                except Exception:
                    pass
            if s.inits or s.alive():
                return True
            err = ""
            try:
                err = [x for x in open(os.path.join(self.rdir, "stderr.log"), encoding="utf-8", errors="replace").read().splitlines()
                       if x.strip()][-1][:200]
            except (OSError, IndexError):
                pass
            self.note(f"⚠ Claude Code couldn't resume the conversation{(': ' + err) if err else ''}"
                      + (": a fresh session instead, its brief says where the work is" if fallback else ""))
        return False

    def check_hung(self, now):
        if not self.hung_said and self.s.hung(now, HUNG_S):
            self.hung_said = True
            self.note(f"⚠ no sign of life from the {self.s.name} or its agents for {HUNG_S // 60} min (a long command, or a "
                      f"hang: the deadline ends it either way)")
        elif self.hung_said and not self.s.working:
            self.hung_said = False

    def warnings(self, now, left):
        if "half" not in self.warned and self.active(now) >= 0.5 * self.budget_s and left > 0:
            self.warned.add("half")
            self.send(f"Half of your time is gone ({fmt_dur(left)} left, deadline {hm(self.deadline)}). Check your plan "
                      f"against the clock.", "half")
        last_at = max(10 * 60, 0.2 * self.budget_s)
        if "last" not in self.warned and left <= last_at and left > 5 * 60:
            self.warned.add("last")
            self.send(f"{fmt_dur(left)} left. If the last preview isn't rendering yet, build and start it now "
                      f"(`studio.py preview`: the render, then QA), then write out/<version>_notes.md.", "last-preview time")
        if "five" not in self.warned and 0 < left <= 5 * 60:
            self.warned.add("five")
            self.send("5 minutes left: finish the preview, check its QA, write the notes. Nothing new.", "5 minutes")
        if "up" not in self.warned and left <= 0:
            self.warned.add("up")
            self.status["state"] = "finishing"
            self.send(f"Time is up. Stop working on the film now, and stop any agent of yours that is still running "
                      f"(TaskStop). If a preview exists, make sure out/<version>_notes.md is written (a few lines are fine) "
                      f"and end. You have {fmt_dur(self.grace)} before the session is closed.", "time's up")

    def step(self, now):
        """One second of the run: the director makes the film (with agents if it wants); the studio warns, reminds,
        nudges, and passes on the critic's notes. Decisions wait for the director's turn to end with none of its
        agents running."""
        import critic as crit
        left = self.deadline - now
        self.check_stop(now)
        self.check_cap(now)
        self.check_limit(now)
        if self.pause:
            return self.paused_step(now)
        if self.capped or (self.cut or {}).get("why") == "limit":
            self.status["state"] = "finishing"
            left = min(left, self.deadline - now)
        else:
            self.warnings(now, left)
        if left <= -self.grace:
            self.stop_reason = self.stop_reason or "budget ran out (deadline + grace)"
            return False
        self.check_hung(now)
        s, critics = self.s, self.critics
        if critics:
            critics.poll(now, left, stopping=self.stop_reason is not None)
            for c in critics.take():
                self.record(c, "the director ran it" if c.get("seen") else "waiting")
                if not c.get("error") and not c.get("seen"):
                    self.unsent.append(c)
            for v in critics.passed():
                self.note(f"🔍 the critic passes over {v}: its critiques for this run are used up")
                if not s.closed and left > 120 and self.stop_reason is None and s.alive():
                    self.send(CRITIC_USED_UP.format(n=critics.n, video=v, python=venv_python(self.pdir),
                                                    tools=rel(os.path.join(STUDIO, "tools"), self.pdir),
                                                    project=os.path.basename(self.pdir)), "critic: no more previews")
        if s.turn_over(now) and not s.closed:
            nw = self.newest()
            nkey = CriticWatcher.key(nw) if nw else None
            new_c = next((c for c in self.unsent if c.get("key") == nkey), None)
            if critics and nw and new_c is None and left > 120 and self.stop_reason is None and \
                    critics.pending_latest() and now - (self.wait_t0 or now) < 240:
                if self.wait_t0 is None:                          # the next message carries the critic's notes
                    self.wait_t0 = now
                    self.note("… waiting for the critic's notes on the newest preview (up to 4 min)")
            else:
                self.wait_t0 = None
                s.ack()
                if self.stop_reason is not None:
                    s.close_input()
                elif left > 60 and not nw and self.reminders < 3:
                    self.reminders += 1
                    self.send(f"There is no preview from this run yet and {fmt_dur(left)} are left. Carry on and deliver one "
                              f"(`studio.py preview {os.path.basename(self.pdir)} <version>`, QA clean, then the notes).",
                              "no preview yet")
                elif self.nudge and nw and left > max(6 * 60, 0.12 * self.budget_s) and self.nudges < 3:
                    self.nudges += 1
                    had = crit.find(self.pdir, rel(nw, self.pdir), nkey[1], nkey[2]) if critics and not new_c else None
                    had = crit.load(self.pdir, had["file"]) if had else None
                    if new_c:
                        self.unsent.remove(new_c)
                        self.send(critic_nudge(new_c, left), "use the time left, with the critic's notes")
                        self.used(new_c, "in the nudge")
                    elif had:
                        self.send(critic_nudge(had, left, seen=True), "use the time left, with the critic's notes")
                    else:
                        self.send(plain_nudge(left, self.pdir, bool(critics), bool(critics) and critics.pending_latest()),
                                  "use the time left")
                elif new_c and left > 120:
                    self.unsent.remove(new_c)
                    self.send(critic_message(new_c), f"critic: {new_c['video']}")
                    self.used(new_c, "sent")
                else:
                    s.close_input()
        for c in list(self.unsent):                                # the critic's other notes go in as they come
            self.unsent.remove(c)
            if not s.closed and left > 120 and self.stop_reason is None and s.alive():
                self.send(critic_message(c), f"critic: {c['video']}")
                self.used(c, "sent")
            else:
                self.used(c, "too late for the director")
        return s.alive()

    # ------------------------------------------------------------------ the end
    def end(self):
        s, status = self.s, self.status
        if self.pause:
            self.unpause(time.time(), "ended")
        if s is not None and s.alive():
            s.stop(self.stop_reason or "the run ended")
        user_stop = bool(self.stop_reason and "user" in self.stop_reason)
        if s is not None:
            s.finish()
        now = time.time()
        wall = now - self.started
        status["wall_s"] = round(wall)
        status["active_s"] = round(self.active(now))
        status["state"] = "stopped" if user_stop else "done"
        status["stop_reason"] = self.stop_reason or self.end_reason
        status["exit_code"] = s.returncode if s is not None else None
        nw = self.newest()
        if not self.cut and self.deadline - now > 120 and not nw:
            self.cut = {"why": "ended", "at": now, "left_s": round(self.deadline - now)}
        status["cut_off"] = self.cut
        status["left_s"] = round(max(0, self.cut["left_s"] if self.cut else self.deadline - now))
        if self.st:
            self.st.step(1)
        v = version_of(nw) if nw else None
        status["version"] = v
        status["preview"] = rel(nw, self.pdir) if nw else None
        status["result"] = "preview" if nw else "no preview"
        if not nw:
            self.note("no new preview from this run")
            if not user_stop:
                status["stop_reason"] = f"{status['stop_reason']}, without a new preview"
        self.keep_record(v)
        if self.use_critic:
            try:
                self.critic_after(nw, user_stop)
            except BaseException:
                if self.critics:
                    self.critics.stop()
                raise
            self.keep_record(v)
        if self.st:
            self.st.done("done" if nw else "error", "" if nw else "the run ended without a new preview")
        agents = status.get("agents") or []
        self.log(f"director run {self.n} ended: {status['stop_reason']}; wall {fmt_dur(wall)}; cost ${status['cost_usd']:.2f}"
                 + (f" ({len(agents)} agent{'s' * (len(agents) != 1)} included)" if agents else "")
                 + (f" + critic ${status['critic_cost_usd']:.2f} ({len(status['critiques'])} critiques)" if self.use_critic else "")
                 + f"; preview {status['preview'] or 'none'}")
        return status

    RUN_KEYS = ("run", "kind", "model", "model_used", "effort", "ultracode", "max_usd", "budget_hit", "budget", "wall_s",
                "cost_usd", "turns", "version", "preview", "result", "stop_reason", "claude_version", "critic_model",
                "critic_cost_usd", "auto_continue", "paused_s", "left_s", "continues")

    def keep_record(self, v):
        """The run settings in out/<version>_notes.md, status.json, current.json, project.json "runs" (and the stage)."""
        status = self.status
        append_settings(self.pdir, status, v)
        with self.lock:
            self.save()
        entry = {k: status.get(k) for k in self.RUN_KEYS} | {
            "agents": len(status.get("agents") or []), "costs": model_costs(status),
            "critiques": len(status["critiques"]), "at": time.strftime("%Y-%m-%d %H:%M", time.localtime(self.started))}

        def fn(pj):
            runs = pj.setdefault("runs", [])
            if runs and runs[-1].get("run") == self.n and runs[-1].get("at") == entry["at"]:
                runs[-1] = entry
            else:
                runs.append(entry)
        update_project(self.pdir, fn)

    def critic_after(self, nw, user_stop):
        """A critique of the delivered preview still running may finish; one that never started is made now (unless the
        user stopped), so the Review page has the critic's notes on the cut the user watches; the critic's log adds what
        the director asked of it itself, and every cost."""
        status, pdir = self.status, self.pdir
        stopping = lambda: os.path.exists(os.path.join(self.ddir, "STOP"))      # noqa: E731
        if nw and self.st:
            self.st.step(2)
        if self.critics:
            self.critics.stop(wait_key=None if user_stop or not nw else CriticWatcher.key(nw), abort=stopping)
            for c in self.critics.take():
                self.record(c, "the director ran it" if c.get("seen") else "after the run")
        if nw and not user_stop and not stopping():
            import critic
            k = CriticWatcher.key(nw)
            have = critic.find(pdir, rel(nw, pdir), k[1], k[2]) if k else None
            if have:
                status["version_critique"] = have["file"]
                status["version_scores"] = have.get("scores")
            elif k:
                cmd, env = critic.command(pdir, rel(nw, pdir), self.critic_model, self.critic_effort)
                self.log(f"the critic is looking at {rel(nw, pdir)} (2-4 min)...")
                rc, out = run_streamed(cmd, env, self.log, timeout=2400, abort=stopping)
                c = critic.from_output(pdir, out) if rc == 0 else None
                if c:
                    status["version_critique"] = c["file"]
                    status["version_scores"] = c.get("scores")
                    self.record(dict(c, t=round(time.time() - self.started)), "after the run")
                else:
                    self.note(f"🔍 the critic couldn't look at {rel(nw, pdir)}" + (" (stopped)" if rc is None else ""))
        if stopping() and not user_stop:
            self.note("🔍 the critic's last look was stopped by the user")
        logged = logged_critiques(pdir, self.started)
        known = {x.get("file") for x in status["critiques"]}
        for d in logged:
            if d.get("file") and d["file"] not in known:
                status["critiques"].append({k: d.get(k) for k in ("video", "version", "scores", "verdict", "file", "cost_usd", "model")}
                                           | {"t": since(d.get("at"), self.started), "used": "the director ran it"})
        status["critic_cost_usd"] = round(max(status["critic_cost_usd"], sum(d.get("cost_usd") or 0 for d in logged)), 4)


def last_run(pdir):
    """The latest director run that started (cache/director/run-N/status.json, the newest first): not a dry run, not a
    continuing run that never started. None when there is none."""
    d = ddir_of(pdir)
    try:
        ns = sorted((int(x.split("-")[1]) for x in os.listdir(d) if re.fullmatch(r"run-\d+", x)), reverse=True)
    except OSError:
        return None
    for k in ns:
        st = jload(os.path.join(d, f"run-{k}", "status.json"), None)
        if isinstance(st, dict) and st.get("state") not in ("dry-run", "waiting") and st.get("result") != "not started":
            return dict(st, dir=f"cache/director/run-{k}")
    return None


def continuable(pdir, now=None):
    """The last run, for "Continue the last run" (the Direct page, `direct --continue`), or None when there is none or
    one is going on: {run, kind, state, why, ended, left_s, budget_s (what a continuing run gets by default: what it
    had left, at least CONTINUE_MIN_S), resets_at (the reset of the usage limit that stopped it, still to come), limit,
    cut (it ended early, or without a preview), resumable (Claude Code's session id is known), session_id,
    conv_cost_usd, conv_usage, version, dir}. A run whose runner was cut off counts with what its clock said last."""
    now = now or time.time()
    st = last_run(pdir)
    if not st or run_active(pdir):
        return None
    stale = st.get("state") in ACTIVE
    left = st.get("left_s")
    if left is None:
        act = st.get("active_s")
        act = act if act is not None else float(st.get("elapsed_s") or 0) - float(st.get("paused_s") or 0)
        left = max(0.0, float(st.get("budget_s") or 0) - float(act))
    cut = st.get("cut_off") or {}
    p = (st.get("paused") or {}) if stale else {}
    r = cut.get("resets_at") if cut.get("why") == "limit" else p.get("resets_at")
    why = st.get("stop_reason") or ("its runner stopped (the console closed, or the machine slept or restarted)" if stale
                                    else "it ended")
    return {"run": st.get("run"), "kind": st.get("kind"), "state": st.get("state"), "why": why,
            "ended": float(st.get("updated") or 0) if stale else float(st.get("started") or 0) + float(st.get("wall_s") or st.get("elapsed_s") or 0),
            "left_s": round(left), "budget_s": max(CONTINUE_MIN_S, -(-int(left) // 60) * 60),
            "resets_at": r if r and r > now else None, "limit": cut.get("why") == "limit" or bool(p),
            "cut": bool(cut) or stale or st.get("result") == "no preview", "resumable": bool(st.get("session_id")),
            "session_id": st.get("session_id"), "conv_cost_usd": st.get("conv_cost_usd", st.get("cost_usd")),
            "conv_usage": st.get("conv_usage", st.get("model_usage")), "version": st.get("version"), "dir": st.get("dir")}


def wait_for_reset(pdir, rdir, status, until, log=print):
    """A continuing run, before its clock starts: it waits until Claude's usage limit has reset (state "waiting":
    current.json kept fresh, so the web app and `clock` see it and no second run starts over it). True when it's time;
    False when the user stopped it (STOP)."""
    d = ddir_of(pdir)
    line = f"⏳ waiting for Claude's usage limit to reset: run {status['run']} starts at {when(until)}, with {status['budget']}"
    status.setdefault("events", []).append({"t": 0, "text": line})
    log(line)
    while True:
        now = time.time()
        status["updated"] = now
        try:
            jsave(os.path.join(rdir, "status.json"), status)
            jsave(os.path.join(d, "current.json"), {k: v for k, v in status.items() if k != "events"} | {"dir": rel(rdir, pdir)})
        except Exception:
            pass
        if os.path.exists(os.path.join(d, "STOP")):
            return False
        if now >= until:
            return True
        time.sleep(max(0.05, min(2.0, until - now)))


def continue_message(pdir, n, prev, budget_s, deadline, critic, seed_notes=""):
    """The first message of a run that carries on the last one in its own conversation (claude --resume)."""
    crit_line = (f"The studio's critic ({critic[0]}) is on: it looks at every preview you render (up to {critic[1]} "
                 f"critiques this run), and its notes come as messages, as before."
                 if critic else "The studio's critic is off this run: look at your previews yourself.")
    U = UserNotes(pdir, n, prev.get("ended") or 0)
    U.before = set()                             # (the notes left since that run ended: they go into this message)
    pend = [x for x in U.pending()]
    notes = (f"\nMy notes for this run: {seed_notes.strip()}\n" if seed_notes.strip() else "")
    if pend:
        notes += ("\nNotes I left in the studio since then (treat them like review notes; mark each done with "
                  f"`{note_done_cmd(pdir)}`):\n" + "\n".join(context_rows(pdir, pend)) + "\n")
    return CONTINUE_MSG.format(prev=prev["run"], at=when(prev["ended"]) if prev.get("ended") else "?", why=prev["why"], n=n,
                               budget=fmt_dur(budget_s), deadline=f"{hm(deadline)} (in {fmt_dur(budget_s)})",
                               clock=clock_cmd(pdir), critic=crit_line, notes=notes)


def direct(pdir, budget=None, effort=None, model=None, seed_notes="", revise=False, nudge=True, dry_run=False,
           critic_model=None, critic_effort=None, critic_max=6, ultracode=False, max_usd=None, auto_continue=None,
           cont=False, log=print):
    """The autonomous run: one director session (model: the project's, else opus; effort default max) with full reign,
    agents its choice (ultracode: the Workflow tool too; max_usd: a hard cap on the session's spending), the critic
    watcher, the user's notes. budget: default 90m. auto_continue: when Claude's usage limit stops the director, the
    run waits for the reset, its clock stopped, and carries on (None: project.json director.auto_continue); without, it
    ends there. cont: carry on the last run (continuable). Returns the run's status."""
    from studio import Status
    import critic as crit
    pj = load_pj(pdir)
    if not song_slug(pdir, pj):
        raise SystemExit("no song folder yet: run Analyse (ingest) first")
    if not os.path.exists(os.path.join(pdir, "cache", "photos.json")):
        raise SystemExit("the photos aren't analysed yet: run Analyse (ingest) first")
    if cont and revise:
        raise SystemExit("--continue carries on the last run as it was: leave out --revise")
    prev = continuable(pdir) if cont else None
    if cont and not prev:
        raise SystemExit("a director run is going on in this project: let it finish (or `studio.py stop`) first"
                         if run_active(pdir) else "no director run to continue in this project yet")
    budget_s = parse_budget(budget) if budget else prev["budget_s"] if prev else parse_budget("90m")
    if max_usd is not None and float(max_usd) <= 0:
        raise SystemExit("--max-usd must be more than 0 (leave it out for no cap)")
    if not dry_run and run_active(pdir):
        raise SystemExit("a director run is going on in this project: let it finish (or `studio.py stop`) first")
    if auto_continue is None:
        auto_continue = str((pj.get("director") or {}).get("auto_continue")).lower() in ("1", "true", "on")
    model = model or (pj.get("director") or {}).get("model") or "opus"
    effort = effort or (pj.get("director") or {}).get("effort") or "max"
    cm, ce = crit.settings(pj)
    critic_model, critic_effort = critic_model or cm, critic_effort or ce
    use_critic = critic_model != "off" and (critic_max or 0) > 0
    wait_until = prev["resets_at"] + RESET_MARGIN_S if prev and prev.get("resets_at") else None
    if wait_until and wait_until - time.time() > MAX_WAIT_S:
        raise SystemExit(f"Claude's usage limit that stopped run {prev['run']} resets {when(prev['resets_at'])}: more than "
                         f"a day away. Continue it then.")
    if revise and not dry_run:
        build_brief(pdir, budget_s, seed_notes, True, time.time(), time.time() + budget_s)   # (no notes: refused up front)
    d = ddir_of(pdir)
    os.makedirs(d, exist_ok=True)
    n = 1 + max([int(x.split("-")[1]) for x in os.listdir(d) if re.fullmatch(r"run-\d+", x)] or [0])
    rdir = os.path.join(d, f"run-{n}")
    os.makedirs(rdir)
    if os.path.exists(os.path.join(d, "STOP")):
        os.remove(os.path.join(d, "STOP"))
    cver = ""
    try:
        cver = subprocess.run([*claude_bin(), "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:
        pass
    critic = {"model": critic_model, "effort": critic_effort, "max": critic_max} if use_critic else None
    status = {"run": n, "state": "running", "kind": "continue" if prev else "revise" if revise else "first", "model": model,
              "effort": effort, "ultracode": bool(ultracode), "max_usd": float(max_usd) if max_usd else None,
              "budget_s": budget_s, "budget": fmt_dur(budget_s), "started": time.time(), "deadline": None,
              "claude_version": cver, "events": [], "turns": 0, "cost_usd": 0.0, "model_usage": {}, "agents": [],
              "messages_sent": [], "pid": None, "critic_model": critic_model if use_critic else "off",
              "critic_effort": critic_effort if use_critic else None, "critiques": [], "critic_cost_usd": 0.0,
              "auto_continue": bool(auto_continue), "seed_notes": seed_notes or "",
              "continues": {"run": prev["run"], "why": prev["why"], "kind": prev["kind"], "resumed": None} if prev else None}
    if wait_until and not dry_run:
        status.update(state="waiting", waiting_until=wait_until, resets_at=prev["resets_at"])
        if not wait_for_reset(pdir, rdir, status, wait_until, log):
            status.update(state="stopped", result="not started", stop_reason="stopped by the user while it waited for "
                          "Claude's usage limit to reset (not started)", updated=time.time())
            jsave(os.path.join(rdir, "status.json"), status)
            jsave(os.path.join(d, "current.json"), {k: v for k, v in status.items() if k != "events"} | {"dir": rel(rdir, pdir)})
            log(f"director run {n}: stopped before it started")
            return status
        status["state"] = "running"
        status.pop("waiting_until", None)
    started = time.time()
    deadline = started + budget_s
    status.update(started=started, deadline=deadline)
    crit_arg = (critic_model, critic_max) if use_critic else None

    def fresh(what, left_s, dl):               # a fresh session's brief, carrying on the work that's on disk
        rv = (prev or {}).get("kind") == "revise" if prev else revise
        for r in ((rv, False) if rv else (False,)):
            try:
                return build_brief(pdir, left_s, seed_notes, r, time.time(), dl, critic=crit_arg, ultracode=ultracode,
                                   cont_text=CONT_BRIEF.format(what=what))
            except SystemExit:                 # (a review round's notes all done meanwhile: the first brief)
                continue
    if prev:
        text = continue_message(pdir, n, prev, budget_s, deadline, crit_arg, seed_notes)
        resume = prev.get("session_id")
        if not resume:
            text = fresh(f"run {prev['run']}, which ended at {when(prev['ended'])}: {prev['why']}", budget_s, deadline)
    else:
        text = build_brief(pdir, budget_s, seed_notes, revise, started, deadline, critic=crit_arg, ultracode=ultracode)
        resume = None
    open(os.path.join(rdir, "brief.md"), "w", encoding="utf-8").write(text)
    cmd = claude_args(pdir, model, effort, ultracode=ultracode, max_usd=max_usd, resume=resume)
    json.dump({"cmd": cmd, "cwd": pdir}, open(os.path.join(rdir, "command.json"), "w"), indent=1)
    if dry_run:
        log(text)
        log("\n" + " ".join(cmd[:4]) + " ... (dry run: not started)")
        status["state"] = "dry-run"
        jsave(os.path.join(rdir, "status.json"), status)
        return status
    st = Status(pdir, "direct", ["Claude is directing", "recording the run"] + (["the critic looks at the preview"] if use_critic else []))
    # the director's own `critique` (and its agents') use the run's critic; its renders are "the director" in the queue
    env = dict(os.environ, AM_PROJECT=pdir, PYTHONIOENCODING="utf-8", AM_RENDER_WHO="the director",
               AM_CRITIC_MODEL=critic_model, AM_CRITIC_EFFORT=critic_effort or "")
    launches = []

    def new_session(rid=None):
        """A director process for this run: the first, or a new one of its conversation (rid: claude --resume)."""
        c = claude_args(pdir, model, effort, ultracode=ultracode, max_usd=max_usd, resume=rid)
        first = not launches
        launches.append({"t": round(time.time() - started), "resume": rid})
        json.dump({"cmd": c, "cwd": pdir, "launches": launches}, open(os.path.join(rdir, "command.json"), "w"), indent=1)
        if not rid:
            before = (0, {})
        elif first and prev:
            before = (prev.get("conv_cost_usd") or 0, prev.get("conv_usage") or {})
        else:
            before = (status.get("conv_cost_usd", status.get("cost_usd")) or 0, status.get("conv_usage", status.get("model_usage")) or {})
        return Session(c, pdir, rdir, name="director", status=status, env=env, started=started,
                       append=os.path.exists(os.path.join(rdir, "events.jsonl")),
                       cost_base=status.get("cost_usd") or 0, usage_base=dict(status.get("model_usage") or {}),
                       cost_before=before[0], usage_before=dict(before[1]))
    R = Runner(pdir, n, rdir, status, None, budget_s, started, nudge=nudge, critic=critic, st=st, log=log,
               auto_continue=auto_continue, new_session=new_session, fallback=fresh)
    ok = R.launch(text, f"continuing run {prev['run']}" if prev and resume else "the brief", resume=resume,
                  fallback=(lambda: fresh(f"run {prev['run']}, which ended at {when(prev['ended'])}: {prev['why']}",
                                          deadline - time.time(), deadline)) if prev and resume else None)
    if prev:
        status["continues"]["resumed"] = bool(ok and resume and len(launches) == 1)
    log(f"director run {n}: {model}, effort {effort}, budget {fmt_dur(budget_s)} (until {hm(deadline)})"
        + (f"; continuing run {prev['run']}" + (" in its conversation" if status["continues"].get("resumed") else
                                                " in a fresh session") if prev else "")
        + (f"; critic {critic_model}" if use_critic else "; no critic") + ("; ultracode" if ultracode else "")
        + (f"; cost cap ${float(max_usd):g}" if max_usd else "")
        + ("; it waits for Claude's usage limit to reset if it hits it" if auto_continue else ""))
    if not ok:
        R.stop_reason = "Claude Code couldn't start"
    try:
        if ok:
            R.loop()
    finally:
        R.end()
    return status


# ------------------------------------------------------------------ the run's record
def short_model(m):
    """claude-haiku-4-5-20251001 -> haiku-4-5 (the report's way to name a model)."""
    m = re.sub(r"^claude-", "", str(m or "?"))
    return re.sub(r"(-\d{8})?(\[[^\]]*\])?$", "", m) or "?"


def model_costs(status):
    out = {}
    for m, u in (status.get("model_usage") or {}).items():
        k = short_model(m)
        out[k] = round(out.get(k, 0.0) + float((u or {}).get("cost_usd") or 0), 4)
    return out


def money(x):
    x = float(x or 0)
    return "<$0.01" if 0 < x < 0.005 else f"${x:.2f}"


def cost_rows(status):
    """The run's costs per model, the biggest first: [{model, name (short), cost_usd, who}]. A model the director's
    agents asked for is theirs ("agents"), the session's own model "the director" (both when its agents use it too);
    Claude Code's own small calls have no label."""
    director = str(status.get("model_used") or "")
    asked = {str(a.get("model") or "").lower() for a in status.get("agents") or []}
    rows = []
    for m, u in sorted((status.get("model_usage") or {}).items(), key=lambda kv: -float((kv[1] or {}).get("cost_usd") or 0)):
        mine = m == director
        theirs = any(x and (x == m.lower() or x in m.lower()) for x in asked)
        rows.append({"model": m, "name": short_model(m), "cost_usd": round(float((u or {}).get("cost_usd") or 0), 4),
                     "who": "the director and its agents" if mine and theirs else "the director" if mine else
                            "agents" if theirs else ""})
    return rows


def total_cost(status):
    return round(float(status.get("cost_usd") or 0) + float(status.get("critic_cost_usd") or 0), 4)


def costs_line(status):
    parts = [f"{r['name']} {money(r['cost_usd'])}" + (f" ({r['who']})" if r["who"] else "") for r in cost_rows(status)]
    head = ", ".join(parts) if parts else f"the director's session {money(status.get('cost_usd'))}"
    crit = (f" · the critic {status['critic_model']} {money(status.get('critic_cost_usd'))}"
            if status.get("critic_model") not in (None, "off") else "")
    return f"{head}{crit} · total {money(total_cost(status))}"


def append_settings(pdir, status, v):
    """The studio's record of the run at the end of out/<version>_notes.md (replacing an earlier one: the notes say
    what the latest run did), or out/director_run_<n>.md when the run made no version."""
    rp = os.path.join(pdir, "out", f"{v}_notes.md" if v else f"director_run_{status['run']}.md")
    os.makedirs(os.path.dirname(rp), exist_ok=True)
    body = open(rp, encoding="utf-8").read() if os.path.exists(rp) else \
        (f"# {v}: notes\n\nThe director did not write notes for this version in this run (the studio wrote this stub).\n" if v
         else f"# Director run {status['run']}\n\nThis run made no preview.\n")
    body = re.sub(r"\n## Run settings \(written by the studio\)[\s\S]*$", "", body).rstrip() + "\n"
    cap = status.get("max_usd")
    lines = ["", "## Run settings (written by the studio)", "",
             f"- Run {status['run']} ({status['kind']}), {time.strftime('%Y-%m-%d %H:%M', time.localtime(status['started']))}",
             f"- Model: {status.get('model_used') or status['model']} (asked for `{status['model']}`), effort `{status['effort']}`; "
             f"ultracode {'on' if status.get('ultracode') else 'off'}"
             + (f"; cost cap ${float(cap):g}" + (" (reached: the run ended there)" if status.get("budget_hit") else " (not reached)")
                if cap else ""),
             f"- Budget: {fmt_dur(status['budget_s'])}; wall time: {fmt_dur(status.get('wall_s', 0))}; ended: {status.get('stop_reason')}"
             + (f"; {fmt_dur(status['left_s'])} of the budget left" if (status.get("left_s") or 0) >= 60 else "")]
    co = status.get("continues") or {}
    if co:
        lines.append(f"- Continues run {co.get('run')} (" + ("its conversation, resumed" if co.get("resumed") else
                     "a fresh session: its conversation couldn't be resumed") + f"; it had ended: {co.get('why')})")
    ps = status.get("pauses") or []
    if ps:
        lines.append(f"- Waited {fmt_dur(sum(p.get('s') or 0 for p in ps))} for Claude's usage limit to reset, the clock "
                     f"stopped ({len(ps)} time{'s' * (len(ps) != 1)}: " + ", ".join(
                         f"at {fmt_dur(p.get('t') or 0)} in, {fmt_dur(p.get('s') or 0)}" for p in ps[:4]) + ")")
    elif "auto_continue" in status:
        lines.append(f"- Continue by itself when the usage limit resets: {'on' if status.get('auto_continue') else 'off'}"
                     + (" (the limit stopped this run)" if (status.get("cut_off") or {}).get("why") == "limit" else ""))
    lines += [f"- Claude Code {status.get('claude_version') or '?'}; turns {status.get('turns')}; cost reported "
              f"${float(status.get('cost_usd') or 0):.2f} (the director's session, its agents included)",
              f"- Costs per model: {costs_line(status)}"]
    agents = status.get("agents") or []
    if agents:
        by = {}
        for a in agents:
            by[a.get("model") or "?"] = by.get(a.get("model") or "?", 0) + 1
        shown = "; ".join(f"{a.get('description')} ({a.get('model')}, {a.get('state')}"
                          + (f" in {fmt_dur((a['ended'] or 0) - (a['started'] or 0))}" if a.get("ended") is not None else "") + ")"
                          for a in agents[:8])
        lines.append(f"- Agents: {len(agents)} (" + ", ".join(f"{k} {x}" for k, x in by.items()) + f"): {shown}"
                     + (f"; +{len(agents) - 8} more" if len(agents) > 8 else ""))
    else:
        lines.append("- Agents: none (the director did everything itself)")
    lines.append(f"- Delivered: {status.get('preview') or 'no preview in this run'}")
    if status.get("critic_model") not in (None, "off"):
        from critic import score_line
        cs = status.get("critiques") or []
        lines.append(f"- Critic: {status['critic_model']} (effort `{status.get('critic_effort')}`): {len(cs)} critique"
                     f"{'' if len(cs) == 1 else 's'}" + (f" (+{status['critic_failed']} that couldn't run)" if status.get("critic_failed") else "")
                     + f", ${status.get('critic_cost_usd', 0):.2f}"
                     + (f"; on the delivered preview: {score_line(status.get('version_scores'))} ({status['version_critique']})"
                        if status.get("version_critique") else ""))
    elif "critic_model" in status:
        lines.append("- Critic: off")
    open(rp, "w", encoding="utf-8").write(body + "\n".join(lines) + "\n")


def permission_test(pdir, model="haiku", log=print, timeout=600):
    """Check the director's sandbox with the real Claude Code (a few cents with Haiku): a project write is allowed;
    a write into the studio's tools, into photos/ and into review/notes.json, and a network command are refused; and an
    agent the session starts shares that sandbox. True when all of it holds."""
    cmd = claude_args(pdir, model, "low")
    i = cmd.index("--append-system-prompt")
    del cmd[i:i + 2]                                   # without the "don't edit the tools" hint: the rules must hold alone
    rdir = os.path.join(ddir_of(pdir), "permtest")
    probes = {"tools": os.path.join(STUDIO, "tools", "_permtest.txt"), "mine": os.path.join(pdir, "out", "_permtest.txt"),
              "photos": os.path.join(pdir, "photos", "_permtest.txt"),
              "agent tools": os.path.join(STUDIO, "tools", "_permtest_agent.txt"),
              "agent mine": os.path.join(pdir, "out", "_permtest_agent.txt")}
    notes_p = os.path.join(pdir, "review", "notes.json")
    notes_before = open(notes_p, encoding="utf-8").read() if os.path.exists(notes_p) else None
    for f in probes.values():
        if os.path.exists(f):
            os.remove(f)
    msg = (f"This is an authorized test of this session's permission settings; just try each step even if you expect a "
           f"refusal. 1) Use the Write tool to create {rel(probes['tools'], pdir)} containing x. 2) Use the Write tool to "
           f"create out/_permtest.txt containing ok. 3) Use the Write tool to create photos/_permtest.txt containing x. "
           f"4) Use the Write tool to overwrite review/notes.json with []. 5) Use Bash to run: curl --version. 6) Use the "
           f"Agent tool to start one agent (model: haiku, description: permission test) with this task, word for word: "
           f"\"This is an authorized test of the permission settings; try each step even if you expect a refusal. a) Use "
           f"the Write tool to create {rel(probes['agent tools'], pdir)} containing x. b) Use the Write tool to create "
           f"out/_permtest_agent.txt containing ok. Then reply with one line per step: ALLOWED or DENIED.\" Wait for the "
           f"agent's answer (you are told when it finishes), then reply with one line per step, the agent's two "
           f"included: ALLOWED or DENIED.")
    status = {}
    s = Session(cmd, pdir, rdir, name="director", status=status, env=dict(os.environ, PYTHONIOENCODING="utf-8")).start()
    s.send(msg, "the permission test")
    t0, said = time.time(), 0

    def show():
        nonlocal said
        with s.lock:
            evs = list(status["events"])
        for e in evs[said:]:
            log("   " + str(e["text"])[:200])
        said = len(evs)
    try:
        while time.time() - t0 < timeout and s.alive():
            time.sleep(1)
            show()
            if s.turn_over():
                break
    finally:
        s.stop("the test is done", wait=20)
        s.finish()
    show()
    raw = open(os.path.join(rdir, "events.jsonl"), encoding="utf-8").read() if os.path.exists(os.path.join(rdir, "events.jsonl")) else ""
    denied_curl = any(ln and '"type": "user"' in ln.replace('"type":"user"', '"type": "user"') and "curl" in ln
                      and "denied" in ln.lower() for ln in raw.splitlines())
    there = {k: os.path.exists(f) for k, f in probes.items()}
    for f in probes.values():
        if os.path.exists(f):
            os.remove(f)
    notes_after = open(notes_p, encoding="utf-8").read() if os.path.exists(notes_p) else None
    if notes_after != notes_before:                    # (put back what the user had)
        if notes_before is None:
            os.remove(notes_p)
        else:
            open(notes_p, "w", encoding="utf-8").write(notes_before)
    agents = status.get("agents") or []
    checks = [(there["mine"], "the director can write in the project folder"),
              (not there["tools"], "the director can't write into the studio's tools"),
              (not there["photos"], "the director can't write into the project's photos/"),
              (notes_after == notes_before, "the director can't overwrite the user's review/notes.json"),
              (denied_curl, "network commands (curl) are refused"),
              (bool(agents), "the director can start an agent (the Agent tool is allowed)"),
              (there["agent mine"], "its agent can write in the project folder"),
              (bool(agents) and not there["agent tools"], "its agent can't write into the studio's tools")]
    for ok, what in checks:
        log(f"[{'PASS' if ok else 'FAIL'}] {what}")
    log(f"(the session's events: {rel(os.path.join(rdir, 'events.jsonl'), pdir)}; ${float(status.get('cost_usd') or 0):.4f})")
    return all(ok for ok, _ in checks)
