"""The user's own lyrics: where they live in project.json, their structure ([Verse] / [Chorus] tags, stanzas), and
placing plain-text lines on the song with Whisper's word times. Standard library only (analyze_audio.py, studio.py and
the web app's server import it). Carried back from Music Video Studio, adapted to several songs per project.

  python tools/studio.py align-lyrics <project> [slug] [--in lines.json]      Whisper first (once per song), then this
  python tools/studio.py run <project> align_lyrics.py [slug] [--in lines.json] [--out cache/lyrics/<slug>_aligned.json]

Where the user's lyrics live (project.json; every key optional, a project without them behaves as before):
  song.lyrics             the project's song (song.slug, or song.file before the first analysis): plain text, LRC with
                          [mm:ss.xx] line times, or word-timed LRC (<mm:ss.xx> word); "[Verse 1]" / "[Chorus]"-style
                          tags above the parts name the song's sections, blank lines between stanzas help without tags
  song.lyrics_synced      true: the LRC was timed on this very file in the web app's lyric timing editor (no offset search)
  song.lyrics_set         the start times of the lines the user set by hand there; the others are placed with Whisper
  songs.<slug>.lyrics     ... the same keys for any other song in music/ (a project with several songs)
Changing the lyrics on the brief page drops lyrics_synced and lyrics_set. lyrics_fix (fix_lyrics.py) still applies.

Whisper placement (anchor()): the words of the lyric are matched, in order and forgiving mishearings, to the words
Whisper heard on the vocal stem (cache/lyrics/<slug>_transcribed.json, made by transcribe_lyrics.py), so each line starts
where its first words were heard and ends where its last ones were. Lines Whisper didn't catch go between their
neighbours. Lines sung again that the lyric has only once (a chorus written once) come back as repeats; stretches heard
that match no line are listed (heard_only), so the user can add what's missing. Whisper stuck on music (one phrase
again and again at one moment) is filtered: a word heard again at the same moment is dropped, and nothing Whisper adds
(a repeat, a line to add) may sit on top of a line already placed.

--in: [{"text": ...}, ...] (the web app's lyric timing editor sends its lines); default: the song's lyrics. Writes
{"lines": [{i, text, t, end, words: [[word, t]], heard, src}], "heard_only": [{t, end, text}], "stats": {...}}: i = the
input line (null for an added repeat), heard = share of its words matched, src = whisper | between | repeat.
Whisper's word times are good to ~0.2 s; align_words.py (forced alignment) then refines every word inside its line.
"""
import argparse, json, os, re, sys
from difflib import SequenceMatcher

GAP_LYRIC = -0.5           # a lyric word Whisper didn't hear
GAP_EDGE = -0.6            # ... the first or last word of a line: those carry the line's timing, so they match first
GAP_HEARD = -0.12          # a word Whisper heard that isn't in the lyric, between lines (ad-libs, repeats)
GAP_INSIDE = -0.45         # ... in the middle of a line: a line's words are sung together, not picked from two lines
MIN_SIM = 0.55             # two words this alike (characters) may match: "pipette" ~ "pipet", "gonna" ~ "going"
PER_WORD = 0.28            # seconds per word, to extrapolate unheard words at the edges of a line

TIME = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")
LRC_META = re.compile(r"^(ar|ti|al|au|by|re|ve|length|offset|tool|lang|la|id)\s*:", re.I)    # LRC header tags
KINDS = (                                   # the tag's words -> the section label the song kit uses; the first match wins
    (r"\bpre[\s-]*(chorus|hook)\b|\bbuild([\s-]*up)?\b|\blift\b", "pre-chorus"),
    (r"\bpost[\s-]*(chorus|hook)\b", "post-chorus"),
    (r"\bchorus\b|\bhook\b|\bdrop\b", "chorus"),
    (r"\brefrain\b", "refrain"),
    (r"\bverse\b|\brap\b", "verse"),
    (r"\bbridge\b|\bmiddle[\s-]*(8|eight)\b", "bridge"),
    (r"\bintro(duction)?\b", "intro"),
    (r"\boutro\b|\bcoda\b|\bend(ing)?\b|\bfade([\s-]*out)?\b", "outro"),
    (r"\binstrumental\b|\binterlude\b|\bsolo\b", "instrumental"),
    (r"\bbreak([\s-]*down)?\b", "break"),
)


# ------------------------------------------------------------------ where the user's lyrics live
def is_main_song(pj, slug=None, file=None):
    """True when slug / file is project.json's own song (its lyrics are in "song"), not another one in music/."""
    s = pj.get("song") or {}
    if s.get("slug") and slug:
        return s["slug"] == slug
    return bool(file) and s.get("file") == file or (not slug and not file)


def lyrics_entry(pj, slug=None, file=None, create=False):
    """The dict in project.json that holds a song's own lyrics keys (lyrics, lyrics_synced, lyrics_set): "song" for the
    project's song, "songs"[slug] for another one. create=True makes it (to write into); else {} when there is none."""
    if is_main_song(pj, slug, file):
        return pj.setdefault("song", {}) if create else (pj.get("song") or {})
    if create:
        return pj.setdefault("songs", {}).setdefault(slug, {})
    return (pj.get("songs") or {}).get(slug) or {}


def lyrics_text(entry):
    txt = entry.get("lyrics") if isinstance(entry, dict) else None
    return str((txt.get("text") if isinstance(txt, dict) else txt) or "")


def lyrics_kind(entry):
    """'lrc' (line times given), 'plain' (text only), 'partly' (timed in the web app's editor, but not every line set by
    hand: Whisper places the others) or None (no lyrics of the user's)."""
    txt = lyrics_text(entry)
    if not txt.strip():
        return None
    stamps = TIME.findall(txt)
    if len(stamps) < 3:
        return "plain"
    return "partly" if entry.get("lyrics_synced") and len(entry.get("lyrics_set") or []) < len(stamps) else "lrc"


# ------------------------------------------------------------------ the lyric's own structure
def kind(tag):
    """The section label for a tag ("Final Chorus" -> chorus, "Breakdown" -> break), None when it names no section."""
    t = str(tag or "").lower()
    for pat, label in KINDS:
        if re.search(pat, t):
            return label
    return None


def walk(text):
    """[{text, part, stanza, stamps}] for every sung line of a lyric (plain text or LRC), in the file's order. text = the
    line without times or tags, part = the last section tag above it (None before the first), stanza = its stanza's
    number (a blank line, an empty LRC line or a section tag starts the next one), stamps = its LRC times (none in plain
    text). Comment lines (#) and tags that name no section ("[Male vocal]") are skipped."""
    out, part, st, fresh = [], None, 0, False
    for raw in str(text or "").splitlines():
        s = raw.strip()
        if s.startswith("#"):
            continue
        stamps = [int(m) * 60 + float(x) for m, x in TIME.findall(s)]
        body = TIME.sub("", s).strip()
        m = re.match(r"^\[([^\]]*)\]\s*(.*)$", body)
        if m and not LRC_META.match(m.group(1).strip()):
            tag = re.sub(r"\s+", " ", m.group(1)).strip()
            if kind(tag):
                part, fresh = tag, True
            body = m.group(2)
        body = re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", re.sub(r"\[[^\]]*\]", "", body))).strip()
        if not body:
            if not s or stamps or (m and kind(m.group(1))):       # a blank line, an empty LRC line: the stanza ends
                fresh = True
            continue
        if fresh and out:
            st += 1
        fresh = False
        out.append({"text": body, "part": part, "stanza": st, "stamps": stamps})
    return out


def lrc_map(text):
    """{LRC time (rounded to ms): (part, stanza)} for every timed line of an LRC lyric."""
    return {round(t, 3): (x["part"], x["stanza"]) for x in walk(text) for t in x["stamps"]}


def fields(part, stanza):
    """The keys a lyric line carries for its place in the lyric (none when it has no place: a repeat Whisper heard)."""
    return {**({"part": part} if part else {}), **({"stanza": stanza} if stanza is not None else {})}


def tagged(lines):
    """True when the lyric names its own sections: its first line is under a section tag and there are two parts or
    more. A lyric that tags only some of its sections (an untagged opening) is not: its tags can't say where an
    untagged part starts."""
    own = [x for x in lines if x.get("stanza") is not None]
    return bool(own) and bool(own[0].get("part")) and len({x.get("part") for x in own}) >= 2


# ------------------------------------------------------------------ Whisper placement
def norm(w):
    return re.sub(r"[^\w']+", "", str(w).lower().replace("’", "'")).strip("'_")


def transcription_for(path, song):
    """Whisper's words [{w, t, end}] from <slug>_transcribed.json when it was made for this song file, else None."""
    try:
        tr = json.load(open(path, encoding="utf-8"))
    except Exception:
        return None
    s = tr.get("song") or {}
    if song and (s.get("file") != os.path.basename(song) or s.get("size") != os.path.getsize(song)):
        return None
    words = [w for L in tr.get("lines") or [] for w in L.get("words") or [] if norm(w.get("w"))]
    return drop_stuck(words) or None


def drop_stuck(words):
    """Whisper on music can get stuck: the same words again and again at one timestamp, or going back in time. Real
    singing moves on, so a word heard at the same moment as the same word just before it, or before the word before
    it, is dropped."""
    out = []
    for w in words:
        t = float(w["t"])
        if out and (t < float(out[-1]["t"]) - 0.05 or
                    any(norm(w["w"]) == norm(o["w"]) and abs(t - float(o["t"])) < 0.05 for o in out[-12:])):
            continue
        out.append(w)
    return out


def _match(U, W, line_of):
    """Global alignment of the lyric's words U (line_of[i] = the line of U[i]) to the heard words W (heard words before
    the first and after the last lyric word are free). Returns {lyric word index: heard word index}."""
    n, m = len(U), len(W)
    gap_h = [GAP_INSIDE if 0 < i < n and line_of[i - 1] == line_of[i] else GAP_HEARD for i in range(n + 1)]
    gap_l = [GAP_EDGE if i == 0 or i == n - 1 or line_of[i - 1] != line_of[i] or line_of[i + 1] != line_of[i] else GAP_LYRIC
             for i in range(n)]
    cache = {}

    def sim(a, b):
        k = (a, b)
        if k not in cache:
            cache[k] = 1.0 if a == b else SequenceMatcher(None, a, b).ratio()
        return cache[k]
    prev = [0.0] * (m + 1)
    back = []                                       # per lyric word: 0 = matched, 1 = lyric gap, 2 = heard gap
    for i in range(1, n + 1):
        gl = gap_l[i - 1]
        cur = [prev[0] + gl] + [0.0] * m
        bp = bytearray(m + 1)
        bp[0] = 1
        u = U[i - 1]
        for j in range(1, m + 1):
            best, how = prev[j] + gl, 1
            v = cur[j - 1] + gap_h[i]
            if v > best:
                best, how = v, 2
            s = sim(u, W[j - 1])
            if s >= MIN_SIM:
                v = prev[j - 1] + 2 * s - 1
                if v >= best:
                    best, how = v, 0
            cur[j], bp[j] = best, how
        back.append(bp)
        prev = cur
    j = max(range(m + 1), key=lambda q: prev[q])    # trailing heard words are free
    i, out = n, {}
    while i > 0 and j > 0:
        how = back[i - 1][j]
        if how == 0:
            out[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif how == 1:
            i -= 1
        else:
            j -= 1
    return out


def anchor(texts, heard, min_heard=0.25):
    """The lyric lines (texts, in sung order) placed on Whisper's words (heard: [{w, t, end}]). See the module doc."""
    W = [(norm(h["w"]), float(h["t"]), float(h.get("end") or float(h["t"]) + 0.3), str(h["w"]).strip())
         for h in drop_stuck(heard) if norm(h["w"])]      # (word as matched, start, end, as Whisper wrote it)
    lines = [{"i": k, "text": re.sub(r"\s+", " ", t).strip(), "words": []} for k, t in enumerate(texts)]
    lines = [x for x in lines if x["text"]]
    U, owner = [], []
    for li, x in enumerate(lines):
        for wi, w in enumerate(x["text"].split()):
            x["words"].append([w, None])
            if norm(w):
                U.append(norm(w))
                owner.append((li, wi))
    pairs = _match(U, [w[0] for w in W], [li for li, _ in owner]) if U and W else {}
    used = set(pairs.values())
    for ui, wj in pairs.items():
        li, wi = owner[ui]
        lines[li]["words"][wi][1] = W[wj][1]
        lines[li].setdefault("ends", []).append(W[wj][2])
    for x in lines:                                  # a line: from its first heard word to its last one's end
        ts = [(k, t) for k, (_, t) in enumerate(x["words"]) if t is not None]
        x["heard"] = round(len(ts) / max(1, len(x["words"])), 2)
        if ts:
            k0, t0 = ts[0]
            k1, _ = ts[-1]
            x["t"] = max(0.0, t0 - PER_WORD * k0)
            x["end"] = max(x.get("ends")) + PER_WORD * (len(x["words"]) - 1 - k1)
            x["src"] = "whisper"
        else:
            x["t"] = x["end"] = None
            x["src"] = "between"
        x.pop("ends", None)
    # lines nobody heard: between their neighbours, by their word counts
    k = 0
    while k < len(lines):
        if lines[k]["t"] is not None:
            k += 1
            continue
        j = k
        while j < len(lines) and lines[j]["t"] is None:
            j += 1
        a = lines[k - 1]["end"] if k > 0 else None
        b = lines[j]["t"] if j < len(lines) else None
        nw = [len(x["words"]) for x in lines[k:j]]
        span_need = PER_WORD * sum(nw)
        if a is None and b is None:
            a = 0.0
        if a is None:
            a = max(0.0, b - span_need - 0.3)
        if b is None or b - a < 0.2 * len(nw):
            b = a + span_need + 0.3
        acc, tot = 0, max(1, sum(nw))
        for q, x in enumerate(lines[k:j]):
            x["t"] = a + (b - a) * acc / tot
            acc += nw[q]
            x["end"] = a + (b - a) * acc / tot
        k = j
    # words not heard: spread between the heard ones in their line
    for x in lines:
        ws = x["words"]
        known = [(q, t) for q, (_, t) in enumerate(ws) if t is not None]
        pts = [(-1, x["t"])] + known + [(len(ws), x["end"])]
        for (q0, t0), (q1, t1) in zip(pts, pts[1:]):
            for q in range(q0 + 1, q1):
                ws[q][1] = t0 + (t1 - t0) * (q - q0) / (q1 - q0) if q0 >= 0 else x["t"] + (t1 - x["t"]) * q / max(1, q1)
        for w in ws:
            w[1] = round(float(w[1]), 3)
        x["t"], x["end"] = round(x["t"], 3), round(max(x["end"], x["t"] + 0.2), 3)
    # sung again but written once: unmatched stretches that read like one of the lines
    repeats, heard_only = [], []
    taken = [(x["t"], x["end"]) for x in lines]       # where lines are already: nothing more goes on top of them

    def free(a, b, n):
        """[a, b] with n words: long enough to be sung (Whisper stuck in a loop stamps them all at once) and not on
        top of a line already placed, a repeat or a heard piece."""
        return b - a >= 0.1 * n and not any(min(b, e) - max(a, s) > 0.4 * (b - a) for s, e in taken)
    seqs = {x["text"]: [norm(w) for w, _ in x["words"] if norm(w)] for x in lines}
    todo = _runs([j for j in range(len(W)) if j not in used], W)
    while todo:
        run = todo.pop()
        best = None
        for text, sq in seqs.items():
            shortest = max(3, round(0.6 * len(sq)))          # Whisper may have caught only part of it
            if len(sq) < 3 or len(run) < shortest:
                continue
            for a_ in range(len(run)):
                for n_ in range(shortest, len(sq) + 2):
                    win = run[a_:a_ + n_]
                    if len(win) < n_:
                        break
                    r = SequenceMatcher(None, sq, [W[j][0] for j in win]).ratio()
                    if r >= 0.6 and (best is None or r > best[0]):
                        best = (r, text, a_, n_)
        if not best:                                 # heard, but in no line: line-sized pieces the user can add
            for piece in _pieces(run, W):
                a, b = W[piece[0]][1], W[piece[-1]][2]
                if len(piece) >= 3 and free(a, b, len(piece)):
                    heard_only.append({"t": round(a, 2), "end": round(b, 2),
                                       "text": " ".join(W[j][3] for j in piece).strip(" ,;:")})
                    taken.append((a, b))
            continue
        r, text, a_, n_ = best
        win = run[a_:a_ + n_]
        todo += [x for x in (run[:a_], run[a_ + n_:]) if x]
        ws = [[w, None] for w in text.split()]
        t0, t1 = W[win[0]][1], W[win[-1]][2]
        if not free(t0, t1, len(win)):               # the same line again on top of itself: Whisper repeating, not the song
            continue
        taken.append((t0, t1))
        for q, w in enumerate(ws):
            w[1] = round(t0 + (t1 - t0) * q / max(1, len(ws)), 3)
        repeats.append({"i": None, "text": text, "t": round(t0, 3), "end": round(t1, 3), "words": ws,
                        "heard": round(r, 2), "src": "repeat"})
    heard_only.sort(key=lambda h: h["t"])
    out = sorted(lines + repeats, key=lambda x: x["t"])
    for a_, b_ in zip(out, out[1:]):                 # in order, no overlaps
        if b_["t"] < a_["t"] + 0.05:
            b_["t"] = round(a_["t"] + 0.05, 3)
        if a_["end"] > b_["t"]:
            a_["end"] = round(max(a_["t"] + 0.2, b_["t"]), 3)
    heard_share = sum(x["heard"] for x in lines) / max(1, len(lines))
    stats = {"lines": len(lines), "lines_heard": sum(x["src"] == "whisper" for x in lines),
             "words_heard": round(len(pairs) / max(1, len(U)), 2), "share": round(heard_share, 2),
             "repeats_added": len(repeats), "heard_only": len(heard_only), "usable": heard_share >= min_heard}
    return {"lines": out, "heard_only": heard_only, "stats": stats}


def _pieces(run, W, gap=0.5, most=12):
    """A run of heard words cut where the voice pauses (or every `most` words): one sung line each."""
    out, cur = [], []
    for j in run:
        if cur and (W[j][1] - W[cur[-1]][2] > gap or len(cur) >= most):
            out.append(cur)
            cur = []
        cur.append(j)
    if cur:
        out.append(cur)
    return out


def _runs(idx, W):
    out, cur = [], []
    for j in idx:
        if cur and (j != cur[-1] + 1 or W[j][1] - W[cur[-1]][2] > 1.5):
            out.append(cur)
            cur = []
        cur.append(j)
    if cur:
        out.append(cur)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?", help="default: the project's song (project.json song.slug)")
    ap.add_argument("--in", dest="inp", help="a JSON list of lines ({text}); default: the song's lyrics")
    ap.add_argument("--out", default=None, help="default: cache/lyrics/<slug>_aligned.json")
    a = ap.parse_args()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from am.common import CACHE, MUSIC, project
    from analyze_audio import SONGS
    pj = project()
    slug = a.slug or (pj.get("song") or {}).get("slug")
    if not slug or slug not in SONGS:
        sys.exit(f"which song? {', '.join(sorted(SONGS)) or 'none in music/'}")
    song = os.path.join(MUSIC, SONGS[slug])
    heard = transcription_for(os.path.join(CACHE, "lyrics", f"{slug}_transcribed.json"), song)
    if not heard:
        sys.exit("no Whisper transcription of this song (transcribe_lyrics.py): nothing to align to")
    if a.inp:
        texts = [str(x.get("text") or "") for x in json.load(open(a.inp, encoding="utf-8"))]
    else:
        texts = [x["text"] for x in walk(lyrics_text(lyrics_entry(pj, slug, SONGS[slug])))]
    res = anchor(texts, heard)
    out = a.out or os.path.join(CACHE, "lyrics", f"{slug}_aligned.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    s = res["stats"]
    print(f"{s['lines_heard']}/{s['lines']} lines placed where Whisper heard them ({s['words_heard'] * 100:.0f}% of the words), "
          f"{s['repeats_added']} repeats added, {s['heard_only']} stretches heard that are not in the lyrics -> {out}")
    for h in res["heard_only"][:12]:
        print(f"   heard at {h['t']:.1f}-{h['end']:.1f} s, not in the lyrics: {h['text']}")


if __name__ == "__main__":
    main()
