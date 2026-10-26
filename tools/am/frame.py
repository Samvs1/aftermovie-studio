"""Frame compositor: evaluates an EDL at film time t and returns an RGB float32 frame.

EDL coordinates are in 1920x1080 design pixels; ctx.S scales them to the output size.
See tools/README.md for the full EDL reference.
"""
import math, os
import numpy as np
import cv2

from .common import CACHE, DESIGN_W, DESIGN_H, hex2rgb
from . import draw as D
from . import props as P
from . import vhs as V
from . import graphic as G
from . import looks as LK
from .photo import SourceCache, plan_crop, lerp_crop, zoom_crop, face_on_screen
from .music import MusicMap


class Ctx:
    def __init__(self, edl, out_w):
        self.edl = edl
        self.S = out_w / DESIGN_W
        self.W = int(round(DESIGN_W * self.S))
        self.H = int(round(DESIGN_H * self.S))
        g = edl.get("grade", {})
        self.sources = SourceCache(g.get("preset", "consumer_film"), g.get("overrides"), size=16)
        self.music = MusicMap(edl)
        self.shots = sorted(edl["shots"], key=lambda s: s["t0"])
        for i, s in enumerate(self.shots):
            s["_i"] = i
        self.crops = {}
        self.cards = {}
        self.finish = edl.get("finish", {})
        self.flashes = edl.get("flashes", [])

    # ------------------------------------------------------------ helpers
    def px(self, v):
        return v * self.S

    def shot_at(self, t):
        cur = None
        for s in self.shots:
            if s["t0"] <= t + 1e-6:
                cur = s
            else:
                break
        return cur or self.shots[0]


def layer_time(shot, L, t):
    """Effective time for motion: honours freeze points and shot-level freeze intervals."""
    te = t
    for a, b in shot.get("freeze", []):
        if te > a:
            te -= min(te, b) - a
    if "freeze_at" in L:
        te = min(te, L["freeze_at"])
    return te


def anim_state(A, t, kind="enter"):
    """Returns (dx, dy, scale, rot, opacity) for an enter/exit animation spec."""
    if not A:
        return 0, 0, 1, 0, 1
    t0 = A["t"]
    dur = A.get("dur", 0.25)
    u = (t - t0) / max(dur, 1e-4)
    typ = A.get("type", "fade")
    if kind == "exit":
        u = 1 - u
    if u <= 0:
        return 0, 0, 1, 0, 0
    if u >= 1:
        return 0, 0, 1, 0, 1
    fx, fy = A.get("from", (0, -700))
    if typ == "drop":
        e = D.ease(u, "back")
        return fx * (1 - e), fy * (1 - e), 1.0, A.get("spin", 12) * (1 - e), min(1, u * 4)
    if typ == "slide":
        e = D.ease(u, "out")
        return fx * (1 - e), fy * (1 - e), 1, 0, min(1, u * 3)
    if typ == "pop":
        e = D.ease(u, "back")
        return 0, 0, 0.55 + 0.45 * e, 0, min(1, u * 3)
    if typ == "thump":  # stamps: big -> settle
        e = D.ease(u, "out")
        return 0, 0, 1.45 - 0.45 * e, 0, min(1, u * 6)
    return 0, 0, 1, 0, D.ease(u, "inout")


def photo_crop_at(ctx, shot, L, t):
    name = L["src"]
    box = L.get("box", [0, 0, DESIGN_W, DESIGN_H])
    aspect = box[2] / box[3]
    key = (shot["id"], L.get("_k", id(L)))
    if key not in ctx.crops:
        z = L.get("zoom", [1.0, 1.08])
        z = z if isinstance(z, (list, tuple)) else [z, z]
        drift = L.get("drift", [[0, 0], [0, 0]])
        focus = L.get("focus", "faces")
        c0 = plan_crop(name, aspect, z[0], focus, drift[0])
        c1 = plan_crop(name, aspect, z[1], focus, drift[1])
        ctx.crops[key] = (c0, c1)
    c0, c1 = ctx.crops[key]
    te = layer_time(shot, L, t)
    T0, T1 = L.get("move", [shot["t0"], shot["t1"]])
    u = D.ease((te - T0) / max(T1 - T0, 1e-3), L.get("ease", "inout"))
    crop = lerp_crop(c0, c1, u)
    # music-reactive zoom pulse / shake
    zp = 1.0
    pulse = L.get("pulse", shot.get("pulse"))
    if pulse:
        kind = pulse.get("on", "kicks")
        zp += pulse.get("amount", 0.035) * ctx.music.pulse(kind, t, pulse.get("decay", 0.11), pulse.get("min", 0.35),
                                                           window=(shot["t0"] - 0.05, shot["t1"]))
    shift = (0.0, 0.0)
    shake = L.get("shake", shot.get("shake"))
    if shake:
        v = ctx.music.pulse(shake.get("on", "bass_hits"), t, shake.get("decay", 0.08), shake.get("min", 0.5))
        rng = np.random.default_rng(int(t * 60))
        shift = tuple((rng.random(2) - 0.5) * 2 * shake.get("amount", 0.012) * v)
    if zp != 1.0 or shift != (0.0, 0.0):
        crop = zoom_crop(crop, zp, shift)
    return crop, box


def draw_photo(ctx, canvas, shot, L, t):
    crop, box = photo_crop_at(ctx, shot, L, t)
    src = ctx.sources.get(L["src"])
    bw, bh = int(round(ctx.px(box[2]))), int(round(ctx.px(box[3])))
    if bw < 2 or bh < 2:
        return
    patch = src.sample(crop, bw, bh)
    if "develop" in L:
        dv = L["develop"]
        patch = P.developed(patch, (t - dv["t"]) / max(dv.get("dur", 1.0), 1e-3))
    if L.get("desat"):
        g = patch.mean(-1, keepdims=True)
        patch = g + (patch - g) * (1 - L["desat"])
    if L.get("halftone"):
        ht = L["halftone"]
        amt = 1.0 if "t" not in ht else D.ease((t - ht["t"]) / max(ht.get("dur", 0.2), 1e-3), "out")
        patch = V.halftone(patch, ctx.px(ht.get("cell", 9)), ht.get("mode", "color"), ht.get("ink", "#141414"),
                           ht.get("paper", "#f4ecd8"), amt, ht.get("angle", 15))
    if L.get("look"):
        patch = LK.apply(patch, L["look"], ctx.S, t)
    dx, dy, sc, rot, op = anim_state(L.get("enter"), t)
    if "exit" in L:
        ex = anim_state(L["exit"], t, "exit")
        dx, dy, sc, rot, op = dx + ex[0], dy + ex[1], sc * ex[2], rot + ex[3], op * ex[4]
    rot += L.get("rot", 0)
    if "turn" in L:         # the print turns over on a beat: {"t", "dur", "deg"} (e.g. 180 = upside down)
        tn = L["turn"]
        rot += tn.get("deg", 180) * D.ease((t - tn["t"]) / max(tn.get("dur", 0.4), 1e-3), "inout")
    border = L.get("border")
    op *= L.get("opacity", 1.0)
    mode = L.get("blend", "normal")
    simple =(abs(rot) < 1e-3 and abs(sc - 1) < 1e-3 and op >= 0.999 and not border and not L.get("shadow")
             and mode == "normal" and not L.get("edge") and not L.get("feather") and not L.get("mask"))
    x, y = ctx.px(box[0] + dx), ctx.px(box[1] + dy)
    if simple:
        D.over(canvas, np.dstack([patch, np.ones(patch.shape[:2], np.float32)]), x, y)
        return
    rgba = np.dstack([patch, np.ones(patch.shape[:2], np.float32)])
    if border:
        bpx = max(1, int(ctx.px(border.get("px", 10))))
        col = np.array(hex2rgb(border.get("color", "#f5f1e8"))[:3], np.float32)
        big = np.ones((bh + 2 * bpx, bw + 2 * bpx, 4), np.float32)
        big[..., :3] = col
        big[bpx:bpx + bh, bpx:bpx + bw] = rgba
        rgba = big
    if L.get("feather"):                     # soft edges: double exposures, dreamy overlaps
        rgba[..., 3] *= G.feather_mask(rgba.shape[0], rgba.shape[1], int(ctx.px(L["feather"])))
    if L.get("edge") == "torn":              # torn-paper cut-out (collage)
        rgba[..., 3] *= G.torn_mask(rgba.shape[0], rgba.shape[1], L.get("seed", 1), ctx.px(L.get("tear", 14)))
    if L.get("mask"):                        # the photo seen through a shape: {"kind": arch|star8|circle, "point"}
        mk = L["mask"]
        rgba[..., 3] *= G.shape_mask(mk.get("kind", "arch"), rgba.shape[0], rgba.shape[1], mk.get("point", 0.5))
    if L.get("shadow"):
        rgba = D.shadow_of(rgba, blur=ctx.px(14), offset=(ctx.px(6), ctx.px(10)), strength=0.5)
    if mode != "normal":
        G.place_blend(canvas, rgba, x + bw / 2, y + bh / 2, sc, rot, op, mode)
    else:
        D.place(canvas, rgba, x + bw / 2, y + bh / 2, sc, rot, op)


def draw_polaroid(ctx, canvas, shot, L, t):
    cw = int(ctx.px(L["w"]))
    pw = int(cw * 0.88)
    ph = int(pw * 1.0)
    dv = L.get("develop")
    u = 1.0 if not dv else D.clamp01((t - dv["t"]) / max(dv.get("dur", 1.0), 1e-3))
    key = (shot["id"], L.get("_k"), round(u, 2) if u < 1 else 1)
    card = ctx.cards.get(key)
    if card is None:
        crop = plan_crop(L["src"], pw / ph, L.get("zoom", 1.15), L.get("focus", "faces"), L.get("offset", (0, 0)))
        patch = ctx.sources.get(L["src"]).sample(crop, pw, ph)
        patch = P.developed(patch, u)
        card = P.polaroid(patch, cw, L.get("caption"), L.get("caption_font", "caveat"),
                          L.get("caption_color", "#1f2a44"), seed=L.get("seed", 0))
        if u >= 1:
            ctx.cards[key] = card
    dx, dy, sc, rot, op = anim_state(L.get("enter"), t)
    if "exit" in L:
        ex = anim_state(L["exit"], t, "exit")
        dx, dy, op = dx + ex[0], dy + ex[1], op * ex[4]
    D.place(canvas, card, ctx.px(L["cx"] + dx), ctx.px(L["cy"] + dy), sc * L.get("scale", 1), L.get("rot", 0) + rot, op)


def draw_strip(ctx, canvas, shot, L, t):
    sw = int(ctx.px(L["w"]))
    fw = int(sw * 0.84)
    fh = int(fw * 0.78)
    key = (shot["id"], L.get("_k"), "strip")
    card = ctx.cards.get(key)
    if card is None:
        frames = []
        for s in L["srcs"]:
            crop = plan_crop(s, fw / fh, L.get("zoom", 1.2), "faces")
            frames.append(ctx.sources.get(s).sample(crop, fw, fh))
        card = P.booth_strip(frames, sw, L.get("color", "#fbfaf6"), L.get("label", ""))
        ctx.cards[key] = card
    dx, dy, sc, rot, op = anim_state(L.get("enter"), t)
    if "exit" in L:
        ex = anim_state(L["exit"], t, "exit")
        dx, dy, op = dx + ex[0], dy + ex[1], op * ex[4]
    drift = L.get("drift_y", 0) * D.clamp01((t - shot["t0"]) / max(shot["t1"] - shot["t0"], 1e-3))
    D.place(canvas, card, ctx.px(L["cx"] + dx), ctx.px(L["cy"] + dy + drift), sc, L.get("rot", 0) + rot, op)


def draw_grid(ctx, canvas, shot, L, t):
    bx, by, bwid, bhei = L.get("box", [0, 0, DESIGN_W, DESIGN_H])
    rows, cols = L["rows"], L["cols"]
    gap = L.get("gap", 14)
    cw = (bwid - gap * (cols + 1)) / cols
    chh = (bhei - gap * (rows + 1)) / rows
    pulse = L.get("pulse")
    for i, cell in enumerate(L["cells"]):
        r, c = divmod(i, cols)
        if "t" in cell and t < cell["t"]:
            continue
        x = bx + gap + c * (cw + gap)
        y = by + gap + r * (chh + gap)
        W_, H_ = int(ctx.px(cw)), int(ctx.px(chh))
        key = (shot["id"], L.get("_k"), i)
        patch = ctx.cards.get(key)
        if patch is None:
            crop = plan_crop(cell["src"], cw / chh, cell.get("zoom", 1.1), cell.get("focus", "faces"))
            patch = ctx.sources.get(cell["src"]).sample(crop, W_, H_)
            patch = np.dstack([patch, np.ones(patch.shape[:2], np.float32)])
            ctx.cards[key] = patch
        sc = 1.0
        if pulse:
            sc += pulse.get("amount", 0.05) * ctx.music.pulse(pulse.get("on", "kicks"), t + pulse.get("lag", 0) * (i == pulse.get("late_cell", -1)),
                                                              pulse.get("decay", 0.12), pulse.get("min", 0.35))
        op = 1.0
        if "t" in cell:
            _, _, s2, _, op = anim_state({"t": cell["t"], "dur": 0.16, "type": cell.get("anim", "pop")}, t)
            sc *= s2
        D.place(canvas, patch, ctx.px(x + cw / 2), ctx.px(y + chh / 2), sc, cell.get("rot", 0), op)


def draw_text(ctx, canvas, shot, L, t):
    t0, t1 = L.get("t0", shot["t0"]), L.get("t1", shot["t1"])
    if t < t0 or t > t1:
        return
    text = L["text"]
    anim = L.get("anim", "pop")
    dur = L.get("dur", 0.22)
    u = (t - t0) / max(dur, 1e-3)
    sc, op, dy = 1.0, 1.0, 0.0
    if L.get("count") is not None:          # "{n}" counts up to count (from count_from, over count_dur or dur)
        cu = (t - t0) / max(L.get("count_dur", dur), 1e-3)
        a = L.get("count_from", 0)
        v = a + (L["count"] - a) * D.ease(D.clamp01(cu), L.get("count_ease", "out"))
        text = text.replace("{n}", f"{int(round(v)):,}")
    if anim == "type":
        n = int(len(text) * D.clamp01(u))
        text = text[:max(0, n)]
        if not text.strip():
            return
    elif anim == "pop":
        e = D.ease(D.clamp01(u), "back")
        sc, op = 0.6 + 0.4 * e, D.clamp01(u * 3)
    elif anim == "fade":
        op = D.ease(D.clamp01(u), "inout")
    elif anim == "rise":
        e = D.ease(D.clamp01(u), "out")
        dy, op = 30 * (1 - e), D.clamp01(u * 2)
    fo = L.get("fade_out", 0.15)
    if fo > 0 and t > t1 - fo:
        op *= D.clamp01((t1 - t) / fo)
    seed = -1
    if L.get("boil"):
        seed = int(t * 7) % 3 + 1
    rgba = D.text_rgba(text, L.get("font", "caveat"), ctx.px(L.get("size", 64)), L.get("color", "#ffffff"),
                       ctx.px(L.get("stroke", 0)), L.get("stroke_color", "#000000"), ctx.px(L.get("shadow", 0)),
                       ctx.px(L.get("spacing", 0)), L.get("line_gap", 1.08), L.get("align", "center"), seed)
    x, y = ctx.px(L.get("x", DESIGN_W / 2)), ctx.px(L.get("y", DESIGN_H / 2) + dy)
    anchor = L.get("anchor", "mm")
    if anim == "type" and anchor == "mm":
        anchor = "lm"
    if anchor == "lm":
        x += rgba.shape[1] / 2 * sc
    elif anchor == "rm":
        x -= rgba.shape[1] / 2 * sc
    if anim == "write":
        k = int(rgba.shape[1] * D.clamp01(u))
        rgba = rgba.copy()
        rgba[:, k:, 3] = 0
    if L.get("panel"):  # paper note behind the text (readable on any photo)
        pn = L["panel"]
        full = D.text_rgba(L["text"], L.get("font", "caveat"), ctx.px(L.get("size", 64)), "#000000")
        padx, pady = ctx.px(pn.get("padx", 26)), ctx.px(pn.get("pady", 6))
        pw, ph = int(full.shape[1] * 0.92 + 2 * padx), int(full.shape[0] * 0.78 + 2 * pady)
        note = D.note_panel(pw, ph, pn.get("color", "#f6f1e4"), pn.get("seed", 0), pn.get("tape", True))
        pop = op * L.get("opacity", 1) * (1 if anim in ("write", "type") else 1)
        pdx = (full.shape[1] / 2 - rgba.shape[1] / 2) * sc if anim == "type" else 0
        D.place(canvas, note, x - pdx, y, sc, L.get("rot", 0) + pn.get("rot", 0), min(1, op * 2) * L.get("opacity", 1))
    D.place(canvas, rgba, x, y, sc, L.get("rot", 0), op * L.get("opacity", 1))


def draw_marker_layer(ctx, canvas, shot, L, t):
    t0 = L.get("t0", shot["t0"])
    if t < t0 or t > L.get("t1", shot["t1"]):
        return
    prog = D.clamp01((t - t0) / max(L.get("dur", 0.25), 1e-3))
    kind = L["kind"]
    S = ctx.S
    if "follow" in L:  # circle a face in another layer
        F = L["follow"]
        PL = shot["layers"][F["layer"]]
        crop, box = photo_crop_at(ctx, shot, PL, t)
        r = face_on_screen(PL["src"], crop, box, F.get("face", "biggest"))
        if r is None:
            return
        fx, fy, fw, fh = r
        pts = D.hand_circle((fx + fw / 2) * S, (fy + fh / 2) * S, fw * 0.75 * S, fh * 0.85 * S, seed=L.get("seed", 1))
        D.draw_marker(canvas, pts, L.get("color", "#ff3b30"), ctx.px(L.get("width", 7)), prog)
        return
    if kind == "circle":
        pts = D.hand_circle(L["x"] * S, L["y"] * S, L["rx"] * S, L["ry"] * S, seed=L.get("seed", 1))
        D.draw_marker(canvas, pts, L.get("color", "#ff3b30"), ctx.px(L.get("width", 7)), prog)
    elif kind == "arrow":
        shaft, head = D.hand_arrow(L["x0"] * S, L["y0"] * S, L["x1"] * S, L["y1"] * S, seed=L.get("seed", 1), bend=L.get("bend", 0.18))
        D.draw_marker(canvas, shaft, L.get("color", "#ff3b30"), ctx.px(L.get("width", 7)), min(1, prog * 1.25))
        if prog > 0.8:
            D.draw_marker(canvas, head, L.get("color", "#ff3b30"), ctx.px(L.get("width", 7)), (prog - 0.8) / 0.2)
    elif kind == "line":
        pts = [(x * S, y * S) for x, y in L["points"]]
        D.draw_marker(canvas, pts, L.get("color", "#ff3b30"), ctx.px(L.get("width", 7)), prog)


def draw_doodle(ctx, canvas, shot, L, t):
    """Hand-drawn star / heart / sparkle / swirl that draws itself on at t (slight boil while visible)."""
    t0 = L.get("t", shot["t0"])
    if t < t0 or t > L.get("t1", shot["t1"]):
        return
    prog = D.clamp01((t - t0) / max(L.get("dur", 0.18), 1e-3))
    seed = L.get("seed", 0) * 10 + (int(t * 8) % 3 if L.get("boil", True) else 0)
    S = ctx.S
    for pts in D.doodle_points(L["kind"], L["x"] * S, L["y"] * S, L.get("size", 40) * S, seed):
        D.draw_marker(canvas, pts, L.get("color", "#ffe066"), ctx.px(L.get("width", 6)), prog, L.get("opacity", 1.0))


def draw_bubble(ctx, canvas, shot, L, t):
    """Speech bubble; the tail points at a fixed spot or at a face in another layer."""
    t0, t1 = L.get("t0", shot["t0"]), L.get("t1", shot["t1"])
    if t < t0 or t > t1:
        return
    bx, by = L["x"], L["y"]
    if "follow" in L:
        F = L["follow"]
        PL = shot["layers"][F["layer"]]
        crop, box = photo_crop_at(ctx, shot, PL, t)
        r = face_on_screen(PL["src"], crop, box, F.get("face", "biggest"))
        tx, ty = (r[0] + r[2] / 2, r[1]) if r else L.get("tail", (bx, by + 200))
    else:
        tx, ty = L.get("tail", (bx, by + 200))
    rgba, _ = D.speech_bubble(L["text"], L.get("font", "caveat"), ctx.px(L.get("size", 60)),
                              ctx.px(tx - bx) * 0.82, ctx.px(ty - by) * 0.82, L.get("seed", 0))
    _, _, sc, _, op = anim_state({"t": t0, "dur": 0.2, "type": "pop"}, t)
    fo = L.get("fade_out", 0.12)
    if fo and t > t1 - fo:
        op *= D.clamp01((t1 - t) / fo)
    D.place(canvas, rgba, ctx.px(bx), ctx.px(by), sc, L.get("rot", 0), op)


def draw_flag(ctx, canvas, shot, L, t):
    if t < L.get("t", shot["t0"]):
        return
    _, _, sc, _, op = anim_state({"t": L.get("t", shot["t0"]), "dur": 0.2, "type": "pop"}, t)
    st = D.flag_sticker(L["code"], int(ctx.px(L.get("w", 110))), L.get("seed", 0))
    dx, dy = 0, 0
    if "exit" in L:
        ex = anim_state(L["exit"], t, "exit")
        dx, dy, op = ex[0], ex[1], op * ex[4]
    D.place(canvas, st, ctx.px(L["x"] + dx), ctx.px(L["y"] + dy), sc, L.get("rot", 0), op)


def draw_stamp(ctx, canvas, shot, L, t):
    if t < L.get("t", shot["t0"]):
        return
    _, _, sc, _, op = anim_state({"t": L["t"], "dur": 0.12, "type": "thump"}, t)
    st = D.passport_stamp(L.get("top", ""), L["mid"], L.get("bottom", ""), int(ctx.px(L.get("size", 200))),
                          L.get("color", "#2b3f9e"), L.get("shape", "circle"), L.get("seed", 0))
    dx, dy = 0, 0
    if "exit" in L:
        ex = anim_state(L["exit"], t, "exit")
        dx, dy, op = ex[0], ex[1], op * ex[4]
    D.place(canvas, st, ctx.px(L["x"] + dx), ctx.px(L["y"] + dy), sc, L.get("rot", 0), op)


def draw_seven(ctx, canvas, shot, L, t):
    if t < L.get("t0", shot["t0"]) or t > L.get("t1", shot["t1"]):
        return
    rg = D.seven_seg(L["text"], int(ctx.px(L.get("h", 40))), L.get("color", "#ff8a1e"))
    D.place(canvas, rg, ctx.px(L["x"]), ctx.px(L["y"]), 1, L.get("rot", 0), L.get("opacity", 0.92))


def draw_leader(ctx, canvas, shot, L, t):
    nums = L["numbers"]
    cur = None
    for i, (tn, n) in enumerate(nums):
        if t >= tn:
            cur = (i, tn, n)
    if cur is None:
        return
    i, tn, n = cur
    tnext = nums[i + 1][0] if i + 1 < len(nums) else L.get("end", tn + 1.8)
    sweep = (t - tn) / max(tnext - tn, 1e-3)
    fr = P.leader_frame(ctx.W, ctx.H, n, sweep, seed=int(t * 24))
    canvas[:] = fr


def draw_label(ctx, canvas, shot, L, t):
    lab = P.camera_label(int(ctx.px(L.get("w", 820))), L.get("title", "SINGLE USE"), L.get("sub", "single-use camera"),
                         str(L.get("count", "27")), L.get("edition", ""))
    dx, dy, sc, rot, op = anim_state(L.get("enter"), t)
    if "exit" in L:
        ex = anim_state(L["exit"], t, "exit")
        dx, dy, op = dx + ex[0], dy + ex[1], op * ex[4]
    D.place(canvas, lab, ctx.px(L["cx"] + dx), ctx.px(L["cy"] + dy), sc, L.get("rot", 0) + rot, op)


def draw_contact(ctx, canvas, shot, L, t):
    """Contact sheet credits: frames light up one by one; active frame enlarges with its credit."""
    frames = L["frames"]
    cols = L.get("cols", 4)
    fw, fh = L.get("fw", 380), L.get("fh", 253)
    gx, gy = L.get("gx", 70), L.get("gy", 200)
    x0 = (DESIGN_W - (cols * fw + (cols - 1) * gx)) / 2
    y0 = L.get("y0", 150)
    S = ctx.S
    # film edge bands behind each row
    rows = (len(frames) + cols - 1) // cols
    BAND = 34
    for r in range(rows):
        yy = y0 + r * (fh + gy)
        band = P.sprocket_strip(ctx.W, int(ctx.px(BAND)), offset=ctx.px(t * 40 * (1 if r % 2 else -1)))
        canvas[int(ctx.px(yy - 48)):int(ctx.px(yy - 48)) + band.shape[0]] = band
        canvas[int(ctx.px(yy + fh + 14)):int(ctx.px(yy + fh + 14)) + band.shape[0]] = band

    def wrap(text, fname, size, maxw):
        """Two lines when a role is wider than its column (split at the space nearest the middle)."""
        if D.text_rgba(text, fname, ctx.px(size)).shape[1] <= ctx.px(maxw) or " " not in text:
            return text
        sp = [k for k, ch in enumerate(text) if ch == " "]
        k = min(sp, key=lambda k: abs(k - len(text) / 2))
        return text[:k] + "\n" + text[k + 1:]
    active = None
    for i, f in enumerate(frames):
        if t >= f["t"]:
            active = i
    if "release" in L and t >= L["release"] + 0.2:
        active = None          # final bar: every frame lit, nothing lifted
    order = [i for i in range(len(frames)) if i != active] + ([active] if active is not None else [])
    for i in order:
        f = frames[i]
        r, c = divmod(i, cols)
        cx = x0 + c * (fw + gx) + fw / 2
        cy = y0 + r * (fh + gy) + fh / 2
        key = (shot["id"], "contact", i)
        patch = ctx.cards.get(key)
        if patch is None:
            crop = plan_crop(f["src"], fw / fh, f.get("zoom", 1.25), f.get("focus", "faces"))
            patch = ctx.sources.get(f["src"]).sample(crop, int(ctx.px(fw)), int(ctx.px(fh)))
            ctx.cards[key] = patch
        lit = t >= f["t"]
        bright = 1.0 if lit else 0.16
        if lit:
            bright += 0.9 * math.exp(-(t - f["t"]) / 0.12)  # flash on reveal
        is_act = i == active
        nxt = frames[i + 1]["t"] if i + 1 < len(frames) else L.get("end", f["t"] + 1.8)
        grow = 0.0
        if is_act:
            grow = D.ease(D.clamp01((t - f["t"]) / 0.24), "out") * (1 - D.ease(D.clamp01((t - nxt + 0.2) / 0.2), "inout"))
        elif lit and active is not None:
            bright *= 0.38
        lx, ly = L.get("loupe", (DESIGN_W / 2, 455))
        cx, cy = cx + (lx - cx) * grow, cy + (ly - cy) * grow
        sc = 1 + (L.get("loupe_scale", 1.85) - 1) * grow
        img = np.clip(patch * bright, 0, 1)
        rgba = np.dstack([img, np.ones(img.shape[:2], np.float32)])
        # frame number in orange edge print
        D.place(canvas, rgba, ctx.px(cx), ctx.px(cy), sc)
        if grow < 0.05:   # edge print sits in the film rebate, not on the credits
            num = D.text_rgba(f"{L.get('first_no', 12) + i}A  ▸", "mono_regular", ctx.px(18), "#ff9a3c")
            D.place(canvas, num, ctx.px(cx - fw / 2 + 60), ctx.px(cy + fh / 2 + 14 + BAND / 2))
        if lit:
            # grease-pencil box around the selected frame
            prog = D.clamp01((t - f["t"]) / 0.35)
            hw, hh = fw * sc / 2 + 10, fh * sc / 2 + 10
            pts = [(cx - hw, cy - hh), (cx + hw, cy - hh + 4), (cx + hw - 3, cy + hh), (cx - hw + 2, cy + hh - 3), (cx - hw, cy - hh - 6)]
            D.draw_marker(canvas, [(x * S, y * S) for x, y in pts], "#e63946", ctx.px(6), prog, 0.95)
            a_ = D.clamp01((t - f["t"]) / 0.15)
            if is_act and grow > 0.02:
                # lifted under the loupe: big credit on a soft dark backing
                nm = D.text_rgba(f["name"].upper(), "anton", ctx.px(26 + 30 * grow), "#ffffff")
                rl = D.text_rgba(wrap(f["role"], "caveat", 30 + 42 * grow, 980), "caveat", ctx.px(30 + 42 * grow), "#f6e7c1", line_gap=0.95)
                ty = cy + fh * sc / 2 + 34
                pw = max(nm.shape[1], rl.shape[1]) / S + 70
                ph = (nm.shape[0] + rl.shape[0]) / S * 0.9 + 30
                panel = np.zeros((int(ctx.px(ph)), int(ctx.px(pw)), 4), np.float32)
                panel[..., 3] = 0.72 * grow
                D.over(canvas, panel, ctx.px(cx - pw / 2), ctx.px(ty - 30))
                D.place(canvas, nm, ctx.px(cx), ctx.px(ty + nm.shape[0] / S * 0.32), 1, 0, a_)
                D.place(canvas, rl, ctx.px(cx), ctx.px(ty + nm.shape[0] / S * 0.75 + rl.shape[0] / S * 0.42), 1, -1.5, a_)
            elif not is_act:
                # resting on the sheet: credit in the black space under the row's lower film band
                ty = y0 + r * (fh + gy) + fh + 14 + BAND + 28
                nm = D.text_rgba(f["name"].upper(), "anton", ctx.px(26), "#ffffff")
                rl = D.text_rgba(wrap(f["role"], "caveat", 30, fw + gx * 0.75), "caveat", ctx.px(30), "#f6e7c1", line_gap=0.92)
                D.place(canvas, nm, ctx.px(cx), ctx.px(ty), 1, 0, a_ * 0.9)
                D.place(canvas, rl, ctx.px(cx), ctx.px(ty + 22 + rl.shape[0] / S * 0.42), 1, -1.5, a_ * 0.9)


def draw_map(ctx, canvas, shot, L, t):
    hl = tuple(L["highlight"]) if "highlight" in L else ("ES", "BE", "NL", "DE", "PL", "TR")
    base, proj = P.base_map(ctx.W, ctx.H, hl, tuple(L["bounds"]) if L.get("bounds") else None)
    img = base.copy()
    S = ctx.S
    if "route" in L:      # a travelled route that draws itself; keys = [[point index, time], ...] (e.g. one per step, on beats)
        R = L["route"]
        pts = np.array([proj(lo, la) for lo, la in R["points"]], np.float32)
        keys = R.get("keys") or [[0, R.get("t0", shot["t0"])], [len(pts) - 1, R.get("t1", shot["t1"])]]
        ki = [k[0] for k in keys]
        kt = [k[1] for k in keys]
        f = float(np.interp(t, kt, ki)) if t >= kt[0] else -1
        if f >= 0 and len(pts) > 1:
            n = int(f)
            part = pts[:n + 1]
            if n + 1 < len(pts):
                part = np.vstack([part, pts[n] + (pts[n + 1] - pts[n]) * (f - n)])
            col = R.get("color", "#c8371f")
            if R.get("dashed", True):
                P.dashed(img, part, col, max(2, ctx.px(R.get("width", 6))), ctx.px(16), ctx.px(10))
            else:
                D.draw_marker(img, part, col, ctx.px(R.get("width", 6)))
            hx, hy = part[-1]
            if R.get("car"):    # a little car (emoji) drives the route head, facing the way it's going
                back = part[max(0, len(part) - 4)]
                car = D.text_rgba(R["car"], "caveat", ctx.px(R.get("car_size", 64)))
                if hx > back[0] + 1:
                    car = car[:, ::-1].copy()      # the emoji car faces left; flip it when driving east
                D.place(img, car, hx, hy - ctx.px(R.get("car_size", 64) * 0.32), 1, 0, 1)
            elif f < len(pts) - 1:
                cv2.circle(img, (int(hx), int(hy)), max(3, int(ctx.px(10))), (0.1, 0.1, 0.12), -1, cv2.LINE_AA)
    for pin in L.get("pins", []):       # a stop: dot pops in on its beat, then its label
        if t < pin["t"]:
            continue
        k = D.clamp01((t - pin["t"]) / 0.18)
        x, y = proj(pin["lon"], pin["lat"])
        cv2.circle(img, (int(x), int(y)), max(3, int(ctx.px(pin.get("r", 12)) * D.ease(k, "back"))), (0.78, 0.2, 0.15), -1, cv2.LINE_AA)
        cv2.circle(img, (int(x), int(y)), max(2, int(ctx.px(pin.get("r", 12)) * 0.45 * D.ease(k, "back"))), (0.98, 0.95, 0.88), -1, cv2.LINE_AA)
        if pin.get("label"):
            lb = D.text_rgba(pin["label"], "caveat", ctx.px(pin.get("size", 46)), "#1f2a44")
            ox, oy = pin.get("off", (0, -48))
            D.place(img, lb, x + ctx.px(ox), y + ctx.px(oy), 1, pin.get("rot", -3), k)
    home = proj(*L["home"]) if "home" in L else None
    # arcs
    for a in L.get("arcs", []):
        if t < a["t"]:
            continue
        p0 = proj(*a.get("from", L["home"]))
        p1 = proj(*a["to"])
        pts = P.arc_points(p0, p1, a.get("bend", 0.22))
        prog = D.clamp01((t - a["t"]) / a.get("dur", 0.55))
        P.dashed(img, pts, a.get("color", "#d1495b"), max(2, ctx.px(5)), ctx.px(16), ctx.px(11), D.ease(prog, "out"))
        if prog < 1:
            head = D.stroke_path(pts, D.ease(prog, "out"))[-1]
            cv2.circle(img, (int(head[0]), int(head[1])), max(3, int(ctx.px(9))), (0.1, 0.1, 0.12), -1, cv2.LINE_AA)
        else:
            k = D.clamp01((t - a["t"] - a.get("dur", 0.55)) / 0.18)
            cv2.circle(img, (int(p1[0]), int(p1[1])), max(3, int(ctx.px(12 * D.ease(k, "back")))), (0.12, 0.12, 0.14), -1, cv2.LINE_AA)
            if "flag" in a:
                st = D.flag_sticker(a["flag"], int(ctx.px(78)), 3)
                ox, oy = a.get("flag_off", (0, -60))
                D.place(img, st, p1[0] + ctx.px(ox), p1[1] + ctx.px(oy), D.ease(k, "back"), a.get("flag_rot", -6), k)
            if "label" in a:
                lb = D.text_rgba(a["label"], "caveat", ctx.px(a.get("size", 46)), "#1f2a44")
                lx, ly = a.get("label_off", (0, 52))
                D.place(img, lb, p1[0] + ctx.px(lx), p1[1] + ctx.px(ly), 1, a.get("label_rot", -3), k)
    # home marker
    if home is not None and t >= L.get("home_t", 0):
        k = D.clamp01((t - L.get("home_t", 0)) / 0.25)
        cv2.circle(img, (int(home[0]), int(home[1])), max(3, int(ctx.px(13))), (0.85, 0.16, 0.2), -1, cv2.LINE_AA)
        if "home_label" in L:
            lb = D.text_rgba(L["home_label"], "caveat", ctx.px(L.get("home_size", 48)), "#b3261e")
            ox, oy = L.get("home_off", (-150, -40))
            D.place(img, lb, home[0] + ctx.px(ox), home[1] + ctx.px(oy), 1, -4, k)
    # slow camera push
    z0, z1 = L.get("zoom", [1.0, 1.06])
    u = D.ease((t - shot["t0"]) / max(shot["t1"] - shot["t0"], 1e-3), "inout")
    z = z0 + (z1 - z0) * u
    fc = L.get("focus_px", (DESIGN_W / 2, DESIGN_H / 2))
    M = cv2.getRotationMatrix2D((ctx.px(fc[0]), ctx.px(fc[1])), 0, z)
    canvas[:] = cv2.warpAffine(img, M, (ctx.W, ctx.H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def draw_fill(ctx, canvas, shot, L, t):
    if L.get("paper"):
        canvas[:] = D.paper_texture(ctx.W, ctx.H, L.get("color", "#f3eee2"))
    else:
        canvas[:] = np.array(hex2rgb(L.get("color", "#000000"))[:3], np.float32)
    if L.get("grid"):                        # sketchbook page: dot grid or squared paper
        canvas[:] = G.page_grid(canvas, ctx.S, L["grid"])


def _enter_exit(L, t):
    dx, dy, sc, rot, op = anim_state(L.get("enter"), t)
    if "exit" in L:
        ex = anim_state(L["exit"], t, "exit")
        dx, dy, sc, rot, op = dx + ex[0], dy + ex[1], sc * ex[2], rot + ex[3], op * ex[4]
    return dx, dy, sc, rot, op


def draw_video(ctx, canvas, shot, L, t):
    """A clip from photos/ (e.g. the terrace hand-dance), graded like the phone shots."""
    box = L.get("box", [0, 0, DESIGN_W, DESIGN_H])
    te = layer_time(shot, L, t)
    fr = V.video_frame(L["src"], L.get("start", 0.0) + (te - shot["t0"]) * L.get("speed", 1.0))
    if L.get("grade", True):
        from .grade import grade_array
        fr = grade_array(fr, ctx.sources.preset, "phone", {"wb": 0.3})
    h, w = fr.shape[:2]
    bw, bh = int(round(ctx.px(box[2]))), int(round(ctx.px(box[3])))
    z = L.get("zoom", 1.0)
    z = z if isinstance(z, (list, tuple)) else [z, z]
    u = D.ease((te - shot["t0"]) / max(shot["t1"] - shot["t0"], 1e-3), "inout")
    zz = z[0] + (z[1] - z[0]) * u
    asp = bw / bh
    cw = min(w, h * asp) / zz
    ch = cw / asp
    fx, fy = L.get("focus", (0.5, 0.5))
    x0 = np.clip(fx * w - cw / 2, 0, w - cw)
    y0 = np.clip(fy * h - ch / 2, 0, h - ch)
    patch = cv2.resize(fr[int(y0):int(y0 + ch), int(x0):int(x0 + cw)], (bw, bh), interpolation=cv2.INTER_CUBIC)
    if L.get("look"):
        patch = np.clip(LK.apply(patch, L["look"], ctx.S, t), 0, 1)
    dx, dy, sc, rot, op = _enter_exit(L, t)
    rgba = np.dstack([patch, np.ones(patch.shape[:2], np.float32)])
    if L.get("feather"):
        rgba[..., 3] *= G.feather_mask(rgba.shape[0], rgba.shape[1], int(ctx.px(L["feather"])))
    if L.get("mask"):
        mk = L["mask"]
        rgba[..., 3] *= G.shape_mask(mk.get("kind", "arch"), rgba.shape[0], rgba.shape[1], mk.get("point", 0.5))
    if L.get("border"):
        bpx = max(1, int(ctx.px(L["border"].get("px", 10))))
        big = np.ones((bh + 2 * bpx, bw + 2 * bpx, 4), np.float32)
        big[..., :3] = np.array(hex2rgb(L["border"].get("color", "#f5f1e8"))[:3], np.float32)
        big[bpx:bpx + bh, bpx:bpx + bw] = rgba
        rgba = big
    if L.get("shadow"):
        rgba = D.shadow_of(rgba, blur=ctx.px(14), offset=(ctx.px(6), ctx.px(10)), strength=0.5)
    if L.get("blend", "normal") != "normal":      # e.g. a clip painted onto a sketchbook page (multiply)
        G.place_blend(canvas, rgba, ctx.px(box[0] + box[2] / 2 + dx), ctx.px(box[1] + box[3] / 2 + dy), sc,
                      L.get("rot", 0) + rot, op * L.get("opacity", 1.0), L["blend"])
        return
    D.place(canvas, rgba, ctx.px(box[0] + box[2] / 2 + dx), ctx.px(box[1] + box[3] / 2 + dy), sc, L.get("rot", 0) + rot, op)


def draw_rect(ctx, canvas, shot, L, t):
    """Flat colour block (poster panels, roll-call backdrops)."""
    w, h = max(1, int(ctx.px(L["w"]))), max(1, int(ctx.px(L["h"])))
    rgba = np.ones((h, w, 4), np.float32)
    rgba[..., :3] = np.array(hex2rgb(L.get("color", "#ffd400"))[:3], np.float32)
    rgba[..., 3] = L.get("alpha", 1.0)
    if L.get("shadow"):
        rgba = D.shadow_of(rgba, blur=ctx.px(12), offset=(ctx.px(6), ctx.px(10)), strength=0.45)
    dx, dy, sc, rot, op = _enter_exit(L, t)
    D.place(canvas, rgba, ctx.px(L["x"] + L["w"] / 2 + dx), ctx.px(L["y"] + L["h"] / 2 + dy), sc, L.get("rot", 0) + rot, op)


def draw_cassette(ctx, canvas, shot, L, t):
    tape = V.cassette(int(ctx.px(L.get("w", 1000))))
    dx, dy, sc, rot, op = _enter_exit(L, t)
    D.place(canvas, tape, ctx.px(L["cx"] + dx), ctx.px(L["cy"] + dy), sc, L.get("rot", 0) + rot, op)


def draw_vinyl(ctx, canvas, shot, L, t):
    """A 7" single that slides out of its sleeve and spins (the sleeve is a photo layer drawn after it)."""
    d = int(ctx.px(L.get("d", 600)))
    disc = V.vinyl_disc(d, L.get("label", "#f4c430"), L.get("text", "SIDE A\n45 RPM"))
    ang = -(t - shot["t0"]) * L.get("spin", 160)
    disc = D.transform_rgba(disc, 1.0, ang)
    pad = (disc.shape[0] - d) // 2
    disc = disc[pad:pad + d, pad:pad + d].copy() if pad > 0 else disc
    disc[..., :3] = np.clip(disc[..., :3] + V.vinyl_sheen(disc.shape[0])[:disc.shape[0], :disc.shape[1]], 0, 1)
    dx, dy, sc, rot, op = _enter_exit(L, t)
    D.place(canvas, D.shadow_of(disc, blur=ctx.px(10), offset=(ctx.px(5), ctx.px(8)), strength=0.5),
            ctx.px(L["cx"] + dx), ctx.px(L["cy"] + dy), sc, 0, op)


def draw_sticker(ctx, canvas, shot, L, t):
    """Die-cut sticker (emoji or words) slapped on at L['t']: big -> settle, like a stamp."""
    if t < L.get("t", shot["t0"]) or t > L.get("t1", 1e9):
        return
    if L.get("img"):          # a photo cut-out (cache/cutouts/<name>.png from tools/cutout.py); size = height
        path = L["img"] if os.path.isabs(L["img"]) else os.path.join(CACHE, L["img"])
        st = V.image_sticker(path, int(ctx.px(L.get("size", 220))), L.get("border", 0.05), L.get("border_color", "#ffffff"))
    else:
        st = V.sticker(L["text"], L.get("font", "anton"), int(ctx.px(L.get("size", 160))), L.get("color", "#141414"),
                       L.get("border", 0.09), L.get("border_color", "#ffffff"))
    _, _, sc, _, op = anim_state({"t": L.get("t", shot["t0"]), "dur": 0.14, "type": "thump"}, t)
    follow = L.get("follow")
    x, y = L.get("x", DESIGN_W / 2), L.get("y", DESIGN_H / 2)
    if "move" in L:                    # keyframed offset [[t, dx, dy], ...]
        mx, my = G.move_at(L["move"], t)
        x, y = x + mx, y + my
    if follow:   # sit on a face (or a body part offset from it) in another layer
        PL = shot["layers"][follow["layer"]]
        crop, box = photo_crop_at(ctx, shot, PL, t)
        r = face_on_screen(PL["src"], crop, box, follow.get("face", "biggest"))
        if r:
            ox, oy = follow.get("off", (0, 0))
            x, y = r[0] + r[2] / 2 + ox * r[2], r[1] + r[3] / 2 + oy * r[3]
    D.place(canvas, st, ctx.px(x), ctx.px(y), sc * L.get("scale", 1.0), L.get("rot", 0), op)


def draw_osd(ctx, canvas, shot, L, t):
    """VCR on-screen display element inside a shot (e.g. a blinking REC)."""
    if t < L.get("t0", shot["t0"]) or t > L.get("t1", shot["t1"]):
        return
    if L.get("blink") and int((t - L.get("t0", shot["t0"])) / L["blink"]) % 2 == 1:
        return
    S = ctx.S
    size = L.get("size", 40)
    col = hex2rgb(L.get("color", "#ffffff"))[:3]
    x, y = L["x"], L["y"]
    if L.get("icon"):
        V.osd_icon(canvas, L["icon"], x * S, y * S, size * S, col)
        x += size * 1.25
    if L.get("text"):
        tx = D.text_rgba(L["text"], "mono", ctx.px(size * 0.95), L.get("color", "#ffffff"), shadow=ctx.px(3))
        D.over(canvas, tx, ctx.px(x) - ctx.px(size * 0.3), ctx.px(y) - tx.shape[0] / 2)


def _sample(ctx, src, aspect, w, h, zoom=1.1):
    key = ("sample", src, w, h, zoom)
    if key not in ctx.cards:
        crop = plan_crop(src, aspect, zoom, "faces")
        ctx.cards[key] = ctx.sources.get(src).sample(crop, w, h)
    return ctx.cards[key]


LAYERS = {
    "photo": draw_photo, "polaroid": draw_polaroid, "strip": draw_strip, "grid": draw_grid, "text": draw_text,
    "marker": draw_marker_layer, "flag": draw_flag, "stamp": draw_stamp, "seven": draw_seven,
    "leader": draw_leader, "label": draw_label, "contact": draw_contact, "map": draw_map, "fill": draw_fill,
    "doodle": draw_doodle, "bubble": draw_bubble,
    "video": draw_video, "rect": draw_rect, "cassette": draw_cassette, "vinyl": draw_vinyl, "sticker": draw_sticker,
    "osd": draw_osd,
    "type_mask": lambda ctx, c, sh, L, t: G.draw_type_mask(ctx, c, sh, L, t, photo_crop_at),
    "shape": lambda ctx, c, sh, L, t: G.draw_shape(ctx, c, sh, L, t, _enter_exit),
    "slices": lambda ctx, c, sh, L, t: G.draw_slices(ctx, c, sh, L, t, photo_crop_at),
    "lyric_type": G.draw_lyric_type,
    "filmstrip": lambda ctx, c, sh, L, t: G.draw_filmstrip(ctx, c, sh, L, t, lambda s_, a_, w_, h_, z_: _sample(ctx, s_, a_, w_, h_, z_)),
}


def render_shot(ctx, shot, t, _trail=True):
    if _trail and shot.get("echo"):         # motion trails: the shot's own recent past, lighten-blended
        e = shot["echo"]
        acc = render_shot(ctx, shot, t, False)
        for k in range(1, e.get("n", 3) + 1):
            tk = t - k * e.get("dt", 0.07)
            if tk < shot["t0"]:
                break
            acc = np.maximum(acc, render_shot(ctx, shot, tk, False) * e.get("decay", 0.6) ** k)
        return acc
    if shot.get("stutter"):                  # motion advances in steps (e.g. an 8th or 16th note)
        q = shot["stutter"]
        t = shot["t0"] + math.floor((t - shot["t0"]) / q) * q
    canvas = np.zeros((ctx.H, ctx.W, 3), np.float32)
    bg = shot.get("bg", "#000000")
    if bg == "paper":
        canvas[:] = D.paper_texture(ctx.W, ctx.H)
    elif bg != "#000000":
        canvas[:] = np.array(hex2rgb(bg)[:3], np.float32)
    post = []
    for k, L in enumerate(shot["layers"]):
        L.setdefault("_k", k)
        if "show" in L and not (L["show"][0] <= t < L["show"][1]):
            continue
        if L.get("post"):
            post.append(L)
            continue
        LAYERS[L["type"]](ctx, canvas, shot, L, t)
    for fx in shot.get("fx", []):
        apply_shot_fx(ctx, canvas, shot, fx, t)
    for L in post:                          # drawn above the shot fx (e.g. a title over a kaleidoscope)
        LAYERS[L["type"]](ctx, canvas, shot, L, t)
    return canvas


def apply_shot_fx(ctx, canvas, shot, fx, t):
    typ = fx["type"]
    if G.shot_fx(ctx, canvas, shot, fx, t):
        return
    if typ == "flash_on":  # white pops on musical events within the shot
        v = ctx.music.pulse(fx.get("on", "cymbals"), t, fx.get("decay", 0.09), fx.get("min", 0.5), window=(shot["t0"] - 0.02, shot["t1"]))
        if v > 0.01:
            D.screen(canvas, np.ones(3, np.float32), min(1, v * fx.get("amount", 0.5)))
    elif typ == "freeze_look":  # during freeze intervals: desaturate + slight fade
        for a, b in shot.get("freeze", []):
            if a <= t < b:
                g = canvas.mean(-1, keepdims=True)
                canvas[:] = (g + (canvas - g) * 0.35) * 0.92 + 0.04
    elif typ == "rgb_split":
        v = ctx.music.pulse(fx.get("on", "snares"), t, fx.get("decay", 0.08), fx.get("min", 0.5),
                            window=(shot["t0"] - 0.02, shot["t1"]))
        sh = int(ctx.px(fx.get("amount", 14)) * v)
        if sh > 0:
            canvas[..., 0] = np.roll(canvas[..., 0], sh, axis=1)
            canvas[..., 2] = np.roll(canvas[..., 2], -sh, axis=1)
    elif typ == "vhs":   # home-video look; optional ramp in/out
        a = fx.get("amount", 1.0)
        if "ramp" in fx:
            r0, r1, a0, a1 = fx["ramp"]
            a = a0 + (a1 - a0) * D.ease((t - r0) / max(r1 - r0, 1e-3), "inout")
        V.vhs(canvas, t, ctx.S, a, fx.get("band", True))
    elif typ == "static":
        if fx["t0"] <= t < fx["t1"]:
            V.static(canvas, t, fx.get("amount", 1.0))
    elif typ == "wobble":  # tape slowing down: picture sags, darkens and drifts
        if t >= fx["t0"]:
            u = D.clamp01((t - fx["t0"]) / fx.get("dur", 1.0))
            H, W = canvas.shape[:2]
            img = canvas.copy()
            for r in range(0, H, 4):
                img[r:r + 4] = np.roll(canvas[r:r + 4], int(ctx.px(30) * u * math.sin(r / H * 9 + t * 20)), axis=1)
            g = img.mean(-1, keepdims=True)
            canvas[:] = (g + (img - g) * (1 - 0.8 * u)) * (1 - fx.get("dark", 0.85) * u ** 1.5)


# ------------------------------------------------------------ transitions & finishing
def blend_transition(ctx, prev_img, cur_img, tr, u, t):
    typ = tr["type"]
    if typ == "dissolve":
        e = D.ease(u, "inout")
        return prev_img * (1 - e) + cur_img * e
    if typ in ("dip_white", "dip_black"):
        col = 1.0 if typ == "dip_white" else 0.0
        if u < 0.5:
            k = D.ease(u * 2, "inout")
            return prev_img * (1 - k) + col * k
        k = D.ease((u - 0.5) * 2, "inout")
        return col * (1 - k) + cur_img * k
    if typ == "whip":
        e = D.ease(u, "inout")
        W = ctx.W
        off = int(e * W)
        out = np.empty_like(cur_img)
        out[:, :W - off] = prev_img[:, off:]
        out[:, W - off:] = cur_img[:, :off]
        k = int(ctx.px(90) * math.sin(math.pi * u)) * 2 + 1
        if k > 3:
            out = cv2.blur(out, (k, 1))
        return out
    if typ == "burn":
        e = math.sin(math.pi * u)
        base = prev_img if u < 0.5 else cur_img
        H, W = base.shape[:2]
        y, x = np.ogrid[0:H, 0:W]
        cx, cy = W * tr.get("cx", 0.85), H * tr.get("cy", 0.2)
        r = np.sqrt(((x - cx) / W) ** 2 + ((y - cy) / H) ** 2)
        m = np.clip(1.4 * e - r * 1.6, 0, 1)[..., None]
        burn = np.array([1.0, 0.62, 0.28], np.float32)
        return np.clip(base * (1 - m) + (burn + (1 - burn) * m) * m, 0, 1)
    if typ == "glitch":
        return V.glitch(prev_img, cur_img, u, ctx.S, tr.get("seed", int(t * 10)))
    out = G.transition(typ, prev_img, cur_img, u, ctx.S, tr, t)
    if out is not None:
        return out
    return cur_img


def finish(ctx, img, t, fidx):
    F = ctx.finish
    H, W = img.shape[:2]
    # global flashes
    for f in ctx.flashes:
        ft, amt = f[0], f[1]
        dec = f[2] if len(f) > 2 else 0.18
        if ft - 0.02 <= t < ft + 5 * dec:
            k = amt * math.exp(-max(0, t - ft) / dec)
            if k > 0.01:
                D.screen(img, np.ones(3, np.float32), min(1, k))
    if F.get("halation", 0) > 0:
        small = cv2.resize(img, (W // 6, H // 6), interpolation=cv2.INTER_AREA)
        l = small.mean(-1)
        hl = np.clip((l - 0.75) / 0.25, 0, 1)
        glow = cv2.GaussianBlur(hl, (0, 0), 3.0)
        glow = cv2.resize(glow, (W, H), interpolation=cv2.INTER_LINEAR)[..., None]
        img += glow * np.array([1.0, 0.4, 0.18], np.float32) * F["halation"]
    if F.get("weave", 0) > 0:
        rng = np.random.default_rng(fidx * 7 + 1)
        dx, dy = rng.normal(0, F["weave"] * ctx.S, 2)
        M = np.float32([[1, 0, dx], [0, 1, dy]])
        img = cv2.warpAffine(img, M, (W, H), borderMode=cv2.BORDER_REFLECT)
    if F.get("flicker", 0) > 0:
        rng = np.random.default_rng(fidx * 13 + 5)
        img *= 1 + rng.normal(0, F["flicker"])
    if F.get("vignette", 0) > 0:
        img *= D.vignette(W, H, F["vignette"])
    if F.get("grain", 0) > 0:
        bank = D.grain_bank(W, H)
        g = bank[fidx % len(bank)]
        ox, oy = (fidx * 3) % 4, (fidx * 5) % 4
        g = g[oy:oy + H, ox:ox + W].astype(np.float32)
        l = img.mean(-1, keepdims=True)
        wgt = 0.45 + 2.2 * l * (1 - l)  # grain strongest in mids
        img += g[..., None] * F["grain"] * wgt
    for ov in ctx.edl.get("overlays", []):
        draw_overlay(ctx, img, ov, t)
    return np.clip(img, 0, 1)


def draw_overlay(ctx, img, ov, t):
    if t < ov.get("t0", 0) or t > ov.get("t1", 1e9):
        return
    if ov["type"] == "counter":
        n = None
        for ts, v in ov["steps"]:
            if t >= ts:
                n = v
        if n is None:
            return
        txt = f"{n:02d}" if isinstance(n, int) else str(n)
        rg = D.seven_seg(txt, int(ctx.px(ov.get("h", 44))), ov.get("color", "#ff8a1e"))
        lab = D.text_rgba(ov.get("label", "EXP"), "mono", ctx.px(16), ov.get("color", "#ff8a1e"))
        x, y = ctx.px(ov.get("x", 1800)), ctx.px(ov.get("y", 70))
        D.place(img, rg, x, y, 1, 0, 0.9)
        D.place(img, lab, x, y + ctx.px(ov.get("h", 44) * 0.85), 1, 0, 0.75)
    elif ov["type"] == "letterbox":
        hh = int(ctx.px(ov.get("h", 140)))
        img[:hh] = 0
        img[ctx.H - hh:] = 0
    elif ov["type"] == "osd":   # VCR display: mode icon + word top-left, tape counter beside it
        if any(a <= t < b for a, b in ov.get("hide", [])):
            return
        state = None
        for st in ov["states"]:
            if t >= st[0]:
                state = st
        if state is None:
            return
        S = ctx.S
        x, y, size = ov.get("x", 70), ov.get("y", 66), ov.get("size", 30)
        op = ov.get("opacity", 0.9)
        icon, word = state[1], state[2]
        if not (len(state) > 3 and state[3] and int((t - state[0]) / 0.5) % 2 == 1):   # optional blink
            V.osd_icon(img, icon, x * S, y * S, size * S, (1, 1, 1), op)
            tx = D.text_rgba(word, "mono", ctx.px(size * 0.95), "#ffffff", shadow=ctx.px(3))
            D.over(img, tx, ctx.px(x + size * 1.2) - ctx.px(size * 0.3), ctx.px(y) - tx.shape[0] / 2, op)
        if "counter_t0" in ov and t >= ov["counter_t0"]:
            s = max(0.0, t - ov["counter_t0"])
            txt = f"SP  {int(s // 3600)}:{int(s // 60) % 60:02d}:{int(s) % 60:02d}"
            tx = D.text_rgba(txt, "mono", ctx.px(size * 0.8), "#ffffff", shadow=ctx.px(3))
            D.over(img, tx, ctx.px(ov.get("cx", 1850)) - tx.shape[1], ctx.px(y) - tx.shape[0] / 2, op)


def render_frame(ctx, t, fidx):
    shot = ctx.shot_at(t)
    img = render_shot(ctx, shot, t)
    i = shot["_i"]
    # incoming transition of this shot (centred on t0 unless align == "start")
    tr = shot.get("in")
    if tr and tr.get("type", "cut") not in ("cut", "flash") and i > 0:
        d = tr.get("dur", 0.3)
        a = tr.get("align", "center")
        start = shot["t0"] - (d / 2 if a == "center" else 0)
        if start <= t < start + d:
            prev = render_shot(ctx, ctx.shots[i - 1], t)
            img = blend_transition(ctx, prev, img, tr, (t - start) / d, t)
    # transition of the *next* shot that starts before its t0 (centred)
    if i + 1 < len(ctx.shots):
        nx = ctx.shots[i + 1]
        tr2 = nx.get("in")
        if tr2 and tr2.get("type", "cut") not in ("cut", "flash") and tr2.get("align", "center") == "center":
            d = tr2.get("dur", 0.3)
            start = nx["t0"] - d / 2
            if start <= t < nx["t0"]:
                cur = render_shot(ctx, nx, t)
                img = blend_transition(ctx, img, cur, tr2, (t - start) / d, t)
    if tr and tr.get("type") == "flash":
        k = tr.get("amount", 1.0) * math.exp(-max(0, t - shot["t0"]) / tr.get("dur", 0.16))
        if k > 0.01:
            D.screen(img, np.ones(3, np.float32), min(1, k))
    return finish(ctx, img, t, fidx)
