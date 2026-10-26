"""Writers for the song kit (tools/song_kit.py): README, song map, timed lyrics, the song-story skeleton, the JSON files
and the lane pictures (overview + 16-bar pages)."""
import json, os
import numpy as np

STAR = {1: "★", 2: "★★", 3: "★★★"}
LANE_COLORS = {"chorus": "#e8734a", "pre-chorus": "#d9a441", "post-chorus": "#d98a41", "refrain": "#d98a41",
               "verse": "#5b8fd9", "bridge": "#a46fd9", "intro": "#6c7a89", "outro": "#6c7a89",
               "instrumental": "#3fae8f", "break": "#2f6f60"}


def mmss(t, digits=1):
    m, s = divmod(max(0.0, float(t)), 60)
    return f"{int(m)}:{s:0{3 + digits if digits else 2}.{digits}f}"


def tempo_word(bpm):
    return "slow" if bpm < 85 else "mid-tempo" if bpm < 115 else "upbeat" if bpm < 135 else "fast"


def stems_str(s):
    return f"{s['voice']} {s['drums']} {s['bass']} {s['other']}"


def chords_str(c):
    if c.get("loop"):
        return " ".join(c["loop"]) + (f" (x{c['repeats']:g})" if c["repeats"] >= 1.5 else "")
    seq = [x for i, x in enumerate(c.get("bars", [])) if x and (i == 0 or x != c["bars"][i - 1])]
    return " ".join(seq[:8]) + (" …" if len(seq) > 8 else "")


def shape(m):
    secs = m["sections"]
    if not secs:
        return ""
    lo, hi = min(s["loud"] for s in secs), max(s["loud"] for s in secs)
    out = []
    for s in secs:
        r = (s["loud"] - lo) / (hi - lo + 1e-9)
        word = "quiet" if r < 0.3 else "" if r < 0.75 else "loud" if r < 0.95 else "LOUDEST"
        out.append(s["name"] + (f" ({word})" if word else ""))
    return " → ".join(out)


# ------------------------------------------------------------------ song-map.md
def song_map_md(m):
    t, k, ld, mu, vo = m["tempo"], m["key"], m["loudness"], m["music"], m["vocals"]
    title = f"{m['artist']} – {m['title']}" if m.get("artist") else m["file"]
    L = [f"# Song map: {title}", "",
         f"Read `README.md` first. Times are seconds in `music/{m['file']}` (m:ss.s). `17:2.5` = bar 17, beat 2.5 = "
         "`F.beat(17, 2.5)`; bar 0 is the first downbeat, beats count from 0 (0 = the downbeat).", "",
         "## At a glance",
         f"- **Tempo** {t['bpm']:g} BPM ({tempo_word(t['bpm'])}); a bar is {t['bar_s']:.2f} s ({t['meter']}); {t['grid']}"
         + (f"; irregular bars at {', '.join(f'{x:.1f}s' for x in t['irregular_bars'][:6])}" if t.get("irregular_bars") else ""),
         f"- **Key** {k['name']} (fit {k['score']:.2f}; next best {k['runner_up']} {k['runner_up_score']:.2f})",
         f"- **Length** {mmss(m['duration'])} in the file; **the music runs {mmss(mu['start'])} – {mmss(mu['end'])}**"
         + (f"; before it: {mu['start']:.0f} s of {mu['before']['kind']}" if mu.get("before") else "")
         + (f"; after it: {m['duration'] - mu['end']:.0f} s of {mu['after']['kind']}" if mu.get("after") else ""),
         f"- **Loudness** {ld['integrated_lufs']:g} LUFS integrated over the music, loudness range {ld['range_lu']:g} LU"]
    if t.get("other_grid"):
        def feel(b):
            r = b / t["bpm"]
            return "half-time" if abs(r - 0.5) < 0.08 else "double-time" if abs(r - 2) < 0.2 else "mixed"
        L.append("- **Beat grid** the tracked beat differs from the main tempo in "
                 + "; ".join(f"{g['section']} ({g['bpm']:g} BPM, {feel(g['bpm'])})" for g in t["other_grid"])
                 + ": `F.beat` counts the tracked beats, so a bar there is longer or shorter (see the bar times)")
    if mu.get("tail"):
        L.append(f"- **After the last bar** ({mmss(mu['tail']['t0'])}–{mmss(mu['tail']['t1'])}): {mu['tail']['kind']}; "
                 "no bar:beat there, use song times")
    if vo.get("range"):
        L.append(f"- **Voice** sung in {vo['sung_bars'] * 100:.0f}% of bars; range {vo['range'][0]}–{vo['range'][1]} "
                 f"(mostly {vo['core'][0]}–{vo['core'][1]})"
                 + (f"; first word {mmss(vo['first'])}, last {mmss(vo['last'])}" if vo.get("first") is not None else ""))
    L.append(f"- **Shape** {shape(m)}")
    lm = m.get("lyrics_meta") or {}
    if m["lyrics"]:
        L.append(f"- **Lyrics** {lm.get('source', '?')} ({len(m['lyrics'])} lines), words force-aligned on the vocal stem: "
                 "word times are when they are *sung*. Full text: `lyrics.md`")
    else:
        L.append("- **Lyrics** none found: sections are named by sound only")
    L += ["", "## Sections",
          "V D B O = voice / drums / bass / other (guitars, keys, synths): 0-9, mean over the section (see README).", "",
          "| # | section | sound | bars | time | length | LUFS | V D B O | chords | first line |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    if mu.get("before"):
        b = mu["before"]
        L.append(f"| – | *before the music* | | – | {mmss(b['t0'])}–{mmss(b['t1'])} | {b['t1'] - b['t0']:.0f} s | | | | {b['kind']} |")
    for i, s in enumerate(m["sections"]):
        L.append(f"| {i + 1} | **{s['name']}** | {s['letter']} | {s['bar0']}–{s['bar1'] - 1} | {mmss(s['t0'])}–{mmss(s['t1'])} | "
                 f"{s['t1'] - s['t0']:.0f} s | {s['loud']:g} | {stems_str(s)} | {chords_str(s['chords'])} | {s['first_line']} |")
    if mu.get("tail"):
        tl = mu["tail"]
        L.append(f"| – | *after the last bar* | | – | {mmss(tl['t0'])}–{mmss(tl['t1'])} | {tl['t1'] - tl['t0']:.0f} s | | | | {tl['kind']} |")
    if mu.get("after"):
        a = mu["after"]
        L.append(f"| – | *after the music* | | – | {mmss(a['t0'])}–{mmss(a['t1'])} | {a['t1'] - a['t0']:.0f} s | | | | {a['kind']} |")
    L += ["", "## Moments", "Where to cut, hold, reveal or go quiet. ★★★ = the big ones (the song's own peaks and turns).", "",
          "| time | bar:beat | ★ | what |", "|---|---|---|---|"]
    for e in m["moments"]:
        L.append(f"| {mmss(e['t'], 2)} | {e['pos']} | {STAR[e['stars']]} | {e['text']} |")
    L += ["", "## Bar by bar",
          "Columns: bar · time · chord · LUFS (the bar's loudness; ↑/↓ = 3+ LU jump) · V D B O (0-9) · sung words "
          "(`word@beat`, beat counted from the bar's downbeat) · events. A `(n)` after the time = n beats in that bar "
          "(when not the usual count)."]
    usual = int(m["tempo"]["meter"].split("/")[0])
    bars = m["bars"]
    for s in m["sections"]:
        L += ["", f"### {s['name']} ({s['letter']}) · bars {s['bar0']}–{s['bar1'] - 1} · {mmss(s['t0'])}–{mmss(s['t1'])}", "```",
              " bar  time        chord    LUFS   V D B O  words / events"]
        for b in bars[s["bar0"]:s["bar1"]]:
            prev = bars[b["i"] - 1]["loud"] if b["i"] else b["loud"]
            arrow = "↑" if b["loud"] - prev >= 3 else "↓" if b["loud"] - prev <= -3 else " "
            nb = f"({b['beats']})" if b["beats"] != usual else ""
            ws = " ".join(f"{w}@{p:g}" if p is not None else w for w, p, _ in
                          [(w, round(p, 1) if p is not None else None, t) for w, p, t in b["words"]])
            ev = ("  ◆ " + ", ".join(b["events"])) if b["events"] else ""
            L.append(f"{b['i']:4d}  {mmss(b['t'], 2):>8s}{nb:<4s} {b['chord']:<8s} {b['loud']:5.0f}{arrow}  "
                     f"{b['v']} {b['d']} {b['b']} {b['o']}  {ws}{ev}".rstrip())
        L.append("```")
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ lyrics.md
def lyrics_md(m):
    title = f"{m['artist']} – {m['title']}" if m.get("artist") else m["file"]
    lm = m.get("lyrics_meta") or {}
    L = [f"# Lyrics, timed: {title}", ""]
    if not m["lyrics"]:
        return "\n".join(L + ["No lyrics: either an instrumental, or none were found (LRCLIB). The song map names sections by sound."]) + "\n"
    L.append(f"Source: {lm.get('source', '?')}" + (f" #{lm['id']} ({lm.get('album')})" if lm.get("id") else "")
             + (f", matched to this file with z = {lm['match_z']}" if lm.get("match_z") is not None else "")
             + ". Times are when each line's first word is **sung** (forced alignment on the vocal stem). "
             "`bar:beat` as `F.beat()` takes it. A caption for a line goes on the 8th at or just before that time (`F.cue`).")
    reps = {}
    for x in m["lyrics"]:
        if x["repeat"]:
            reps.setdefault(x["text"].strip().lower(), [x["text"], 0])[1] += 1
    if reps:
        top = sorted(reps.values(), key=lambda v: -v[1])[:6]
        L.append("")
        L.append("**Lines that come back** (the hook): " + " · ".join(f"\"{t}\" ×{n}" for t, n in top))
    bysec = {}
    for s in m["sections"]:
        for li in s["lines"]:
            bysec[li] = s
    cur = None
    for x in m["lyrics"]:
        s = bysec.get(x["i"])
        if s is not cur:
            cur = s
            head = f"{s['name']} · bars {s['bar0']}–{s['bar1'] - 1} · {mmss(s['t0'])}–{mmss(s['t1'])}" if s else "(between sections)"
            L += ["", f"## {head}", "", "| sung at | bar:beat | line | melody |", "|---|---|---|---|"]
        mel = []
        if x.get("contour"):
            mel.append(x["contour"])
        if x.get("peak"):
            mel.append(f"peak {x['peak']['note']}" + (f" on \"{x['peak']['word']}\"" if x["peak"].get("word") else ""))
        held = [f"\"{w['w']}\" {w['held']:.1f} s" for w in x["words"] if w.get("held", 0) >= 0.6]
        if held:
            mel.append("holds " + ", ".join(held[:3]))
        rep = f" *(×{x['repeat'] + 1})*" if x["repeat"] else ""
        L.append(f"| {mmss(x['t'], 2)} | {x.get('pos', '')} | {x['text']}{rep} | {'; '.join(mel)} |")
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ song-story.md (skeleton)
def story_md(m):
    title = f"{m['artist']} – {m['title']}" if m.get("artist") else m["file"]
    L = [f"# Song story: {title}", "",
         "> Written by the director after reading `lyrics.md` and `song-map.md`, then checked with the user. It is the *why*",
         "> behind the edit: what the song is about and how its arc can carry this trip. Keep it short; the user's own",
         "> associations with the song win over any reading of the lyric.", "",
         "## What it's about", "_2–4 sentences: the situation, the feeling, who sings to whom._", "",
         "## The arc, section by section", "",
         "| section | bars | time | in the song | feeling | what the film could do |", "|---|---|---|---|---|---|"]
    for s in m["sections"]:
        L.append(f"| {s['name']} | {s['bar0']}–{s['bar1'] - 1} | {mmss(s['t0'], 0)}–{mmss(s['t1'], 0)} | "
                 f"{('“' + s['first_line'] + '”') if s['first_line'] else ''} |  |  |")
    L += ["", "## Lines that could carry a moment", "_Lyric-literal ideas: the line (time), what photo or device could answer it._", "",
          "## Where it peaks, where it breathes", "_The 2–3 biggest moments in the song map and what each is for._", "",
          "## This trip, these people", "_How the song's story maps onto the trip. The user's own associations with the song._", ""]
    return "\n".join(L)


# ------------------------------------------------------------------ README.md
def readme_md(m, report):
    return f"""# The song folder: how to read it

Made by `tools/song_kit.py` from the mix, the Demucs stems and the aligned lyrics (`studio.py song <project>` remakes it).
The AI can't hear the song: these files are what a good editor hears, written down. Start with `song-map.md`,
look at `overview.png`, read `lyrics.md`, then write `song-story.md` with the user.

| file | what |
|---|---|
| `song-map.md` | at a glance → sections → moments → every bar (chord, loudness, voice/drums/bass/other, sung words, events) |
| `lyrics.md` | the lyric by section: when each line is sung, `bar:beat`, the hook, melody (contour, peak note, held words) |
| `song-story.md` | what the song is about and how its arc can carry the film: written by the director, never overwritten |
| `overview.png` | the whole song in lanes, the way an editor sees a timeline |
| `pages/bars_*.png` | 16 bars per picture: every word, chord and beat readable |
| `song-map.json` | everything as data: `beats`, `bars`, `sections`, `moments`, `lyrics` (words with sung time, note, held), `notes` (vocal + bass), `chords` |
| `envelopes.json` | 10 Hz curves: `loudness_lufs` (momentary), `short_lufs` (3 s), `voice`, `drums`, `bass`, `other` (0-1), `brightness_hz` |
| `report.json` | models, device, timings, confidence and warnings: check it when something looks wrong |

## Notation
- **Time**: seconds in the song file (`m:ss.s`). Film time = song time − segment in + segment at (`F.song2film`).
- **bar:beat**: `17:2.5` = `F.beat(17, 2.5)`: bar 17 (bar 0 = the first downbeat, as `F.bar(n)`), beat 2.5 counted
  from that downbeat (0 = the downbeat itself; .5 = the 8th after a beat). Negative beats = pickups before bar 0.
- **LUFS**: loudness as ears hear it (EBU R128, K-weighted). −8 is very loud, −14 normal, −25 quiet. Differences
  matter more than values: +3 LU is clearly louder, +6 LU is a big lift.
- **V D B O** (0-9): **V** = how much of the bar is sung (9 = sung all through); **D / B / O** = how loud the drums,
  bass and *other* (guitars, keys, synths, strings) are against their own loudest bars (0 = not playing, 9 = full).
- **Sections**: names come from repetition (the *sound* letter: sections with the same letter share chords and
  texture) and the lyric (lines that come back = chorus). A *sound* letter like `AB` = merged from two classes.
- **Moments**: ★ (cut on it if it's handy) → ★★★ (the song's own peaks and turns: build the film's big ideas here).

## Caveats
- Section names are inferred: if the bar map says otherwise (who sings what, where the hook is), trust your reading
  and say so in `song-story.md`.
- Chords are major/minor triads from the *other* + *bass* stems (no 7ths/sus): good for where harmony changes,
  approximate for spelling. Key: {m['key']['name']} (fit {m['key']['score']:.2f} vs {m['key']['runner_up']} {m['key']['runner_up_score']:.2f}).
- Notes come from pitch tracking (CREPE) on the vocal / bass stems: reliable for contour, highest notes and holds;
  backing vocals and bleed can add stray notes.
- What fills a stretch without a beat (film, talking, ambience, silence) comes from a zero-shot audio tagger (CLAP).
  Genre, mood and instrument tags were tested and left out: too often wrong. The song's character is for you to
  read from the measurements, the lyric and the user.
- Made {report['created']} on {report['device']['gpu'] or 'the CPU'}; stems: {report['models']['stems']}.
"""


# ------------------------------------------------------------------ pictures
def plot(m, env, raw, path, t0=None, t1=None, bars=None, width=20.0, title=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    G = raw["G"]
    t0 = m["music"]["start"] if t0 is None else t0
    t1 = m["music"]["end"] if t1 is None else t1
    detail = (t1 - t0) < 60
    bg, fg, dim, accent = "#101114", "#e8e6e1", "#6f7278", "#e8734a"
    lanes = ["sections", "loud & quiet", "notes", "chords", "beats", "voice", "drums", "bass", "other", "lyrics"]
    hts = [0.55, 1.1, 1.3, 0.5, 0.45, 0.7, 0.7, 0.7, 0.7, 1.0 if detail else 0.6]
    fig, axes = plt.subplots(len(lanes), 1, figsize=(width, sum(hts) + 1.1), sharex=True,
                             gridspec_kw={"height_ratios": hts, "hspace": 0.12})
    fig.patch.set_facecolor(bg)
    for ax, name in zip(axes, lanes):
        ax.set_facecolor(bg)
        for sp in ax.spines.values():
            sp.set_visible(False)
        ax.tick_params(colors=dim, labelsize=9, length=0)
        ax.set_yticks([])
        ax.set_ylabel(name, rotation=0, ha="right", va="center", color=fg, fontsize=12, family="monospace", labelpad=10)
        ax.set_xlim(t0, t1)
    fps = env["fps"]
    tt = np.arange(len(env["loudness_lufs"])) / fps
    sel = (tt >= t0) & (tt <= t1)
    # sections
    ax = axes[0]
    for s in m["sections"]:
        if s["t1"] < t0 or s["t0"] > t1:
            continue
        c = LANE_COLORS.get(s["label"].split(" ")[0], "#6c7a89")
        ax.add_patch(Rectangle((s["t0"], 0.05), s["t1"] - s["t0"], 0.9, color=c, alpha=0.85, lw=0))
        mid = (max(s["t0"], t0) + min(s["t1"], t1)) / 2
        if (min(s["t1"], t1) - max(s["t0"], t0)) / (t1 - t0) * width > 0.45:
            ax.text(mid, 0.5, s["name"], ha="center", va="center", color="#101114", fontsize=10, fontweight="bold", clip_on=True)
    tl = m["music"].get("tail")
    if tl and tl["t1"] > t0 and tl["t0"] < t1:
        ax.add_patch(Rectangle((tl["t0"], 0.05), tl["t1"] - tl["t0"], 0.9, facecolor="none", edgecolor=dim, hatch="//", lw=0.8))
        if (min(tl["t1"], t1) - max(tl["t0"], t0)) / (t1 - t0) * width > 0.6:
            ax.text((max(tl["t0"], t0) + min(tl["t1"], t1)) / 2, 0.5, "no beat", ha="center", va="center", color=fg,
                    fontsize=9, clip_on=True)
    ax.set_ylim(0, 1)
    # loud & quiet (+ moments)
    ax = axes[1]
    lu = np.array(env["loudness_lufs"])
    ref = m["loudness"]["integrated_lufs"]
    v = np.clip((lu - (ref - 24)) / 30, 0, 1)
    ax.fill_between(tt[sel], 0, v[sel], color=accent, alpha=0.45, lw=0)
    ax.plot(tt[sel], v[sel], color=accent, lw=0.9)
    ax.set_ylim(0, 1.25)
    for e in m["moments"]:
        if t0 <= e["t"] <= t1 and (e["stars"] >= 2 or detail):
            ax.axvline(e["t"], color=fg, lw=0.6, alpha=0.5)
            if e["stars"] >= 3 or detail:
                ax.text(e["t"], 1.22, e["short"], color=fg, fontsize=8, rotation=0, ha="left", va="top", clip_on=True)
    # notes: melody (top) + bass line (bottom band)
    ax = axes[2]
    vn = [n for n in m["notes"]["vocal"] if n["end"] > t0 and n["t"] < t1]
    bn = [n for n in m["notes"]["bass"] if n["end"] > t0 and n["t"] < t1]
    allv = [n["midi"] for n in m["notes"]["vocal"] if n.get("in_lyric", True)] or [60]
    lo, hi = np.percentile(allv, 1), np.percentile(allv, 99) + 1
    for n in vn:
        y_ = 0.42 + 0.56 * np.clip((n["midi"] - lo) / (hi - lo + 1e-9), 0, 1)
        sungn = n.get("in_lyric", True)
        ax.add_patch(Rectangle((n["t"], y_), n["dur"], 0.035, color=fg if sungn else dim, alpha=1 if sungn else 0.5, lw=0))
        if detail and n["dur"] >= 0.5 and sungn:
            ax.text(n["t"], y_ + 0.05, n["name"], color=fg, fontsize=7, clip_on=True)
    allb = [n["midi"] for n in m["notes"]["bass"]] or [36]
    blo, bhi = np.percentile(allb, 1), np.percentile(allb, 99) + 1
    for n in bn:
        y_ = 0.02 + 0.33 * np.clip((n["midi"] - blo) / (bhi - blo + 1e-9), 0, 1)
        ax.add_patch(Rectangle((n["t"], y_), n["dur"], 0.03, color="#7fb2ff", lw=0))
    ax.set_ylim(0, 1.05)
    # chords
    ax = axes[3]
    fifths = {r: i for i, r in enumerate(["C", "G", "D", "A", "E", "B", "F#", "C#", "Ab", "Eb", "Bb", "F"])}
    import colorsys
    for c in m["chords"]:
        if c["end"] < t0 or c["t"] > t1 or c["chord"] == "N":
            continue
        root = c["chord"].rstrip("m")
        h = fifths.get(root, 0) / 12
        col = colorsys.hsv_to_rgb(h, 0.45 if c["chord"].endswith("m") else 0.65, 0.8)
        ax.add_patch(Rectangle((c["t"], 0.1), c["end"] - c["t"], 0.8, color=col, alpha=0.8, lw=0))
        if (c["end"] - c["t"]) / (t1 - t0) * width > (0.22 if detail else 0.35):
            ax.text(c["t"] + 0.02 * (t1 - t0) / width, 0.5, c["chord"], color="#101114", fontsize=9, va="center", clip_on=True)
    ax.set_ylim(0, 1)
    # beats
    ax = axes[4]
    for b in G.beats:
        if t0 <= b <= t1:
            ax.plot([b, b], [0, 0.35], color=dim, lw=0.7)
    every = 1 if detail else 4 if (t1 - t0) < 150 else 8
    for i, d in enumerate(G.db):
        if t0 <= d <= t1:
            ax.plot([d, d], [0, 0.8], color=fg, lw=1.0)
            if i % every == 0:
                ax.text(d, 0.85, str(i), color=fg, fontsize=8, ha="left", va="bottom", clip_on=True)
    ax.set_ylim(0, 1.4)
    # stems
    for ax, key, col in zip(axes[5:9], ("voice", "drums", "bass", "other"), (fg, fg, fg, fg)):
        v = np.array(env[key])
        ax.fill_between(tt[sel], 0, v[sel], color=col, alpha=0.18, lw=0)
        ax.plot(tt[sel], v[sel], color=col, lw=0.8)
        ax.set_ylim(0, 1.05)
    # lyrics
    ax = axes[9]
    for x in m["lyrics"]:
        if x["end"] < t0 or x["t"] > t1:
            continue
        ax.add_patch(Rectangle((x["t"], 0.1), max(0.2, x["end"] - x["t"]), 0.8, color="#a8a49c", alpha=0.35 if detail else 0.8, lw=0))
        if detail:
            for k, w in enumerate(x["words"]):
                ax.text(w["t"], 0.72 - 0.28 * (k % 3), w["w"], color=fg, fontsize=8, clip_on=True)
        elif (x["end"] - x["t"]) / (t1 - t0) * width > 0.9:
            ax.text(x["t"] + 0.1, 0.5, " ".join(w["w"] for w in x["words"][:3]) + "…", color="#101114", fontsize=7.5,
                    va="center", clip_on=True)
    ax.set_ylim(0, 1)
    ax = axes[-1]
    ticks = np.arange(np.ceil(t0 / (5 if detail else 15)) * (5 if detail else 15), t1, 5 if detail else 15)
    ax.set_xticks(ticks)
    ax.set_xticklabels([mmss(x, 0) for x in ticks], color=dim, family="monospace")
    ttl = title or f"{m.get('artist', '')} – {m.get('title', '')}".strip(" –") or m["slug"]
    fig.suptitle(f"{ttl}   {m['tempo']['bpm']:g} BPM · {m['key']['name']} · {mmss(t0)}–{mmss(t1)}", color=fg,
                 fontsize=14, family="monospace", x=0.01, ha="left", y=0.995)
    fig.subplots_adjust(left=0.085, right=0.995, top=0.95, bottom=0.04)
    fig.savefig(path, dpi=80 if not detail else 90, facecolor=bg)
    plt.close(fig)


# ------------------------------------------------------------------ write everything
def write(out, m, env, report, raw):
    os.makedirs(os.path.join(out, "pages"), exist_ok=True)
    G = raw["G"]
    for x in m["lyrics"]:
        x["pos"] = G.pos_str(x["t"])
    open(os.path.join(out, "song-map.md"), "w", encoding="utf-8").write(song_map_md(m))
    open(os.path.join(out, "lyrics.md"), "w", encoding="utf-8").write(lyrics_md(m))
    sp = os.path.join(out, "song-story.md")
    if not os.path.exists(sp):
        open(sp, "w", encoding="utf-8").write(story_md(m))
    open(os.path.join(out, "README.md"), "w", encoding="utf-8").write(readme_md(m, report))
    json.dump(m, open(os.path.join(out, "song-map.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"),
              default=_np)
    json.dump(env, open(os.path.join(out, "envelopes.json"), "w"), separators=(",", ":"), default=_np)
    json.dump(report, open(os.path.join(out, "report.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False, default=_np)
    plot(m, env, raw, os.path.join(out, "overview.png"))
    for f in os.listdir(os.path.join(out, "pages")):
        os.remove(os.path.join(out, "pages", f))
    nb = len(G.db)
    for a in range(0, nb, 16):
        b = min(nb, a + 16)
        t0 = G.db[a] - (0.5 if a == 0 else 0)
        t1 = G.ends[b - 1]
        plot(m, env, raw, os.path.join(out, "pages", f"bars_{a:03d}-{b - 1:03d}.png"), t0=t0, t1=t1, width=18.0,
             title=f"bars {a}–{b - 1}")


def _np(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (set, tuple)):
        return list(o)
    raise TypeError(type(o))
