"""First-draft film builder. Copy to projects/<name>/build.py and make it this film's own.

Run:  python tools/studio.py build <name>      (then: studio.py preview <name>)

As-is it makes a clean, music-locked first draft from the project's data:
  * the whole song, from its first note (put at most ONE join between identical passages in SEGMENTS)
  * title over the intro, then one photo per bar in story order (project.json chapters, hero shots first)
  * landscapes full frame with a slow move; portraits as whole prints, two per screen
  * a flash + shutter on every section change, a small note at each new chapter
  * the ending note from project.json typed out in silence after the song, one line per felt bar
Everything a real film needs on top (lyric gags on sung onsets, people moments, a signature device per
section) is the director's job: see .claude/skills/aftermovie/SKILL.md and projects/elevate-2026/build_time_to_pretend.py.
"""
import json, os, sys
sys.path.insert(0, os.environ.get("AM_TOOLS") or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from am.common import CACHE, project  # noqa: E402
from am.kit import Film, W  # noqa: E402

P = project()
SONG = P["song"]
SLUG = SONG["slug"]
A = json.load(open(os.path.join(CACHE, "audio", f"{SLUG}.json"), encoding="utf-8"))
PRE = 0.8                                                       # a beat of black before the first note
SEGMENTS = [(0.0, A["duration"], PRE)]                          # [(song_in, song_out, film_at)]; one join max
VERSION = os.environ.get("AM_VERSION") or P.get("version") or SLUG

F = Film(VERSION, P.get("title") or "Aftermovie", f"music/{SONG['file']}", SLUG, SEGMENTS,
         grade={"preset": P.get("grade", "consumer_film"), "overrides": {}}, tail=16.0)
bars = [i for i, t in enumerate(A["downbeats"]) if F.song2film(t) is not None]

# ------------------------------------------------------------------ photo order: chapters (story order), heroes first
chapters = [c["id"] for c in P.get("chapters", [])]
log = F.shotlog
TRIP = F.trip()                                                 # Polarsteps import, if any
photos = [p for p in sorted(F.META) if not p.startswith("_")]
if TRIP:                                                        # skipped steps stay out of the film
    photos = [p for p in photos if not (TRIP["photo_step"].get(p) or {}).get("skip")]
step_chapter = {sid: c["id"] for c in P.get("chapters", []) for sid in c.get("steps", [])}


def chapter_of(p):
    """Shot-log chapter, else the chapter of the photo's Polarsteps step."""
    if log.get(p, {}).get("chapter"):
        return log[p]["chapter"]
    s = TRIP["photo_step"].get(p) if TRIP else None
    return step_chapter.get(s["id"]) if s else None


def order_key(p):
    e = log.get(p, {})
    ch = chapters.index(chapter_of(p)) if chapter_of(p) in chapters else len(chapters)
    st = (TRIP["photo_step"].get(p) or {}).get("i", 0) if TRIP else 0
    return (ch, st, -e.get("hero", 1), p)


photos.sort(key=order_key)
photos = [p for p in photos if log.get(p, {}).get("hero", 1) > 0] or photos     # hero 0 = flash-frame only

# ------------------------------------------------------------------ intro: title card
t0 = F.bar(bars[0])
title_end = F.bar(bars[min(2, len(bars) - 1)])
F.shot(0.0, t0, [F.wall("#050505")], sync="pre-roll")
F.shot(t0, title_end, [F.wall(F.CREAM, True),
                       F.text(P.get("title") or "", W / 2, 470, t0, title_end, 120, "playfair", F.INK, anim="fade", dur=0.6),
                       F.text(P.get("when_where") or P.get("occasion") or "", W / 2, 620, F.beat(bars[0], 2), title_end, 54,
                              "caveat", F.RED, anim="write", dur=0.5)],
       sync="intro: title on the first downbeat")
if TRIP and len(bars) > 8:                                     # trip stats, one number per beat, counting up
    s0, s1 = title_end, F.bar(bars[4])
    T = TRIP["trip"]
    stats = [(T.get("days"), "days"), (len(T.get("countries", [])), "countries" if len(T.get("countries", [])) != 1 else "country"),
             (T.get("km"), "km")]
    stats = [x for x in stats if x[0]]
    lay = [F.wall(F.CREAM, True)]
    for j, (val, lab) in enumerate(stats):
        x = W / 2 + (j - (len(stats) - 1) / 2) * 560
        tj = F.beat(bars[2], j)
        lay += [F.text("{n}", x, 470, tj, s1, 190, "anton", F.INK, anim="pop", dur=0.6, count=val),
                F.text(lab, x, 640, tj, s1, 64, "caveat", F.RED, anim="pop")]
        F.sfx("drop", tj, db=-22)
    F.shot(s0, s1, lay, sync="intro: trip stats count up, one per beat", **F.tr("dissolve"))
    title_end = s1

# ------------------------------------------------------------------ montage: photos spread over the song, a cut on every slot
sections = {round(F.song2film(s["start"]) or -1, 2) for s in A.get("sections", [])}
WALLS = [F.wall(F.CREAM, True), F.wall(F.KRAFT, True), F.wall("#161412")]
last_bar = bars[-2] if len(bars) > 3 else bars[-1]
end_t = F.bar(last_bar)
slots = [i for i in bars if title_end <= F.bar(i) < end_t]
hero = lambda p: log.get(p, {}).get("hero", 1)                                   # noqa: E731
# the best landscape of the last chapter closes the film
land = [p for p in photos if not F.portrait(p)]
closer = max(land[-max(1, len(land) // 4):], key=hero) if land else None
pool = [p for p in photos if p != closer]
# units: a landscape alone, or two portraits side by side (whole prints, two per screen)
units, k = [], 0
while k < len(pool):
    if F.portrait(pool[k]) and k + 1 < len(pool) and F.portrait(pool[k + 1]):
        units.append([pool[k], pool[k + 1]])
        k += 2
    else:
        units.append([pool[k]])
        k += 1
map_steps = [s for s in TRIP["steps"] if not s["skip"] and s.get("lon") is not None] if TRIP else []
MAP_BARS = min(4, max(2, -(-len(map_steps) // 4) + 1)) if map_steps else 0       # bars kept for the route map
present = [c for c in P.get("chapters", []) if any(chapter_of(x) == c["id"] for u in units for x in u)]
bar_med = sorted(F.bar(slots[q + 1]) - F.bar(slots[q]) for q in range(len(slots) - 1))[len(slots) // 2] if len(slots) > 2 else 2.0
reserve = sum(max(0, -(-(F.need(c.get("label", c["id"]) + (f"  ·  {c['when']}" if c.get("when") else "")) + 0.15) // bar_med) - 1)
              for c in present)                 # extra bars the chapter notes hold for reading time
budget = max(1, len(slots) - MAP_BARS - int(reserve))
while len(units) > budget:                      # too many photos: drop the weakest, keep the story order
    units.pop(min(range(len(units)), key=lambda j: (max(hero(x) for x in units[j]), j)))
per = max(1, min(4, budget // max(1, len(units))))      # ~1 photo per bar; fewer photos -> longer holds (max 4 bars)
spare = budget - per * len(units)
seen_ch, i, mi = set(), 0, 0
MOTIONS = [((1.0, 1.08), ((0, 0), (0, 0))), ((1.1, 1.0), ((0, 0), (0, 0))), ((1.08, 1.08), ((-0.05, 0), (0.05, 0))),
           ((1.08, 1.08), ((0.05, 0), (-0.05, 0)))]
for u in units:
    if i >= len(slots) - MAP_BARS:
        break
    n_bars = per + (1 if spare > 0 and per < 4 and len(u) == 1 else 0)
    a = F.bar(slots[i])
    ch = chapter_of(u[0])
    new_ch = bool(ch and ch not in seen_ch and ch in chapters)
    if new_ch:                                  # hold the shot until its chapter note is readable (short bars, fast songs)
        c = next(c for c in P["chapters"] if c["id"] == ch)
        label = c.get("label", c["id"]) + (f"  ·  {c['when']}" if c.get("when") else "")
        while i + n_bars < len(slots) - MAP_BARS and F.bar(slots[i + n_bars]) - a < F.need(label) + 0.15:
            n_bars += 1
    spare -= n_bars - per
    b_ = F.bar(slots[i + n_bars]) if i + n_bars < len(slots) else end_t
    cap = []
    if new_ch:
        seen_ch.add(ch)
        single_portrait = F.portrait(u[0]) and len(u) == 1
        cap = [F.note(label, 1500 if single_portrait else 1440, 170 if single_portrait else 200, a, b_, 64 if single_portrait else 68,
                      seed=len(seen_ch), rot=-3, anim="pop")]
        st = (TRIP["photo_step"].get(u[0]) if TRIP else None) or {}
        if st.get("note") and len(st["note"]) <= 70 and (b_ - a) - 0.6 >= F.need(st["note"]):
            cap.append(F.note(st["note"], W / 2, 975, F.beat(slots[i], 1), b_, 52, seed=40 + len(seen_ch), rot=-1.5,
                              anim="write", dur=0.4, tape=False))
    if F.portrait(u[0]):
        two = len(u) == 2
        layers = [dict(WALLS[len(seen_ch) % 3])] + F.pr(u[0], "montage", 560 if two else 820, 540, (620, 860), -3, a, tapes=False,
                                                       enter="drop")
        if two:
            layers += F.pr(u[1], "montage", 1360, 540, (620, 860), 3, F.beat(slots[i], 2), tapes=False, enter="drop", zoom=(1.04, 1.0))
        layers += cap
    else:
        z, d = MOTIONS[mi % len(MOTIONS)]
        mi += 1
        layers = [F.full(u[0], "montage", z, "faces", d)] + cap
    flash = round(a, 2) in sections
    if flash:
        F.sfx("shutter", a - 0.01, db=-18)
    F.shot(a, b_, layers, sync=f"bar {slots[i]}" + (": section change, flash" if flash else ""),
           **({"in": {"type": "flash", "dur": 0.18, "amount": 0.8}} if flash else F.tr(["cut", "whip", "cut", "dissolve"][i % 4])))
    i += n_bars

# ------------------------------------------------------------------ trip: the route draws itself, one stop per beat
if MAP_BARS and i + MAP_BARS <= len(slots):
    n_map = MAP_BARS
    m0, m1 = F.bar(slots[i]), F.bar(slots[i + n_map]) if i + n_map < len(slots) else end_t
    beats_avail = [F.beat(slots[i] + q // 4, q % 4) for q in range(1, n_map * 4 - 1)]
    pick = [beats_avail[round(q * (len(beats_avail) - 1) / max(1, len(map_steps) - 1))] for q in range(len(map_steps))]
    F.shot(m0, m1, [F.route_map(TRIP, pick)], sync="trip: route map, a stop on each beat", **F.tr("dissolve"))
    for tp in pick:
        F.sfx("drop", tp, db=-24)
    i += n_map

# ------------------------------------------------------------------ ending: the closer holds through the last chord
end_a = F.bar(slots[i]) if i < len(slots) else end_t
lay = [F.full(closer, "ending", (1.0, 1.1))] if closer else [F.wall("#000000")]
lay += [F.note(P.get("title") or "", W / 2, 960, end_a + 0.6 if end_a + 0.6 < F.song_end else end_a, F.song_end, 84, seed=9, rot=-2,
               anim="write", dur=0.5)]
F.shot(end_a, F.near(F.song_end + 2 * F.beat_len), lay, sync="ending: hold through the last chord", **F.tr("dissolve"))

# ------------------------------------------------------------------ thank-you note in silence, one line per felt bar
EP = F.near(F.song_end + 2 * F.beat_len)
lines = [l for l in (P.get("ending_note") or "").split("\n") if l.strip()]
ep = [F.wall("#efe8d8", True)]
bar_len = 4 * F.beat_len
for j, line in enumerate(lines[:7]):
    ep.append(F.text(line, W / 2, 200 + j * 105, F.near(EP + bar_len * j), F.duration, 60, "caveat",
                     F.RED if j == len(lines) - 1 else F.INK, anim="write", dur=0.9, fade_out=0.0))
if P.get("editor"):
    ep.append(F.text(f"— {P['editor']}", 1400, 950, F.near(EP + bar_len * len(lines[:7])), F.duration, 80, "caveat", F.INK,
                     anim="write", dur=0.5, rot=-4, fade_out=0.0))
F.B.edl["meta"]["duration"] = round(max(F.duration, EP + bar_len * (len(lines[:7]) + 2)), 3)
F.duration = F.B.edl["meta"]["duration"]
F.shot(EP, F.duration, ep, sync="silence: the thank-you note", **{"in": {"type": "dip_black", "dur": 0.8, "align": "start"}})
F.save()
