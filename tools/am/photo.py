"""Photo sources (graded, mip-mapped) and face-safe framing.

A crop is (cx, cy, cw, ch) in normalised image coordinates (0..1 of width / height).
plan_crop() picks a crop of a given output aspect + zoom around a focus, then nudges it so
that no face is cut through by the frame edge (faces are either fully in, or clearly out).
Containment is preserved under linear interpolation of crop edges, so a Ken Burns move between
two safe crops never cuts a face either.
"""
import math
from collections import OrderedDict

import numpy as np
import cv2

from .common import faces as face_list, photo_meta
from .grade import ensure_graded


class Source:
    def __init__(self, path):
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        self.levels = [img]
        while min(self.levels[-1].shape[:2]) > 300:
            self.levels.append(cv2.pyrDown(self.levels[-1]))
        self.h, self.w = img.shape[:2]

    def sample(self, crop, out_w, out_h, rot=0.0):
        """Warp the normalised crop into an out_w x out_h float32 RGB patch."""
        cx, cy, cw, ch = crop
        px_w = cw * self.w
        scale = px_w / max(out_w, 1)  # source px per output px
        lvl = 0
        while lvl + 1 < len(self.levels) and scale >= 2.0:
            scale /= 2
            lvl += 1
        src = self.levels[lvl]
        sh, sw = src.shape[:2]
        k = sw / self.w
        s = (cw * self.w * k) / out_w
        ang = math.radians(rot)
        ca, sa = math.cos(ang) * s, math.sin(ang) * s
        # output (u,v) -> source (x,y): centre to centre
        ox, oy = out_w / 2, out_h / 2
        sx, sy = cx * sw, cy * sh
        M = np.array([[ca, -sa, sx - ca * ox + sa * oy], [sa, ca, sy - sa * ox - ca * oy]], np.float32)
        out = cv2.warpAffine(src, M, (int(out_w), int(out_h)), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                             borderMode=cv2.BORDER_REFLECT_101)
        return out.astype(np.float32) * (1 / 255)


class SourceCache:
    def __init__(self, preset, overrides=None, size=14):
        self.preset = preset
        self.overrides = overrides or {}
        self.size = size
        self.d = OrderedDict()

    def get(self, name):
        if name in self.d:
            self.d.move_to_end(name)
            return self.d[name]
        src = Source(ensure_graded(self.preset, name, self.overrides.get(name)))
        self.d[name] = src
        if len(self.d) > self.size:
            self.d.popitem(last=False)
        return src


def image_aspect(name):
    m = photo_meta()[name]
    return m["w"] / m["h"]


def _focus_box(name, focus):
    fl = face_list(name)
    if isinstance(focus, (list, tuple)) and len(focus) == 2:
        return (focus[0], focus[1], 0.0, 0.0), fl
    if focus in (None, "center"):
        return (0.5, 0.5, 0.0, 0.0), fl
    sel = fl
    if isinstance(focus, str) and focus.startswith("face:"):
        idx = sorted(range(len(fl)), key=lambda i: -fl[i]["box"][2])
        k = int(focus.split(":")[1])
        sel = [fl[idx[k]]] if k < len(idx) else fl
    elif isinstance(focus, str) and focus.startswith("person:"):
        pid = focus.split(":")[1]
        sel = [f for f in fl if f["person"] == pid] or fl
    elif focus == "biggest":
        sel = sorted(fl, key=lambda f: -f["box"][2])[:1]
    if not sel:
        return (0.5, 0.45, 0.0, 0.0), fl
    x0 = min(f["box"][0] for f in sel)
    y0 = min(f["box"][1] for f in sel)
    x1 = max(f["box"][0] + f["box"][2] for f in sel)
    y1 = max(f["box"][1] + f["box"][3] for f in sel)
    return ((x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0), fl


def auto_zoom(name, out_aspect, focus, face_frac=0.42):
    """Zoom so the focus face(s) fill ~face_frac of the crop height."""
    ia = image_aspect(name)
    ch0 = 1.0 if out_aspect < ia else ia / out_aspect
    (_, _, fw, fh), _ = _focus_box(name, focus)
    if fh <= 0:
        return 1.0
    return float(min(max(ch0 * face_frac / fh, 1.0), 4.0))


def plan_crop(name, out_aspect, zoom=1.0, focus="faces", offset=(0.0, 0.0), headroom=0.06):
    """Return a face-safe normalised crop (cx, cy, cw, ch). zoom may be 'auto' or 'auto:<frac>'."""
    if isinstance(zoom, str) and zoom.startswith("auto"):
        frac = float(zoom.split(":")[1]) if ":" in zoom else 0.42
        zoom = auto_zoom(name, out_aspect, focus, frac)
    ia = image_aspect(name)
    # largest crop of out_aspect inside the image (cover), then zoom in
    if out_aspect >= ia:
        cw, ch = 1.0, ia / out_aspect
    else:
        cw, ch = out_aspect / ia, 1.0
    cw /= zoom
    ch /= zoom
    (fx, fy, fw, fh), fl = _focus_box(name, focus)
    # faces sit a little above centre (headroom)
    want_x = fx + offset[0] * cw
    want_y = fy + offset[1] * ch + (headroom * ch if fh > 0 else 0)

    def clampc(x, y):
        return min(max(x, cw / 2), 1 - cw / 2), min(max(y, ch / 2), 1 - ch / 2)

    def cost(x, y):
        x0, y0, x1, y1 = x - cw / 2, y - ch / 2, x + cw / 2, y + ch / 2
        c = ((x - want_x) / cw) ** 2 + ((y - want_y) / ch) ** 2
        for f in fl:
            bx, by, bw, bh = f["box"]
            ix = max(0, min(x1, bx + bw) - max(x0, bx))
            iy = max(0, min(y1, by + bh) - max(y0, by))
            frac = (ix * iy) / max(bw * bh, 1e-9)
            if 0.04 < frac < 0.97:
                c += 8.0 * (1 - abs(frac - 0.5) * 2) + 3.0  # partially cut face
        if fw > 0:  # focus group must be inside
            if fx - fw / 2 < x0 or fx + fw / 2 > x1 or fy - fh / 2 < y0 or fy + fh / 2 > y1:
                c += 3.0
        return c

    best = None
    for dx in np.linspace(-0.45, 0.45, 19):
        for dy in np.linspace(-0.45, 0.45, 19):
            x, y = clampc(want_x + dx * cw, want_y + dy * ch)
            c = cost(x, y)
            if best is None or c < best[0]:
                best = (c, x, y)
    return (best[1], best[2], cw, ch)


def cut_faces(name, crop):
    """Number of faces partially cut by this crop (QA helper)."""
    cx, cy, cw, ch = crop
    x0, y0, x1, y1 = cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2
    n = 0
    for f in face_list(name):
        bx, by, bw, bh = f["box"]
        ix = max(0, min(x1, bx + bw) - max(x0, bx))
        iy = max(0, min(y1, by + bh) - max(y0, by))
        frac = (ix * iy) / max(bw * bh, 1e-9)
        if 0.15 < frac < 0.85:
            n += 1
    return n


def lerp_crop(a, b, u):
    """Interpolate crop edges (keeps containment)."""
    ax0, ay0, ax1, ay1 = a[0] - a[2] / 2, a[1] - a[3] / 2, a[0] + a[2] / 2, a[1] + a[3] / 2
    bx0, by0, bx1, by1 = b[0] - b[2] / 2, b[1] - b[3] / 2, b[0] + b[2] / 2, b[1] + b[3] / 2
    x0, y0 = ax0 + (bx0 - ax0) * u, ay0 + (by0 - ay0) * u
    x1, y1 = ax1 + (bx1 - ax1) * u, ay1 + (by1 - ay1) * u
    return ((x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0)


def zoom_crop(crop, z, shift=(0.0, 0.0)):
    cx, cy, cw, ch = crop
    cw2, ch2 = cw / z, ch / z
    cx2 = min(max(cx + shift[0] * cw, cw2 / 2), 1 - cw2 / 2) if cw2 < 1 else 0.5
    cy2 = min(max(cy + shift[1] * ch, ch2 / 2), 1 - ch2 / 2) if ch2 < 1 else 0.5
    return (cx2, cy2, cw2, ch2)


def face_on_screen(name, crop, box, which="biggest"):
    """Screen rect (x, y, w, h) of a face given the crop and the layer box (design px)."""
    fl = face_list(name)
    if not fl:
        return None
    if isinstance(which, str) and which.startswith("person:"):
        sel = [f for f in fl if f["person"] == which.split(":")[1]]
        f = sel[0] if sel else max(fl, key=lambda f: f["box"][2])
    else:
        f = max(fl, key=lambda f: f["box"][2])
    cx, cy, cw, ch = crop
    bx, by, bw, bh = box
    x = bx + ((f["box"][0] - (cx - cw / 2)) / cw) * bw
    y = by + ((f["box"][1] - (cy - ch / 2)) / ch) * bh
    return (x, y, f["box"][2] / cw * bw, f["box"][3] / ch * bh)
