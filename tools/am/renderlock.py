"""The render queue: one video render at a time on this machine.

Parallel agents speed up thinking and coding, not rendering: two renders at once only share the same CPU (or GPU)
and both take twice as long. So every video render (render.py: previews, finals, the board and stills aside) takes a
machine-wide lock first and waits its turn:

    from am.renderlock import render_queue
    with render_queue("v2 preview -> out/v2_preview.mp4"):
        ...render...

The lock is a file, <studio>/cache/render.lock, created with os.open(O_CREAT | O_EXCL) (atomic on Windows and POSIX)
and holding {pid, who, what, started, token}. `who` is AM_RENDER_WHO (the director runner sets it: "the director";
an interactive render is "a render"). While it waits, it prints `waiting for the render queue: <who> (<what>) since <time>` at once and then
every ~30 s. A lock is stale (taken over) when its process is gone (a render killed with its tree leaves the file
behind), when it has been held for 6 h (a hung render doesn't block the machine for good), or when it shows no sign
of life for 10 min (the holder touches the file every minute, so a pid that Windows gave to another process doesn't
keep the queue). Stale locks are broken under a second short lock, so two waiters can't both break one and then
remove each other's new lock.
AM_RENDER_LOCK=0 turns the queue off (renders then run side by side, as before). AM_RENDER_LOCK_FILE moves the lock
(the tests use their own).
"""
import json, os, threading, time, uuid
from contextlib import contextmanager

from .util import STUDIO
from .claude import pid_alive

MAX_HOLD_S = 6 * 3600       # held this long: taken over whatever its pid says (a hung render)
QUIET_S = 600               # no sign of life for this long: the holder is gone (its pid may be someone else's now)
BEAT_S = 60                 # the holder touches the lock this often
SAY_S = 30                  # a waiting render says so this often


def lock_path():
    return os.environ.get("AM_RENDER_LOCK_FILE") or os.path.join(STUDIO, "cache", "render.lock")


def enabled():
    return os.environ.get("AM_RENDER_LOCK", "1").strip().lower() not in ("0", "off", "no", "false")


def read(path=None):
    """The lock's record ({pid, who, what, started, token, age_s}), {} when there is a lock file but it can't be read
    yet (being written), or None when the queue is free."""
    path = path or lock_path()
    try:
        age = time.time() - os.path.getmtime(path)
        with open(path, encoding="utf-8") as f:
            txt = f.read()
    except FileNotFoundError:
        return None
    except OSError:
        return {}
    try:
        d = json.loads(txt)
    except ValueError:
        d = {}
    if isinstance(d, dict) and d:
        d["age_s"] = round(age)
        return d
    return {"age_s": round(age)}


def holder(path=None):
    """Who has the render queue right now: (record, alive) or (None, False) when it is free. Used by status lines."""
    d = read(path)
    if d is None:
        return None, False
    return d, not stale(d)


def stale(d):
    """A lock nobody holds any more: its process is gone, it was held for MAX_HOLD_S, or it showed no sign of life for
    QUIET_S. A record that can't be read yet is someone in the middle of writing it: stale only after a minute."""
    if not d.get("pid"):
        return d.get("age_s", 0) > 60
    try:
        held = time.time() - float(d.get("started"))
    except (TypeError, ValueError):
        held = 0
    return not pid_alive(d["pid"]) or held > MAX_HOLD_S or d.get("age_s", 0) > QUIET_S


def _try_create(path, rec):
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(rec))
    return True


def _break_stale(path, seen, log):
    """Remove a stale lock, but only the one we judged stale: under a short second lock, re-read it first."""
    brk = path + ".break"
    if not _try_create(brk, {"pid": os.getpid(), "started": time.time()}):
        try:                                       # a breaker that died between its two steps
            if time.time() - os.path.getmtime(brk) > 60:
                os.remove(brk)
        except OSError:
            pass
        return
    try:
        now = read(path)
        if now is not None and now.get("token") == seen.get("token") and stale(now):
            os.remove(path)
            who = seen.get("who") or "a render"
            why = "its process is gone" if seen.get("pid") and not pid_alive(seen["pid"]) else \
                "held for hours" if seen.get("age_s", 0) <= QUIET_S else "no sign of life for minutes"
            log(f"render queue: took over a stale lock from {who} ({why})")
    except OSError:
        pass
    finally:
        try:
            os.remove(brk)
        except OSError:
            pass


def _since(d):
    try:
        return time.strftime("%H:%M:%S", time.localtime(float(d.get("started"))))
    except (TypeError, ValueError):
        return "?"


def describe(d):
    """'the director (v2 preview -> out/v2_preview.mp4) since 14:02:11' for a lock record."""
    what = f" ({d['what']})" if d.get("what") else ""
    return f"{d.get('who') or 'a render'}{what} since {_since(d)}"


@contextmanager
def render_queue(what="", who=None, log=None, poll=2.0, say_every=SAY_S):
    """Hold the machine's render queue for the duration of the block (waiting for it first). A no-op with
    AM_RENDER_LOCK=0."""
    log = log or (lambda s: print(s, flush=True))
    if not enabled():
        yield None
        return
    path = lock_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    who = who or os.environ.get("AM_RENDER_WHO") or "a render"
    rec = {"pid": os.getpid(), "who": who, "what": what, "started": time.time(), "token": uuid.uuid4().hex,
           "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    t0, said, last = time.time(), None, 0.0
    while True:
        rec["started"] = time.time()
        if _try_create(path, rec):
            break
        d = read(path)
        if d is None:
            continue                               # freed between the two looks: try again at once
        if stale(d):
            _break_stale(path, d, log)
            continue
        key = d.get("token")
        if key != said or time.time() - last >= say_every:
            log(f"waiting for the render queue: {describe(d)}")
            said, last = key, time.time()
        time.sleep(poll)
    if said is not None:
        log(f"render queue: my turn after {time.time() - t0:.0f} s")
    done = threading.Event()

    def beat():                                    # a sign of life, so a long render is never taken for stale
        while not done.wait(BEAT_S):
            try:
                os.utime(path, None)
            except OSError:
                pass
    threading.Thread(target=beat, daemon=True).start()
    try:
        yield rec
    finally:
        done.set()
        _release(path, rec["token"])


def _release(path, token, tries=20):
    """Remove our lock (only ours). On Windows a waiter reading the file at that instant makes the remove fail: try
    again a few times rather than leave the queue blocked until this process ends."""
    for _ in range(tries):
        d = read(path)
        if d is None or (d and d.get("token") not in (None, token)):
            return                                 # gone already, or someone else's (it was taken over)
        if d.get("token") == token:
            try:
                os.remove(path)
                return
            except FileNotFoundError:
                return
            except OSError:
                pass
        time.sleep(0.1)
