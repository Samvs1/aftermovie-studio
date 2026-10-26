"""Vibe read: what the song and the photos are like, as material for creative directions.

  python tools/studio.py vibe <project>      -> cache/vibe.md (also printed)

Song: tempo feel, band vs programmed, intro length, builds / peaks / breaks, stop-time silences, how it ends, how
much is sung, the lyric (condensed). Photos: day vs night, palette (dominant colours), warm vs cool, saturation,
portraits vs landscapes, groups vs solo, film vs phone, clips. No judgement here: directions are the director's job.
"""
import glob, json, os, sys
import numpy as np
import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from am.common import ROOT, CACHE, PHOTOS, project  # noqa: E402


def song_read_kit(slug, m):
    """The song from the song kit (song/<slug>/song-map.json): named sections, the big moments, the voice, the lyric."""
    t, mu, vo = m["tempo"], m["music"], m["vocals"]
    out = [f"## Song: {m.get('artist', '')} – {m.get('title', '')}".rstrip(" –"),
           f"- full map, timed lyrics and lanes picture: `song/{slug}/` (start with README.md, song-map.md, overview.png)",
           f"- {t['bpm']:.0f} BPM ({'slow' if t['bpm'] < 85 else 'mid' if t['bpm'] < 115 else 'upbeat' if t['bpm'] < 135 else 'fast'}), "
           f"bar = {t['bar_s']:.2f} s, {m['key']['name']}, {t['grid']}",
           f"- the music runs {mu['start']:.1f}–{mu['end']:.1f} s of a {m['duration']:.0f} s file"
           + (f" (before it: {mu['before']['kind']})" if mu.get("before") else "")
           + (f" (after it: {mu['after']['kind']})" if mu.get("after") else ""),
           f"- loudness {m['loudness']['integrated_lufs']} LUFS, range {m['loudness']['range_lu']} LU"]
    if vo.get("range"):
        out.append(f"- voice: sung in {vo['sung_bars'] * 100:.0f}% of bars, range {vo['range'][0]}–{vo['range'][1]}, "
                   f"first word at {vo['first']:.1f} s")
    out.append("- structure: " + " → ".join(f"{s['name']} ({s['t0']:.0f}s, {s['bar1'] - s['bar0']} bars, {s['loud']:.0f} LUFS)"
                                         for s in m["sections"]))
    big = [e for e in m["moments"] if e["stars"] >= 3]
    if big:
        out.append("- the big moments: " + "; ".join(f"{e['t']:.1f}s ({e['pos']}) {e['text']}" for e in big))
    seen, uniq = set(), []
    for x in m.get("lyrics", []):
        if x["text"].lower() not in seen:
            seen.add(x["text"].lower())
            uniq.append(x["text"])
    if uniq:
        out.append("- lyric (unique lines): " + " / ".join(uniq[:40]))
    sp = os.path.join(ROOT, "song", slug, "song-story.md")
    if os.path.exists(sp) and "_2–4 sentences" not in open(sp, encoding="utf-8").read():
        out.append(f"- song story: written (`song/{slug}/song-story.md`)")
    else:
        out.append(f"- song story: not written yet (`song/{slug}/song-story.md`): what is the song about, and this group's version of it?")
    return out


def song_read(slug):
    kp = os.path.join(ROOT, "song", slug, "song-map.json")
    if os.path.exists(kp):
        return song_read_kit(slug, json.load(open(kp, encoding="utf-8")))
    d = json.load(open(os.path.join(CACHE, "audio", f"{slug}.json"), encoding="utf-8"))
    db, be = np.array(d["downbeats"]), np.array(d.get("bar_energy", []))
    n = len(db)
    bp = d["beat_period"]
    bpm = d["tempo"]
    out = [f"## Song: {slug}", f"- {bpm:.0f} BPM ({'slow' if bpm < 85 else 'mid' if bpm < 115 else 'upbeat' if bpm < 135 else 'fast'}), "
           f"bar = {4 * bp:.2f} s, {n} bars, {d['duration'] / 60:.0f}:{d['duration'] % 60:02.0f} long",
           f"- timing: {'click-steady (programmed / tight band)' if (d.get('grid') or {}).get('constant') else 'tempo breathes (live band)'}"]
    words = [w["t"] for L in d.get("lyrics", []) for w in L.get("words", [])]
    first_vocal = min(words) if words else None
    if first_vocal is not None:
        ib = int(np.searchsorted(db, first_vocal))
        out.append(f"- intro: {first_vocal:.0f} s before the first sung word" + (f" (~{ib} bars)" if first_vocal > db[0] + 4 * bp else ""))
    if len(be):
        e = (be - be.min()) / (np.ptp(be) + 1e-9)
        peak = int(np.argmax(np.convolve(e, np.ones(8) / 8, "same")))
        out.append(f"- energy: starts at {e[:4].mean():.2f}, peaks around bar {peak} ({db[min(peak, n - 1)]:.0f} s), "
                   f"ends at {e[-4:].mean():.2f} (0 = quietest bar, 1 = loudest)")
        dips = [i for i in range(4, n - 4) if e[i] < e[i - 4:i].mean() - 0.3 and e[i] < 0.45]
        if dips:
            out.append(f"- breakdowns / quiet bars: {', '.join(str(i) for i in dips[:10])}")
    secs = d.get("sections", [])
    if secs:
        out.append("- sections (start s, bars, energy, vocal): " + "; ".join(
            f"{s['start']:.0f}s {s['bars']}b e{s['energy']:.2f} v{s['vocal']:.2f}" for s in secs))
    # stop-time silences and the ending, from the mix
    try:
        import librosa
        from am.common import MUSIC
        f = next(x for x in os.listdir(MUSIC) if os.path.splitext(x)[0] and slug.split("_")[0] in x.lower().replace(" ", "_")) \
            if os.path.isdir(MUSIC) else None
        f = f or d.get("file")
        y, sr = librosa.load(os.path.join(MUSIC, f), sr=11025, mono=True)
        hop = int(0.05 * sr)
        rms = librosa.feature.rms(y=y, frame_length=hop * 2, hop_length=hop)[0]
        db_ = 20 * np.log10(rms + 1e-6)
        loud = np.percentile(db_, 75)
        gaps, i = [], int(5 / 0.05)
        while i < len(db_) - int(5 / 0.05):
            if db_[i] < loud - 22:
                j = i
                while j < len(db_) and db_[j] < loud - 22:
                    j += 1
                before, after = db_[max(0, i - 20):i], db_[j:j + 20]
                if 0.15 <= (j - i) * 0.05 <= 3 and len(before) and len(after) and                         np.median(before) > loud - 8 and np.median(after) > loud - 8:     # a real stop: loud on both sides
                    gaps.append(f"{i * 0.05:.1f}s ({(j - i) * 0.05:.2f}s)")
                i = j
            i += 1
        if gaps:
            out.append(f"- stop-time silences (great for freezes / stamps / reveals): {', '.join(gaps[:8])}")
        tail = db_[-int(6 / 0.05):]
        drop = tail[0] - tail.min()
        end = "fades out" if np.all(np.diff(tail[: int(4 / 0.05)]) <= 1.5) and drop > 15 else "ends on a hit / short ring-out"
        out.append(f"- ending: {end}")
    except Exception as ex:
        out.append(f"- (silence / ending scan skipped: {ex})")
    vocal_bars = sum(1 for s in secs for _ in range(s["bars"]) if s["vocal"] > 0.5)
    if secs:
        out.append(f"- sung: ~{100 * vocal_bars / max(1, sum(s['bars'] for s in secs)):.0f}% of bars carry vocals")
    lines = [L["text"] for L in d.get("lyrics", []) if L.get("text")]
    if lines:
        seen, uniq = set(), []
        for l in lines:
            if l.lower() not in seen:
                seen.add(l.lower())
                uniq.append(l)
        out.append("- lyric (unique lines): " + " / ".join(uniq[:40]))
    return out


def photo_read():
    meta = json.load(open(os.path.join(CACHE, "photos.json")))
    files = sorted(meta)
    if not files:
        return ["## Photos", "- none analysed yet"]
    br = np.array([meta[f]["brightness"] for f in files])
    sat = np.array([meta[f]["saturation"] for f in files])
    faces = np.array([len([x for x in meta[f]["faces"] if x["score"] >= 0.7]) for f in files])
    port = sum(1 for f in files if meta[f]["h"] > meta[f]["w"] * 1.05)
    film = sum(1 for f in files if meta[f].get("source") == "disposable")
    px, warm = [], []
    for f in files[:200]:
        tp = os.path.join(CACHE, "thumbs", os.path.splitext(f)[0] + ".jpg")
        im = cv2.imread(tp if os.path.exists(tp) else os.path.join(PHOTOS, f), cv2.IMREAD_REDUCED_COLOR_4)
        if im is None:
            continue
        im = cv2.resize(im, (48, 48))[..., ::-1].reshape(-1, 3).astype(np.float32) / 255
        px.append(im)
        warm.append(float((im[:, 0] - im[:, 2]).mean()))
    out = ["## Photos", f"- {len(files)} stills ({port} portrait, {len(files) - port} landscape; {film} film/disposable-style, "
                        f"{len(files) - film} phone)",
           f"- light: {np.mean(br < 0.3) * 100:.0f}% night/dark, {np.mean(br > 0.55) * 100:.0f}% bright/daylight "
           f"(mean brightness {br.mean():.2f})",
           f"- colour: saturation {sat.mean():.2f} ({'muted' if sat.mean() < 0.25 else 'natural' if sat.mean() < 0.4 else 'vivid'}), "
           f"{'warm' if np.mean(warm) > 0.03 else 'cool' if np.mean(warm) < -0.03 else 'neutral'} overall",
           f"- people: {np.mean(faces == 0) * 100:.0f}% no faces (places/details), {np.mean(faces == 1) * 100:.0f}% solo, "
           f"{np.mean((faces >= 2) & (faces <= 3)) * 100:.0f}% pairs/trios, {np.mean(faces >= 4) * 100:.0f}% groups"]
    if px:
        allp = np.concatenate(px)
        crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
        _, lab, cen = cv2.kmeans(allp, 6, None, crit, 3, cv2.KMEANS_PP_CENTERS)
        share = np.bincount(lab.ravel(), minlength=6) / len(lab)
        order = np.argsort(-share)
        out.append("- palette (share): " + ", ".join(
            "#{:02x}{:02x}{:02x} {:.0f}%".format(*(np.clip(cen[i], 0, 1) * 255).astype(int), share[i] * 100) for i in order))
    clips = [f for f in os.listdir(PHOTOS) if f.lower().endswith((".mp4", ".mov", ".m4v"))]
    if clips:
        out.append(f"- clips: {len(clips)} video(s)")
    return out


def main():
    pj = project()
    slug = (pj.get("song") or {}).get("slug")
    if not slug:
        auds = sorted(glob.glob(os.path.join(CACHE, "audio", "*.json")))
        slug = os.path.basename(auds[0])[:-5] if auds else None
    lines = [f"# Vibe read: {pj.get('title') or os.path.basename(ROOT)}", ""]
    if pj.get("vibe") or pj.get("references") or pj.get("style_leanings"):
        lines += ["## What they asked for", f"- vibe: {pj.get('vibe', '')}", f"- adventurousness: {pj.get('adventurous', 'bold')}",
                  f"- style leanings: {pj.get('style_leanings', '')}", f"- references: {pj.get('references', '')}", ""]
    if slug and os.path.exists(os.path.join(CACHE, "audio", f"{slug}.json")):
        lines += song_read(slug) + [""]
    lines += photo_read()
    tp = os.path.join(CACHE, "trip.json")
    if os.path.exists(tp):
        t = json.load(open(tp, encoding="utf-8"))["trip"]
        lines += ["", f"## Trip: {t.get('name')}: {t.get('days')} days, {', '.join(t.get('country_names', []))}, ~{t.get('km')} km"]
    txt = "\n".join(lines)
    open(os.path.join(CACHE, "vibe.md"), "w", encoding="utf-8").write(txt)
    print(txt)


if __name__ == "__main__":
    main()
