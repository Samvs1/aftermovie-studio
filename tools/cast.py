"""Turn face clusters into named people.

Reads cache/photos.json, cache/face_clusters.json and cache/cast.json.
Every face gets a person id: faces in a listed cluster take that person; leftover faces
are matched to the nearest person centroid when similar enough (else left unknown).
Writes cache/faces_people.json ({photo: [person id or null per face]}, cluster-backed only),
cache/faces_people_guess.json (plus nearest-centroid guesses) and
cache/cast_sheet.jpg (one row per person, with names once cast.json has them).

usage: python tools/cast.py
"""
import json, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from am.common import PHOTOS, CACHE  # noqa: E402
MATCH = 0.38  # min cosine similarity to a person centroid for unclustered faces


def main():
    meta = json.load(open(os.path.join(CACHE, "photos.json")))
    clusters = json.load(open(os.path.join(CACHE, "face_clusters.json")))
    cast = json.load(open(os.path.join(CACHE, "cast.json")))
    people = cast["people"]
    excluded = {(m["photo"], m["idx"]) for c in cast.get("exclude_clusters", []) for m in clusters.get(c, [])}

    assign = {n: [None] * len(m["faces"]) for n, m in meta.items()}
    members = {}
    for pid, p in people.items():
        for c in p["clusters"]:
            for m in clusters.get(c, []):
                assign[m["photo"]][m["idx"]] = pid
                members.setdefault(pid, []).append(m)

    strong = {n: list(v) for n, v in assign.items()}  # cluster-backed only
    cent = {pid: np.mean([meta[m["photo"]]["faces"][m["idx"]]["emb"] for m in ms], axis=0) for pid, ms in members.items()}
    for pid in cent:
        cent[pid] /= np.linalg.norm(cent[pid])
    for n, m in meta.items():
        taken = {p for p in assign[n] if p}
        for i, f in enumerate(m["faces"]):
            if assign[n][i] or (n, i) in excluded or f["score"] < 0.7:
                continue
            e = np.array(f["emb"])
            sims = {pid: float(e @ c) for pid, c in cent.items() if pid not in taken}
            if sims:
                best = max(sims, key=sims.get)
                if sims[best] >= MATCH:
                    assign[n][i] = best
                    taken.add(best)
    json.dump(strong, open(os.path.join(CACHE, "faces_people.json"), "w"), indent=0)
    json.dump(assign, open(os.path.join(CACHE, "faces_people_guess.json"), "w"), indent=0)

    # cast sheet
    T, per = 170, 6
    fnt = ImageFont.truetype("arialbd.ttf", 44)
    mid = ImageFont.truetype("arialbd.ttf", 22)
    small = ImageFont.truetype("arial.ttf", 17)
    lab = ImageFont.truetype("arialbd.ttf", 18)
    label_w = 300
    cols = 2
    cell_w = label_w + per * (T + 6) + 20
    rows = (len(people) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell_w, rows * (T + 18) + 10), (22, 22, 22))
    d = ImageDraw.Draw(sheet)
    imcache = {}
    for k, (pid, p) in enumerate(people.items()):
        ms = sorted(members.get(pid, []), key=lambda m: -meta[m["photo"]]["faces"][m["idx"]]["box"][2] * meta[m["photo"]]["w"])
        photos = sorted({m["photo"] for m in ms})
        # prefer one crop per photo, spread over sources
        seen, picks = set(), []
        for m in ms:
            if m["photo"] not in seen:
                picks.append(m)
                seen.add(m["photo"])
        idxs = np.linspace(0, len(picks) - 1, min(per, len(picks))).round().astype(int) if picks else []
        picks = [picks[i] for i in idxs]
        x0 = (k % cols) * cell_w + 10
        y0 = (k // cols) * (T + 18) + 10
        d.text((x0, y0 + 10), f"#{pid}", fill=(255, 215, 0), font=fnt)
        d.text((x0, y0 + 66), p["name"] or "who?", fill=(255, 255, 255), font=mid)
        n_all = sum(1 for n in assign if pid in assign[n])
        d.text((x0, y0 + 96), f"in {n_all} photos", fill=(170, 170, 170), font=small)
        for j, m in enumerate(picks):
            pm = meta[m["photo"]]
            if m["photo"] not in imcache:
                im = ImageOps.exif_transpose(Image.open(os.path.join(PHOTOS, m["photo"]))).convert("RGB")
                imcache[m["photo"]] = im.rotate(-90 * pm["rot"], expand=True) if pm["rot"] else im
            im = imcache[m["photo"]]
            W, H = im.size
            x, y, w, h = pm["faces"][m["idx"]]["box"]
            cx, cy, r = (x + w / 2) * W, (y + h / 2) * H, max(w * W, h * H) * 0.8
            crop = im.crop((int(cx - r), int(cy - r), int(cx + r), int(cy + r))).resize((T, T))
            X = x0 + label_w - 140 + j * (T + 6)
            sheet.paste(crop, (X, y0))
            d.rectangle([X, y0, X + 22, y0 + 22], fill=(0, 0, 0))
            d.text((X + 5, y0 + 1), "abcdef"[j], fill=(255, 215, 0), font=lab)
    sheet.save(os.path.join(CACHE, "cast_sheet.jpg"), quality=90)
    print("people per photo written; sheet at cache/cast_sheet.jpg")
    for pid, p in people.items():
        ph = sorted(n for n in assign if pid in assign[n])
        print(f"#{pid:>2} {p['name'] or '?':10} {len(ph):3d} photos")


if __name__ == "__main__":
    main()
