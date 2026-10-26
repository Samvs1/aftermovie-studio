"""Build the shot log (out/shot_log.md + a local, self-contained out/shot_log.html).

Merges my hand-written notes (cache/shotlog_notes.json) with the analysis
(cache/photos.json) and who-is-in-it (cache/faces_people.json + cache/cast.json).
Also writes cache/shotlog.json, which the EDL builder reads.

usage: python tools/shotlog.py
"""
import base64, io, json, os, re
from collections import Counter
from PIL import Image, ImageOps

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from am.common import PHOTOS, CACHE, OUT, project  # noqa: E402
os.makedirs(OUT, exist_ok=True)

# in story order (Sam's timeline); Elevate itself runs from karaoke onwards
CHAPTERS = {
    "canal": "Canal boat", "bridge": "Bridge, daytime", "attic": "The attic (house party)",
    "dinner": "Red restaurant", "karaoke": "Karaoke (Elevate starts)", "hotel": "Hotel suite (suits)",
    "club": "Club (teal)", "lounge": "Lounge bar", "terrace": "Terrace (video)", "bus": "Night coach",
    "pier": "Harbour sunset", "street": "Night streets",
}
ELEVATE = {"karaoke", "hotel", "club", "lounge", "terrace", "bus", "pier", "street"}
PROJ = project()
if PROJ:   # a studio project: chapters (story order) and title come from project.json
    CHAPTERS = {c["id"]: c.get("label", c["id"]) for c in PROJ.get("chapters", [])}
    ELEVATE = set()
TITLE = PROJ.get("title") or "Elevate 2026"


def person_label(pid, cast):
    p = cast["people"].get(pid)
    return (p["name"] if p and p["name"] else f"#{pid}")


def named(text, cast):
    return re.sub(r"#(\d+)", lambda m: person_label(m.group(1), cast), text)


def main():
    notes = json.load(open(os.path.join(CACHE, "shotlog_notes.json")))
    meta = json.load(open(os.path.join(CACHE, "photos.json")))
    fpp, cp = os.path.join(CACHE, "faces_people.json"), os.path.join(CACHE, "cast.json")
    fp = json.load(open(fpp)) if os.path.exists(fpp) else {}
    cast = json.load(open(cp, encoding="utf-8")) if os.path.exists(cp) else {"people": {}}
    log = []
    for fn, n in notes.items():
        if fn.startswith("_"):
            continue
        chapter, desc, mood, energy, quality, hero, extra = n
        m = meta.get(fn, {})
        # who = what I saw (#ids in the description) + cluster-backed face matches
        people = sorted({p for p in fp.get(fn, []) if p} | set(re.findall(r"#(\d+)", desc)), key=lambda x: int(x))
        log.append({
            "file": fn, "id": fn[3:7] if fn.startswith("img") else fn[-8:-4],
            "source": "video" if fn.endswith(".mp4") else m.get("source"),
            "chapter": chapter, "desc": desc, "mood": mood, "energy": energy, "quality": quality,
            "hero": hero, "notes": extra, "people": people, "elevate": chapter in ELEVATE,
            "orient": m.get("orient", "landscape"), "rot": m.get("rot", 0),
            "faces": [{"box": f["box"], "person": (fp.get(fn) or [None] * 99)[i]} for i, f in enumerate(m.get("faces", []))],
        })
    json.dump(log, open(os.path.join(CACHE, "shotlog.json"), "w"), indent=1)

    # ---------- markdown ----------
    by_ch = {c: [] for c in CHAPTERS}
    for e in log:
        by_ch.setdefault(e["chapter"], []).append(e)
    by_ch = {c: v for c, v in by_ch.items() if v}
    md = [f"# Shot log - {TITLE}", "",
          f"{sum(1 for e in log if e['source'] != 'video')} photos + 1 video. "
          f"{sum(1 for e in log if e['source'] == 'disposable')} disposable scans, "
          f"{sum(1 for e in log if e['source'] == 'phone')} phone/camera shots. "
          "Hero: 3 = must use, 2 = strong, 1 = usable, 0 = flash-frame only. Chapters in story order.", ""]
    for ch, items in by_ch.items():
        md.append(f"## {CHAPTERS.get(ch, ch)} ({len(items)})\n")
        md.append("| id | src | what | who | mood | energy | quality | hero | notes |")
        md.append("|---|---|---|---|---|---|---|---|---|")
        for e in sorted(items, key=lambda e: (-e["hero"], e["id"])):
            who = ", ".join(person_label(p, cast) for p in e["people"]) or "-"
            md.append(f"| {e['id']} | {e['source'][:4]} | {named(e['desc'], cast)} | {who} | {e['mood']} | {'●' * e['energy']} | {'★' * e['quality']} | {e['hero']} | {e['notes']} |")
        md.append("")
    open(os.path.join(OUT, "shot_log.md"), "w", encoding="utf-8").write("\n".join(md))

    # ---------- html (local only, thumbnails embedded) ----------
    def thumb(fn, rot):
        if fn.endswith(".mp4"):
            return ""
        im = ImageOps.exif_transpose(Image.open(os.path.join(PHOTOS, fn))).convert("RGB")
        if rot:
            im = im.rotate(-90 * rot, expand=True)
        im.thumbnail((520, 520))
        b = io.BytesIO()
        im.save(b, "JPEG", quality=78)
        return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()

    def b64file(path):
        return "data:image/jpeg;base64," + base64.b64encode(open(path, "rb").read()).decode()

    cards = []
    for ch, items in by_ch.items():
        cards.append(f'<h2>{CHAPTERS.get(ch, ch)} <span>{len(items)}</span></h2><div class="grid">')
        for e in sorted(items, key=lambda e: (-e["hero"], e["id"])):
            who = ", ".join(person_label(p, cast) for p in e["people"]) or "&mdash;"
            src = thumb(e["file"], e["rot"])
            img = f'<img src="{src}" loading="lazy">' if src else '<div class="vid">VIDEO 16.5s</div>'
            cards.append(
                f'<figure class="h{e["hero"]}">{img}<figcaption><b>{e["id"]}</b> <i>{e["source"]}</i> '
                f'<em>{"★" * e["hero"] or "·"}</em><p>{named(e["desc"], cast)}</p><p class="m">who: {who}<br>mood: {e["mood"]} · '
                f'energy {e["energy"]}/5 · quality {e["quality"]}/5</p>'
                + (f'<p class="n">{e["notes"]}</p>' if e["notes"] else "") + "</figcaption></figure>")
        cards.append("</div>")
    cs = os.path.join(CACHE, "cast_sheet.jpg")
    cast_img = b64file(cs) if os.path.exists(cs) else ""
    html = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Shot log</title><style>
:root{{--bg:#111;--fg:#eee;--mut:#999;--acc:#ffd23f;--card:#1c1c1c}}
body{{background:var(--bg);color:var(--fg);font:14px/1.4 system-ui,sans-serif;margin:0;padding:24px 16px;max-width:1500px;margin:auto}}
h1{{font-size:28px;margin:0 0 4px}} h2{{margin:36px 0 12px;font-size:20px}} h2 span{{color:var(--mut);font-weight:400}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:14px}}
figure{{margin:0;background:var(--card);border-radius:8px;overflow:hidden;border:2px solid transparent}}
figure.h3{{border-color:var(--acc)}} figure img{{width:100%;height:220px;object-fit:contain;background:#000;display:block}}
.vid{{height:220px;display:grid;place-items:center;background:#000;color:var(--acc);font-weight:700}}
figcaption{{padding:8px 10px}} figcaption i{{color:var(--mut);font-style:normal;font-size:12px}} figcaption em{{float:right;color:var(--acc);font-style:normal}}
figcaption p{{margin:6px 0 0}} .m{{color:var(--mut);font-size:12px}} .n{{color:#f7a;font-size:12px}}
.cast{{width:100%;border-radius:8px;margin-top:12px}} .lead{{color:var(--mut)}}
</style></head><body><h1>{TITLE} &mdash; shot log</h1>
<p class="lead">{len(log)} items. Gold border = hero shot. Chapters in story order.</p>
{f'<img class="cast" src="{cast_img}">' if cast_img else ""}{''.join(cards)}</body></html>"""
    open(os.path.join(OUT, "shot_log.html"), "w", encoding="utf-8").write(html)
    ch_count = Counter(e["chapter"] for e in log)
    print("chapters:", dict(ch_count))
    print("heroes:", [e["id"] for e in log if e["hero"] == 3])
    print("wrote out/shot_log.md, out/shot_log.html, cache/shotlog.json")


if __name__ == "__main__":
    main()
