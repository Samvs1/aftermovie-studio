"""The studio's critic: a cheaper model with fresh eyes looks at a rendered aftermovie and reports back in text, so the
director (often the most expensive model) doesn't spend its own tokens looking at every picture.

  python tools/studio.py critique <p> <video> [--model sonnet] [--effort medium] [--focus "..."] [--max-usd 2] [--no-look]
  python tools/studio.py critique <p> v2          the newest render of version v2 (its preview, or its final)
  python tools/studio.py run <p> critic.py <video> ...                     (the same as the first form)

<video> is relative to the project: out/<v>_preview.mp4 (the usual one), out/<v>.mp4 (a final), out/rounds/<v>_rN.mp4.
1. Eyes first: unless cache/eyes/<name>/index.md is newer than the video (or --no-look), eyes.py look (a sheet tile per
   shot with its song context, captions and photos; the ★★★ moments; a beat sheet; the QA cut sheets); then a strip
   (8 consecutive frames) at up to three of the strongest ★★★ moments.
2. The prompt (templates/critic-prompt.md): the intent (out/treatment.md and the chosen direction), the song's
   essentials (song-story.md and the song map's overview), the user's brief (their "avoid" is a hard rule), the people,
   the stylebook's anti-defaults, the house rules (inlined from the skill, so they stay in sync), what the eyes
   measured, the QA report's verdicts and failures, the caption board (every line and its source), the pictures to
   open, and the previous critique (what got fixed). Not the director's notes or log: fresh eyes judge the picture
   against the intent, not the director's account of it.
3. One headless print-mode call (am/claude.py): read-only tools, cwd = the project folder, the prompt on stdin.
4. review/critic/<name>_NN.md + .json (verdict, scores, problems, keep, safe, anti_defaults, fixed_since_last; plus the
   video, its size and mtime, version, model, effort, cost_usd, duration_s, at) and a line in review/critic/log.jsonl
   (review/ is in git: the critiques stay with the project).
While it works, cache/critic/pending/ has a marker for the cut (its path, size and mtime, this process): the director
runner's critic watcher doesn't critique a cut twice.
It prints the report, then one line:  critic: ambition 7 · song fit 6 · story 8 · craft 8 · readability 9 · $0.12 · review/critic/x_02.md
Exit 0 whatever it found; 1 only when it couldn't run (no pictures of this cut, no answer, or Claude Code's own error
text instead of a critique: a usage limit, a login): then nothing is written but a log line with the error and what it
cost, and the last line is  critic: couldn't run: <why> ($0.0310 spent).
"""
import argparse, glob, json, os, re, subprocess, sys, time
from contextlib import contextmanager

HERE = os.path.dirname(os.path.abspath(__file__))
STUDIO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from am.util import jload, jsave, load_project as load_pj, song_slug  # noqa: E402
from am.claude import claude_print, pid_alive, READ_ONLY  # noqa: E402

TEMPLATE = os.path.join(STUDIO, "templates", "critic-prompt.md")
SKILL_DIR = os.path.join(STUDIO, ".claude", "skills", "aftermovie")
DEFAULT_MODEL, DEFAULT_EFFORT, DEFAULT_MAX_USD = "sonnet", "medium", 2.0
SCORES = (("ambition", "ambition"), ("song_fit", "song fit"), ("story", "story"), ("craft", "craft"),
          ("readability", "readability"))
LISTS = ("keep", "safe", "anti_defaults", "fixed_since_last")
CDIR = os.path.join("review", "critic")              # the critiques (in git, with the user's notes)


def rel(p, start):
    return os.path.relpath(p, start).replace("\\", "/")


def mmss(t):
    m, s = divmod(max(0.0, float(t)), 60)
    return f"{int(m)}:{s:04.1f}"


def need_project():
    p = os.environ.get("AM_PROJECT")
    if not p:
        raise SystemExit("no project: run this through `python tools/studio.py critique <project> <video>`")
    return os.path.abspath(p)


# ------------------------------------------------------------------ settings and results (also used by director.py)
def settings(pj):
    """(model, effort) of the automatic critic from project.json "director" (critic_model "off" = no critic). Inside an
    autonomous run the run's critic wins (AM_CRITIC_MODEL / AM_CRITIC_EFFORT, set for the director's session and so its
    agents), so their own `critique` uses the critic the run was started with."""
    d = pj.get("director") or {}
    return (str(os.environ.get("AM_CRITIC_MODEL") or d.get("critic_model") or DEFAULT_MODEL),
            str(os.environ.get("AM_CRITIC_EFFORT") or d.get("critic_effort") or DEFAULT_EFFORT))


def score_line(scores):
    """'ambition 7 · song fit 6 · story 8 · craft 8 · readability 9' (a ? where the critic gave none)."""
    s = scores or {}
    return " · ".join(f"{lab} {s.get(k) if s.get(k) is not None else '?'}" for k, lab in SCORES)


def result_line(d):
    cost = f"${d['cost_usd']:.2f}" if isinstance(d.get("cost_usd"), (int, float)) else "$?"
    return f"critic: {score_line(d.get('scores'))} · {cost} · {d.get('file')}"


class NoAnswer(RuntimeError):
    """The critic couldn't run; .cost is what the call spent anyway (a cap hit, a refused call), when Claude said."""
    def __init__(self, msg, cost=None):
        super().__init__(msg)
        self.cost = cost


def spent(out):
    """What a critic.py run that couldn't answer spent, from its "critic: couldn't run: ... ($0.031 spent)" line."""
    m = re.findall(r"^critic: couldn't run: .*\(\$([\d.]+) spent\)\s*$", out or "", re.M)
    return float(m[-1]) if m else None


def critiques(pdir):
    """Every critique in review/critic/ (the json files), oldest first."""
    out = []
    for f in glob.glob(os.path.join(pdir, CDIR, "*.json")):
        d = jload(f, None)
        if isinstance(d, dict) and d.get("video"):
            out.append(dict(d, json=rel(f, pdir)))
    return sorted(out, key=lambda d: (d.get("at") or "", d["json"]))


def find(pdir, video, size=None, mtime=None):
    """The latest critique of this exact file (its path, and its size + mtime when given), or None."""
    hits = [d for d in critiques(pdir) if d["video"] == video and (size is None or d.get("size") == size)
            and (mtime is None or abs((d.get("mtime") or 0) - mtime) < 1)]
    return hits[-1] if hits else None


def of_version(pdir, v):
    """The critiques of one version's renders (its previews, its final, its rounds), oldest first."""
    return [d for d in critiques(pdir) if d.get("version") == v]


PENDING_S = 45 * 60               # a marker older than this is left over (a critique never takes that long)


@contextmanager
def pending(pdir, video):
    """While a critique of this cut is being made: a marker in cache/critic/pending/ with the cut (path, size, mtime)
    and this process."""
    d = os.path.join(pdir, "cache", "critic", "pending")
    os.makedirs(d, exist_ok=True)
    st = os.stat(video)
    p = os.path.join(d, f"{os.getpid()}_{time.time_ns()}.json")
    jsave(p, {"video": rel(video, pdir), "size": st.st_size, "mtime": st.st_mtime, "pid": os.getpid(), "at": time.time()})
    try:
        yield
    finally:
        try:
            os.remove(p)
        except OSError:
            pass


def is_pending(pdir, video, size, mtime):
    """A critique of this exact cut (path relative to the project, size, mtime) is being made by a process that is
    still running. Markers of processes that are gone are removed."""
    hit = False
    for f in glob.glob(os.path.join(pdir, "cache", "critic", "pending", "*.json")):
        d = jload(f, None)
        if not isinstance(d, dict):
            continue
        if not pid_alive(d.get("pid")) or time.time() - float(d.get("at") or 0) > PENDING_S:
            try:
                os.remove(f)
            except OSError:
                pass
            continue
        hit |= d.get("video") == video and d.get("size") == size and abs(float(d.get("mtime") or 0) - mtime) < 1
    return hit


def any_pending(pdir):
    """The cuts being critiqued right now (for the web app: "the critic is looking at ...")."""
    out = []
    for f in glob.glob(os.path.join(pdir, "cache", "critic", "pending", "*.json")):
        d = jload(f, None)
        if isinstance(d, dict) and pid_alive(d.get("pid")) and time.time() - float(d.get("at") or 0) < PENDING_S:
            out.append(d.get("video"))
    return out


def load(pdir, md_file):
    """A written critique (its .md path relative to the project): the json, with the markdown report as "report"."""
    base = os.path.splitext(os.path.join(pdir, md_file))[0]
    d = jload(base + ".json", None)
    if not isinstance(d, dict):
        return None
    d["report"] = open(base + ".md", encoding="utf-8").read() if os.path.exists(base + ".md") else ""
    return d


def from_output(pdir, out):
    """The critique a critic.py run wrote, from its last line ("critic: ... · review/critic/x_02.md"), or None."""
    lines = [x.strip() for x in (out or "").splitlines() if x.startswith("critic: ") and x.strip().endswith(".md")]
    return load(pdir, lines[-1].rsplit(" · ", 1)[-1]) if lines else None


def json_block(text):
    """An answer -> (markdown without its json block, the block's object or None, warning). The last ```json block
    is the data (an earlier one may be an example or a draft); missing or broken: None, and the warning says which."""
    text = (text or "").strip()
    blocks = list(re.finditer(r"```(?:json\w*)?\s*(\{[\s\S]*?\})\s*```", text, re.I))
    data = None
    if blocks:
        m = blocks[-1]
        try:
            data = json.loads(m.group(1))
            text = (text[:m.start()] + text[m.end():]).strip()
        except Exception:
            data = None
        if not isinstance(data, dict):
            data = None
    warn = "" if data is not None else "the json block didn't parse" if blocks else "there was no readable json block"
    return text, data, warn


def parse(text):
    """The critic's answer -> (markdown, data, warning). The last ```json block is the data; missing or broken: the
    markdown is kept, the scores are None, and the warning says so."""
    text, data, warn = json_block(text)
    if data is None:
        warn = "the critic's answer had no readable json block: the report is kept, the scores are missing" \
            if "no readable" in warn else "the critic's json block didn't parse: the report is kept, the scores are missing"
        data = {}
    sc = data.get("scores") if isinstance(data.get("scores"), dict) else {}
    scores = {}
    for k, _ in SCORES:
        try:
            scores[k] = max(1, min(10, int(round(float(sc.get(k))))))
        except Exception:
            scores[k] = None
    probs = []
    for p in data.get("problems") or []:
        if isinstance(p, dict):
            q = {k: p.get(k) for k in ("severity", "t0", "t1", "where", "what", "push")}
            sev = str(q["severity"] or "").strip().lower()
            q["severity"] = sev if sev in ("high", "medium", "low") else "medium"
            for k in ("t0", "t1"):
                try:
                    q[k] = round(float(q[k]), 2)
                except Exception:
                    q[k] = None
            probs.append(q)
    out = {"verdict": str(data.get("verdict") or "").strip(), "scores": scores if any(v is not None for v in scores.values()) else None,
           "problems": probs[:12]}
    for k in LISTS:
        v = data.get(k) or []
        out[k] = [str(x) for x in (v if isinstance(v, list) else [v])][:12]
    return text, out, warn


def problems_text(d, n=4):
    """The top problems as short lines (for a message to the director)."""
    out = []
    for i, p in enumerate((d.get("problems") or [])[:n], 1):
        span = f"{mmss(p['t0'])}–{mmss(p['t1'])}" if p.get("t0") is not None and p.get("t1") is not None else \
            mmss(p["t0"]) if p.get("t0") is not None else "?"
        out.append(f"{i}. [{p.get('severity')}] {span} · {p.get('where') or '-'}: {p.get('what') or ''}"
                   + (f" Push: {p['push']}" if p.get("push") else ""))
    return "\n".join(out)


# ------------------------------------------------------------------ what the critic reads
def section(md, title, level="##"):
    """One '<level> title' section of a markdown text (up to the next heading of that level or higher)."""
    stop = r"^#{1,%d} " % len(level)
    m = re.search(rf"^{level} {re.escape(title)}[^\n]*\n([\s\S]*?)(?={stop}|\Z)", md, re.M)
    return m.group(0).strip() if m else ""


def house_rules():
    """The craft rules from the skill (its "House rules" part), so the critic and the director read the same."""
    sk = open(os.path.join(SKILL_DIR, "SKILL.md"), encoding="utf-8").read()
    body = section(sk, "House rules", "###")
    return re.sub(r"^### [^\n]*\n", "", body).strip() or "(the house rules are in .claude/skills/aftermovie/SKILL.md)"


def anti_defaults():
    """The stylebook's anti-defaults, its rule on committing to one language and its device budget."""
    t = open(os.path.join(SKILL_DIR, "stylebook.md"), encoding="utf-8").read()
    out = []
    m = re.search(r"\*\*Anti-defaults\.\*\*[\s\S]*?(?=\n\n)", t)
    if m:
        out.append(m.group(0).strip())
    m = re.search(r"^5\. Commit:[\s\S]*?(?=\n\n|\n## )", t, re.M)
    if m:
        out.append(re.sub(r"^5\. ", "", m.group(0)).strip())
    b = section(t, "Device budget")
    if b:
        out.append(re.sub(r"^## [^\n]*\n", "**Device budget.** ", b).strip())
    return "\n\n".join(out) or "(see .claude/skills/aftermovie/stylebook.md)"


def song_brief(pdir, slug):
    """The song's essentials: song-story.md (what it is about, written with the user) and the song map's "At a
    glance", "Sections" and "Moments" (written once to cache/critic/song-brief.md; not the bar-by-bar)."""
    sd = os.path.join(pdir, "song", slug or "")
    sm = os.path.join(sd, "song-map.md")
    if not slug or not os.path.exists(sm):
        return None, "(no song map: the song hasn't been analysed)"
    brief = os.path.join(pdir, "cache", "critic", f"song-brief_{slug}.md")
    story = os.path.join(sd, "song-story.md")
    srcs = [sm] + ([story] if os.path.exists(story) else [])
    if not os.path.exists(brief) or os.path.getmtime(brief) < max(os.path.getmtime(x) for x in srcs):
        md = open(sm, encoding="utf-8").read()
        head = md.split("\n## ", 1)[0].strip()
        parts = [head] + [section(md, t) for t in ("At a glance", "Sections", "Moments")]
        if os.path.exists(story):
            st = open(story, encoding="utf-8").read().strip()
            if "_2–4 sentences" not in st:                   # the skeleton isn't a story yet
                parts.append("## The song story (song-story.md, written with the user)\n\n" + re.sub(r"^# [^\n]*\n", "", st).strip())
        os.makedirs(os.path.dirname(brief), exist_ok=True)
        open(brief, "w", encoding="utf-8").write("\n\n".join(p for p in parts if p) + "\n")
    return rel(brief, pdir), open(brief, encoding="utf-8").read().strip()


BRIEF_LABELS = (("occasion", "What it was"), ("when_where", "When & where"), ("group_name", "The group"),
                ("vibe", "The vibe they want"), ("adventurous", "How adventurous"), ("style_leanings", "Styles they lean to"),
                ("references", "References"), ("text_amount", "How much text"), ("people_notes", "The people"),
                ("jokes", "Inside jokes"), ("musts", "Must-haves"), ("credits", "Credit lines (verbatim)"),
                ("ending_note", "The ending"), ("language", "Language of on-screen text"), ("extra", "Other"))


def user_brief(pj):
    out = []
    for k, lab in BRIEF_LABELS:
        v = pj.get(k)
        v = ", ".join(map(str, v)) if isinstance(v, list) else str(v or "").strip()
        if v:
            out.append(f"- {lab}: {v}")
    if pj.get("must_use"):
        out.append(f"- Starred photos (must be in the film): {', '.join(pj['must_use'][:30])}")
    for r in pj.get("order") or []:
        if isinstance(r, dict) and r.get("first"):
            out.append(f"- Story order: {r['first']} before {', '.join(r.get('then') or [])}" + (f" ({r['why']})" if r.get("why") else ""))
    return "\n".join(out) or "(no brief: the director had a free hand)"


def people(pdir):
    cp = jload(os.path.join(pdir, "cache", "cast.json"), {}) or {}
    rows = []
    for pid, p in (cp.get("people") or {}).items():
        if isinstance(p, dict) and p.get("name"):
            rows.append(f"- #{pid} {p['name']}" + (f" ({p['nick']})" if p.get("nick") else "")
                        + (" · main cast" if p.get("core") else " · extra"))
    return "\n".join(rows) or "(the faces aren't named yet)"


def intent(pdir, pj):
    """What the director says it is making: out/treatment.md, and the direction that was chosen."""
    parts = []
    tp = os.path.join(pdir, "out", "treatment.md")
    if os.path.exists(tp):
        parts.append("(from `out/treatment.md`)\n\n" + open(tp, encoding="utf-8").read().strip())
    dr = pj.get("direction") or {}
    if dr.get("id"):
        ds = jload(os.path.join(pdir, "out", "directions.json"), []) or []
        d = next((x for x in ds if isinstance(x, dict) and str(x.get("id")) == str(dr["id"])), None)
        parts.append(f"The user picked direction {dr['id']}" + (f" (“{d.get('name')}”: {d.get('concept')})" if d else "")
                     + (f"; their note: {dr['note']}" if dr.get("note") else ""))
    return "\n\n".join(parts) or ("(the director hasn't written out/treatment.md yet: judge the film against the song and the "
                                  "brief, and say what idea you can read in the pictures)")


def describe(pdir, video, edl, v):
    """What the video is: (kind, a few lines for the prompt)."""
    from eyes import probe
    vr = rel(video, pdir)
    pr = probe(video)
    b = os.path.basename(video)
    if "/rounds/" in vr:
        kind = f"an earlier review round of version {v}"
    elif b.endswith("_preview.mp4") or b.endswith("_preview_share.mp4"):
        kind = f"the preview of version {v} (960 px wide: judge sizes relative to the frame)"
    else:
        kind = f"the 1080p final of version {v}"
    span = f"the whole film, {mmss(pr['duration'])}"
    if edl:
        segs = (edl.get("audio") or {}).get("segments") or []
        if len(segs) > 1:
            span += f"; the song has a join at film {mmss(segs[1]['at'])} (song {mmss(segs[0]['src'][1])} → {mmss(segs[1]['src'][0])})"
        span += f"; {len(edl.get('shots') or [])} shots"
    return kind, f"`{vr}`: {kind}. {pr['width']}×{pr['height']}, {pr['fps']:.0f} fps, {span}."


def run_tool(pdir, args, timeout=1800):
    env = dict(os.environ, AM_PROJECT=pdir, PYTHONIOENCODING="utf-8", AM_IN_VENV="1")
    cmd = [sys.executable, "-W", "ignore", os.path.join(HERE, args[0])] + list(args[1:])
    try:
        return subprocess.run(cmd, cwd=STUDIO, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", f"{args[0]} took longer than {timeout // 60} min")


def busy_marker(path):
    """eyes.py look's .looking file, if a look is really going on (a marker of a look that was killed is removed)."""
    if not os.path.exists(path):
        return False
    try:
        pid = open(path, encoding="utf-8").read().strip()
    except OSError:
        return False
    age = time.time() - os.path.getmtime(path)
    alive = (pid_alive(pid) and age < 1800) if pid.isdigit() else age < 900
    if not alive:
        try:
            os.remove(path)
        except OSError:
            pass
    return alive


def wait_quiet(d, since, log, quiet=20, most=360):
    """The director may be looking at the same video right now: wait while eyes.py look works on it."""
    t0, said = time.time(), False
    while time.time() - t0 < most:
        ms = [os.path.getmtime(f) for f in glob.glob(os.path.join(d, "*")) if os.path.isfile(f)]
        newest = max(ms or [0])
        if not busy_marker(os.path.join(d, ".looking")) and (newest <= since or time.time() - newest > quiet):
            return
        if not said:
            log("eyes: something is looking at this video already; waiting for it")
            said = True
        time.sleep(3)


def strongest_moments(song, clock, dur, n=3):
    """Up to n ★★★ moments that play in the film (film times), where most happens at once, in film order."""
    ms = []
    for m in song.moments(3):
        ft = clock.film(m["t"])
        if ft is not None and 0.2 <= ft <= dur - 0.2:
            ms.append(dict(m, ft=ft))
    rank = lambda m: len(m["kind"].split("+")) + (1 if "ending" in m["kind"] else 0) + \
        (0.5 if any(k in m["kind"] for k in ("stop", "drop", "tempo")) else 0)    # noqa: E731
    return sorted(sorted(ms, key=lambda m: -rank(m))[:n], key=lambda m: m["ft"])


def newer(p, t):
    return os.path.exists(p) and os.path.getmtime(p) > t


PIC_KINDS = {"sheet": "sheet: a tile per shot (its time, bar:beat, section, sung line, the photos and every line of text with its source)",
             "moments": "moments: a frame on each ★★/★★★ moment of the song", "beats": "beat sheet of the loudest section",
             "cuts": "QA cut sheet: the frame before and after every cut"}


def look(pdir, video, log, fresh_look=True):
    """Eyes first: the look (unless it's newer than the video), then strips at the strongest ★★★ moments. Returns
    ([(picture path relative to the project, what it is)], the eyes folder, warnings)."""
    import eyes
    from am.song import Song, FilmClock
    d = eyes.out_dir(video, pdir)
    vm = os.path.getmtime(video)
    idx = os.path.join(d, "index.md")
    warns = []
    if fresh_look and not newer(idx, vm):
        wait_quiet(d, vm, log)
    if fresh_look and not newer(idx, vm):
        log(f"eyes: looking at {rel(video, pdir)} (a minute or two)...")
        r = run_tool(pdir, ["eyes.py", "look", video])
        if r.returncode:
            log("eyes.py look failed: " + (r.stdout + r.stderr)[-600:])
    if os.path.exists(idx) and not newer(idx, vm):
        warns.append("the eyes' look at this video is from an earlier cut with this name" +
                     (" (eyes.py look failed)" if fresh_look else " (--no-look)") + ": left out")
    pics = []
    if newer(idx, vm):
        for k, p in re.findall(r"^- \*\*(\w+)\*\*: `([^`]+)`", open(idx, encoding="utf-8").read(), re.M):
            if os.path.exists(os.path.join(pdir, p)):
                base = re.sub(r"\d+$", "", k)
                pics.append((p, PIC_KINDS.get(base, k) + (f" ({k[len(base):]})" if k != base else "")))
    v, edl = eyes.edl_of(pdir, video)
    try:
        slug = (edl or {}).get("meta", {}).get("analysis") or song_slug(pdir)
        song, clock = Song(pdir, slug), FilmClock(edl)
        dur = eyes.probe(video)["duration"]
    except Exception:
        song = None
    for m in strongest_moments(song, clock, dur) if song else []:
        at = round(m["ft"], 3)
        p = os.path.join(d, f"strip_at{at:g}.jpg")              # the name eyes.py strip gives it
        if fresh_look and not newer(p, vm):
            r = run_tool(pdir, ["eyes.py", "strip", video, "--at", f"{at:.3f}", "--n", "8"], timeout=600)
            found = [x for x in r.stdout.strip().splitlines() if x.endswith(".jpg")]
            p = found[-1] if found else p
        if newer(p, vm):
            pics.append((rel(p, pdir), f"strip around film {mmss(m['ft'])} ({m.get('pos', '')}): ★★★ {m['text']}"))
    if not pics:
        raise NoAnswer(f"the eyes couldn't make pictures of {rel(video, pdir)}"
                       + ("" if fresh_look else " (with --no-look there were none of this cut)"))
    return pics, d, warns, v, edl


def trimmed(path, most=45, keep=None):
    if not path or not os.path.exists(path):
        return ""
    lines = open(path, encoding="utf-8").read().splitlines()
    if keep:
        lines = [x for x in lines if keep(x)]
    return "\n".join(lines[:most] + ([f"... ({len(lines) - most} more lines in {os.path.basename(path)})"] if len(lines) > most else []))


def qa_about(pdir, v, video):
    """cache/qa/<v>/report.md when it is about this cut (written after the video): the verdicts and every ⚠ line."""
    qa = os.path.join(pdir, "cache", "qa", v or "", "report.md")
    if not v or not os.path.exists(qa) or os.path.getmtime(qa) < os.path.getmtime(video) - 120:
        return "(no QA report for this cut)"
    return f"(from `{rel(qa, pdir)}`: the verdicts and what didn't pass)\n" + \
        trimmed(qa, 60, keep=lambda x: x.startswith("#") or x.startswith("**") or "⚠" in x)


def caption_board(pdir, edl):
    """Every line of text in the cut, the shot it sits on, its source and what the user decided (the caption board)."""
    if not edl:
        return "(no EDL for this cut: no caption board)"
    try:
        os.environ.setdefault("AM_PROJECT", pdir)
        from am import checks
        pj = load_pj(pdir)
        caps = checks.captions(edl, pj)
        rv = checks.caption_review(caps)
    except Exception as e:
        return f"(the caption board couldn't be read: {e})"
    if not caps:
        return "(no text in this cut)"
    rows = ["| shot | film t | text | source | basis | photos | the user |", "|---|---|---|---|---|---|---|"]
    for c in caps[:90]:
        d_ = rv["decisions"].get(c["key"], {})
        verdict = ("VETOED: " + d_.get("comment", "")) if d_.get("ok") is False else "ok" if d_.get("ok") else ("to check" if c.get("check") else "")
        rows.append(f"| {c['shot']} | {mmss(c['t0'])} | {c['text'][:60].replace(chr(10), ' / ').replace('|', '/')} | "
                    f"{c.get('origin')} | {str(c.get('basis') or '')[:50].replace('|', '/')} | "
                    f"{', '.join(c.get('photos') or [])[:60]} | {verdict} |")
    if len(caps) > 90:
        rows.append(f"| ... | | ({len(caps) - 90} more lines) | | | | |")
    return "\n".join(rows)


def previous(pdir, video):
    size, vm = os.path.getsize(video), os.path.getmtime(video)
    # the newest critique of this cut or of one made before it (an older cut can't have "fixed" a newer one's problems)
    cs = [d for d in critiques(pdir) if d.get("size") == size or (d.get("mtime") or 0) < vm - 1]
    if not cs:
        return "(none earlier: this is the first critique in this project; `fixed_since_last` stays empty)"
    d = cs[-1]
    head = (f"`{d['json']}`, of `{d['video']}` at {d.get('at')}: {score_line(d.get('scores'))}. Its verdict: "
            f"{d.get('verdict') or '-'}\nIts problems:\n{problems_text(d, 8) or '(none listed)'}\n")
    if d.get("size") == size:
        return head + ("It looked at **this very cut**: nothing has changed since, so `fixed_since_last` stays empty. "
                       "Judge it afresh; where you see it differently, say so.")
    return head + ("Say in `fixed_since_last` what of this is fixed in the film you see now; don't repeat a problem that is "
                   "gone. (A new version may have a different structure: compare by the song's sections, not by shot ids.)")


def user_notes_on(pdir, v):
    """The user's own review notes on this version (they can hear; the critic can't): context, already the director's."""
    try:
        from am.notes import read_notes
        ns = [n for n in read_notes(pdir) if isinstance(n, dict) and str(n.get("version")) == str(v)]
    except Exception:
        ns = []
    if not ns:
        return ""
    rows = [f"- {mmss(float(n.get('t') or 0))}: {str(n.get('text') or '').strip()}" + (" (done: " + n["fix"] + ")" if n.get("done") and n.get("fix") else
                                                                                       " (done)" if n.get("done") else "")
            for n in sorted(ns, key=lambda n: float(n.get("t") or 0))[:30]]
    return ("## The user's own notes on this version (they watched it with sound; these are the director's to answer, "
            "listed so you don't repeat them as discoveries)\n" + "\n".join(rows) + "\n")


def build_prompt(pdir, video, what, pics, eyes_d, v, edl, focus=""):
    pj = load_pj(pdir)
    slug = (edl or {}).get("meta", {}).get("analysis") or song_slug(pdir, pj)
    vals = {"what": what, "concept": intent(pdir, pj)}
    src, vals["song"] = song_brief(pdir, slug)
    if src:
        vals["song"] = f"(from `{src}`)\n\n" + vals["song"]
    vals["brief"] = user_brief(pj)
    vals["people"] = people(pdir)
    vals["avoid"] = str(pj.get("avoid") or "").strip() or "(nothing)"
    vals["anti"], vals["craft"] = anti_defaults(), house_rules()
    idx, vm = os.path.join(eyes_d, "index.md"), os.path.getmtime(video)
    vals["eyes"] = re.sub(r"^## Pictures[\s\S]*?(?=^## )", "", open(idx, encoding="utf-8").read(), flags=re.M).strip() \
        if newer(idx, vm) else "(the eyes couldn't measure this cut: judge from the pictures below)"
    vals["qa"] = qa_about(pdir, v, video)
    vals["captions"] = caption_board(pdir, edl)
    vals["notes"] = user_notes_on(pdir, v)
    vals["pictures"] = "\n".join(f"- `{p}`: {w}" for p, w in pics) or "(none: the eyes couldn't make pictures)"
    vals["previous"] = previous(pdir, video)
    vals["focus"] = (f"**The director asks you to look especially at:** {focus.strip()}\n") if (focus or "").strip() else ""
    text = open(TEMPLATE, encoding="utf-8").read()
    return re.sub(r"\{\{(\w+)\}\}", lambda m: str(vals.get(m.group(1), "")), text)


# ------------------------------------------------------------------ the critique
def resolve_video(pdir, video):
    """A video path (relative to the project, or absolute), or a version name ("v2": its newest render)."""
    p = video if os.path.isabs(video) else os.path.join(pdir, video)
    if os.path.isfile(p):
        return os.path.abspath(p)
    if re.fullmatch(r"[A-Za-z0-9_.-]+", video or ""):
        cands = [os.path.join(pdir, "out", f"{video}{s}.mp4") for s in ("_preview", "")]
        cands = [c for c in cands if os.path.isfile(c)]
        if cands:
            return max(cands, key=os.path.getmtime)
    raise RuntimeError(f"no such video: {video} (give a path like out/v1_preview.mp4, or a version name)")


def critique(pdir, video, model=None, effort=None, focus="", max_usd=DEFAULT_MAX_USD, fresh_look=True, log=print):
    """Look, ask, write. Returns the critique (dict, as written to the json) or raises RuntimeError when it couldn't
    run (no Claude Code, no pictures, no answer: NoAnswer, with what the call cost)."""
    pdir = os.path.abspath(pdir)
    video = resolve_video(pdir, video)
    with pending(pdir, video):                   # (the runner's critic watcher won't make the same critique meanwhile)
        return made(pdir, video, model, effort, focus, max_usd, fresh_look, log)


def made(pdir, video, model, effort, focus, max_usd, fresh_look, log):
    pj = load_pj(pdir)
    m0, e0 = settings(pj)
    model = model or (m0 if m0 != "off" else DEFAULT_MODEL)
    effort = effort or e0
    size, mtime = os.path.getsize(video), os.path.getmtime(video)
    pics, eyes_d, warns, v, edl = look(pdir, video, log, fresh_look)
    kind, what = describe(pdir, video, edl, v)
    prompt = build_prompt(pdir, video, what, pics, eyes_d, v, edl, focus)
    cdir = os.path.join(pdir, CDIR)
    os.makedirs(cdir, exist_ok=True)
    os.makedirs(os.path.join(pdir, "cache", "critic"), exist_ok=True)
    open(os.path.join(pdir, "cache", "critic", "last-prompt.md"), "w", encoding="utf-8").write(prompt)   # what it was asked
    log(f"the critic ({model}, effort {effort}) is looking at {rel(video, pdir)}: {len(pics)} pictures (2-4 min)...")
    r = claude_print(prompt, pdir, model=model, effort=effort or None, tools=READ_ONLY, timeout=900, max_usd=max_usd)
    res = r["json"]
    cost = round(r["cost_usd"], 4) if isinstance(r["cost_usd"], (int, float)) else None
    md, data, warn = parse(r["text"])
    failed = r["returncode"] or res.get("is_error")
    if not r["text"].strip() or (failed and warn):
        # no answer, or Claude Code's own error text (a usage limit, a login, an overloaded API) instead of a critique:
        # nothing is written as a critique (so nothing reuses it), only a line in the log with what it cost
        why = (r["text"].strip()[:300] if r["text"].strip() else "") or res.get("subtype") or \
            (r["stderr"] or r["stdout"]).strip()[-400:] or f"exit {r['returncode']}"
        if "budget" in str(res.get("subtype") or why):
            why = f"it reached its ${max_usd:g} cap before answering ({res.get('subtype') or why})"
        with open(os.path.join(cdir, "log.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "video": rel(video, pdir), "size": size,
                                "mtime": mtime, "version": v, "model": model, "effort": effort, "error": why[:300],
                                "cost_usd": cost}, ensure_ascii=False) + "\n")
        raise NoAnswer(f"the critic didn't answer: {why}", cost)
    warnings = r["warnings"] + warns + ([warn] if warn else [])
    if failed:
        warnings.append(f"Claude Code reported an error ({res.get('subtype') or 'exit ' + str(r['returncode'])}), "
                        f"but the critique came through whole")
    stem = os.path.splitext(os.path.basename(video))[0]
    nn = [int(x.group(1)) for f in os.listdir(cdir) for x in [re.fullmatch(re.escape(stem) + r"_(\d{2,})\.json", f)] if x]
    base = os.path.join(cdir, f"{stem}_{max(nn or [0]) + 1:02d}")
    mdp, jp = base + ".md", base + ".json"
    used = list((res.get("modelUsage") or {}).keys())
    d = {"video": rel(video, pdir), "size": size, "mtime": mtime, "version": v, "kind": kind, **data,
         "model": model, "model_used": used[0] if len(used) == 1 else used or None, "effort": effort,
         "cost_usd": cost, "duration_s": r["duration_s"], "at": time.strftime("%Y-%m-%d %H:%M:%S"), "file": rel(mdp, pdir),
         "pictures": [p for p, _ in pics], "focus": focus or "", "warnings": warnings}
    open(mdp, "w", encoding="utf-8").write(md.rstrip() + "\n")
    jsave(jp, d)
    with open(os.path.join(cdir, "log.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({k: d.get(k) for k in ("at", "video", "size", "mtime", "version", "model", "effort", "scores",
                                                 "verdict", "cost_usd", "file")}, ensure_ascii=False) + "\n")
    return d


def command(pdir, video, model=None, effort=None, max_usd=None, focus="", fresh_look=True, python=None):
    """critic.py as a command list + env, for running it in the background (the director runner, the web app)."""
    cmd = [python or sys.executable, "-W", "ignore", os.path.join(HERE, "critic.py"), video]
    for flag, v in (("--model", model), ("--effort", effort), ("--max-usd", max_usd), ("--focus", focus)):
        if v:
            cmd += [flag, str(v)]
    if not fresh_look:
        cmd.append("--no-look")
    return cmd, dict(os.environ, AM_PROJECT=os.path.abspath(pdir), PYTHONIOENCODING="utf-8", AM_IN_VENV="1")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", help="a render (out/v1_preview.mp4) or a version name (v1: its newest render)")
    ap.add_argument("--model", help=f"default: project.json director.critic_model, else {DEFAULT_MODEL}")
    ap.add_argument("--effort", help=f"default: project.json director.critic_effort, else {DEFAULT_EFFORT}")
    ap.add_argument("--focus", default="", help="what to look at especially")
    ap.add_argument("--max-usd", type=float, default=DEFAULT_MAX_USD, help="spending cap for this critique")
    ap.add_argument("--no-look", action="store_true", help="use the pictures that are there; don't run eyes.py look")
    a = ap.parse_args()
    pdir = need_project()
    try:
        d = critique(pdir, a.video, a.model, a.effort, a.focus, a.max_usd, not a.no_look, log=lambda s: print(s, flush=True))
    except RuntimeError as e:
        cost = getattr(e, "cost", None)
        print(f"critic: couldn't run: {e}" + (f" (${cost:.4f} spent)" if cost else ""), flush=True)
        sys.exit(1)
    print("\n" + open(os.path.join(pdir, d["file"]), encoding="utf-8").read().rstrip() + "\n", flush=True)
    for w in d.get("warnings") or []:
        print(f"warning: {w}", flush=True)
    if d.get("pictures"):                      # made already: the director opens only the ones it needs
        print("the pictures it looked at: " + ", ".join(d["pictures"]), flush=True)
    print(result_line(d), flush=True)


if __name__ == "__main__":
    main()
