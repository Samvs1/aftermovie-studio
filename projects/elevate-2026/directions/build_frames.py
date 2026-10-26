"""Style frames for the Sweet Disposition directions (A cinematic Super 8, B kinetic knockout type, C riso tour zine).

Run: python tools/studio.py run elevate ../projects/elevate-2026/directions/build_frames.py
then: python tools/studio.py stills elevate sd_directions <times printed below>
Mock-ups only: photos may repeat across directions; the film's builder enforces no-reuse.
"""
import json, os, sys
sys.path.insert(0, os.environ.get("AM_TOOLS") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "tools"))
os.environ.setdefault("AM_PROJECT", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from am.common import CACHE  # noqa: E402
from am.kit import Film, W, H  # noqa: E402

A = json.load(open(os.path.join(CACHE, "audio", "sweet_disposition.json"), encoding="utf-8"))
F = Film("sd_directions", "Sweet Disposition: directions", "music/The Temper Trap - Sweet Disposition (Official Video).mp3",
         "sweet_disposition", [(0.0, A["duration"], 0.0)], tail=0.0)
F.used = {}                                    # mock-ups: allow the same photo in different directions
F.use = lambda src, where: src                 # noqa: E731
GOLD = {"name": "faded", "amount": 0.8}
SEG = 3.0
frames, t = {}, 1.0
F.shot(0.0, 1.0, [F.wall("#000000")], sync="pre")


def shot(key, layers, fx=None, **kw):
    global t
    s = F.shot(t, t + SEG, layers, sync=key, **kw)
    if fx:
        s["fx"] = fx
    frames[key] = round(t + SEG * 0.7, 3)
    t += SEG


# ---- A: cinematic Super 8 -------------------------------------------------------------------------------
shot("a_1", [F.full("1000052753.jpg", "A", (1.04, 1.1), look=GOLD),
             F.text("a moment", W / 2, 905, 0, 9999, 52, "playfair_italic", "#f6ead2", anim="fade", dur=0.01, shadow=4, fade_out=0)],
     fx=[{"type": "light_leak", "amount": 0.42, "seed": 5}, {"type": "letterbox", "h": 138}])
shot("a_2", [F.full("1000052394.jpg", "A", (1.08, 1.12), look={"name": "faded", "amount": 0.5}),
             F.full("1000053175.jpg", "A", (1.0, 1.0), box=[760, -120, 1300, 1320], blend="screen", opacity=0.6, feather=380),
             F.shape("rect", 960, 1000, 1920, 160, "#000000", alpha=0.45),
             F.text("won't stop 'til it's over", W / 2, 985, 0, 9999, 70, "playfair_italic", "#fff3dc", anim="fade", dur=0.01,
                    shadow=5, fade_out=0)],
     fx=[{"type": "light_leak", "amount": 0.22, "seed": 9, "colors": ["#ff9a3c", "#ffd29a", "#ff6f91", "#ffe0b0"]}])

# ---- B: kinetic knockout type -----------------------------------------------------------------------------
shot("b_1", [F.wall("#0e0e0e"),
             F.type_mask("1000052608.jpg", "B", "A KISS", size=560, y=560, look={"name": "bw", "contrast": 1.45}, zoom=[1.1, 1.1],
                         focus="faces", fade=0),
             F.text("04 / 08", 120, 120, 0, 9999, 40, "mono", "#e63946", anchor="lm", fade_out=0),
             F.text("a kiss, a cry, our rights, our wrongs", 120, 980, 0, 9999, 34, "mono", "#8a8a8a", anchor="lm", fade_out=0)])
shot("b_2", [F.full("1000053636.jpg", "B", (1.05, 1.05), look={"name": "bw", "contrast": 1.5, "lift": -0.08}),
             F.shape("rect", 960, 540, 1920, 1080, "#000000", alpha=0.35),
             F.shape("rect", 228, 560, 22, 600, "#e63946"),
             F.lyric_type([{"w": "WON'T", "t": 0}, {"w": "STOP", "t": 0}, {"w": "'TIL", "t": 0}, {"w": "IT'S", "t": 0}, {"w": "OVER", "t": 0}],
                          x=700, y=560, mode="stack", font="anton", size=190, maxw=900, color="#ffffff", line_gap=0.92, accent="#e63946")])

# ---- C: riso tour zine --------------------------------------------------------------------------------------
shot("c_1", [F.wall("#f2ede4", True),
             F.full("1000052092.jpg", "C", (1.0, 1.0), box=[120, 120, 520, 700], rot=-6, edge="torn", seed=4, shadow=True),
             F.full("img0013.jpg", "C", (1.0, 1.0), box=[600, 330, 760, 510], rot=3, edge="torn", seed=7, shadow=True),
             F.full("1000052743.jpg", "C", (1.0, 1.0), box=[1360, 90, 430, 600], rot=5, edge="torn", seed=9, shadow=True),
             F.text("No. 6", 1540, 860, 0, 9999, 230, "anton", "#141414", rot=-4, fade_out=0),
             F.text("SIX COUNTRIES\nONE SUMMER", 520, 940, 0, 9999, 92, "anton", "#141414", line_gap=0.88, rot=-2, fade_out=0)],
     fx=[{"type": "look", "look": {"name": "riso", "ink1": "#ff48b0", "ink2": "#0078bf", "offset": 4}}])
shot("c_2", [F.full("1000052042.jpg", "C", (1.15, 1.25)),
             F.shape("circle", W / 2, 540, 620, color="#f2ede4", post=True),
             F.text("WON'T\nSTOP", W / 2, 545, 0, 9999, 190, "anton", "#141414", line_gap=0.82, fade_out=0, post=True)],
     fx=[{"type": "kaleido", "n": 8, "spin": 0.4},
         {"type": "look", "look": {"name": "riso", "ink1": "#ff48b0", "ink2": "#00a95c", "offset": 6}}])

F.B.edl["meta"]["duration"] = round(t + 0.5, 3)
F.duration = F.B.edl["meta"]["duration"]
F.save()
print("STILLS " + ",".join(str(v) for v in frames.values()))
json.dump(frames, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "frames.json"), "w"))
