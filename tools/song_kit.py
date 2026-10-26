"""Song kit: turn the project's song into a folder the director can read. The AI can't listen, so this writes down what
a good editor hears: where the song breathes and hits, what each instrument does, the melody and the chords, the
structure, every sung word on the beat grid, and a picture of it all.

  python tools/studio.py song <project> [slug] [--no-tags] [--cpu]
  python tools/song_kit.py [slug] [--no-tags] [--cpu]          (inside a project: AM_PROJECT)

Needs music/<file>, cache/stems/<slug>/ (separate.py) and cache/audio/<slug>.json (analyze_audio.py, align_words.py);
`studio.py ingest` runs them all and then this. Writes song/<slug>/ in the project:

  README.md       how to read the folder (start here)
  song-map.md     at a glance, sections, moments, then bar by bar: chord, loudness, voice/drums/bass/other, sung words
  lyrics.md       the lyric by section: times, bar:beat, repeats (the hook), held and high notes
  song-story.md   what the song is about: a skeleton the director fills in with the user (never overwritten)
  song-map.json   all of it as data; envelopes.json: 10 Hz curves; report.json: models, timings, confidence, warnings
  overview.png    the whole song in lanes; pages/bars_<a>-<b>.png: 16 bars per page, readable word by word

Bar numbers are the builder's: bar n = F.bar(n) (0 = the first downbeat); "17:2.5" = F.beat(17, 2.5).
GPU: pitch (CREPE full) and the tagger (CLAP) run on CUDA when there is room (am/device.py); --cpu forces the CPU
(CREPE tiny). The tagger only runs when the file has a stretch without a beat (a music-video rip's film intro): it
tells film / talking / ambience / silence from quiet music. --no-tags skips it. ~40 s per song on an RTX 4060.
"""
import argparse, glob, json, os, re, sys, time
from collections import Counter
from difflib import SequenceMatcher

import numpy as np
import librosa
import scipy.ndimage as ndi

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from am.common import ROOT, CACHE, MUSIC, project  # noqa: E402
from am import device as D, listen as L, songdoc  # noqa: E402

SR, FPS = L.SR, L.FPS
STEMS = ("vocals", "drums", "bass", "other")
MIN_SECTION = 4          # bars: shorter runs join a neighbour unless they are a real (quieter) break


def default_slug():
    s = (project().get("song") or {}).get("slug")
    if s:
        return s
    js = [os.path.basename(p)[:-5] for p in glob.glob(os.path.join(CACHE, "audio", "*.json"))]
    js = [j for j in js if j != "beat_this" and not j.endswith("_tmp")]
    if len(js) == 1:
        return js[0]
    sys.exit(f"which song? {', '.join(sorted(js)) or 'none analysed yet (run studio.py ingest)'}")


def song_meta(slug, file):
    """Artist + title: project.json's song when it is this one (or its `songs` list), else from 'Artist - Title (...)'."""
    pj = project()
    s = pj.get("song") or {}
    if s.get("slug") == slug or s.get("file") == file:
        return s
    if slug in (pj.get("songs") or {}):
        return pj["songs"][slug]
    base = re.sub(r"\s*[\[(].*?[\])]", "", os.path.splitext(file)[0])
    a, t = (base.split(" - ", 1) + [""])[:2] if " - " in base else ("", base)
    return {"artist": a.strip(), "title": re.sub(r"\s+-\s+.*$", "", t).strip()}


class Clock:
    def __init__(self):
        self.t, self.d = time.time(), {}

    def __call__(self, name):
        now = time.time()
        self.d[name] = round(now - self.t, 1)
        print(f"   {name}: {self.d[name]:.1f} s", flush=True)
        self.t = now


# ------------------------------------------------------------------ the beat grid
class Grid:
    """Bars and beats from cache/audio/<slug>.json, with the builder's bar:beat notation."""

    def __init__(self, A, dur):
        self.beats = np.array(A["beats"], dtype=float)
        self.db = np.array(A["downbeats"], dtype=float)
        self.beat_s = float(A["beat_period"])
        self.bar_s = float(np.median(np.diff(self.db))) if len(self.db) > 1 else 4 * self.beat_s
        last = min(dur, max(self.db[-1] + self.bar_s, self.beats[-1] + self.beat_s))
        self.ends = np.r_[self.db[1:], last]
        self.nb = len(self.db)
        self.dbi = np.array([int(np.argmin(np.abs(self.beats - d))) for d in self.db])
        self.bar_beats = [np.where((self.beats >= a - 0.03) & (self.beats < b - 0.03))[0] for a, b in zip(self.db, self.ends)]
        self.spans = [(int(a * FPS), int(b * FPS)) for a, b in zip(self.db, self.ends)]
        bib = np.full(len(self.beats), 1, dtype=int)                 # beat position inside its bar (0 = downbeat)
        for i, j0 in enumerate(self.dbi):
            j1 = self.dbi[i + 1] if i + 1 < self.nb else len(self.beats)
            bib[j0:j1] = np.arange(j1 - j0)
        self.beat_in_bar = bib

    def bar_of(self, t):
        return int(np.clip(np.searchsorted(self.db, t + 0.03, "right") - 1, 0, self.nb - 1))

    def pos(self, t):
        """(bar, beat offset) as F.beat(bar, k) takes it; None outside the beat grid (film intro, beatless outro)."""
        b = self.beats
        if t < b[0] - 2 * self.beat_s or t > self.ends[-1] + 0.5 * self.beat_s:
            return None
        i = self.bar_of(t)
        jb = int(np.searchsorted(b, t + 0.03, "right") - 1)
        if jb < 0:
            k, jb = (t - b[0]) / self.beat_s, 0
        else:
            k = (t - b[jb]) / (b[jb + 1] - b[jb] if jb + 1 < len(b) else self.beat_s)
        k = round(jb - self.dbi[i] + k, 2)
        return i, (0.0 if -0.06 < k < 0 else k)

    def pos_str(self, t, digits=1):
        p = self.pos(t)
        if p is None:
            return "-"
        return f"{p[0]}:{round(p[1], digits) + 0.0:g}"

    def bar_bpm(self, i):
        idx = self.bar_beats[i]
        if len(idx) >= 2:
            return 60 / float(np.median(np.diff(self.beats[idx])))
        return 60 / self.beat_s


def load_stem(stems_dir, name, n):
    s, _ = librosa.load(os.path.join(stems_dir, f"{name}.wav"), sr=SR, mono=True)
    return np.pad(s, (0, max(0, n - len(s))))[:n]


# ------------------------------------------------------------------ lyrics
def lyric_lines(A, G, warn):
    out = []
    for li, Lr in enumerate(A.get("lyrics") or []):
        ws = [w for w in Lr.get("words", []) if w.get("w")]
        if not ws:
            continue
        t0 = float(ws[0]["t"])
        t1 = float(max(w.get("t_end", w["t"] + 0.3) for w in ws))
        cap = max(3.0, 0.9 * len(ws))
        # a line spread this wide without forced alignment is a failed estimate; force-aligned lines are trusted (slow
        # songs hold words for seconds: "Sweet disposition" is sung over ~8 s)
        if t1 - t0 > cap and not all("fa" in w for w in ws):
            warn.append(f"words of \"{Lr['text']}\" are spread over {t1 - t0:.0f} s from {t0:.1f} s: check the alignment "
                        f"(align_words.py) before trusting its word times")
            t1 = t0 + cap
        home = G.bar_of(t0)
        p = G.pos(t0)
        nbeats = len(G.bar_beats[home]) or 4
        if p and p[0] == home and p[1] >= nbeats - 1.5 and home + 1 < G.nb:    # a pickup into the next bar
            home += 1
        out.append({"i": li, "t": round(t0, 3), "end": round(t1, 3), "text": Lr["text"], "home": home,
                    "norm": L.norm_line(Lr["text"]), "words": ws})
    for a in out:                           # how often the same (or nearly the same) line comes back elsewhere
        a["repeat"] = sum(1 for b in out if b is not a and abs(b["home"] - a["home"]) >= 1 and
                          (b["norm"] == a["norm"] or SequenceMatcher(None, a["norm"], b["norm"]).ratio() >= 0.8))
    return out


# ------------------------------------------------------------------ structure
def segment(G, bar_lab, lines, vfrac, loud, lvl):
    """Section boundaries from evidence per bar: the singing stopping or starting (2), the lyric turning from new lines
    to lines that come back or back (1.5), a new stanza after a gap (1), a loudness step (1-1.5), the sound class
    changing (1), drums / bass coming in or dropping out (0.75). The strongest points at least MIN_SECTION bars apart
    win (evidence one bar away counts half). Returns [(sound class, bar0, bar1)] and the reasons per boundary."""
    nb = G.nb
    S = np.zeros(nb + 1)
    why = [[] for _ in range(nb + 1)]

    def add(i, w, r):
        if 0 < i < nb:
            S[i] += w
            why[i].append(r)
    for i in range(1, nb):
        if bar_lab[i] != bar_lab[i - 1]:
            add(i, 1.0, "sound changes")
    if lines:
        cov = np.zeros(nb, bool)
        for x in lines:
            for i in range(G.bar_of(x["t"]), G.bar_of(x["end"]) + 1):
                ov = min(x["end"], G.ends[i]) - max(x["t"], G.db[i])
                if ov >= 0.25 * (G.ends[i] - G.db[i]):
                    cov[i] = True
            cov[x["home"]] = True
    else:
        cov = np.asarray(vfrac) >= 0.25
    for i in range(1, nb - 1):                          # a one-bar breath doesn't end a section
        if not cov[i] and cov[i - 1] and cov[i + 1]:
            cov[i] = True
    for val, a, b in L.runs(list(cov)):
        if not val and b - a >= 3:
            add(a, 2.0, "singing stops")
            add(b, 2.0, "singing starts")
    for k in range(1, len(lines)):
        if lines[k]["t"] - lines[k - 1]["end"] >= 0.8 * G.bar_s:
            add(lines[k]["home"], 1.0, "new stanza")
    flags = [x["repeat"] > 0 for x in lines]
    for p in range(2, len(lines) - 1):
        if flags[p - 1] == flags[p - 2] and flags[p] == flags[p + 1] and flags[p] != flags[p - 1]:
            add(lines[p]["home"], 1.5, "lyric turns " + ("to lines that come back" if flags[p] else "to new lines"))
    for i in range(2, nb - 1):
        d = L.energy_mean_db(loud[i:i + 2]) - L.energy_mean_db(loud[i - 2:i])
        if abs(d) >= 3:
            add(i, 1.0 if abs(d) < 5 else 1.5, f"loudness {d:+.0f} LU")
    for key, name in (("drums", "drums"), ("bass", "bass")):
        lv = lvl[key]
        for i in range(2, nb - 1):
            if max(lv[i - 2:i]) <= 2 and min(lv[i:i + 2]) >= 4:
                add(i, 0.75, f"{name} in")
            elif min(lv[i - 2:i]) >= 4 and max(lv[i:i + 2]) <= 2:
                add(i, 0.75, f"{name} out")
    strength = S + 0.5 * np.r_[0, S[:-1]] + 0.5 * np.r_[S[1:], 0]
    cand = sorted([i for i in range(2, nb - 1) if S[i] >= 1.0 and strength[i] >= 2.0], key=lambda i: (-S[i], -strength[i]))
    chosen = []
    for i in cand:
        if all(abs(i - j) >= MIN_SECTION for j in chosen):
            chosen.append(i)
    bounds = [0] + sorted(chosen) + [nb]
    R = [(int(np.bincount([x for x in bar_lab[a:b] if x >= 0] or [0]).argmax()), a, b) for a, b in zip(bounds[:-1], bounds[1:])]
    return R, {i: why[i] for i in chosen}


def label_sections(R, lines, vfrac, loud, has_lyrics):
    """Name each run: intro / verse / pre-chorus / chorus / post-chorus / bridge / instrumental / break / outro."""
    secs, letters = [], {}
    for lab, a, b in R:
        letters.setdefault(lab, "ABCDEFGHIJ"[len(letters) % 10])
        ls = [x for x in lines if a <= x["home"] < b]
        secs.append({"bar0": a, "bar1": b, "letter": letters[lab], "lines": ls,
                     "vocal": float(np.mean(vfrac[a:b])) if b > a else 0.0,
                     "loud": float(L.energy_mean_db(loud[a:b])),
                     "rep": float(np.mean([x["repeat"] > 0 for x in ls])) if ls else 0.0,
                     "norms": {x["norm"] for x in ls}})
    voc = [i for i, s in enumerate(secs) if (s["lines"] if has_lyrics else s["vocal"] >= 0.3)]
    med = float(np.median(loud)) if len(loud) else -20

    def overlap(i, j):
        A_, B_ = secs[i]["norms"], secs[j]["norms"]
        if not A_ or not B_:
            return 0.0
        hit = sum(1 for x in A_ if any(x == y or SequenceMatcher(None, x, y).ratio() >= 0.8 for y in B_))
        return hit / min(len(A_), len(B_))
    others = []
    if has_lyrics and voc:
        # chorus = the biggest group of sections sharing their lines; ties go to the louder group
        groups, seen = [], set()
        for i in voc:
            if i in seen or secs[i]["rep"] < 0.5:
                continue
            g = [i] + [j for j in voc if j != i and j not in seen and secs[j]["rep"] >= 0.5 and overlap(i, j) >= 0.5]
            seen.update(g)
            groups.append(g)
        multi = [g for g in groups if len(g) >= 2]
        chorus = set(max(multi or groups, key=lambda g: (len(g), np.mean([secs[i]["loud"] for i in g])))) if groups else set()
        others = [set(g) for g in multi if not chorus & set(g)]
    else:
        # no lyrics: the loudest sound class that comes back is the chorus (by sound)
        by = {}
        for i in voc:
            by.setdefault(secs[i]["letter"], []).append(i)
        cand = [g for g in by.values() if len(g) >= 2]
        chorus = set(max(cand, key=lambda g: np.mean([secs[i]["loud"] for i in g]))) if cand else set()
    first_v, last_v = (min(voc), max(voc)) if voc else (len(secs), -1)
    group_of = {i: gi for gi, g in enumerate(others) for i in g}
    last_ch = max(chorus) if chorus else None
    for i, s in enumerate(secs):
        if i in chorus:
            s["label"] = "chorus"
        elif i not in voc:
            s["label"] = "intro" if i < first_v else "outro" if i > last_v else \
                ("instrumental" if s["loud"] >= med - 1.5 else "break")
        elif i in group_of:
            s["label"] = "post-chorus" if i - 1 in chorus else "pre-chorus" if i + 1 in chorus else "refrain"
        elif last_ch is not None and i > last_ch:
            s["label"] = "outro"
        else:
            s["label"] = "verse"
    # pre-chorus: a short non-repeating vocal section that leads into a chorus, more than once
    verse_len = np.median([s["bar1"] - s["bar0"] for s in secs if s["label"] == "verse"] or [8])
    lead_ins = [i for i, s in enumerate(secs) if s["label"] == "verse" and i + 1 in chorus and s["bar1"] - s["bar0"] < verse_len]
    if len(lead_ins) >= 2:
        for i in lead_ins:
            secs[i]["label"] = "pre-chorus"
    # bridge: new singing between the second and the last chorus (not a group heard before the second chorus), unless
    # it is a third verse (one part that sounds like the earlier verses and is about as long)
    ch = sorted(chorus)
    if len(ch) >= 3:
        early_groups = {group_of[i] for i in range(ch[1]) if i in group_of}
        block = [i for i in range(ch[1] + 1, ch[-1]) if i in voc and i not in chorus
                 and not (i in group_of and group_of[i] in early_groups)]
        early = [s for s in secs[:ch[1]] if s["label"] == "verse"]
        if block:
            blen = sum(secs[i]["bar1"] - secs[i]["bar0"] for i in block)
            elen = float(np.median([s["bar1"] - s["bar0"] for s in early])) if early else 0.0
            third_verse = (early and len(block) == 1 and secs[block[0]]["label"] == "verse"
                           and {secs[i]["letter"] for i in block} <= {s["letter"] for s in early} and abs(blen - elen) <= 0.25 * elen)
            if not third_verse:
                for i in block:
                    secs[i]["label"] = "bridge"
    # a short riff between two sung sections (under 6 bars) belongs to the section before it, unless it is a real
    # break (4+ LU quieter than a neighbour); the moments still list what changes there
    i = 1
    while i < len(secs) - 1:
        s, p, q = secs[i], secs[i - 1], secs[i + 1]
        if (s["label"] in ("instrumental", "break") and s["bar1"] - s["bar0"] < 6 and p["label"] != "intro"
                and q["label"] not in ("outro",) and not s["loud"] < max(p["loud"], q["loud"]) - 4):
            w0, w1 = p["bar1"] - p["bar0"], s["bar1"] - s["bar0"]
            p["vocal"] = (p["vocal"] * w0 + s["vocal"] * w1) / (w0 + w1)
            p["bar1"] = s["bar1"]
            del secs[i]
            continue
        i += 1
    if not has_lyrics:
        for s in secs:
            if s["label"] in ("verse", "chorus"):
                s["label"] += " (by sound)"
    out = []                          # neighbours with the same name become one section; then number repeated names
    for s in secs:
        if out and out[-1]["label"] == s["label"]:
            o = out[-1]
            w0, w1 = o["bar1"] - o["bar0"], s["bar1"] - s["bar0"]
            o["vocal"] = (o["vocal"] * w0 + s["vocal"] * w1) / (w0 + w1)
            o["bar1"] = s["bar1"]
            o["lines"] += s["lines"]
            o["letter"] = o["letter"] if s["letter"] in o["letter"] else o["letter"] + s["letter"]
        else:
            out.append(s)
    total = Counter(s["label"] for s in out)
    count = Counter()
    for s in out:
        if total[s["label"]] > 1 and s["label"] not in ("intro", "outro"):
            count[s["label"]] += 1
            s["name"] = f"{s['label']} {count[s['label']]}"
        else:
            s["name"] = s["label"]
        s.pop("norms", None)
    return out


# ------------------------------------------------------------------ before / after the music
def region_kind(kinds, lufs):
    """What fills a stretch with no beat: silence, film talking, ambience, or quiet free-time music."""
    if lufs < -50:
        return "silence"
    if not kinds:
        return "no beat (film, talking or free-time music)"
    c = Counter(kinds)
    if c["people talking"] >= 0.3 * len(kinds):
        return "film / people talking"
    if c["music"] >= 0.6 * len(kinds):
        return "quiet music without a beat"
    return "film / ambient sound (no music)"


# ------------------------------------------------------------------ the analysis
def analyse(slug, tags=True, cpu=False):
    if cpu:
        os.environ["AM_DEVICE"] = "cpu"
    clock = Clock()
    warn = []
    A = json.load(open(os.path.join(CACHE, "audio", f"{slug}.json"), encoding="utf-8"))
    mix = os.path.join(MUSIC, A["file"])
    stems_dir = os.path.join(CACHE, "stems", slug)
    song = song_meta(slug, A["file"])
    y, _ = librosa.load(mix, sr=SR, mono=True)
    n = len(y)
    nf = 1 + n // L.HOP
    dur = n / SR
    st = {k: load_stem(stems_dir, k, n) for k in STEMS}
    G = Grid(A, dur)
    clock("load")

    # ---- loud and quiet (stereo mix, BS.1770 K-weighting)
    y2, sr2 = librosa.load(mix, sr=44100, mono=False)
    LD = L.loudness(y2, sr2, nf)
    del y2
    mom, short = LD["momentary"], LD["short"]
    bright = librosa.feature.spectral_centroid(y=y, sr=SR, hop_length=L.HOP)[0]
    bright = np.pad(bright, (0, max(0, nf - len(bright))))[:nf]
    clock("loudness")

    # ---- music region: from the first to the last beat, stretched over the band playing around them
    E = {k: L.stem_env(st[k], nf) for k in STEMS}
    mus_s = ndi.uniform_filter1d(np.maximum.reduce([E[k]["act"] for k in ("drums", "bass", "other")]), int(0.5 * FPS))
    k = int(G.beats[0] * FPS)
    while k > 0 and mus_s[k - 1] > 0.3:
        k -= 1
    music_start = k / FPS
    k = int(G.beats[-1] * FPS)
    while k < nf - 1 and mus_s[k] > 0.12:
        k += 1
    music_end = min(dur, k / FPS)

    # ---- tagger (CLAP), only when the file has a stretch without a beat: film / talking, ambience, silence or music?
    clap, before, after = None, None, None
    dev = D.pick(1.5)
    if tags and (music_start > 4.0 or dur - G.ends[-1] > 4.0):
        try:
            y48, _ = librosa.load(mix, sr=L.Clap.SR, mono=True)
            C = L.Clap(dev)
            TX = C.text()
            tg, T_ = TX["kind"]

            def kinds(t0, t1):
                ps = np.arange(t0, max(t0 + 0.1, t1 - 1.5), 1.5)
                return ps, [tg[int(np.argmax(T_ @ e))] for e in C.audio(y48, ps, 3.0)]
            if music_start > 4.0:
                ps, kd = kinds(0.0, G.beats[0])
                last_non = max([i for i, x in enumerate(kd) if x != "music"], default=-1)
                if last_non >= 0:
                    music_start = max(music_start, min(G.beats[0], ps[last_non] + 3.0))
                before = {"windows": [[round(float(s), 1), x] for s, x in zip(ps, kd)]}
            if dur - G.ends[-1] > 4.0:
                ps, kd = kinds(G.ends[-1], dur)
                for i in range(len(kd) - 1):        # the music ends where two windows in a row are not music
                    if kd[i] != "music" and kd[i + 1] != "music":
                        music_end = min(music_end, max(G.ends[-1], float(ps[i]) + 1.5))
                        break
                after = {"windows": [[round(float(s), 1), x] for s, x in zip(ps, kd)]}
            clap = {"device": dev}
            C.close()
            del y48, C
        except Exception as ex:
            warn.append(f"music tagger skipped: {ex}")
            print("   tagger skipped:", ex)
        D.release()
        clock("tagger")
    if music_start > 2.0:
        lu_pre = L.energy_mean_db(mom[:int(music_start * FPS)])
        before = dict(before or {}, t0=0.0, t1=round(music_start, 2),
                      kind=region_kind([x for _, x in (before or {}).get("windows", [])] if before else [], lu_pre))
    if dur - music_end > 2.0:
        lu_post = L.energy_mean_db(mom[int(music_end * FPS):])
        win_after = [x for s, x in (after or {}).get("windows", []) if s >= music_end - 0.1]
        after = dict(after or {}, t0=round(music_end, 2), t1=round(dur, 2), kind=region_kind(win_after, lu_post))
    else:
        after = None
    tail = None
    if music_end - G.ends[-1] > 2.0:
        tail = {"t0": round(float(G.ends[-1]), 2), "t1": round(music_end, 2),
                "kind": "the music goes on without a beat grid (free time, ring-out or a coda)"}
    fm0, fm1 = int(music_start * FPS), int(music_end * FPS)
    in_music = np.zeros(nf, bool)
    in_music[fm0:fm1] = True
    E = {k: L.stem_env(st[k], nf, in_music) for k in STEMS}         # loud references measured on the music only
    lufs, lra = L.integrated(LD, music_start, music_end)

    # ---- voice: CREPE on the vocal stem, gated by the stem's level; "sung" = voiced inside a lyric line (brass and
    # synths that leak into the vocal stem are voiced too, but they don't sit on the lyric)
    lines = lyric_lines(A, G, warn)
    if lines and not any("fa" in w for x in lines for w in x["words"]):
        warn.append("the lyric was never force-aligned (no align_words.py run): word times are estimates")
    lyr = np.zeros(nf, bool)
    for x in lines:
        lyr[max(0, int((x["t"] - 0.3) * FPS)):int((x["end"] + 0.6) * FPS)] = True
    dev = D.pick(1.0)
    pitch_model = None
    try:
        y16 = librosa.resample(st["vocals"], orig_sr=SR, target_sr=16000)
        f0, per, pitch_model = L.pitch_track(y16, dev, 65.0, 1100.0)
        vact = np.repeat(E["vocals"]["act"], 2)[:len(f0)]               # 50 fps -> CREPE's 100 fps
        vact = np.pad(vact, (0, len(f0) - len(vact)))
        voiced100 = (per > 0.5) & (vact > 0.25)
        vnotes = L.notes_from_f0(f0, voiced100)
        voiced = np.pad(voiced100[::2][:nf], (0, max(0, nf - len(voiced100[::2]))))
        yb = librosa.resample(st["bass"], orig_sr=SR, target_sr=16000)
        bf0, bper, _ = L.pitch_track(yb, dev, 33.0, 400.0)                # CREPE's lowest bin is C1 (32.7 Hz)
        bact = np.repeat(E["bass"]["act"], 2)[:len(bf0)]
        bact = np.pad(bact, (0, len(bf0) - len(bact)))
        bnotes = L.notes_from_f0(bf0, (bper > 0.45) & (bact > 0.3), min_len=0.1)
        del y16, yb, f0, per, bf0, bper
    except Exception as ex:
        warn.append(f"pitch tracking failed ({ex}); voice activity from the stem level only")
        print("   pitch tracking failed:", ex)
        voiced = E["vocals"]["act"] > 0.45
        vnotes, bnotes = [], []
    D.release()
    sung = voiced & lyr if lines else voiced
    for nt in vnotes:
        nt["in_lyric"] = bool(lyr[min(nf - 1, int((nt["t"] + nt["end"]) / 2 * FPS))]) if lines else True
    voice_lane = ndi.uniform_filter1d(voiced.astype(float) * np.maximum(E["vocals"]["act"], 0.35), 5)
    clock(f"pitch ({pitch_model or 'none'} on {dev})")

    # ---- harmony: chords per beat, key
    hs, bs, lv = L.harmony_chroma(st["other"] + 0.15 * st["vocals"], st["bass"], G.beats)
    beat_ch = L.chords(hs, bs, lv, G.beat_in_bar[:hs.shape[1]])
    beat_ch = beat_ch + [beat_ch[-1]] * (len(G.beats) - len(beat_ch))
    key_name, key_score, key2, key2_score = L.key(hs + 0.5 * bs, weights=10 ** (lv / 20))
    key_spelled, spell = L.speller(key_name)                    # Db in Ab major, G# in E major (output only)
    beat_ch = [spell(c) for c in beat_ch]
    bar_ch = L.bar_chords(beat_ch, G.bar_beats)
    clock("chords + key")

    # ---- structure: repetition classes per beat -> bars; boundaries from all the evidence (segment); names
    harm_mix = st["other"] + st["bass"] + 0.6 * st["vocals"]
    cq = librosa.amplitude_to_db(np.abs(librosa.cqt(y=harm_mix, sr=SR, hop_length=512, bins_per_octave=36, n_bins=6 * 36,
                                                    fmin=librosa.note_to_hz("C1"))), ref=np.max)
    bfr = np.clip(librosa.time_to_frames(G.beats, sr=SR, hop_length=512), 0, cq.shape[1] - 1)
    Cs = librosa.util.sync(cq, bfr, aggregate=np.median, pad=False)
    mf = librosa.feature.mfcc(y=y, sr=SR, hop_length=512, n_mfcc=13)
    Ms = librosa.util.sync(mf, bfr, aggregate=np.mean, pad=False)
    del cq, mf, harm_mix
    k_cls = int(np.clip(round(G.nb / 16) + 2, 4, 7))
    blab = L.structure(Cs, Ms, k_cls)
    blab = np.r_[blab, blab[-1:]][:len(G.beats)]
    bar_lab = [int(np.bincount(blab[idx]).argmax()) if len(idx) else -1 for idx in G.bar_beats]
    bar_loud = np.array([L.energy_mean_db(mom[a:max(b, a + 1)]) for a, b in G.spans])
    vfrac = np.array([float(sung[a:max(b, a + 1)].mean()) for a, b in G.spans])

    def ref90(key):
        return float(np.percentile([L.energy_mean_db(E[key]["db"][a:max(b, a + 1)]) for a, b in G.spans], 90))
    lvl = {k: L.bar_level(E[k]["db"], ref90(k), G.spans) for k in ("drums", "bass", "other")}
    R, why = segment(G, bar_lab, lines, vfrac, bar_loud, lvl)
    secs = label_sections(R, lines, vfrac, bar_loud, bool(lines))
    for s in secs:
        s["why"] = why.get(s["bar0"], ["start"] if s["bar0"] == 0 else [])
    clock(f"structure (k={k_cls})")

    # ---- per bar
    vdig = [int(np.clip(round(9 * min(1.0, f / 0.7)), 0, 9)) for f in vfrac]
    words = [(float(w["t"]), w["w"]) for x in lines for w in x["words"]]
    bars = []
    for i, (t0, t1) in enumerate(zip(G.db, G.ends)):
        bw = [(w, G.pos(t)[1], round(t, 3)) for t, w in words if G.bar_of(t) == i and G.pos(t)]
        bars.append({"i": i, "t": round(float(t0), 3), "end": round(float(t1), 3), "beats": int(len(G.bar_beats[i])),
                     "bpm": round(G.bar_bpm(i), 1), "chord": bar_ch[i], "loud": round(float(bar_loud[i]), 1),
                     "v": vdig[i], "d": lvl["drums"][i], "b": lvl["bass"][i], "o": lvl["other"][i],
                     "words": [list(x) for x in bw], "events": []})
    for s in secs:
        for b in bars[s["bar0"]:s["bar1"]]:
            b["section"] = s["name"]

    # ---- melody per lyric line: the peak note, held words
    lyric_notes = [nt for nt in vnotes if nt["in_lyric"]]
    for x in lines:
        ns = [nt for nt in lyric_notes if nt["t"] < x["end"] + 0.4 and nt["end"] > x["t"] - 0.05]
        for w in x["words"]:
            wn = [nt for nt in ns if nt["t"] < w.get("t_end", w["t"] + 0.3) + 0.05 and nt["end"] > w["t"]]
            if wn:
                w["note"] = max(wn, key=lambda nt: nt["dur"])["name"]
                w["held"] = round(max(nt["end"] for nt in wn) - w["t"], 2)
        if ns:
            pk = max(ns, key=lambda nt: (nt["midi"], nt["dur"]))
            x["peak"] = {"note": pk["name"], "midi": pk["midi"], "t": pk["t"],
                         "word": next((w["w"] for w in x["words"] if w["t"] <= pk["t"] + 0.08 and pk["t"] < w.get("t_end", w["t"]) + 0.15), None)}
            x["contour"] = contour([nt["midi"] for nt in ns])
    clock("lyrics")

    # ---- moments
    moments = find_moments(G, secs, bars, E, mom, lyric_notes, A, music_start, music_end, dur, lufs, key_name,
                           hs, bs, lv, before, after, tail)
    for m in moments:
        p = G.pos(m["t"])
        if p and 0 <= p[0] < len(bars):
            bars[p[0]]["events"].append(m["short"])
    clock("moments")

    # ---- sections: summaries
    main_bpm = 60 / G.beat_s
    for s in secs:
        a, b = s["bar0"], s["bar1"]
        s["t0"], s["t1"] = round(float(G.db[a]), 3), round(float(G.ends[b - 1]), 3)
        s["loud"] = round(L.energy_mean_db(bar_loud[a:b]), 1)
        for k_, key_ in (("voice", "v"), ("drums", "d"), ("bass", "b"), ("other", "o")):
            s[k_] = int(round(np.mean([bb[key_] for bb in bars[a:b]])))
        loop, reps = L.loop_of(bar_ch[a:b])
        s["chords"] = {"loop": loop, "repeats": round(reps, 1)} if loop else {"bars": bar_ch[a:b]}
        s["first_line"] = s["lines"][0]["text"] if s["lines"] else ""
        s["n_lines"] = len(s["lines"])
        s["lines"] = [x["i"] for x in s["lines"]]
        s["bpm"] = round(float(np.median([bb["bpm"] for bb in bars[a:b]])), 1)
    half = [s["name"] for s in secs if abs(s["bpm"] - main_bpm) / main_bpm > 0.15]

    in_lyr = [nt["midi"] for nt in lyric_notes if nt["dur"] >= 0.12]
    model = {
        "slug": slug, "file": A["file"], "artist": song.get("artist", ""), "title": song.get("title", ""),
        "duration": round(dur, 3),
        "tempo": {"bpm": round(main_bpm, 1), "beat_s": round(G.beat_s, 4), "bar_s": round(G.bar_s, 3),
                  "grid": "constant (click-steady)" if (A.get("grid") or {}).get("constant") else "live (tempo breathes)",
                  "meter": f"{int(np.median([len(x) for x in G.bar_beats]))}/4", "irregular_bars": A.get("irregular_bars", []),
                  "other_grid": [{"section": s["name"], "bpm": s["bpm"]} for s in secs if s["name"] in half]},
        "key": {"name": key_spelled, "score": key_score, "runner_up": L.speller(key2)[0], "runner_up_score": key2_score},
        "loudness": {"integrated_lufs": round(lufs, 1), "range_lu": round(lra, 1)},
        "music": {"start": round(music_start, 2), "end": round(music_end, 2), "first_beat": round(float(G.beats[0]), 3),
                  "last_beat": round(float(G.beats[-1]), 3), "grid_end": round(float(G.ends[-1]), 3),
                  "before": before, "after": after, "tail": tail},
        "vocals": {"range": [L.note_name(min(in_lyr)), L.note_name(max(in_lyr))] if in_lyr else None,
                   "core": [L.note_name(np.percentile(in_lyr, 10)), L.note_name(np.percentile(in_lyr, 90))] if in_lyr else None,
                   "sung_bars": round(float(np.mean(np.array(vdig) >= 3)), 2),
                   "first": round(lines[0]["t"], 2) if lines else None, "last": round(lines[-1]["end"], 2) if lines else None},
        "lyrics_meta": A.get("lyrics_meta"),
        "beats": [round(float(b), 3) for b in G.beats],
        "sections": secs, "bars": bars, "moments": moments,
        "lyrics": [{k_: v for k_, v in x.items() if k_ != "norm"} for x in lines],
        "notes": {"vocal": vnotes, "bass": bnotes},
        "chords": collapse([(float(G.beats[j]), c) for j, c in enumerate(beat_ch)], float(G.ends[-1])),
    }
    env = {"fps": 10, "loudness_lufs": dec(mom, 5, np.mean, 1), "short_lufs": dec(short, 5, np.mean, 1),
           "voice": dec(voice_lane, 5, np.mean, 2), "sung": dec(sung.astype(float), 5, np.mean, 2),
           "drums": dec(E["drums"]["act"], 5, np.max, 2), "bass": dec(E["bass"]["act"], 5, np.mean, 2),
           "other": dec(E["other"]["act"], 5, np.mean, 2), "brightness_hz": dec(bright, 5, np.mean, 0)}
    mt = os.path.join(stems_dir, "model.txt")
    report = {"slug": slug, "created": time.strftime("%Y-%m-%d %H:%M"), "device": D.info(), "vram_peak_gb": D.peak_gb(),
              "models": {"stems": open(mt).read().strip() if os.path.exists(mt) else "htdemucs (no model.txt: made before the GPU separation)",
                         "beats": "beat_this final0", "lyric_alignment": "torchaudio MMS_FA",
                         "pitch": f"torchcrepe {pitch_model}" if pitch_model else None,
                         "tagger": L.CLAP_MODEL if clap is not None else None},
              "timings_s": clock.d, "warnings": warn,
              "confidence": confidence(A, lines, key_score, key2_score, secs, sung, in_music)}
    return model, env, report, {"G": G}


def contour(ms):
    if len(ms) < 3:
        return "level"
    a, b, c = np.mean(ms[:max(1, len(ms) // 3)]), max(ms), np.mean(ms[-max(1, len(ms) // 3):])
    if b - max(a, c) >= 3:
        return "arches up"
    if c - a >= 2:
        return "rises"
    if a - c >= 2:
        return "falls"
    return "level"


def collapse(seq, end):
    out = []
    for t, c in seq:
        if out and out[-1]["chord"] == c:
            continue
        if out:
            out[-1]["end"] = round(t, 3)
        out.append({"t": round(t, 3), "end": None, "chord": c})
    if out:
        out[-1]["end"] = round(end, 3)
    return out


def dec(x, f, agg, digits):
    n = len(x) // f
    v = agg(np.asarray(x[:n * f], dtype=float).reshape(n, f), axis=1)
    return [round(float(a), digits) if digits else int(round(float(a))) for a in v]


def confidence(A, lines, ks, k2s, secs, sung, in_music):
    meta = A.get("lyrics_meta") or {}
    ws = [w for x in lines for w in x["words"]]
    aligned = np.mean([w.get("fa", 0) >= 0.02 for w in ws]) if ws else None
    return {"lyrics": f"{meta.get('source', 'none')}, match_z {meta.get('match_z')}" if meta else "no lyrics",
            "words_aligned": round(float(aligned), 2) if aligned is not None else None,
            "key_margin": round(ks - k2s, 3),
            "beat_grid": "constant" if (A.get("grid") or {}).get("constant") else f"live (drift {(A.get('grid') or {}).get('drift_ms')} ms)",
            "sections": len(secs), "sung_share_of_music": round(float(sung[in_music].mean()), 2) if in_music.any() else None}


# ------------------------------------------------------------------ moments
STEM_WORDS = {"d": ("drums", "come in", "drop out"), "b": ("bass", "comes in", "drops out"),
              "o": ("the band (guitars / keys / synths)", "comes in", "drops out")}


def find_moments(G, secs, bars, E, mom, vnotes, A, m0, m1, dur, lufs, key_name, hs, bs, lv, before, after, tail):
    """Events an editor cuts on, ranked 1-3 stars."""
    M = []

    def add(t, kind, text, stars, short=None):
        M.append({"t": round(float(t), 3), "pos": G.pos_str(t), "kind": kind, "text": text, "stars": stars,
                  "short": short or kind})
    loud = np.array([b["loud"] for b in bars])
    nb = len(bars)
    if before:
        add(m0, "music starts", f"the music starts after {m0:.0f} s of {before['kind']}", 2, "music starts")
    else:
        add(m0, "music starts", "the song starts", 1, "music starts")
    chor = [s for s in secs if s["label"] == "chorus"]
    for s in secs[1:]:
        big = chor and (s is chor[0] or s is chor[-1])
        st = 3 if big else 2 if s["label"] in ("chorus", "bridge", "instrumental", "break") else 1
        add(G.db[s["bar0"]], "section", f"{s['name']} starts", st, s["name"])
    # loudness lifts and drops between bars (2 bars before vs 2 after); of jumps within 2 bars only the biggest counts,
    # and only the song's three biggest lifts get three stars
    ups, downs = [], []
    for i in range(2, nb - 1):
        d = L.energy_mean_db(loud[i:i + 2]) - L.energy_mean_db(loud[i - 2:i])
        if d >= 4.0 and loud[i] - loud[i - 1] >= 2.5:
            ups.append((d, i))
        elif d <= -5.0 and loud[i] - loud[i - 1] <= -3:
            downs.append((-d, i))

    def strongest(c):
        keep = []
        for d, i in sorted(c, reverse=True):
            if all(abs(i - j) > 2 for _, j in keep):
                keep.append((d, i))
        return keep
    ups = strongest(ups)
    for rank, (d, i) in enumerate(ups):
        entering = [STEM_WORDS[k][0].split(" ")[0] for k in ("d", "b") if bars[i][k] - max(bars[i - 1][k], bars[i - 2][k]) >= 3]
        kind = "drop" if d >= 6 and entering else "lift"
        add(G.db[i], kind, f"{'a drop' if kind == 'drop' else 'a lift'}: +{d:.0f} LU" + (f" ({' + '.join(entering)} in)" if entering else ""),
            3 if d >= 6 and rank < 3 else 2, f"{kind} +{d:.0f}")
    for d, i in strongest(downs):
        add(G.db[i], "drop-out", f"it drops away: -{d:.0f} LU", 2, f"drop-out -{d:.0f}")
    # stem entrances and exits (2 bars out -> 2 bars in, or the reverse)
    for key, (name, vin, vout) in STEM_WORDS.items():
        lv_ = np.array([b[key] for b in bars])
        stem = {"d": "drums", "b": "bass", "o": "other"}[key]
        for i in range(2, nb - 1):
            if lv_[i - 2:i].max() <= 2 and lv_[i:i + 2].min() >= 4:
                away = next((i - j for j in range(i - 1, -1, -1) if lv_[j] > 2), i)
                big = key == "d" and away >= 8        # the drums arriving after 8+ bars (or for the first time)
                add(first_hit(E[stem], G, i), "enters", f"{name} {vin}" + (f" after {away} bars without" if big else ""),
                    3 if big else 2, f"{name.split(' ')[0]} in")
            if lv_[i - 2:i].min() >= 4 and lv_[i:i + 2].max() <= 2:
                add(G.db[i], "drops out", f"{name} {vout}", 2, f"{name.split(' ')[0]} out")
    # a cappella: singing with (almost) no band
    def bare(b):
        return b["v"] >= 5 and b["d"] <= 1 and b["b"] <= 2 and b["o"] <= 3
    i = 0
    while i < nb:
        if bare(bars[i]):
            j = i
            while j + 1 < nb and bare(bars[j + 1]):
                j += 1
            add(G.db[i], "a cappella", f"(almost) a cappella for {j - i + 1} bar{'s' if j > i else ''}: the voice alone", 3, "a cappella")
            i = j + 1
        else:
            i += 1
    # builds: loudness climbing for 2+ bars into a lift / drop / chorus
    targets = sorted({G.bar_of(m["t"]) for m in M if m["kind"] in ("drop", "lift")} |
                     {s["bar0"] for s in secs if s["label"] == "chorus"})
    for i in targets:
        if i < 3:
            continue
        j = i - 1
        while j - 1 >= 0 and loud[j] - loud[j - 1] >= 0.4 and i - j < 8:
            j -= 1
        if i - j >= 2 and loud[i - 1] - loud[j] >= 2.5:
            add(G.db[j], "build", f"a build: {i - j} bars climbing {loud[i - 1] - loud[j]:.0f} LU into bar {i}", 2, "build")
    # stop-time silences (loud on both sides)
    k0, k1 = int(m0 * FPS) + int(2 * FPS), int(m1 * FPS) - int(2 * FPS)
    i = k0
    while i < k1:
        if mom[i] < lufs - 18:
            j = i
            while j < k1 and mom[j] < lufs - 18:
                j += 1
            d_ = (j - i) / FPS
            if 0.15 <= d_ <= 3.0 and np.median(mom[max(0, i - int(FPS)):i]) > lufs - 8 and np.median(mom[j:j + int(FPS)]) > lufs - 8:
                add(i / FPS - 0.2, "stop", f"stop-time: {d_:.1f} s of near-silence", 3, f"stop {d_:.1f}s")
            i = j
        i += 1
    # crash cymbals on downbeats (the strongest few)
    cy = [c for c in A.get("cymbals", []) if c["s"] >= 0.8 and np.min(np.abs(G.db - c["t"])) < 0.06]
    for c in sorted(cy, key=lambda c: -c["s"])[:8]:
        add(c["t"], "crash", "crash cymbal on the downbeat", 1, "crash")
    # drum fills into a section: a busy last beat before its downbeat
    hits = np.array(sorted([h["t"] for h in A.get("snares", []) + A.get("kicks", [])]))
    if len(hits) and nb > 2:
        dens = [int(np.sum((hits >= G.db[i] - G.beat_s) & (hits < G.db[i] - 0.03))) for i in range(1, nb)]
        med = np.median(dens)
        for s in secs[1:]:
            i = s["bar0"]
            if dens[i - 1] >= max(3, 2 * med + 1):
                add(G.db[i] - G.beat_s, "fill", f"drum fill into {s['name']}", 1, "fill")
    # the voice (only notes sung on the lyric): highest notes, long holds
    if vnotes:
        for nt in sorted([nt for nt in vnotes if nt["dur"] >= max(0.9, 2 * G.beat_s)], key=lambda nt: -nt["dur"])[:6]:
            add(nt["t"], "held note", f"held {nt['name']} for {nt['dur']:.1f} s", 2, f"held {nt['dur']:.1f}s")
        seen = []
        for nt in sorted([nt for nt in vnotes if nt["dur"] >= 0.25], key=lambda nt: (-nt["midi"], -nt["dur"])):
            if len(seen) >= 3:
                break
            if all(abs(nt["t"] - s) > 8 for s in seen):
                seen.append(nt["t"])
                add(nt["t"], "high note", f"one of the highest sung notes: {nt['name']} ({nt['dur']:.1f} s)", 2, f"high {nt['name']}")
    # key change: a late section clearly in a key a step or two above
    for s in [s for s in secs if s["bar1"] - s["bar0"] >= 4][2:]:
        idx = np.concatenate([G.bar_beats[i] for i in range(s["bar0"], s["bar1"])])
        idx = idx[idx < hs.shape[1]]
        if len(idx) < 8:
            continue
        kn, ksc, _, _ = L.key(hs[:, idx] + 0.5 * bs[:, idx], weights=10 ** (lv[idx] / 20))
        up = (L.PITCH.index(kn.split()[0]) - L.PITCH.index(key_name.split()[0])) % 12
        if kn.split()[1] == key_name.split()[1] and up in (1, 2, 3) and ksc >= 0.8:
            add(G.db[s["bar0"]], "key change", f"key change: up {up} semitone{'s' if up > 1 else ''} to {L.speller(kn)[0]}", 3, f"key +{up}")
    # peak: the loudest 4 bars
    if nb >= 6:
        p = int(np.argmax(np.convolve(10 ** (loud / 10), np.ones(4) / 4, "valid")))
        add(G.db[p], "peak", f"the loudest stretch: bars {p}-{p + 3}", 2, "loudest")
    # the ending
    if tail:
        add(tail["t0"], "beat grid ends", f"the beat grid ends; {tail['kind']} until {songdoc.mmss(tail['t1'])}", 2, "grid ends")
    tl = mom[max(0, int(m1 * FPS) - int(8 * FPS)):int(m1 * FPS)]
    if len(tl) > 10:
        slope = np.polyfit(np.arange(len(tl)), tl, 1)[0] * FPS
        if slope < -2.0 and tl[: len(tl) // 3].mean() - tl[-len(tl) // 4:].mean() > 12:
            add(m1 - 8, "ending", f"fades out over the last ~8 s (to {songdoc.mmss(m1)})", 2, "fade")
        else:
            hs_ = [o["t"] for o in A.get("onsets", []) if o["s"] > 0.5 and o["t"] < m1]
            last = hs_[-1] if hs_ else m1
            add(last, "ending", f"ends on a hit at {songdoc.mmss(last, 2)}; rings out to {songdoc.mmss(m1)}", 3, "last hit")
    if after:
        add(m1, "music ends", f"the music ends; {dur - m1:.0f} s of {after['kind']} follow in the file", 2, "music ends")
    M.sort(key=lambda m: (m["t"], -m["stars"]))
    out = []                                   # one row per moment in time: merge what happens together
    for m in M:
        if out and m["t"] - out[-1]["t"] < 0.12:
            o = out[-1]
            o["stars"] = max(o["stars"], m["stars"])
            if m["text"] not in o["text"]:
                o["text"] += " · " + m["text"]
                o["short"] += ", " + m["short"]
                o["kind"] += "+" + m["kind"]
            continue
        out.append(dict(m))
    return out


def first_hit(env, G, i):
    """The first beat in bar i (or the beat before it: pickups) where a stem is clearly playing."""
    act = env["act"]
    for j in range(max(0, G.dbi[i] - 1), G.dbi[i] + len(G.bar_beats[i])):
        f = int(G.beats[j] * FPS)
        if act[f:f + int(0.15 * FPS)].max() > 0.55:
            return float(G.beats[j])
    return float(G.db[i])


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--no-tags", action="store_true", help="skip the CLAP check of stretches without a beat")
    ap.add_argument("--cpu", action="store_true", help="run every model on the CPU")
    a = ap.parse_args()
    slug = a.slug or default_slug()
    print(f"== song kit: {slug}  ({'CPU (--cpu)' if a.cpu else D.info()['gpu'] or 'CPU'})", flush=True)
    model, env, report, raw = analyse(slug, tags=not a.no_tags, cpu=a.cpu)
    out = os.path.join(ROOT, "song", slug)
    songdoc.write(out, model, env, report, raw)
    print(f"-> {out}")


if __name__ == "__main__":
    main()
