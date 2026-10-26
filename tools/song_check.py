"""Check that a suggested song exists (LRCLIB, free, no key) and how long it is / whether synced lyrics exist.

  python tools/song_check.py "<artist>" "<title>"            one song, JSON out
  python tools/song_check.py --file suggestions.json         a list of {artist, title}; adds "check" to each

Used to verify Claude's song suggestions: nothing invented gets through as "verified".
"""
import argparse, difflib, json, re, sys, time, urllib.parse, urllib.request

UA = {"User-Agent": "aftermovie-studio/1.0"}


def norm(s):
    s = (s or "").lower()
    s = re.sub(r"\s*[\(\[].*?[\)\]]", "", s)                     # (Remastered), [Live]...
    s = re.sub(r"\b(feat\.?|ft\.?|featuring)\b.*", "", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def sim(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 0.95
    return difflib.SequenceMatcher(None, a, b).ratio()


def search(params):
    url = "https://lrclib.net/api/search?" + urllib.parse.urlencode(params)
    try:
        return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20).read().decode("utf-8"))
    except Exception:
        return None


def lookup(artist, title):
    res = search({"artist_name": artist, "track_name": title})
    if not res:
        res = search({"q": f"{artist} {title}"})
    if res is None:
        return {"found": None, "note": "lyrics database unreachable (offline?)"}
    best, score = None, 0.0
    for r in res[:25]:
        sc = 0.55 * sim(title, r.get("trackName")) + 0.45 * sim(artist, r.get("artistName"))
        if sc > score:
            best, score = r, sc
    if not best or score < 0.72:
        return {"found": False, "note": "not found: check the title"}
    same = [r for r in res if sim(title, r.get("trackName")) > 0.9 and sim(artist, r.get("artistName")) > 0.8]
    synced = any(r.get("syncedLyrics") for r in same) or bool(best.get("syncedLyrics"))
    durs = sorted(r["duration"] for r in same if r.get("duration")) or [best.get("duration")]
    return {"found": True, "artist": best.get("artistName"), "title": best.get("trackName"), "album": best.get("albumName"),
            "duration": round(durs[len(durs) // 2]) if durs and durs[0] else None, "synced": synced,
            "instrumental": bool(best.get("instrumental")), "match": round(score, 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("artist", nargs="?")
    ap.add_argument("title", nargs="?")
    ap.add_argument("--file")
    a = ap.parse_args()
    if a.file:
        items = json.load(open(a.file, encoding="utf-8"))
        for it in items:
            it["check"] = lookup(it.get("artist", ""), it.get("title", ""))
            time.sleep(0.2)
        json.dump(items, open(a.file, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        for it in items:
            c = it["check"]
            print(f"{'ok ' if c.get('found') else '?? '} {it.get('artist')} - {it.get('title')}  {c.get('duration') or ''}s  synced={c.get('synced')}")
    else:
        print(json.dumps(lookup(a.artist, a.title), ensure_ascii=False))


if __name__ == "__main__":
    main()
