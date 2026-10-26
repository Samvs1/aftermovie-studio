"""Motion prototype of the Souq-pop opening (title + first verse lines) to check the language in motion. Mock-up only."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import build as B  # noqa: E402
from build import F, bar, bt, sung, ph, vc, framed, framed_clip, backdrop, field, slap, arabic  # noqa: E402
from build import RED, GREEN, WHITE, SAFFRON, TEAL, INK, PINK, BLUE, CREAM, MAROON, W, H  # noqa: E402

F.use = lambda src, where: src      # noqa: E731  (prototype)
F.version = "proto_intro"
F.B.edl["meta"]["version"] = "proto_intro"

# ---- intro, bars 0-3: the JBL on the dash starts the song; the title builds on the beats
t0 = 0.0
L = [backdrop("stripes", (TEAL, WHITE), cell=96, scroll=[24, 0]),
     F.sticker(bar(0), 960, 470, 520, img="cutouts/jbl.png", rot=-6)]
L += F.block("OMAN", 560, 250, bar(1), bar(4), RED, WHITE, "anton", 210, rot=-3)
L += F.block(arabic("عمان"), 1390, 260, bt(1, 2), bar(4), GREEN, WHITE, "arabic_heavy", 150, rot=3)
L += F.tag("INSHALLAH  ·  " + "15 DAYS", 960, 860, bar(2), bar(4), 40, rot=-2)
L += F.tag("SAM + TOM  ·  31.03 — 14.04.2024", 1180, 960, bt(2, 2), bar(4), 36, rot=2, bg=SAFFRON)
F.shot(t0, bar(4), L, sync="intro: title on the beats")
for t in (bar(0), bar(1), bt(1, 2), bar(2), bt(2, 2)):
    slap(t)

# ---- bar 4 "Hope when you take that jump": the cheap flight
L = [field(SAFFRON), backdrop("chevron", (SAFFRON, "#e8940c"), cell=120, scroll=[40, 0])]
L += framed(6, 760, 540, (1000, 760), bar(4), "blue")
L += F.tag("CHEAPEST FLIGHT TO MUSCAT: BOOKED", 1360, 250, sung("Hope", 4), bar(6), 38, rot=4)
L += F.tag("WHY SO CHEAP? (DIDN'T CHECK)", 1330, 860, sung("You", 5), bar(6), 38, rot=-3, bg=WHITE)
F.shot(bar(4), bar(6), L, sync="bar 4: take that jump = booking")
slap(sung("Hope", 4))
slap(sung("You", 5))

# ---- bar 6: the reveal
L = [field(RED)]
L += framed(1, 960, 600, (1300, 700), bar(6), "green")
L += F.block("RAMADAN", 700, 180, bar(6), bar(8), INK, WHITE, "anton", 170, rot=-4)
L += F.block(arabic("رمضان"), 1400, 190, bt(6, 1), bar(8), WHITE, INK, "arabic_heavy", 120, rot=3)
L += F.tag("RESTAURANTS: CLOSED UNTIL SUNSET", 960, 990, bt(6, 2), bar(8), 38, rot=-2)
F.shot(bar(6), bar(8), L, sync="bar 6: Ramadan reveal")
slap(bar(6), -18)

# ---- bar 8 "water rises" / bar 9.5 "built a wall": Sam then Tom on the corniche wall
L = [backdrop("stripes", (BLUE, WHITE), cell=80, prot=90.0)]
L += framed(16, 560, 560, (760, 620), bar(8), "teal", rot=-2)
L += framed(19, 1380, 540, (520, 740), sung("You", 9), "red", rot=2)
L += F.tag("MUTTRAH CORNICHE  ·  DAY 3", 960, 1000, bt(8, 2), bar(10), 36, rot=-1)
F.shot(bar(8), bar(10), L, sync="bar 8-9: the wall")
F.B.edl["meta"]["duration"] = bar(10) + 0.5
F.duration = F.B.edl["meta"]["duration"]
F.save(os.path.join(os.path.dirname(os.path.abspath(__file__)), "proto_intro_edl.json"))
