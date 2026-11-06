"""The user's review notes (review/notes.json), written safely: the web app adds notes while the director's runner
forwards them and the director marks them done (`studio.py note-done`), so every write goes through update_notes (a
lock between threads and a lock file between processes, a re-read, the change, an atomic replace).

A note: {"id" (ms since the epoch: when it was made), "version", "t" (film seconds), "text", "done", "at", "round",
"fix" (the director's one-line answer, shown under the note), "forwarded_run" / "forwarded_at" (a running director
got it as a message)}.
"""
import json, os, threading, time

from .util import file_lock, jsave

NOTES = os.path.join("review", "notes.json")
_LOCK = threading.RLock()


def read_notes(pdir, tries=20):
    """The notes ([] when there are none). A file that can't be read this instant (being replaced, on Windows) is read
    again; one that stays unreadable raises: it is never taken for empty (that would lose every note on the next write)."""
    p = os.path.join(pdir, NOTES)
    for k in range(tries):
        if not os.path.exists(p):
            return []
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, list) else []
        except (ValueError, OSError):
            if k == tries - 1:
                raise RuntimeError("review/notes.json can't be read (is it valid JSON?)")
        time.sleep(0.05)
    return []


def update_notes(pdir, fn):
    """Change review/notes.json in place: fn(notes) changes the list (or returns a new one). Returns the notes as
    written."""
    p = os.path.join(pdir, NOTES)
    with _LOCK, file_lock(p):
        notes = read_notes(pdir)
        out = fn(notes)
        notes = notes if out is None else out
        jsave(p, notes)
        return notes


def note_done(pdir, nid, fix="", undo=False):
    """Mark one note done with its one-line fix (or open again). The note as written, or None when there is no note
    with that id."""
    hit = []

    def fn(ns):
        for x in ns:
            if isinstance(x, dict) and str(x.get("id")) == str(nid).strip():
                if undo:
                    x["done"] = False
                else:
                    x["done"] = True
                    if str(fix or "").strip():
                        x["fix"] = " ".join(str(fix).split())[:500]
                hit.append(x)
    update_notes(pdir, fn)
    return hit[0] if hit else None
