"""Claude Code from the studio: where the command is, and one headless print-mode call (the story step, the critic,
the pitch verdict). The autonomous director's long stream-json session lives in director.py.

  claude_print(prompt, cwd, model="sonnet", tools=["Read", "Glob", "Grep"], max_usd=2)
      -> {"ok", "text", "json", "cost_usd", "duration_s", "returncode", "stdout", "stderr", "cmd", "warnings"}

The call (checked against `claude --help` of Claude Code 2.1.x):
  claude -p --output-format json --permission-mode dontAsk --allowedTools <tools> --disallowedTools <the rest>
         --strict-mcp-config --no-session-persistence [--model M] [--effort E] [--max-budget-usd X]
  cwd = the project folder; the prompt goes in on stdin, never as an argument (on Windows an npm `claude.cmd` passes
  arguments through cmd.exe, which mangles newlines, quotes and parentheses).
"""
import json, os, shutil, subprocess, sys, time

READ_ONLY = ["Read", "Glob", "Grep"]
NEVER = ["Write", "Edit", "Bash", "WebFetch", "WebSearch"]     # a print-mode call reads; it never writes or fetches
# what a Claude Code session's Bash exports about that session (seen with Claude Code 2.1.312): a CLI started with
# them takes itself for that session's child (its nesting limit, its session id, its effort)
SESSION_ENV = ("CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_SESSION_ATTENDED",
               "CLAUDE_PID", "CLAUDE_EFFORT", "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH")


def clean_env(env=None):
    """The environment for a Claude Code call or session the studio starts: one of its own, not a child of the Claude
    Code session it may have been started from (an interactive director running the critic or `studio.py pitch`):
    env (default os.environ) without SESSION_ENV."""
    out = dict(os.environ if env is None else env)
    for k in SESSION_ENV:
        out.pop(k, None)
    return out


def claude_bin():
    """The claude command as a list (AM_CLAUDE overrides; a .py there runs with this Python: tests use a stand-in)."""
    c = os.environ.get("AM_CLAUDE") or shutil.which("claude")
    if not c:
        return None
    return [sys.executable, c] if c.endswith(".py") else [c]


def descendants(pid):
    """The processes a process started, and theirs (POSIX: pgrep -P; [] when pgrep isn't there)."""
    out, todo = [], [pid]
    while todo:
        try:
            r = subprocess.run(["pgrep", "-P", str(todo.pop())], capture_output=True, text=True, timeout=10)
            kids = [int(x) for x in r.stdout.split()]
        except Exception:
            kids = []
        out += kids
        todo += kids
    return out


def kill_tree(proc):
    """Stop a process and what it started (an npm claude.cmd is cmd.exe -> node on Windows; critic.py -> claude, the
    eyes, ffmpeg): a child left running would keep spending."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        kids = descendants(proc.pid)                   # before the parent goes: orphans can't be found by it after
        proc.kill()
        for k in kids:
            try:
                os.kill(k, 9)
            except OSError:
                pass
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        pass


def pid_alive(pid):
    """Is this process still running? (On Windows os.kill(pid, 0) would end it: OpenProcess there.)"""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = ctypes.c_void_p      # a handle is pointer-sized
        k32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        h = k32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.get_last_error() == 5        # access denied: it exists, it isn't ours
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return bool(ok) and code.value == 259          # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def print_cmd(model=None, effort=None, tools=("Read",), max_usd=None, args=()):
    cl = claude_bin()
    if not cl:
        raise RuntimeError("Claude Code isn't installed (https://claude.com/claude-code)")
    cmd = [*cl, "-p", "--output-format", "json", "--permission-mode", "dontAsk", "--allowedTools", *tools,
           "--disallowedTools", *[t for t in NEVER if t not in tools], "--strict-mcp-config", "--no-session-persistence"]
    if model:
        cmd += ["--model", model]
    if effort:
        cmd += ["--effort", effort]
    if max_usd:
        cmd += ["--max-budget-usd", f"{float(max_usd):g}"]
    return cmd + list(args)


def claude_print(prompt, cwd, model=None, effort=None, tools=("Read",), timeout=1200, max_usd=None, args=(), env=None,
                 on_start=None):
    """One headless print-mode call with read-only tools. The answer's text is "text" (the json "result"; the raw
    stdout when it isn't json), "json" the parsed reply ({} if none). Raises RuntimeError only when Claude Code is
    missing or doesn't answer in time; a call that ran but failed comes back with ok False and its stderr.
    A CLI that doesn't know --max-budget-usd is asked again without it (and says so in "warnings").
    on_start(proc): called with the process once it runs (a caller in another thread can end it: kill_tree)."""
    tools = list(tools)
    warnings = []
    env = dict(clean_env(env), PYTHONIOENCODING="utf-8")       # a call of its own, not a nested one
    for attempt in (0, 1):
        cmd = print_cmd(model, effort, tools, max_usd, args)
        t0 = time.time()
        proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace", env=env,
                                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        if on_start:
            on_start(proc)
        try:
            out, err = proc.communicate(prompt, timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_tree(proc)
            raise RuntimeError(f"Claude didn't answer within {timeout // 60} min")
        except BaseException:                    # Ctrl+C: the call doesn't outlive the one who made it
            kill_tree(proc)
            raise
        if attempt == 0 and max_usd and proc.returncode and "max-budget-usd" in (err + out) and \
                any(w in (err + out).lower() for w in ("unknown option", "unknown argument", "unrecognized")):
            warnings.append("this Claude Code doesn't know --max-budget-usd: ran without a spending cap")
            max_usd = None
            continue
        break
    try:
        res = json.loads(out)
        text = res.get("result", "") if isinstance(res, dict) else out
        res = res if isinstance(res, dict) else {}
    except Exception:
        res, text = {}, out
    return {"ok": proc.returncode == 0 and not res.get("is_error"), "text": text or "", "json": res,
            "cost_usd": res.get("total_cost_usd"), "duration_s": round(time.time() - t0, 1), "returncode": proc.returncode,
            "stdout": out, "stderr": err, "cmd": cmd, "warnings": warnings}
