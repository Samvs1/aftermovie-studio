"""Cut an object out of a photo (OpenCV GrabCut) for a die-cut sticker layer ({"type": "sticker", "img": ...}).

  python tools/cutout.py <photo file> <name> --rect x0,y0,x1,y1 [--iter 8] [--fg x,y,r ...] [--bg x,y,r ...]

rect = the object's box in normalised coordinates of the upright photo (0..1). --fg / --bg mark extra sure-foreground /
sure-background discs (normalised x, y, radius) when the first pass leaks. Writes cache/cutouts/<name>.png (RGBA,
cropped to the object) and cache/cutouts/<name>_check.jpg (on a checkerboard) to look at.
"""
import argparse, os, sys
import numpy as np
import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from am.common import CACHE, load_upright  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photo")
    ap.add_argument("name")
    ap.add_argument("--rect", required=True)
    ap.add_argument("--iter", type=int, default=8)
    ap.add_argument("--fg", action="append", default=[])
    ap.add_argument("--bg", action="append", default=[])
    ap.add_argument("--max", type=int, default=1600)
    a = ap.parse_args()
    im = np.array(load_upright(a.photo, a.max))[:, :, ::-1].copy()          # BGR
    H, W = im.shape[:2]
    x0, y0, x1, y1 = [float(v) for v in a.rect.split(",")]
    rect = (int(x0 * W), int(y0 * H), int((x1 - x0) * W), int((y1 - y0) * H))
    mask = np.zeros((H, W), np.uint8)
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(im, mask, rect, bgd, fgd, a.iter, cv2.GC_INIT_WITH_RECT)
    if a.fg or a.bg:
        for spec, val in [(s, cv2.GC_FGD) for s in a.fg] + [(s, cv2.GC_BGD) for s in a.bg]:
            x, y, r = [float(v) for v in spec.split(",")]
            cv2.circle(mask, (int(x * W), int(y * H)), max(2, int(r * W)), int(val), -1)
        cv2.grabCut(im, mask, None, bgd, fgd, a.iter, cv2.GC_INIT_WITH_MASK)
    fg = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 1, 0).astype(np.uint8)
    # keep the biggest blob, fill holes, soften the edge a touch
    n, lab, stats, _ = cv2.connectedComponentsWithStats(fg)
    if n > 1:
        fg = (lab == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))).astype(np.uint8)
    fl = fg.copy()
    cv2.floodFill(fl, np.zeros((H + 2, W + 2), np.uint8), (0, 0), 1)
    fg = fg | (1 - fl)
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    alpha = cv2.GaussianBlur(fg.astype(np.float32), (0, 0), 1.0)
    ys, xs = np.where(fg > 0)
    if not len(xs):
        sys.exit("nothing cut out: adjust --rect")
    bx0, by0, bx1, by1 = max(0, xs.min() - 4), max(0, ys.min() - 4), min(W, xs.max() + 5), min(H, ys.max() + 5)
    rgba = np.dstack([im, (alpha * 255).astype(np.uint8)])[by0:by1, bx0:bx1]
    out = os.path.join(CACHE, "cutouts")
    os.makedirs(out, exist_ok=True)
    cv2.imwrite(os.path.join(out, f"{a.name}.png"), rgba)
    # preview on a checkerboard
    h, w = rgba.shape[:2]
    chk = ((np.indices((h, w)).sum(0) // 16) % 2 * 60 + 150).astype(np.uint8)
    chk = np.dstack([chk] * 3).astype(np.float32)
    al = rgba[..., 3:4].astype(np.float32) / 255
    prev = (rgba[..., :3].astype(np.float32) * al + chk * (1 - al)).astype(np.uint8)
    cv2.imwrite(os.path.join(out, f"{a.name}_check.jpg"), prev)
    print(f"wrote cache/cutouts/{a.name}.png ({w}x{h}) and {a.name}_check.jpg")


if __name__ == "__main__":
    main()
