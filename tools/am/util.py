"""Small stdlib-only helpers for the studio's own side (the director runner, the critic, the web app): atomic JSON, a
lock file between processes, the project file. Unlike am/common.py these never read AM_PROJECT at import time and need
no image libraries, so the web app and the runner can use them for any project.
"""
import json, os, threading, time
from contextlib import contextmanager

STUDIO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the studio install
TOOLS = os.path.join(STUDIO, "tools")
PROJECTS = os.path.join(STUDIO, "projects")


def jload(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _np(o):
    try:
        import numpy as np
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
    except ImportError:
        pass
    raise TypeError(f"not JSON serializable: {type(o).__name__}")


def jsave(path, obj, indent=1):
    """Write JSON atomically (a crash never leaves half a file). The temporary file is the writer's own (two processes
    or threads saving one file don't move each other's), and on Windows the replace is tried again for a moment while
    someone reads the file (the web app polls these files every 2 s; an open file can't be replaced there)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.{os.getpid()}-{threading.get_ident()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=indent, ensure_ascii=False, default=_np)
    for k in range(40):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if k == 39:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise
            time.sleep(0.05)


@contextmanager
def file_lock(path, wait=5.0, stale_s=30.0):
    """A lock between processes for one bookkeeping file (path + ".lock", os.open O_CREAT | O_EXCL): the web app and
    the director's runner both write review/notes.json. A lock file older than stale_s is left over from a writer that
    was killed. After `wait` s it goes on without the lock: a bookkeeping write never holds up the work."""
    lk = path + ".lock"
    os.makedirs(os.path.dirname(os.path.abspath(lk)), exist_ok=True)
    t0, fd = time.time(), None
    while fd is None and time.time() - t0 < wait:
        try:
            fd = os.open(lk, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except (FileExistsError, PermissionError):       # Windows says PermissionError while it is being removed
            try:
                if time.time() - os.path.getmtime(lk) > stale_s:
                    os.remove(lk)
                    continue
            except OSError:
                pass
            time.sleep(0.02)
        except OSError:
            break
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
            for _ in range(20):
                try:
                    os.remove(lk)
                    break
                except FileNotFoundError:
                    break
                except OSError:                          # Windows: someone is checking its age right now
                    time.sleep(0.05)


def load_project(pdir):
    return jload(os.path.join(pdir, "project.json"), {}) or {}


_PJ_LOCK = threading.RLock()


def save_project(pdir, pj):
    """project.json, written atomically (the web app, the runner and the tools all write it)."""
    with _PJ_LOCK:
        jsave(os.path.join(pdir, "project.json"), pj)


def update_project(pdir, fn):
    """Change project.json in place under a lock (re-read, fn(pj) changes it, an atomic write). Returns the project."""
    p = os.path.join(pdir, "project.json")
    with _PJ_LOCK, file_lock(p):
        pj = load_project(pdir)
        out = fn(pj)
        pj = pj if out is None else out
        jsave(p, pj)
        return pj


def song_slug(pdir, pj=None):
    """The project's song folder name (song/<slug>/): project.json song.slug or analysis.song_slug, else the only (or
    newest) folder in song/ that has a song-map.json; None when there is none yet."""
    pj = pj if pj is not None else load_project(pdir)
    sd = os.path.join(pdir, "song")
    for s in ((pj.get("song") or {}).get("slug"), (pj.get("analysis") or {}).get("song_slug")):
        if s and os.path.isfile(os.path.join(sd, s, "song-map.json")):
            return s
    have = [d for d in os.listdir(sd) if os.path.isfile(os.path.join(sd, d, "song-map.json"))] if os.path.isdir(sd) else []
    if not have:
        return None
    return max(have, key=lambda d: os.path.getmtime(os.path.join(sd, d, "song-map.json")))
