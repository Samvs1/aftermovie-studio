"""Photo analysis: orientation fix, face detection, face embeddings, basic image stats.

Writes cache/photos.json. Rotation is chosen per photo by running the face detector
at 0/90/180/270 degrees and keeping the rotation where faces are found most confidently.
Manual overrides in cache/rotation_overrides.json win over the automatic choice.

usage: python tools/analyze_photos.py
"""
import json, os, sys, glob
import numpy as np
import cv2
from PIL import Image, ImageOps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from am.common import PHOTOS, CACHE, MODELS  # noqa: E402
DET_MAX = 1600  # long side used for detection

os.makedirs(CACHE, exist_ok=True)


def load_rgb(path):
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    return np.array(im)


def rotate(img, k):
    """k = number of 90deg clockwise turns"""
    if k == 0:
        return img
    return np.ascontiguousarray(np.rot90(img, -k))


def make_detector():
    return cv2.FaceDetectorYN.create(
        os.path.join(MODELS, "face_detection_yunet_2023mar.onnx"), "", (320, 320),
        score_threshold=0.6, nms_threshold=0.3, top_k=50)


def detect(det, rgb):
    h, w = rgb.shape[:2]
    s = DET_MAX / max(h, w)
    small = cv2.resize(rgb, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else rgb
    s = min(s, 1.0)
    bgr = cv2.cvtColor(small, cv2.COLOR_RGB2BGR)
    det.setInputSize((bgr.shape[1], bgr.shape[0]))
    _, faces = det.detect(bgr)
    if faces is None:
        return [], bgr, s
    return faces, bgr, s


def orientation_score(faces, shape):
    h, w = shape[:2]
    tot = 0.0
    for f in faces:
        score = float(f[14])
        if score < 0.75:
            continue
        area = (f[2] * f[3]) / (w * h)
        tot += score * (0.5 + min(area * 40, 1.5))
    return float(tot)


_SOURCES = None


def is_scan(path, name):
    """Film scans / disposables (no camera EXIF) may be stored sideways; phone shots are upright via EXIF.
    cache/photo_sources.json ({name: "phone"|"disposable"}, e.g. written by the Polarsteps importer) wins."""
    global _SOURCES
    if _SOURCES is None:
        sp = os.path.join(CACHE, "photo_sources.json")
        _SOURCES = json.load(open(sp)) if os.path.exists(sp) else {}
    if name in _SOURCES:
        return _SOURCES[name] == "disposable"
    if name.startswith("img"):                     # the Elevate disposable scans
        return True
    try:
        ex = Image.open(path).getexif()
        return not (ex.get(0x010F) or ex.get(0x0110))   # no Make / Model
    except Exception:
        return True


def main():
    force = "--force" in sys.argv
    overrides_path = os.path.join(CACHE, "rotation_overrides.json")
    overrides = json.load(open(overrides_path)) if os.path.exists(overrides_path) else {}
    out_path = os.path.join(CACHE, "photos.json")
    old = json.load(open(out_path)) if os.path.exists(out_path) and not force else {}
    det = make_detector()
    rec = cv2.FaceRecognizerSF.create(os.path.join(MODELS, "face_recognition_sface_2021dec.onnx"), "")
    out = {}
    files = sorted(p for p in glob.glob(os.path.join(PHOTOS, "*")) if p.lower().endswith((".jpg", ".jpeg")))
    for i, p in enumerate(files):
        name = os.path.basename(p)
        if name in old and int(overrides.get(name, old[name]["rot"])) == old[name]["rot"]:
            out[name] = old[name]                  # already analysed (incremental)
            continue
        rgb0 = load_rgb(p)
        scan = is_scan(p, name)
        scores = {}
        for k in range(4):
            faces, bgr, s = detect(det, rotate(rgb0, k))
            scores[k] = orientation_score(faces, bgr.shape)
        auto_k = max(scores, key=scores.get)
        # prefer the stored orientation when nothing is confidently better
        if scores[auto_k] < 0.9 or scores[auto_k] < scores[0] * 1.15:
            auto_k = 0 if scores[0] >= scores[auto_k] * 0.87 else auto_k
        if not scan:
            auto_k = 0  # phone photos are stored upright; lying-down faces would fool the vote
        k = int(overrides.get(name, auto_k))
        rgb = rotate(rgb0, k)
        faces, bgr, s = detect(det, rgb)
        H, W = rgb.shape[:2]
        flist = []
        for f in faces:
            if float(f[14]) < 0.6:
                continue
            aligned = rec.alignCrop(bgr, f)
            emb = rec.feature(aligned).flatten()
            emb = emb / (np.linalg.norm(emb) + 1e-9)
            x, y, fw, fh = [float(v) / s for v in f[:4]]
            flist.append({
                "box": [x / W, y / H, fw / W, fh / H],  # normalized to the upright image
                "score": round(float(f[14]), 3),
                "emb": [round(float(v), 5) for v in emb],
            })
        gray = cv2.cvtColor(cv2.resize(rgb, (256, int(256 * H / W))), cv2.COLOR_RGB2GRAY)
        hsv = cv2.cvtColor(cv2.resize(rgb, (256, int(256 * H / W))), cv2.COLOR_RGB2HSV)
        sharp = cv2.Laplacian(cv2.cvtColor(cv2.resize(rgb, (800, int(800 * H / W))), cv2.COLOR_RGB2GRAY), cv2.CV_64F).var()
        out[name] = {
            "rot": k,
            "auto_rot": int(auto_k),
            "rot_scores": {str(a): round(b, 2) for a, b in scores.items()},
            "w": W, "h": H,
            "orient": "landscape" if W > H * 1.05 else ("portrait" if H > W * 1.05 else "square"),
            "source": "disposable" if scan else "phone",
            "brightness": round(float(gray.mean()) / 255, 3),
            "contrast": round(float(gray.std()) / 255, 3),
            "saturation": round(float(hsv[..., 1].mean()) / 255, 3),
            "sharpness": round(float(sharp), 1),
            "faces": flist,
        }
        print(f"[{i+1}/{len(files)}] {name} rot={k} (auto {auto_k}) faces={len(flist)} scores={out[name]['rot_scores']}", flush=True)
    json.dump(out, open(out_path, "w"))
    print(f"wrote {out_path} ({len(out)} photos)")


if __name__ == "__main__":
    main()
