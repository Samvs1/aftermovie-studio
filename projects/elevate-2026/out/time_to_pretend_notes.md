# THE BAD BANANAS: FATED TO PRETEND — notes (v2, FINAL)

**Song:** MGMT, *Time to Pretend* (100.996 BPM, click-steady grid) · **Length:** 2:53 (song edit 2:35 + a silent liner-notes thank-you) · **Format:** 1920×1080, 30 fps
**Tone:** jokey rockumentary on a home-video tape, caption-heavy. The eight Bad Bananas are a band that can't play any instruments; MGMT's rock-star lyrics get hijacked line by line. Grade `punchy`.

**Status:** Sam approved the v2 preview ("Its good! Ship it").
- `out/time_to_pretend.mp4`: the 1080p master (716 MB)
- `out/time_to_pretend_share.mp4`: 720p, 26 MB, for the group chat

QA was re-run on the master and every gate passes (same numbers as below).

## What changed after v1
| Sam's feedback | v2 |
|---|---|
| captions come slightly **too late** (rough/raw, prime, models/wives, "many more") | The LRC word times were spread evenly across each line, including held notes, so inside a line they ran **~0.6 s late** (up to a whole bar on "vision"/"fun"). New `tools/align_words.py` force-aligns every word on the Demucs vocal stem; its line starts agree with LRC to ~0.1 s. Every lyric cue now lands on the beat or 8th **at or just before the sung onset** (all within ±0.05 s). |
| shots **rushed**, can't read the text / see the photo (e.g. 0:29) | New reading-time rule: every caption stays fully visible for ≥ 0.8 s + 55 ms per character (1.4–3 s) before it goes. Nothing is revealed in a shot's last beat. It's enforced in the builder and as a new QA gate (§4b). The title subtitle is gone. Rough/raw/prime is now **one screen that builds and holds for 4 s**. The roll-call role now shows with the name on the downbeat. |
| 1:20 house rule: arrow points at nothing, rushed | The card arrives on beat 3 of bar 32. The rule ("hit THAT cup = pants off.") and the circle land together on the next downbeat, and the **arrow ends on the circled red cup**. The rule stays up 2.4 s. |
| "hi mom! we ate vegetables" — don't get it | Now just **"hi mom! 👋"** on "Forget about our mothers": the classic wave to mum on camera. |
| where are they now: rushed | **Two people per screen, 2 bars per screen** (4 screens). Pairs by city where possible: Gabriel + Maria · Tim + Daria (Frankfurt) · Maja + Jakub (Poland) · Esra + Sam. Each quote stays up 3.5–3.9 s, Sam's 3.6 s. |
| don't render full resolution before review | Preview only. Saved as a rule. |

Other small changes:
- the cassette label now reads *fated to pretend · tour '26*
- the cold-open narration is shorter: *8 friends. 6 countries.* and *(zero musical talent.)*
- "(study??)" covers the whole "what else can we do?" line
- the "wake up" gag was cut so offices and commute have room
- "in a movie" now shows the phone and film twins of the cigarette shot
- "(pretending to be a band.)" is a closed-caption line over the live footage
- Jakub's end card uses the crying-laughing shot

## Audio
| film | song | |
|---|---|---|
| 0:00–0:01 | — | black |
| 0:01–1:56.4 | 0:00.3–1:55.7 | intro → verse 1 → "This is our decision…" → "overwhelming / offices" → chorus 1 up to "We're fated to", **untouched** |
| 1:56.4–2:35.0 | 3:40.2–4:18.8 | final chorus from "…pretend" → "I said yeah, yeah, yeah" outro → the final hit; a **tape-stop** on its ring-out |
| 2:35–2:53 | — | silence: STOP / EJECT, then the liner notes |

The one join is bar 49 → 93, between "fated to" and "pretend": the same bar position, mel corr 0.918, cut in a −34 dB vocal gap. QA measures a −0.8 dB level step and no click. Verses 2 and 3 drop out. The verse-1 drug lines play only under the band roll call, and nothing captions or illustrates them.

## Structure (bar = 2.376 s; every caption time = sung onset)
| film | music | picture |
|---|---|---|
| 0:01–0:06 | synth intro | A VHS cassette lands. Its label writes itself on the beats: *THE BAD BANANAS · fated to pretend · tour '26 · DO NOT TAPE OVER!!* |
| 0:06 | bar 2 | *clunk*: blue screen, ▶ PLAY, snow on beat 4 |
| 0:08–0:18 | synth intro | Cold open, one closed caption per downbeat: *amsterdam, 2026.* → *8 friends. 6 countries.* → *one band.* → *(zero musical talent.)* |
| 0:18–0:27 | synth hook | *tour manager. (has a map)* → *HQ: the attic.* → *rehearsals: nightly.* → *(mostly screaming.)* |
| 0:27 | drums in | **THE / BAD / BANANAS** on 8ths over the halftone "album cover", held |
| 0:30–0:37 | "rough… raw… prime of my life" | one screen: a print + **ROUGH.** / **RAW.** / **PRIME.** *(of our lives)* land on each "I'm…", then everything holds |
| 0:37–0:46 | "music, money, models for wives" | **THE PLAN:** each item writes on its phrase. The tick and the evidence print land on the key word. *(pending)* lands on the downbeat after "wives" |
| 0:46 | instrumental | **MEET THE BAND.** *(in order of appearance)* |
| 0:49–1:08 | verse 1 (Paris/cocaine lines) | roll call, one per bar: name + role on the downbeat, face circled on beat 2, flag on beat 3 |
| 1:08 | "This is our decision" | *the committee.* |
| 1:10–1:13 | "to live fast / and die young" | **LIVE FAST.** → *(and nap young.)*, one print per half-line |
| 1:13 | "We've got the vision" | Maja's glasses circled: *the vision. (she has glasses)* |
| 1:15–1:18 | "now let's have some fun" | ***(fun.)*** with sparkles |
| 1:18–1:27 | synth break | **THE PANTS RULE**: *HOUSE RULE #1 (by tim)* → *hit THAT cup = pants off.* (cup circled, arrow onto it) → *the rule was respected.* → 🍌 censor: *…religiously.* |
| 1:27–1:38 | "overwhelming / what else can we do / jobs in offices / morning commute" | *overwhelming.* → *(study??)* → *jobs in offices: done.* ✓ → *the ~~morning~~ **4am** commute.* |
| 1:38–1:46 | synth break | Kuba's bubble *can we have a bigger one?* at the restaurant → the hit single, *PLATINUM · 1 COPY*, *(bought by kuba.)* |
| 1:46–2:12 | chorus → join → final chorus | *hi mom! 👋* → ***never.*** (friends) → *(pretending to be adults.)* → *(…to be in a movie.)* (phone + film twins) → **LIVE FOOTAGE** *(pretending to be a band.)* → ***(pretending we're not sad it's over.)*** |
| 2:12–2:31 | "I said yeah, yeah, yeah" | **where are they now?** 4 screens × 2 bars, two people each, with Sam's credit lines verbatim |
| 2:31–2:35 | last bar + final hit | the farewell tour poster (title on beat 1, cities on beat 2), **SOLD OUT** on the hit, then the tape stops |
| 2:35–2:53 | silence | STOP → EJECT → liner notes: the thank-you typed one line per felt bar, *— sam* 🍌 |

## QA (v2 preview)
- **48/48** shot boundaries and **74/74** detected visual hits are within one frame of a musical event.
- **0** adjacent pairs flagged.
- **54** distinct photos plus the terrace video; **0** reused.
- **0** of 108 crop keyframes cut a face.
- **0** captions below 3:1 contrast or 34 px; **0** shown too briefly to read.
- The join: −0.8 dB, no click.
- Full report: `cache/qa/time_to_pretend/report.md`.

**QA can't hear.** Check by ear:
- the join at **1:56.4**
- the tape stop at **2:33.3**

## Open questions for Sam
- The roll-call roles are Claude's jokes:

  | Sam | Maria | Kuba | Gabriel | Tim | Daria | Maja | Esra |
  |---|---|---|---|---|---|---|---|
  | lead vocals | flash photography | hype man | wardrobe (optional) | rules & regulations | attitude | stunts | the boss |

- Same for *(study??)*, *(and nap young.)*, *(bought by kuba.)*, *(zero musical talent.)*.

## Backlog
- PG version: the bong is visible in the suits group (1:32) and the mirror selfie (1:49), and the verse-1 drug lyrics are audible under the roll call.
