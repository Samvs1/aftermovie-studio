"""Tests for the autonomous director, the critic and Claude's usage limit, with a stand-in for Claude Code (no usage
spent): python tests/test_director.py [--e2e] [--keep]

 1. the session plumbing (am/session.py) with tests/fake_claude.py: messages sent while a turn runs join it (one
    result, as on the real CLI); a message to an idle session starts a turn of its own; a background agent keeps the
    session working, then it starts a turn of its own; the costs as running totals; the cost cap
 2. the runner (director.Runner) in-process on a simulated clock: no reminder, nudge or closing while the director's
    agents work; the user's notes made during the run reach it at once (marked forwarded; old ones, done ones and a
    stopping run's not sent); the cost cap ends the run; the run settings in out/<version>_notes.md
 3. Claude's usage limit: read from Claude Code's own messages (the reset in its many forms; not a throttle, the
    director's words or the cost cap); a session counts each refused turn once; the runner waits with the clock stopped
    and carries on (the same session, a resumed one, or a fresh one told where the work is), or ends the run with what
    was left; continuable / wait_for_reset
 4. the critic's parts that need no project: the lenient parser, the house rules and anti-defaults read from the
    skill, a dry-run brief's sandbox (the deny rules)
 5. --e2e: a synthetic project (generated photos + tests/make_test_song.py's song) analysed with the offline
    fallbacks, then `studio.py direct` with the stand-in: a preview round (studio.py draft), the critic's notes on it
    as a message and in review/critic/, the run settings in the notes, project.json "runs"; then a note on the
    preview -> `direct --revise` (the note marked done); then a run Claude's usage limit stops and `direct --continue`
    (its own conversation through --resume); `story` and `critique` from the command line
Exit code 0 = everything passed.
"""
import argparse, glob, json, os, shutil, subprocess, sys, tempfile, time

TESTS = os.path.dirname(os.path.abspath(__file__))
STUDIO = os.path.dirname(TESTS)
sys.path.insert(0, os.path.join(STUDIO, "tools"))
PY = sys.executable
FAKE = os.path.join(TESTS, "fake_claude.py")
RESULTS = []


def say(res, what, detail=""):
    RESULTS.append((res, what))
    print(f"[{res}] {what}" + (f"\n       {detail}" if detail and res != "PASS" else ""), flush=True)


# ------------------------------------------------------------------ 1. the session plumbing
def session_check(tmp):
    print("== 1. the session plumbing (stand-ins)", flush=True)
    import am.session as ms
    from am.session import Session
    keep_cross = (ms.CROSS_S, ms.CROSS_SETTLE_S)
    ms.CROSS_S = 1.0
    d = os.path.join(tmp, "_session")
    cmd = [PY, FAKE, "-p", "--input-format", "stream-json", "--output-format", "stream-json"]
    s = Session(cmd, tmp, d, name="echo", env=dict(os.environ, FAKE_ECHO_S="2", PYTHONIOENCODING="utf-8")).start()

    def wait_turn(s, most=30):
        t0 = time.time()
        while time.time() - t0 < most and not s.turn_over():
            time.sleep(0.2)
        return s.turn_over()
    s.send("<!-- am:echo --> one", "first")
    time.sleep(0.5)
    s.send("two", "second")
    s.send("three", "third")
    over1 = wait_turn(s)
    n1 = len(s.results)
    time.sleep(2.5)
    n1b = len(s.results)
    joined = [m.get("joined") for m in s.status["messages_sent"]]
    texts = " ".join(e["text"] for e in s.status["events"])
    s.ack()
    time.sleep(3)
    s.send("four", "fourth")
    busy = s.busy
    fresh = s.quiet() < 1 and not s.hung(time.time(), 2)
    over2 = wait_turn(s)
    n2 = len(s.results)
    s.ack()
    ms.CROSS_S, ms.CROSS_SETTLE_S = 10.0, 6.0
    s.send("five", "fifth")
    time.sleep(0.5)
    s.send("six", "sixth (crosses the result)")
    t_res = time.time()
    while time.time() - t_res < 20 and len(s.results) < 3:
        time.sleep(0.1)
    t_res = time.time()
    early = s.turn_over(t_res + 3)
    over3 = wait_turn(s)
    late = time.time() - t_res >= 5
    ms.CROSS_S, ms.CROSS_SETTLE_S = keep_cross
    s.ack()
    s.stop("the test is done", wait=10)
    s.finish()
    say("PASS" if over1 and n1 == 1 and n1b == 1 and joined[:3] == [None, True, True] and "echo: two" in texts
        and "echo: three" in texts and busy and fresh and over2 and n2 == 2 and not early and over3 and late and not s.alive() else "FAIL",
        "the session: messages sent while it works join the running turn (one result); a message to an idle session starts one; "
        "a message just before a result waits for a turn of its own",
        f"results {n1} (then {n1b}), joined {joined}, after the fourth {n2}; quiet {fresh}; crossed: {early}, {over3}, {late}")
    d2 = os.path.join(tmp, "_session_agent")
    s = Session(cmd, tmp, d2, name="echo", env=dict(os.environ, FAKE_ECHO_S="1", FAKE_AGENT_S="5", PYTHONIOENCODING="utf-8")).start()
    s.send("<!-- am:echo-agent --> go", "first")
    t0 = time.time()
    while time.time() - t0 < 30 and not s.results:
        time.sleep(0.1)
    time.sleep(2.5)
    mid = {"results": len(s.results), "busy": s.busy, "working": s.working, "over": s.turn_over(), "hung": s.hung(time.time(), 0.9),
           "agents": [(a["description"], a["model"], a["state"]) for a in s.status["agents"]]}
    over = wait_turn(s, 40)
    st = s.status
    evs = [e["text"] for e in st["events"]]
    s.stop("the test is done", wait=10)
    s.finish()
    raw = [json.loads(x) for x in open(os.path.join(d2, "events.jsonl"), encoding="utf-8") if x.strip()]
    res = [e for e in raw if e.get("type") == "result"]
    a = (st.get("agents") or [{}])[0]
    ok = (mid["results"] == 1 and not mid["busy"] and mid["working"] and not mid["over"] and not mid["hung"]
          and mid["agents"] == [("echo agent", "haiku", "running")] and over and len(res) == 2
          and sum("session started" in x for x in evs) == 1 and any("started a turn of its own (its agent finished)" in x for x in evs)
          and a.get("state") == "done" and st["cost_usd"] == res[-1]["total_cost_usd"] < sum(r["total_cost_usd"] for r in res)
          and st["turns"] == sum(r["num_turns"] for r in res) and set(st["model_usage"]) == {"fake-echo", "claude-haiku-fake"})
    say("PASS" if ok else "FAIL", "a background agent: the turn ends while it works (working, no turn over), then the session's "
        "own turn; the cost is the latest running total, the turns add up, the costs per model",
        f"mid {mid}; {len(res)} results; cost {st['cost_usd']} ({[r['total_cost_usd'] for r in res]}); agent {a}")
    d3 = os.path.join(tmp, "_session_cap")
    s = Session(cmd + ["--max-budget-usd", "0.015"], tmp, d3, name="echo", env=dict(os.environ, FAKE_ECHO_S="0.2",
                                                                                   PYTHONIOENCODING="utf-8")).start()
    s.send("<!-- am:echo --> one", "first")
    first_hit = wait_turn(s) and s.status.get("budget_hit")
    s.ack()
    s.send("two", "second")
    wait_turn(s)
    s.stop("the test is done", wait=10)
    s.finish()
    say("PASS" if not first_hit and s.status.get("budget_hit") else "FAIL",
        "the cost cap (--max-budget-usd): the result that goes past it marks the session (budget_hit)",
        f"after the first turn {first_hit}, after the second {s.status.get('budget_hit')}")


# ------------------------------------------------------------------ 2. the runner, in-process
class FakeSession:
    """The director for the runner's checks: the test says when it ends a turn (over()), and reads what it was sent."""

    def __init__(self):
        import threading
        self.name, self.lock, self.closed, self.busy, self.returncode = "director", threading.RLock(), False, False, None
        self.status = {"events": [], "turns": 0, "cost_usd": 0.0, "messages_sent": [], "pid": 0, "agents": [], "model_usage": {}}
        self.sent, self._over, self._alive, self.proc, self.working = [], False, True, None, False
        self.inits = 1

    def start(self):
        return self

    def send(self, text, why):
        if self.closed or not self._alive:
            return False
        self.sent.append((why, text))
        self.status["messages_sent"].append({"t": 0, "why": why})
        return True

    def over(self):
        self._over = True

    def turn_over(self, now=None, settle=2):
        return self._over and not self.working

    def ack(self):
        self._over = False

    def alive(self):
        return self._alive and not self.closed

    def hung(self, now, after):
        return False

    def note(self, line):
        self.status["events"].append({"t": 0, "text": line})

    def close_input(self):
        self.closed = True

    def stop(self, reason=None, wait=20):
        self.closed = True

    def finish(self):
        pass

    def whys(self):
        return [w for w, _ in self.sent]


def make_runner(root, budget=3600, auto=False, factory=None, fallback=None, **st):
    import director
    shutil.rmtree(root, ignore_errors=True)
    for sub in ("cache/director/run-1", "out", "review"):
        os.makedirs(os.path.join(root, *sub.split("/")), exist_ok=True)
    s = FakeSession()
    t0 = time.time()
    status = dict({"run": 1, "state": "running", "kind": "first", "model": "fake", "effort": "max", "budget_s": budget,
                   "started": t0, "deadline": t0 + budget, "critiques": [], "critic_cost_usd": 0.0, "critic_model": "off",
                   "limit_hits": 0, "session_id": "sid-1"}, **st) | \
        {"events": s.status["events"], "messages_sent": s.status["messages_sent"], "agents": s.status["agents"]}
    s.status = status
    R = director.Runner(root, 1, os.path.join(root, "cache", "director", "run-1"), status, s, budget, t0, log=lambda x: None,
                        auto_continue=auto, new_session=factory, fallback=fallback)
    return R, s, t0


def runner_check(tmp):
    print("== 2. the runner (in-process, a scripted director)", flush=True)
    import director
    root = os.path.join(tmp, "_runner")
    out = {}
    R, s, t0 = make_runner(root)
    s.over()
    s.working = True
    for k in range(5):
        R.step(t0 + 60 + k)
    held = (s.whys(), s.closed)
    s.working = False
    R.step(t0 + 70)
    out["agents"] = (held, s.whys())
    ok_agents = held == ([], False) and s.whys() == ["no preview yet"] and not s.closed
    np = os.path.join(root, "review", "notes.json")

    def note(text, **kw):
        ns = json.load(open(np, encoding="utf-8")) if os.path.exists(np) else []
        ns.append(dict({"id": int(time.time() * 1000) + len(ns), "version": "v1", "t": 12.5, "text": text, "done": False}, **kw))
        json.dump(ns, open(np, "w", encoding="utf-8"))
    marks = lambda: {n["text"]: n.get("forwarded_run") for n in json.load(open(np, encoding="utf-8"))}   # noqa: E731
    R, s, t0 = make_runner(root)
    note("from before the run", id=int((t0 - 120) * 1000))
    note("done already", done=True)
    s.working = True
    note("more room before the drop")
    R.notes_step(t0 + 10)
    solo = s.sent[-1] if s.sent else ("", "")
    R.stop_reason = "stopped by the user"
    note("never mind")
    R.notes_step(t0 + 20)
    out["notes"] = (solo[0], marks())
    ok_notes = (solo[0] == "the user's note (1)" and "Then carry on" in solo[1] and "studio.py note-done" in solo[1]
                and "more room before the drop" in solo[1] and len(s.sent) == 1
                and marks() == {"from before the run": None, "done already": None, "more room before the drop": 1, "never mind": None})
    R, s, t0 = make_runner(root, max_usd=5.0)
    R.step(t0 + 30)
    s.status["budget_hit"] = True
    alive1 = R.step(t0 + 31)
    sent_cap = list(s.whys())
    s.over()
    R.step(t0 + 32)
    out["cap"] = (R.stop_reason, sent_cap, s.closed, alive1)
    ok_cap = R.stop_reason == "the cost cap ($5) was reached" and sent_cap == [] and s.closed and R.deadline <= t0 + 31
    # a preview delivered early: the nudge (no critic: the plain one)
    R, s, t0 = make_runner(root)
    open(os.path.join(root, "out", "v1_preview.mp4"), "wb").write(b"x" * 100)
    os.utime(os.path.join(root, "out", "v1_preview.mp4"), (t0 + 5, t0 + 5))
    s.over()
    R.step(t0 + 600)
    ok_nudge = s.whys() == ["use the time left"] and "Never the final" in s.sent[-1][1] and not s.closed
    s.over()
    R.nudges = 3
    R.step(t0 + 700)
    ok_nudge = ok_nudge and s.closed                      # (nothing more to say: the session is closed)
    out["nudge"] = s.whys()
    # the run settings in out/<version>_notes.md
    rs = {"run": 3, "kind": "first", "model": "opus", "model_used": "claude-opus-fake", "effort": "max", "ultracode": True,
          "max_usd": 5.0, "budget_hit": True, "budget_s": 3600, "started": time.time(), "wall_s": 1800,
          "stop_reason": "the cost cap ($5) was reached", "claude_version": "test", "turns": 12, "cost_usd": 4.22,
          "model_usage": {"claude-opus-fake": {"cost_usd": 4.1}, "claude-haiku-fake": {"cost_usd": 0.12},
                          "claude-quick-fake": {"cost_usd": 0.003}},
          "agents": [{"description": "log the photos", "model": "haiku", "state": "done", "started": 100, "ended": 340}],
          "critic_model": "sonnet", "critic_effort": "medium", "critic_cost_usd": 0.4, "critiques": [{}, {}],
          "preview": "out/v1_preview.mp4"}
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(os.path.join(root, "out"))
    open(os.path.join(root, "out", "v1_notes.md"), "w", encoding="utf-8").write("# v1\nThe director's own words.\n")
    director.append_settings(root, rs, "v1")
    director.append_settings(root, rs, "v1")              # (twice: one record, the latest)
    rep = open(os.path.join(root, "out", "v1_notes.md"), encoding="utf-8").read()
    ok_rep = ("The director's own words." in rep and rep.count("## Run settings (written by the studio)") == 1
              and "ultracode on; cost cap $5 (reached: the run ended there)" in rep
              and "- Costs per model: opus-fake $4.10 (the director), haiku-fake $0.12 (agents), quick-fake <$0.01 · the critic "
                  "sonnet $0.40 · total $4.62" in rep
              and "- Agents: 1 (haiku 1): log the photos (haiku, done in 4 min)" in rep
              and "- Delivered: out/v1_preview.mp4" in rep and director.total_cost(rs) == 4.62)
    out["report"] = [x for x in rep.splitlines() if x.startswith("- ")]
    shutil.rmtree(root, ignore_errors=True)
    bad = [k for k, v in (("agents at work", ok_agents), ("the user's notes", ok_notes), ("the cost cap", ok_cap),
                          ("the early-finish nudge", ok_nudge), ("the run settings", ok_rep)) if not v]
    say("FAIL" if bad else "PASS", "the runner: no reminder, nudge or closing while the director's agents work (then the reminder); "
        "the user's notes at once (marked forwarded; old, done ones and a stopping run's not sent); the cost cap ends the run; "
        "the nudge for an early preview; the run settings in out/<version>_notes.md", ("failed: " + "; ".join(bad) + f" {out}")[:2500] if bad else "")


# ------------------------------------------------------------------ 3. Claude's usage limit
def limit_check(tmp):
    print("== 3. Claude's usage limit (in-process)", flush=True)
    import datetime as dt
    import director
    from am.session import Session, reset_at, limit_of
    bad, out = [], {}
    now = time.time()
    r = {k: reset_at(k, now) for k in ("Claude AI usage limit reached|1762178400", "resets in 2h 15m", "resets 3pm",
                                       "resets 18:05Z", "resets 3pm (Europe/Brussels)", "resets Mon 10am", "resets Nov 4, 10am",
                                       "no time here", "resets Feb 30, 1am")}
    loc = lambda t: dt.datetime.fromtimestamp(t)                     # noqa: E731
    try:
        from zoneinfo import ZoneInfo
        bxl = dt.datetime.fromtimestamp(r["resets 3pm (Europe/Brussels)"], ZoneInfo("Europe/Brussels"))
    except Exception:
        bxl = loc(r["resets 3pm (Europe/Brussels)"])
    utc = dt.datetime.fromtimestamp(r["resets 18:05Z"], dt.timezone.utc)
    ok_read = (r["Claude AI usage limit reached|1762178400"] == 1762178400 and r["resets in 2h 15m"] == now + 8100
               and (loc(r["resets 3pm"]).hour, loc(r["resets 3pm"]).minute) == (15, 0) and -60 < r["resets 3pm"] - now <= 86400
               and (utc.hour, utc.minute) == (18, 5) and (bxl.hour, bxl.minute) == (15, 0)
               and loc(r["resets Mon 10am"]).weekday() == 0 and loc(r["resets Mon 10am"]).hour == 10
               and (loc(r["resets Nov 4, 10am"]).month, loc(r["resets Nov 4, 10am"]).day) == (11, 4)
               and r["no time here"] is None and r["resets Feb 30, 1am"] is None)
    syn = lambda text, **kw: dict({"type": "assistant", "parent_tool_use_id": None,           # noqa: E731
                                   "message": {"model": "<synthetic>", "content": [{"type": "text", "text": text}]}}, **kw)
    hit = limit_of(syn("You've hit your session limit · resets 3pm", error="rate_limit"), None, now)
    old = limit_of({"type": "result", "is_error": True, "result": "Claude AI usage limit reached|1762178400"}, None, now)
    nots = [limit_of(syn("API Error: Server is temporarily limiting requests (not your usage limit)", error="rate_limit"), None, now),
            limit_of({"type": "assistant", "message": {"model": "opus", "content": [{"type": "text", "text": "I'll keep it under the usage limit"}]}}, None, now),
            limit_of({"type": "result", "is_error": True, "subtype": "error_max_budget_usd", "result": "Budget limit reached"}, None, now)]
    ok_of = hit and hit["resets_at"] == r["resets 3pm"] and old and old["resets_at"] == 1762178400 and nots == [None] * len(nots)
    out["read"] = (r, hit, old, nots)
    if not ok_read:
        bad.append("reset_at")
    if not ok_of:
        bad.append("limit_of")
    cmd = [PY, FAKE, "-p", "--input-format", "stream-json", "--output-format", "stream-json"]
    d = os.path.join(tmp, "_session_limit")
    s = Session(cmd, tmp, d, name="echo", env=dict(os.environ, FAKE_ECHO_S="0.2", FAKE_LIMIT="2:2", FAKE_LIMIT_WARN="1",
                                                    PYTHONIOENCODING="utf-8")).start()

    def wait(most=20):
        t0 = time.time()
        while time.time() - t0 < most and not s.turn_over():
            time.sleep(0.1)
        s.ack()
    s.send("<!-- am:echo --> one", "first")
    wait()
    cost1 = s.status["cost_usd"]
    t_hit = time.time()
    s.send("two", "second")
    wait()
    hits2, lim, cost2 = s.status["limit_hits"], dict(s.status.get("limit") or {}), s.status["cost_usd"]
    time.sleep(2.3)
    s.send("three", "third")
    wait()
    s.stop("the test is done", wait=10)
    s.finish()
    evs = [e["text"] for e in s.status["events"]]
    ok_sess = (hits2 == 1 and s.status["limit_hits"] == 1 and lim.get("kind") == "five_hour"
               and 0 < (lim.get("resets_at") or 0) - t_hit <= 3 and cost2 == cost1 and s.status["cost_usd"] > cost2
               and sum("⛔ Claude's usage limit stopped the echo" in x for x in evs) == 1 and any("echo: three" in x for x in evs))
    d2 = os.path.join(tmp, "_session_resume_bad")
    s = Session(cmd + ["--resume", "nope"], tmp, d2, name="director", env=dict(os.environ, FAKE_RESUME_BAD="1", PYTHONIOENCODING="utf-8")).start()
    s.send("carry on", "continuing")
    t0 = time.time()
    while time.time() - t0 < 10 and s.alive():
        time.sleep(0.1)
    s.finish()
    ok_bad = not s.alive() and s.inits == 0 and "No conversation found" in open(os.path.join(d2, "stderr.log"), encoding="utf-8").read()
    out["session"] = (hits2, lim, cost1, cost2, [x for x in evs if "limit" in x])
    if not ok_sess:
        bad.append("a session with the stand-in")
    if not ok_bad:
        bad.append("a --resume that Claude Code doesn't have")
    root = os.path.join(tmp, "_runner_limit")

    def limit(R, t, resets_at):
        R.status["limit_hits"] += 1
        R.status["limit"] = {"text": "You've hit your session limit · resets 3pm", "resets_at": resets_at, "kind": "five_hour", "at": t}
    # 1. auto_continue: it waits (nothing sent, no reminder, no note), then carries on with the clock moved
    R, s, t0 = make_runner(root, auto=True)
    limit(R, t0 + 100, t0 + 600)
    s.over()
    a1 = R.step(t0 + 100)
    st1 = (R.status["state"], dict(R.status.get("paused") or {}))
    np = os.path.join(root, "review", "notes.json")
    json.dump([{"id": int((t0 + 1) * 1000), "version": "v1", "t": 3.0, "text": "a note while it waits", "done": False}],
              open(np, "w", encoding="utf-8"))
    R.notes_step(t0 + 300)
    a2 = R.step(t0 + 400)
    held = list(s.whys())
    t_on = t0 + 600 + director.RESET_MARGIN_S + 1
    a3 = R.step(t_on)
    moved = R.deadline - (t0 + 3600)
    ok1 = (a1 and a2 and a3 and st1[0] == "paused" and st1[1].get("until") == t0 + 600 + director.RESET_MARGIN_S
           and st1[1].get("left_s") == 3500 and held == [] and s.whys() == ["the usage limit reset: carry on"]
           and "you still have 58 min" in s.sent[-1][1] and abs(moved - (t_on - (t0 + 100))) < 1 and R.status["state"] == "running"
           and len(R.status["pauses"]) == 1 and R.status["pauses"][0]["end"] == "carried on" and abs(R.active(t_on) - 100) < 1)
    R.notes_step(t_on + 10)
    ok1 = ok1 and s.whys()[-1] == "the user's note (1)"
    out["auto"] = (st1, held, s.whys(), moved, R.status.get("pauses"))
    if not ok1:
        bad.append("auto_continue: wait, then carry on")
    # 2. no reset time given: it tries again after RETRY_S
    R, s, t0 = make_runner(root, auto=True)
    limit(R, t0 + 50, None)
    R.step(t0 + 50)
    p2 = dict(R.status.get("paused") or {})
    R.step(t0 + 50 + director.RETRY_S + 1)
    ok2 = p2.get("until") == t0 + 50 + director.RETRY_S and s.whys() == ["the usage limit reset: carry on"]
    if not ok2:
        bad.append("no reset time: try again later")
    # 3. without auto_continue: the run ends there, with what was left
    R, s, t0 = make_runner(root, auto=False)
    limit(R, t0 + 100, t0 + 600)
    s.over()
    R.step(t0 + 100)
    R.step(t0 + 101)
    cut3 = dict(R.cut or {})
    ok3 = ("Claude's usage limit was reached" in (R.stop_reason or "") and cut3.get("why") == "limit" and cut3.get("left_s") == 3500
           and cut3.get("resets_at") == t0 + 600 and s.whys() == [] and s.closed and R.status["state"] == "finishing")
    out["no auto"] = (R.stop_reason, cut3, s.whys(), s.closed)
    if not ok3:
        bad.append("without auto_continue: the run ends")
    # 4. a reset days away: it ends; 5. stopped while it waits: it ends
    R, s, t0 = make_runner(root, auto=True)
    limit(R, t0 + 100, t0 + 3 * 86400)
    R.step(t0 + 100)
    ok4 = R.pause is None and "too far to wait" in (R.stop_reason or "")
    R, s, t0 = make_runner(root, auto=True)
    limit(R, t0 + 100, t0 + 600)
    R.step(t0 + 100)
    open(os.path.join(root, "cache", "director", "STOP"), "w").write("x")
    a5 = R.step(t0 + 200)
    ok5 = a5 is False and R.stop_reason == "stopped by the user" and s.whys() == [] and (R.cut or {}).get("left_s") == 3500
    if not ok4:
        bad.append("a reset too far away")
    if not ok5:
        bad.append("stopped while it waits")
    # 6. its session ended meanwhile: resumed (--resume sid-1); one Claude Code can't resume: a fresh session
    made = []
    box = {}

    def factory(good):
        def f(rid=None):
            x = FakeSession()
            x.status = box["R"].status
            x.inits = 1 if (good or rid is None) else 0
            x._alive = good or rid is None
            made.append((rid, x))
            return x
        return f
    for good in (True, False):
        made.clear()
        R6, s, t0 = make_runner(root, auto=True, factory=factory(good),
                                fallback=lambda what, left, dl: f"FRESH BRIEF: This carries on {what}.")
        box["R"] = R6
        limit(R6, t0 + 100, t0 + 600)
        R6.step(t0 + 100)
        s._alive = False
        old_wait = director.RESUME_WAIT_S
        director.RESUME_WAIT_S = 1
        R6.step(t0 + 700)
        director.RESUME_WAIT_S = old_wait
        new = made[-1][1] if made else None
        if good:
            ok6 = [m[0] for m in made] == ["sid-1"] and R6.s is new and new.whys() == ["the usage limit reset: carry on"]
        else:
            ok6 = ([m[0] for m in made] == ["sid-1", None] and R6.s is new
                   and new.whys() == ["the brief (a fresh session: the conversation couldn't be resumed)"]
                   and "FRESH BRIEF: This carries on this run (run 1)" in new.sent[0][1]
                   and "FRESH BRIEF" in open(os.path.join(root, "cache", "director", "run-1", "brief.md"), encoding="utf-8").read())
        out[f"relaunch {'good' if good else 'bad'}"] = ([m[0] for m in made], new.whys() if new else None)
        if not ok6:
            bad.append("its session resumed" if good else "a fresh session when it can't be resumed")
    # 7. continuable() and wait_for_reset()
    pd = os.path.join(tmp, "_continue")
    for k in (1, 2, 3):
        os.makedirs(os.path.join(pd, "cache", "director", f"run-{k}"))
    t = time.time()
    json.dump({"run": 1, "state": "done", "kind": "first", "budget_s": 5400, "started": t - 4000, "wall_s": 3000, "left_s": 2400,
               "stop_reason": "Claude's usage limit was reached", "session_id": "sid-a", "cost_usd": 3.0,
               "cut_off": {"why": "limit", "at": t - 1000, "left_s": 2400, "resets_at": t + 900}, "result": "no preview"},
              open(os.path.join(pd, "cache", "director", "run-1", "status.json"), "w"))
    json.dump({"run": 2, "state": "stopped", "result": "not started", "kind": "continue"},
              open(os.path.join(pd, "cache", "director", "run-2", "status.json"), "w"))
    json.dump({"run": 3, "state": "dry-run"}, open(os.path.join(pd, "cache", "director", "run-3", "status.json"), "w"))
    json.dump({"run": 2, "state": "stopped", "dir": "cache/director/run-2", "updated": t},
              open(os.path.join(pd, "cache", "director", "current.json"), "w"))
    c = director.continuable(pd) or {}
    ok7 = (c.get("run") == 1 and c.get("left_s") == 2400 and c.get("budget_s") == 2400 and c.get("resets_at") == t + 900
           and c.get("limit") and c.get("cut") and c.get("resumable") and c.get("session_id") == "sid-a" and c.get("conv_cost_usd") == 3.0)
    st = {"run": 4, "budget": "40 min", "state": "waiting", "events": []}
    rd = os.path.join(pd, "cache", "director", "run-4")
    os.makedirs(rd)
    t0 = time.time()
    w1 = director.wait_for_reset(pd, rd, st, t0 + 1.2, log=lambda x: None)
    waited = time.time() - t0
    cur = json.load(open(os.path.join(pd, "cache", "director", "current.json"), encoding="utf-8"))
    open(os.path.join(pd, "cache", "director", "STOP"), "w").write("x")
    t0 = time.time()
    w2 = director.wait_for_reset(pd, rd, st, t0 + 60, log=lambda x: None)
    ok7 = ok7 and w1 is True and 1.1 <= waited < 4 and cur.get("state") == "waiting" and w2 is False and time.time() - t0 < 5
    out["continue"] = (c, w1, round(waited, 1), cur.get("state"), w2)
    if not ok7:
        bad.append("continuable / wait_for_reset")
    say("FAIL" if bad else "PASS", "Claude's usage limit: read from Claude Code's own messages; a session counts each refused turn "
        "once; the runner waits with the clock stopped and carries on (the same session, a resumed one, or a fresh one told "
        "where the work is), or ends the run with what was left; continuable / wait_for_reset",
        ("failed: " + "; ".join(bad) + f" {out}")[:3000] if bad else "")


# ------------------------------------------------------------------ 4. the critic's parts and the sandbox
def parts_check(tmp):
    print("== 4. the critic's parser, the house rules, the sandbox", flush=True)
    import critic, director
    md, data, warn = critic.parse("# Critique\ntext\n```json\n{\"verdict\": \"v\", \"scores\": {\"ambition\": 11, \"story\": \"6\"}, "
                                  "\"problems\": [{\"severity\": \"HIGH\", \"t0\": \"3.5\", \"what\": \"x\"}]}\n```\n")
    md2, data2, warn2 = critic.parse("no json here")
    rules, anti = critic.house_rules(), critic.anti_defaults()
    ok_parse = (data["scores"]["ambition"] == 10 and data["scores"]["story"] == 6 and data["scores"]["craft"] is None
                and data["problems"][0]["severity"] == "high" and data["problems"][0]["t0"] == 3.5 and "```" not in md
                and not warn and data2["scores"] is None and "no readable json" in warn2)
    ok_rules = "Music first" in rules and "No photo twice" in rules and "scrapbook" in anti.lower() and "Device budget" in anti
    pd = os.path.join(tmp, "proj")
    os.makedirs(os.path.join(pd, "photos"), exist_ok=True)
    deny = director.deny_rules(pd)
    rp = director.rule_path
    ok_deny = (f"Write({rp(os.path.join(STUDIO, 'tools'))}/**)" in deny and f"Edit({rp(os.path.join(pd, 'photos'))}/**)" in deny
               and f"Write({rp(os.path.join(pd, 'review', 'notes.json'))})" in deny and "Bash(curl:*)" in deny
               and not any(rp(pd) + "/**" in x for x in deny))
    say("PASS" if ok_parse and ok_rules and ok_deny else "FAIL",
        "the critic's lenient parser (the last json block, scores clamped, a missing block kept as the report); the house rules "
        "and anti-defaults read from the skill; the sandbox's deny rules (the studio, photos/, the user's notes; not the project)",
        f"parse {ok_parse} {data} {warn2}; rules {ok_rules}; deny {ok_deny} {deny[-12:]}")


# ------------------------------------------------------------------ 5. end to end
def studio(*args, env=None, timeout=1800, check=True):
    r = subprocess.run([PY, os.path.join(STUDIO, "tools", "studio.py"), *args], cwd=STUDIO, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env or os.environ, timeout=timeout, stdin=subprocess.DEVNULL)
    if check and r.returncode:
        raise RuntimeError(f"studio.py {' '.join(args)} failed (exit {r.returncode}):\n" + (r.stdout + r.stderr)[-3000:])
    return r


def make_project(name):
    """A synthetic project: generated photos (no faces needed) and tests/make_test_song.py's song, analysed."""
    from PIL import Image, ImageDraw
    pdir = os.path.join(STUDIO, "projects", name)
    shutil.rmtree(pdir, ignore_errors=True)
    plain = name.lstrip("_")                        # (`new` makes a slug without the "_" of an internal project)
    shutil.rmtree(os.path.join(STUDIO, "projects", plain), ignore_errors=True)
    studio("new", plain, "--title", "Director test")
    os.replace(os.path.join(STUDIO, "projects", plain), pdir)
    for k in range(40):
        im = Image.new("RGB", (1200, 800) if k % 3 else (800, 1200), ((k * 53) % 255, (k * 97) % 255, (k * 31) % 255))
        d = ImageDraw.Draw(im)
        for j in range(6):
            d.ellipse([60 + j * 150, 100 + (k * 37 + j * 71) % 500, 200 + j * 150, 240 + (k * 37 + j * 71) % 500],
                      fill=((j * 80) % 255, 200, (k * 11) % 255))
        im.save(os.path.join(pdir, "photos", f"img{k:03d}.jpg"), quality=88)
    mk = os.path.join(TESTS, "make_test_song.py")
    if not os.path.exists(mk):
        raise RuntimeError("tests/make_test_song.py is missing (the synthetic song)")
    sd = os.path.join(pdir, "cache", "_song")
    r = subprocess.run([PY, mk, sd], capture_output=True, text=True)
    if r.returncode or not os.path.exists(os.path.join(sd, "test_song.mp3")):
        raise RuntimeError("make_test_song.py failed: " + (r.stdout + r.stderr)[-1500:])
    shutil.copyfile(os.path.join(sd, "test_song.mp3"), os.path.join(pdir, "music", "test_song.mp3"))
    pj = json.load(open(os.path.join(pdir, "project.json"), encoding="utf-8"))
    pj.update(occasion="a test trip", vibe="bright, quick", avoid="the red photo", song={"file": "test_song.mp3", "artist": "", "title": ""})
    json.dump(pj, open(os.path.join(pdir, "project.json"), "w", encoding="utf-8"), indent=1)
    studio("ingest", name, timeout=3600)
    return pdir


def e2e_check(keep):
    print("== 5. end to end: a synthetic project, `direct` with the stand-in", flush=True)
    name = "_test-director"
    try:
        pdir = make_project(name)
    except Exception as e:
        say("FAIL", "the synthetic project (photos + song, ingest with the offline fallbacks)", str(e)[-2500:])
        return
    env = dict(os.environ, AM_CLAUDE=FAKE, PYTHONIOENCODING="utf-8", AM_RENDER_LOCK_FILE=os.path.join(pdir, "cache", "test_render.lock"))
    t0 = time.time()
    r = studio("direct", name, "--budget", "20m", "--critic-model", "fake", "--no-nudge", env=env, check=False, timeout=2400)
    pj = json.load(open(os.path.join(pdir, "project.json"), encoding="utf-8"))
    last = (pj.get("runs") or [{}])[-1]
    rdir = os.path.join(pdir, "cache", "director", f"run-{last.get('run')}")
    rs = json.load(open(os.path.join(rdir, "status.json"), encoding="utf-8")) if os.path.exists(os.path.join(rdir, "status.json")) else {}
    notes = open(os.path.join(pdir, "out", "draft_notes.md"), encoding="utf-8").read() if os.path.exists(os.path.join(pdir, "out", "draft_notes.md")) else ""
    crits = sorted(glob.glob(os.path.join(pdir, "review", "critic", "draft_preview_*.json")))
    msgs = open(os.path.join(rdir, "messages.md"), encoding="utf-8").read() if os.path.exists(os.path.join(rdir, "messages.md")) else ""
    brief = open(os.path.join(rdir, "brief.md"), encoding="utf-8").read() if os.path.exists(os.path.join(rdir, "brief.md")) else ""
    cmd = json.load(open(os.path.join(rdir, "command.json"), encoding="utf-8"))["cmd"] if os.path.exists(os.path.join(rdir, "command.json")) else []
    ok = (r.returncode == 0 and last.get("preview") == "out/draft_preview.mp4" and rs.get("result") == "preview"
          and "## Run settings (written by the studio)" in notes and "the test stand-in" in notes and crits
          and any(c.get("used") in ("sent", "in the nudge") for c in rs.get("critiques") or [])
          and "The studio's critic (" in msgs and "studio.py preview" in brief and "Never run `studio.py final`" in brief
          and "never show / mention" in brief.lower() and "the red photo" in brief
          and "--max-budget-usd" not in cmd and cmd[cmd.index("--effort") + 1] == "max" and "Workflow" not in cmd
          and not os.path.exists(os.path.join(pdir, "out", "draft.mp4")))
    say("PASS" if ok else "FAIL", "`direct`: the stand-in makes a preview round (studio.py draft); the critic's notes reach it as a "
        "message and land in review/critic/; the run settings in out/draft_notes.md; project.json runs; the brief (preview only, "
        "the avoid list) and the command (effort max, no cap, no Workflow); no final rendered",
        f"exit {r.returncode} in {time.time() - t0:.0f} s; run {last}; critiques {[os.path.basename(c) for c in crits]} "
        f"{[(c.get('video'), c.get('used')) for c in rs.get('critiques') or []]}; " + (r.stdout + r.stderr)[-1500:])
    # a note on the preview -> a review round
    from am.notes import update_notes
    nid = int(time.time() * 1000)
    update_notes(pdir, lambda ns: ns.append({"id": nid, "version": "draft", "t": 6.0, "text": "hold the first photo longer",
                                             "done": False, "at": time.strftime("%Y-%m-%d %H:%M")}))
    r = studio("direct", name, "--revise", "--budget", "20m", "--critic-model", "off", "--no-nudge", env=env, check=False, timeout=2400)
    from am.notes import read_notes
    n = next((x for x in read_notes(pdir) if x.get("id") == nid), {})
    pj = json.load(open(os.path.join(pdir, "project.json"), encoding="utf-8"))
    last = (pj.get("runs") or [{}])[-1]
    rdir = os.path.join(pdir, "cache", "director", f"run-{last.get('run')}")
    brief = open(os.path.join(rdir, "brief.md"), encoding="utf-8").read() if os.path.exists(os.path.join(rdir, "brief.md")) else ""
    say("PASS" if r.returncode == 0 and n.get("done") and "re-cut" in (n.get("fix") or "") and last.get("kind") == "revise"
        and "hold the first photo longer" in brief and f"(id {nid})" in brief and "0:06.00" in brief else "FAIL",
        "`direct --revise`: the note in the brief with its context and id; the stand-in marks it done (studio.py note-done)",
        f"exit {r.returncode}; note {n}; run {last}; " + (r.stdout + r.stderr)[-1200:])
    # Claude's usage limit stops a run (no waiting) -> `direct --continue`
    open(os.path.join(pdir, "FAKE_LIMIT"), "w").write("1:-1")
    r = studio("direct", name, "--budget", "20m", "--critic-model", "off", "--no-auto-continue", env=env, check=False, timeout=600)
    os.remove(os.path.join(pdir, "FAKE_LIMIT"))
    pj = json.load(open(os.path.join(pdir, "project.json"), encoding="utf-8"))
    cut = (pj.get("runs") or [{}])[-1]
    import director
    c = director.continuable(pdir) or {}
    r2 = studio("direct", name, "--continue", "--critic-model", "off", "--no-nudge", env=env, check=False, timeout=2400)
    pj = json.load(open(os.path.join(pdir, "project.json"), encoding="utf-8"))
    last = (pj.get("runs") or [{}])[-1]
    rdir = os.path.join(pdir, "cache", "director", f"run-{last.get('run')}")
    cmd = json.load(open(os.path.join(rdir, "command.json"), encoding="utf-8"))["cmd"] if os.path.exists(os.path.join(rdir, "command.json")) else []
    first = open(os.path.join(rdir, "brief.md"), encoding="utf-8").read() if os.path.exists(os.path.join(rdir, "brief.md")) else ""
    say("PASS" if "usage limit" in (cut.get("stop_reason") or "") and c.get("limit") and c.get("resumable") and c.get("budget_s", 0) >= 900
        and r2.returncode == 0 and last.get("kind") == "continue" and (last.get("continues") or {}).get("resumed")
        and "--resume" in cmd and "The studio again. Your run" in first and last.get("preview") else "FAIL",
        "a run Claude's usage limit stops (no auto-continue) ends with what it had left; `direct --continue` resumes its "
        "conversation (--resume) with the studio's carry-on first and delivers a preview",
        f"cut {cut.get('stop_reason')}; continuable {c}; continue: exit {r2.returncode}, {last}; " + (r2.stdout + r2.stderr)[-1200:])
    # story and critique from the command line
    r = studio("story", name, env=env, check=False)
    from am.util import song_slug
    sp = os.path.join(pdir, "song", song_slug(pdir), "song-story.md")
    r2 = studio("critique", name, "draft", "--model", "fake", env=env, check=False)
    say("PASS" if r.returncode == 0 and "Drafted by the test stand-in" in open(sp, encoding="utf-8").read()
        and r2.returncode == 0 and "critic: ambition 6 · song fit 7 · story 6" in r2.stdout else "FAIL",
        "`story` writes the song story; `critique <p> draft` looks at the newest render of a version",
        (r.stdout + r.stderr)[-600:] + (r2.stdout + r2.stderr)[-900:])
    web_check(name, env)
    if not keep:
        shutil.rmtree(pdir, ignore_errors=True)


def web_check(name, env):
    """The web app with the stand-in: the Direct page's settings kept, a run started from it (POST direct), its status
    polled (GET director) until it ends, the critic asked from the Review page (POST critique); the Direct and Review
    pages drawn in headless Chromium without a JS error."""
    import socket, urllib.request
    print("== 5b. the web app: Direct and Review (stand-in)", flush=True)
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        port = so.getsockname()[1]
    srv = subprocess.Popen([PY, os.path.join(STUDIO, "tools", "studio.py"), "serve", "--port", str(port), "--no-browser"],
                           cwd=STUDIO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"

    def call(path, body=None):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"}, method="POST" if body is not None else "GET")
        return json.loads(urllib.request.urlopen(req, timeout=30).read().decode("utf-8"))
    out, errs = {}, []
    try:
        for _ in range(50):
            try:
                call("/api/projects")
                break
            except Exception:
                time.sleep(0.2)
        pj = call(f"/api/p/{name}/director-settings", {"budget": "20", "model": "fake", "effort": "high", "critic_model": "fake",
                                                      "ultracode": False, "max_usd": "", "auto_continue": True})
        out["saved"] = pj.get("director")
        run0 = (call(f"/api/p/{name}/director") or {}).get("run") or 0
        call(f"/api/p/{name}/direct", {"budget": "20", "model": "fake", "effort": "high", "critic_model": "fake", "nudge": False})
        t0, d = time.time(), {}
        while time.time() - t0 < 1500:
            d = call(f"/api/p/{name}/director") or {}
            j = call(f"/api/p/{name}/job")
            if (d.get("run") or 0) > run0 and d.get("state") in ("done", "stopped") and not j.get("running"):
                break
            time.sleep(2)
        out["run"] = {k: d.get(k) for k in ("run", "state", "result", "preview", "effort", "stop_reason", "total_usd")}
        out["crit_in_run"] = [c.get("used") for c in d.get("critiques") or []]
        st = call(f"/api/p/{name}")
        out["critiques"] = len((st.get("critiques") or {}).get("items") or [])
        try:
            from playwright.sync_api import sync_playwright
            exe = "/opt/pw-browsers/chromium" if os.path.isfile("/opt/pw-browsers/chromium") else None
            with sync_playwright() as p:
                b = p.chromium.launch(executable_path=exe, args=["--no-sandbox"]) if exe else p.chromium.launch()
                pg = b.new_page()
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.goto(f"{base}/#{name}/direct")
                pg.wait_for_selector("#dir-ev", timeout=15000)
                out["direct_page"] = pg.inner_text("#pane")[:4000]
                pg.goto(f"{base}/#{name}/review")
                pg.wait_for_selector("#wcritic", timeout=15000)
                out["review_page"] = pg.inner_text("#wcritic")[:2000]
                b.close()
        except ImportError:
            out["direct_page"] = out["review_page"] = "(no playwright)"
    finally:
        srv.terminate()
        try:
            srv.wait(10)
        except Exception:
            srv.kill()
    ok = (out.get("saved", {}).get("effort") == "high" and out["saved"].get("auto_continue") is True
          and out["run"].get("state") == "done" and out["run"].get("result") == "preview" and out["run"].get("effort") == "high"
          and out["critiques"] >= 1 and not errs and "Run " in out.get("direct_page", "") and "Costs" in out.get("direct_page", "")
          and ("ambition" in out.get("review_page", "") or out.get("review_page") == "(no playwright)"))
    say("PASS" if ok else "FAIL", "the web app: the Direct form's settings kept, a run started from it and watched to its end, the "
        "critic's notes on the Review page; the pages drawn without a JS error", f"{ {k: v for k, v in out.items() if 'page' not in k} }; "
        f"errors {errs}; review page: {out.get('review_page', '')[:300]!r}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--e2e", action="store_true", help="also the end-to-end run on a synthetic project (needs ffmpeg; ~5-10 min)")
    ap.add_argument("--keep", action="store_true", help="keep the synthetic project (projects/_test-director)")
    ap.add_argument("--only", default="", help="comma-separated: session, runner, limit, parts, e2e")
    a = ap.parse_args()
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    tmp = tempfile.mkdtemp(prefix="am_director_test_")
    try:
        for key, fn in (("session", session_check), ("runner", runner_check), ("limit", limit_check), ("parts", parts_check)):
            if not only or key in only:
                try:
                    fn(tmp)
                except Exception as e:
                    import traceback
                    say("FAIL", f"{key}: crashed", traceback.format_exc()[-2000:])
        if a.e2e or "e2e" in only:
            e2e_check(a.keep)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    bad = [w for r, w in RESULTS if r == "FAIL"]
    print(f"\n{len(RESULTS) - len(bad)} passed, {len(bad)} failed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
