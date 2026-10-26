"""Engine check for the Souq-pop helpers (F.frame, F.tag, F.block, F.sticker img, pattern scroll). Mock-up only."""
import json, os, shutil, subprocess, sys
sys.path.insert(0, os.environ.get("AM_TOOLS") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "tools"))
os.environ.setdefault("AM_PROJECT", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from am.common import CACHE, OUT, arabic, project  # noqa: E402
from am.kit import Film, W, H  # noqa: E402

TOOLS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "tools")
P = project()
IDX = dict(l.rstrip("\n").split("\t") for l in open(os.path.join(CACHE, "sheets", "index.txt"), encoding="utf-8") if "\t" in l)
ph = lambda n: IDX[str(n)]  # noqa: E731
RED, GREEN, WHITE, SAFFRON, TEAL, INK = "#d7261e", "#0f8a4a", "#fbf6ea", "#f2a516", "#13a3a1", "#141414"

F = Film("souq_test", "test", f"music/{P['song']['file']}", P["song"]["slug"], [(52.9, 307.0, 0.0)],
         grade={"preset": "punchy", "overrides": {}}, finish={"grain": 0.006, "vignette": 0.0, "halation": 0.0}, tail=0.0)
F.use = lambda src, where: src  # noqa: E731
F.shot(0.0, 1.0, [F.wall("#000000")], sync="pre")
t = 1.0
L = [F.shape("pattern", 960, 540, W, H, motif="chevron", cell=110, colors=(SAFFRON, "#e8940c"), scroll=[60, 0])]
L += F.frame(ph(168), "test", 640, 560, (560, 760), t, motif="diamond", colors=(GREEN, WHITE, RED), border=56)
L += F.frame(ph(166), "test", 1380, 470, (700, 520), t + 0.25, motif="star8", colors=(RED, WHITE, GREEN), border=50, rot=3)
L += [F.sticker(t + 0.5, 1040, 300, 300, img="cutouts/suntop.png", rot=-14)]
L += F.tag("ANTI-RAMADAN PITSTOP · DAY 9", 1360, 900, t + 0.75, t + 3, 30, rot=-3)
L += F.block(arabic("رمضان"), 420, 150, t + 1.0, t + 3, TEAL, WHITE, "arabic_heavy", 96, rot=-4)
CL = json.load(open(os.path.join(CACHE, "sheets", "vgrid", "info.json")))
v44 = [c[1] for c in CL if c[0] == 44][0]
L2 = [F.shape("pattern", 960, 540, W, H, motif="stripes", cell=90, colors=(TEAL, WHITE))]
L2 += F.vframe(v44, "test", 960, 540, (520, 900), t + 3.0, start=2.0, motif="star8", colors=(RED, WHITE, GREEN), border=40)
F.shot(t, t + 3.0, L, sync="test")
F.shot(t + 3.0, t + 6.0, L2, sync="clip")
F.B.edl["meta"]["duration"] = 7.5
F.duration = 7.5
edl = os.path.join(os.path.dirname(os.path.abspath(__file__)), "souq_test_edl.json")
F.save(edl)
subprocess.run([sys.executable, "-W", "ignore", os.path.join(TOOLS, "render.py"), edl, "--width", "1920", "--stills", "1.05,3.2,5.5"], check=True)
for s in ("1.050", "3.200", "5.500"):
    shutil.copy(os.path.join(CACHE, "render", f"souq_test_{float(s):07.3f}.png"), os.path.join(OUT, "directions", f"_test_{s}.png"))
