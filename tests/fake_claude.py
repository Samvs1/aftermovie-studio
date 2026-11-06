"""A stand-in for the `claude` CLI, for tests that must not spend real usage (AM_CLAUDE=tests/fake_claude.py).

It speaks the same headless protocol the studio uses (ported from Music Video Studio's stand-in):
  claude --version                                                     -> a version line
  claude -p --output-format json ... (the prompt on stdin)             -> the story step: a song story from the song map;
        a prompt with <!-- am:critic --> gets a canned critique instead (markdown + a json block, its worst problem at
        the first ★★★ moment the prompt names; it says how many of the pictures it was told to open exist)
  claude -p --input-format stream-json --output-format stream-json ... -> a session: reads the first message from
        stdin, emits init / assistant / tool_use / result events, answers the studio's follow-ups, exits when stdin
        closes. Like the real CLI: every turn starts with a system/init and ends with ONE result; messages that arrive
        while it works are merged into that turn; num_turns is the turn's own; total_cost_usd and modelUsage are the
        session's running totals (each turn adds $0.01, an agent $0.004 on its model). An agent runs in the background
        (the Agent tool_use, "Async agent launched", background_tasks_changed, task_started, task_progress,
        task_notification, then the session's own turn). With --max-budget-usd, the turn that takes the total past it
        ends with subtype error_max_budget_usd.
        The role comes from the first message:
        - the director brief: `studio.py draft <p>` (the template builder + a preview round: render, QA), then
          out/draft_notes.md; a review round re-previews and marks its notes done (`studio.py note-done`, by the ids the
          brief gives); to the user's notes during a run ("left a note") it marks them done with a fix.
          FAKE_DIRECTOR=agents (env, or a file of that name in the project): the same, plus one background agent (haiku,
          "log the photos", FAKE_AGENT_S seconds) started before the draft; its turn ends while the agent works, and in the
          turn the session starts when the agent is done it makes the draft.
        - <!-- am:echo -->: works FAKE_ECHO_S seconds (default 2) on each turn, then answers every message of the turn
          (the session plumbing's test). <!-- am:echo-agent --> also starts a background agent in its first turn.
FAKE_LIMIT=K:S (or a file of that name in the project) plays Claude's usage limit: the Kth message the session gets is
        refused the way Claude Code 2.1.317 says it, and so is every message until S seconds later (S < 0: only that one).
FAKE_LIMIT_WARN=1: a rate_limit_event "allowed_warning" at the start of every turn.
--resume <id>: the session is that conversation's director; FAKE_RESUME_BAD=1 says "No conversation found with session
        ID: <id>" on stderr and exits 1 before anything.
FAKE_CLAUDE_SLOW=<s> (or a file of that name in the project) sleeps that long first (to test stopping a run).
FAKE_CLAUDE_CRITIC_ERROR=1 answers a critic prompt with Claude Code's login error (exit 1, is_error).
"""
import json, os, re, sys, threading, time

TESTS = os.path.dirname(os.path.abspath(__file__))
OUT = threading.Lock()                         # the session's events come from its turns and its agents' threads


def emit(ev):
    with OUT:
        sys.stdout.write(json.dumps(ev) + "\n")
        sys.stdout.flush()


def assistant(text=None, tool=None, inp=None, parent=None, tid=None):
    content = []
    if text:
        content.append({"type": "text", "text": text})
    if tool:
        content.append({"type": "tool_use", "id": tid or f"t{time.time_ns()}", "name": tool, "input": inp or {}})
    emit({"type": "assistant", "message": {"role": "assistant", "content": content}, "parent_tool_use_id": parent})


class Costs:
    """The session's running totals, as a real result reports them: $0.01 a turn on the session's model, $0.004 an
    agent on its own."""

    def __init__(self, model, cap=None):
        self.by, self.model, self.cap = {}, model, cap
        self.lock = threading.Lock()

    def add(self, model, usd):
        with self.lock:
            self.by[model] = round(self.by.get(model, 0.0) + usd, 4)

    def total(self):
        with self.lock:
            return round(sum(self.by.values()), 4)

    def over(self):
        return self.cap is not None and self.total() > self.cap

    def usage(self):
        with self.lock:
            return {m: {"inputTokens": 10, "outputTokens": 100, "cacheReadInputTokens": 1000, "cacheCreationInputTokens": 500,
                        "costUSD": c} for m, c in self.by.items()}


def result(turns, t0, costs, capped=False, error=None):
    emit({"type": "result", "subtype": "error_max_budget_usd" if capped else "success", "num_turns": turns,
          "total_cost_usd": costs.total(), "modelUsage": costs.usage(), "is_error": capped or bool(error),
          "duration_ms": int((time.time() - t0) * 1000), "usage": {"input_tokens": 0, "output_tokens": 0}}
         | ({"result": error} if error else {}))


class Limit:
    """Claude's usage limit, played (FAKE_LIMIT=K:S): refuse() answers a message the way Claude Code does when the
    limit holds (and says so: the text), or returns None."""

    def __init__(self, spec):
        k, _, sec = (spec or "").partition(":")
        self.k = int(k) if k.strip() else None
        self.sec = float(sec or 0)
        self.n, self.until = 0, 0.0

    def refuse(self, session_id):
        self.n += 1
        now = time.time()
        if self.k is not None and self.n == self.k:
            self.until = now + self.sec
        elif now >= self.until:
            return None
        resets = int(self.until)
        h = time.localtime(resets).tm_hour
        text = f"You've hit your session limit · resets {(h % 12) or 12}{'am' if h < 12 else 'pm'}"
        emit({"type": "rate_limit_event", "rate_limit_info": {"status": "rejected", "resetsAt": resets, "rateLimitType": "five_hour",
              "isUsingOverage": False}, "uuid": f"u{time.time_ns()}", "session_id": session_id})
        emit({"type": "assistant", "message": {"role": "assistant", "model": "<synthetic>", "content": [{"type": "text", "text": text}]},
              "parent_tool_use_id": None, "error": "rate_limit"})
        return text


def story(prompt):
    slug = (re.search(r"song/([^/\s]+)/song-map\.md", prompt) or [None, ""])[1]
    m = json.load(open(os.path.join("song", slug, "song-map.json"), encoding="utf-8"))
    rows = "\n".join(f"| {s['name']} | {s['bar0']}–{s['bar1'] - 1} | {s['t0']:.0f}–{s['t1']:.0f} s | {s.get('first_line') or ''} | "
                     f"{'quiet' if s.get('loud', 0) < -25 else 'full'} | one photo per bar, a hold on the landscapes |" for s in m["sections"])
    text = (f"# Song story: {m.get('title') or m.get('file')}\n\n> Drafted by the test stand-in for Claude.\n\n"
            "## What it's about\nA summer that keeps going when it should end.\n\n"
            "## The arc, section by section\n\n| section | bars | time | in the song | feeling | what the film could do |\n"
            f"|---|---|---|---|---|---|\n{rows}\n\n## Lines that could carry a moment\n- \"hold the light\": a hold.\n\n"
            "## Where it peaks, where it breathes\n- The stop: a freeze.\n\n## This group's version of it\n(test)\n")
    emit({"type": "result", "subtype": "success", "result": text, "total_cost_usd": 0.0})


def critic(prompt):
    """A canned critique of the film the prompt names, its worst problem at the first ★★★ moment in the prompt."""
    video = (re.search(r"## What you are looking at\s*\n`([^`]+)`", prompt) or [None, "the film"])[1]
    m = re.search(r"★★★[^\n]*?(\d+):(\d\d(?:\.\d+)?)", prompt) or re.search(r"(\d+):(\d\d(?:\.\d+)?)[^\n]*★★★", prompt)
    t = round(int(m.group(1)) * 60 + float(m.group(2)), 2) if m else 10.0
    pics = re.findall(r"^- `([^`]+\.(?:png|jpg))`", prompt, re.M)
    there = sum(os.path.exists(p) for p in pics)
    mm = f"{int(t // 60)}:{t % 60:04.1f}"
    data = {"verdict": "Photos cut on the beat: the ★★★ moments should change the film's rules (test stand-in).",
            "scores": {"ambition": 6, "song_fit": 7, "story": 6, "craft": 8, "readability": 9},
            "problems": [{"severity": "high", "t0": t, "t1": round(t + 4, 2), "where": "the first ★★★ moment",
                          "what": "the pages keep the rhythm they had before it", "push": "make the moment change the rules"},
                         {"severity": "low", "t0": 0.0, "t1": 4.0, "where": "intro", "what": "the title sits there",
                          "push": "let the intro start from nothing"}],
            "keep": ["the stats card"], "safe": [f"{mm} the same layout before and after"],
            "anti_defaults": [], "fixed_since_last": []}
    text = (f"# Critique: {video}\n**Verdict:** {data['verdict']}\n**Scores:** ambition 6 · song fit 7 · story 6 · craft 8 · "
            f"readability 9 (out of 10)\n\n## Ambition\nThe test stand-in can't see: this is a canned critique.\n\n"
            f"## Problems (worst first, at most 8)\n1. **[high] {mm}–{mm} · the first ★★★ moment** The pages keep their "
            f"rhythm. **Push:** make the moment change the rules.\n\n## What works (keep it)\n- the stats card\n\n"
            f"## Can't tell from the pictures\n- everything (test stand-in: {there} of {len(pics)} pictures exist)\n\n"
            f"```json\n{json.dumps(data)}\n```\n")
    emit({"type": "result", "subtype": "success", "result": text, "total_cost_usd": 0.0123, "is_error": False,
          "modelUsage": {"fake-critic": {}}})


def text_of(line):
    try:
        return json.loads(line)["message"]["content"][0]["text"]
    except Exception:
        return None


def studio_cmd(*args, log=None):
    """tools/studio.py, the way a session's Bash tool runs it (stdin closed: ffmpeg would eat the studio's messages)."""
    import subprocess
    r = subprocess.run([sys.executable, os.path.join(os.path.dirname(TESTS), "tools", "studio.py"), *args], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    tail = [x for x in (r.stdout + r.stderr).splitlines() if x.strip()][-2:]
    if log:
        log(f"$ studio.py {' '.join(args[:4])}: exit {r.returncode}; {' | '.join(tail)[:300]}")
    return r


def notes_done(text, fix, say):
    """Mark the notes a brief or a message names (by "(id N)") done with `studio.py note-done`, as the text says to (a
    text that doesn't name the command marks nothing: the test then sees the notes still open)."""
    ids = list(dict.fromkeys(re.findall(r"\(id (\d+)\)", text)))
    if "studio.py note-done" not in text:
        ids = []
    proj = os.path.basename(os.getcwd())
    for i in ids:
        say(f"Marking note {i} done.", "Bash", {"command": f'studio.py note-done {proj} {i} "{fix}"'})
        studio_cmd("note-done", proj, i, fix, log=say)
    return ids


class Agent(threading.Thread):
    """A background agent of the session: its lifecycle events while `work(say)` runs, then the session's own turn."""

    def __init__(self, q, costs, description, model, work=None, seconds=6.0):
        super().__init__(daemon=True)
        self.q, self.costs, self.description, self.model, self.work, self.seconds = q, costs, description, model, work, seconds
        self.id = f"a{time.time_ns() % 10**12}"
        self.call = f"toolu_{self.id}"
        self.done = False

    def launch(self):
        assistant(f"Starting an agent: {self.description}.", "Agent", {"description": self.description, "model": self.model,
                  "run_in_background": True, "prompt": "(test stand-in)"}, tid=self.call)
        task = {"task_id": self.id, "task_type": "local_agent", "subagent_type": "general-purpose", "description": self.description}
        emit({"type": "system", "subtype": "background_tasks_changed", "tasks": [task]})
        emit({"type": "system", "subtype": "task_started", "task_id": self.id, "tool_use_id": self.call,
              "description": self.description, "subagent_type": "general-purpose", "is_backgrounded": True,
              "task_type": "local_agent"})
        emit({"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": self.call,
              "content": [{"type": "text", "text": f"Async agent launched successfully.\nagentId: {self.id}"}]}]}})
        self.start()

    def run(self):
        t0, k = time.time(), 0
        while time.time() - t0 < self.seconds:
            k += 1
            emit({"type": "system", "subtype": "task_progress", "task_id": self.id, "tool_use_id": self.call,
                  "usage": {"total_tokens": 1000 * k, "tool_uses": k}, "last_tool_name": "Read"})
            time.sleep(0.5)
        say = lambda text, tool=None, inp=None: assistant(text, tool, inp, parent=self.call)     # noqa: E731
        if self.work:
            self.work(say)
        self.costs.add(self.model_id(), 0.004)
        emit({"type": "system", "subtype": "task_updated", "task_id": self.id, "patch": {"status": "completed"}})
        emit({"type": "system", "subtype": "task_notification", "task_id": self.id, "tool_use_id": self.call,
              "status": "completed", "summary": "done (test stand-in)"})
        emit({"type": "system", "subtype": "background_tasks_changed", "tasks": []})
        self.done = True
        self.q.put(("own", self))

    def model_id(self):
        return f"claude-{self.model}-fake"


def user_notes_done(msg, say):
    """The user's notes the studio forwarded during a run: each marked done with a fix, by the id the message gives."""
    ids = notes_done(msg, "the shot answers the note (test stand-in)", say)
    say(f"Took the user's note{'s' * (len(ids) != 1)} ({len(ids)}): marked done.")


def make_draft(say, version="draft"):
    """What a director run delivers, without the creative part: the template builder + a preview round."""
    proj = os.path.basename(os.getcwd())
    say("Building the first draft and its preview.", "Bash", {"command": f"studio.py draft {proj}"})
    r = studio_cmd("draft", proj, log=say)
    if r.returncode:
        say(f"The draft failed: {(r.stdout + r.stderr)[-600:]}")
        return False
    with open(os.path.join("out", f"{version}_notes.md"), "w", encoding="utf-8") as f:
        f.write(f"# {version}: notes (the test stand-in)\n\nThe template's first draft: stats, a montage, the route or the "
                "ending.\n\nCheck by ear: the ending.\n")
    with open(os.path.join("out", "director_log.md"), "a", encoding="utf-8") as f:
        f.write("- made the draft (test stand-in)\n")
    return True


class Director:
    """The director brief, played: `studio.py draft` (a review round: the same, then its notes marked done)."""

    def __init__(self, brief, q, costs):
        self.brief, self.q, self.costs = brief, q, costs

    def running(self):
        return False

    def first(self, say):
        try:
            ok = make_draft(say)
            if ok and "review round" in self.brief.lower():
                notes_done(self.brief, "re-cut (test stand-in)", say)
                with open(os.path.join("out", "draft_notes.md"), "a", encoding="utf-8") as f:
                    f.write("\n## Round 2\nAddressed every note (test stand-in).\n")
            say("Delivered the preview and wrote out/draft_notes.md." if ok else "No preview.")
        except Exception as ex:
            say(f"The stand-in director failed: {ex}")

    def answer(self, msg, say):
        if "left a note" in msg or "left 2 notes" in msg or re.search(r"left \d+ notes", msg):
            return user_notes_done(msg, say)
        say(f"(studio said: {msg[:60]}...) Nothing more to improve in the test.")

    def own(self, agent, say):
        say(f"The agent ({agent.description}) finished.")


class AgentDirector(Director):
    """A director that deploys one background agent first (FAKE_DIRECTOR=agents): it writes cache/shotlog_notes_agent.txt,
    and the draft is made in the turn the session starts when the agent is done."""

    def __init__(self, brief, q, costs):
        super().__init__(brief, q, costs)
        self.agent = Agent(q, costs, "log the photos", "haiku", work=self.log_photos,
                           seconds=float(os.environ.get("FAKE_AGENT_S") or 6))

    def running(self):
        return not self.agent.done

    def log_photos(self, say):
        say("Logging the photos.", "Write", {"file_path": "cache/shotlog_notes_agent.txt"})
        os.makedirs("cache", exist_ok=True)
        open(os.path.join("cache", "shotlog_notes_agent.txt"), "w").write("logged (test stand-in)\n")

    def first(self, say):
        say("Starting an agent for the shot log; I'll build when it's done.")
        self.agent.launch()

    def own(self, agent, say):
        say(f"The agent ({agent.description}) finished: building now.")
        Director.first(self, say)

    def answer(self, msg, say):
        if not self.agent.done:
            open(os.path.join("cache", "_fake_agent_heard.txt"), "a").write(msg[:80].replace("\n", " ") + "\n")
        return Director.answer(self, msg, say)


class Echo:
    """Works a little on each turn; says what it got (the session plumbing's test). <!-- am:echo-agent --> also starts
    a background agent in its first turn."""

    def __init__(self, brief, q, costs):
        self.wait = float(os.environ.get("FAKE_ECHO_S") or 2)
        self.agent = Agent(q, costs, "echo agent", "haiku", seconds=float(os.environ.get("FAKE_AGENT_S") or 4)) \
            if "<!-- am:echo-agent -->" in brief else None

    def running(self):
        return bool(self.agent and not self.agent.done)

    def first(self, say):
        time.sleep(self.wait)
        if self.agent:
            self.agent.launch()
        say("echo: the first message")

    def answer(self, msg, say):
        say(f"echo: {msg[:80]}")
        time.sleep(self.wait)

    def own(self, agent, say):
        say("echo: the agent finished")


def director_kind():
    k = os.environ.get("FAKE_DIRECTOR") or (open("FAKE_DIRECTOR").read().strip() if os.path.exists("FAKE_DIRECTOR") else "")
    return AgentDirector if k == "agents" else Director


def session(argv):
    """A stream-json session: one turn per message that finds it idle; lines that come in while it works join that
    turn; an agent that finishes while it is idle starts a turn of its own."""
    import queue
    q = queue.Queue()

    def reader():
        for line in sys.stdin:
            q.put(line)
        q.put(None)
    threading.Thread(target=reader, daemon=True).start()
    sid = argv[argv.index("--resume") + 1] if "--resume" in argv else "fake"
    if "--resume" in argv and os.environ.get("FAKE_RESUME_BAD"):
        print(f"No conversation found with session ID: {sid}", file=sys.stderr)
        sys.exit(1)
    first = q.get()
    brief = (text_of(first) or "") if first else ""
    role = Echo if "<!-- am:echo" in brief else director_kind()
    model = f"fake-{role.__name__.lower()}"
    cap = float(argv[argv.index("--max-budget-usd") + 1]) if "--max-budget-usd" in argv else None
    costs = Costs(model, cap)
    limit = Limit(os.environ.get("FAKE_LIMIT") or (open("FAKE_LIMIT").read().strip() if os.path.exists("FAKE_LIMIT") else ""))
    init = {"type": "system", "subtype": "init", "model": model, "tools": ["Task", "Read", "Bash", "TaskStop"],
            "permissionMode": "dontAsk", "session_id": sid}
    warn = lambda: os.environ.get("FAKE_LIMIT_WARN") and emit({"type": "rate_limit_event", "rate_limit_info": {   # noqa: E731
        "status": "allowed_warning", "resetsAt": int(time.time() // 3600 * 3600 + 7200), "rateLimitType": "five_hour",
        "utilization": 0.9, "isUsingOverage": False}, "uuid": f"u{time.time_ns()}", "session_id": sid})
    emit(init)
    warn()
    t0 = time.time()
    who = role(brief, q, costs)
    say = lambda text, tool=None, inp=None: assistant(text, tool, inp)     # noqa: E731
    refused = limit.refuse(sid) if first else None
    started = False
    if not refused:
        assistant("Reading the brief.", "Read", {"file_path": "project.json"})
        slow = os.environ.get("FAKE_CLAUDE_SLOW") or (open("FAKE_CLAUDE_SLOW").read().strip() if os.path.exists("FAKE_CLAUDE_SLOW") else "0")
        time.sleep(float(slow))
        who.first(say)
        started = True
    turns, done, capped = 1 if refused else 2, first is None, False

    def end():                                     # stdin closed: it exits (a lingering one keeps "working")
        if getattr(who, "lingers", False):
            time.sleep(600)

    def handle(item):
        nonlocal turns, done, refused, started
        if item is None:
            done = True
        elif isinstance(item, tuple):                  # an agent finished while this turn ran
            turns += 1
            who.own(item[1], say)
        else:
            msg = text_of(item)
            if msg:
                turns += 1
                no = limit.refuse(sid)
                if no:
                    refused = no
                elif capped:
                    say("(the cost cap was reached: nothing more)")
                elif not started:                      # (its first message was refused: the work starts now)
                    started = True
                    who.first(say)
                else:
                    who.answer(msg, say)
    while True:
        while True:                                # what came in meanwhile joins this turn
            try:
                item = q.get_nowait()
            except queue.Empty:
                break
            handle(item)
        if not refused:                            # (a refused request costs nothing)
            costs.add(model, 0.01)
        capped = capped or costs.over()
        result(turns, t0, costs, capped, error=refused)
        refused = None
        if done:
            return end()
        item = q.get()                             # idle until the next message, or one of its agents finishing
        if item is None:
            return end()
        t0, turns = time.time(), 0
        emit(init)                                 # every turn starts with an init (the real CLI's way)
        warn()
        handle(item)


MARKERS = ("CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_SESSION_ATTENDED",
           "CLAUDE_PID", "CLAUDE_EFFORT", "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH")


def main():
    a = sys.argv[1:]
    if os.environ.get("FAKE_ENV_LOG") and ("-p" in a):
        with open(os.environ["FAKE_ENV_LOG"], "a", encoding="utf-8") as f:
            f.write(json.dumps({"mode": "session" if "stream-json" in a else "print",
                                "markers": [k for k in MARKERS if k in os.environ]}) + "\n")
    if "--version" in a:
        print("0.0.0 (fake Claude Code for the studio's tests)")
    elif a[:2] == ["auth", "status"]:
        print(json.dumps({"loggedIn": True, "authMethod": "fake"}))
    elif "stream-json" in a:
        session(a)
    elif "-p" in a:
        if "--max-budget-usd" in a and os.environ.get("FAKE_CLAUDE_NO_BUDGET"):
            print("error: unknown option '--max-budget-usd'", file=sys.stderr)
            sys.exit(1)
        prompt = sys.stdin.read()                  # the prompt comes in on stdin
        if "<!-- am:critic -->" in prompt and os.environ.get("FAKE_CLAUDE_CRITIC_ERROR"):
            emit({"type": "result", "subtype": "success", "is_error": True, "result": "Invalid API key · Please run /login",
                  "total_cost_usd": 0.004})
            sys.exit(1)
        critic(prompt) if "<!-- am:critic -->" in prompt else story(prompt)
    else:
        print("fake claude: nothing to do", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
