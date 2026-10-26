"""Group detected faces into identities and build a numbered who's-who sheet.

Reads cache/photos.json, writes cache/face_clusters.json and cache/whos_who.jpg.
Once people are named, cache/people.json maps cluster id -> name and every face
in photos.json gets a "person" field via tools/apply_names.py.

usage: python tools/cluster_faces.py [threshold]
"""
import json, os, sys
import numpy as np
from scipy.cluster.hierarchy import linkage, fcluster
from PIL import Image, ImageDraw, ImageFont, ImageOps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from am.common import PHOTOS, CACHE  # noqa: E402
THRESH = float(sys.argv[1]) if len(sys.argv) > 1 else 0.62  # cosine distance cut


def load_upright(name, rot):
    im = ImageOps.exif_transpose(Image.open(os.path.join(PHOTOS, name))).convert("RGB")
    return im.rotate(-90 * rot, expand=True) if rot else im


def main():
    meta = json.load(open(os.path.join(CACHE, "photos.json")))
    faces = []
    for name, m in meta.items():
        for i, f in enumerate(m["faces"]):
            x, y, w, h = f["box"]
            px = w * m["w"]
            if f["score"] < 0.7 or px < 40:  # too small/unsure to identify
                continue
            faces.append({"photo": name, "idx": i, "emb": np.array(f["emb"]), "px": px, "score": f["score"]})
    if len(faces) < 2:
        json.dump({str(i + 1): [{"photo": f["photo"], "idx": f["idx"]}] for i, f in enumerate(faces)},
                  open(os.path.join(CACHE, "face_clusters.json"), "w"), indent=1)
        json.dump([], open(os.path.join(CACHE, "face_clusters_ui.json"), "w"))
        print(f"{len(faces)} usable faces: nothing to cluster")
        return
    E = np.stack([f["emb"] for f in faces])
    Z = linkage(E, method="average", metric="cosine")
    labels = fcluster(Z, t=THRESH, criterion="distance")
    clusters = {}
    for f, l in zip(faces, labels):
        clusters.setdefault(int(l), []).append(f)
    # order: biggest clusters first
    ordered = sorted(clusters.values(), key=lambda c: (-len({f["photo"] for f in c}), -max(f["px"] for f in c)))
    out = {}
    for cid, members in enumerate(ordered, 1):
        out[str(cid)] = [{"photo": f["photo"], "idx": f["idx"]} for f in sorted(members, key=lambda f: -f["px"] * f["score"])]
    json.dump(out, open(os.path.join(CACHE, "face_clusters.json"), "w"), indent=1)

    # who's-who sheet: one row per cluster with up to 6 example crops
    keep = [(cid, m) for cid, m in out.items() if len({x["photo"] for x in m}) >= 2]
    T = 150
    cols = 2  # two clusters per row
    per_cluster = 7
    cell_w = 90 + per_cluster * (T + 6)
    rows = (len(keep) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell_w + 20, rows * (T + 16) + 10), (24, 24, 24))
    d = ImageDraw.Draw(sheet)
    fnt = ImageFont.truetype("arialbd.ttf", 40)
    small = ImageFont.truetype("arial.ttf", 16)
    cache_img = {}
    for n, (cid, members) in enumerate(keep):
        cx = (n % cols) * cell_w + 10
        cy = (n // cols) * (T + 16) + 10
        d.text((cx + 4, cy + T // 2 - 30), f"#{cid}", fill=(255, 220, 0), font=fnt)
        d.text((cx + 6, cy + T // 2 + 16), f"{len({m['photo'] for m in members})} pics", fill=(200, 200, 200), font=small)
        # spread samples across the whole cluster so a wrong merge is visible
        picks = [members[int(round(t))] for t in np.linspace(0, len(members) - 1, min(per_cluster, len(members)))]
        for j, mm in enumerate(picks):
            pm = meta[mm["photo"]]
            if mm["photo"] not in cache_img:
                cache_img[mm["photo"]] = load_upright(mm["photo"], pm["rot"])
            im = cache_img[mm["photo"]]
            x, y, w, h = pm["faces"][mm["idx"]]["box"]
            W, H = im.size
            cxf, cyf, s = (x + w / 2) * W, (y + h / 2) * H, max(w * W, h * H) * 0.85
            crop = im.crop((int(cxf - s), int(cyf - s), int(cxf + s), int(cyf + s))).resize((T, T))
            sheet.paste(crop, (cx + 90 + j * (T + 6), cy))
    sheet.save(os.path.join(CACHE, "whos_who.jpg"), quality=88)

    # face crops for the studio's "who's who" page: up to 8 per cluster seen in >= 2 photos
    fdir = os.path.join(CACHE, "faces")
    os.makedirs(fdir, exist_ok=True)
    ui = []
    for cid, members in out.items():
        n_ph = len({x["photo"] for x in members})
        if n_ph < 2:
            continue
        crops = []
        seen = set()
        for mm in members:
            if mm["photo"] in seen or len(crops) >= 8:
                continue
            seen.add(mm["photo"])
            pm = meta[mm["photo"]]
            if mm["photo"] not in cache_img:
                cache_img[mm["photo"]] = load_upright(mm["photo"], pm["rot"])
            im = cache_img[mm["photo"]]
            x, y, w, h = pm["faces"][mm["idx"]]["box"]
            W, H = im.size
            cxf, cyf, s = (x + w / 2) * W, (y + h / 2) * H, max(w * W, h * H) * 0.9
            fn = f"c{cid}_{len(crops)}.jpg"
            im.crop((int(cxf - s), int(cyf - s), int(cxf + s), int(cyf + s))).resize((160, 160)).save(os.path.join(fdir, fn), quality=85)
            crops.append(f"cache/faces/{fn}")
        ui.append({"cluster": cid, "photos": n_ph, "faces": len(members), "crops": crops})
    json.dump(ui, open(os.path.join(CACHE, "face_clusters_ui.json"), "w"), indent=1)
    print(f"{len(faces)} faces -> {len(out)} clusters ({len(keep)} shown)")
    for cid, m in out.items():
        print(cid, len(m), sorted({x['photo'][-8:-4] for x in m}))


if __name__ == "__main__":
    main()
