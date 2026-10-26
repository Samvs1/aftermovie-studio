# Elevate 2026 — the Bad Bananas films (project CLAUDE.md)

Films for Sam's friend group, for the group chat only. The studio-wide rules, environment and QA gates are in the root `CLAUDE.md`. This file is the Elevate-specific context.

**Run things through the studio**, for example `python tools/studio.py build elevate cool_kids`, then `preview elevate cool_kids` / `final …`. (`elevate` is short for this folder.)

## Context
- Friends from a graduate program who lived together in Amsterdam. "Elevate 2026" was a corporate event (Amsterdam, Sept 2026). **Never** mention ING or anything corporate.
- Vibe: bittersweet, because everyone moved back home. Six countries.
- **Core group = "the Bad Bananas" (8):**

  | person id | name | where they went |
  |---|---|---|
  | 1 | Sam | Belgian, **stays in Amsterdam**. The user and editor. |
  | 2 | Maria | Spanish, moved to **Brussels** for a new job (ES → BE) |
  | 3 | Jakub "Kuba" | → **Poland** |
  | 4 | Gabriel | → **Madrid** |
  | 5 | Daria | → **Frankfurt** |
  | 6 | Tim | → **Frankfurt** |
  | 7 | Maja | → **Poland** |
  | 11 | Esra | → **Türkiye** |

  Everyone else went back to their own country. Paola, Ismail (9), Lara (12), Lara's friend (13), Teresa (15) and Basia (16) may appear in group photos, but get **no** polaroid, credit, board or map label.
- **Inside jokes:**
  - "Bad Bananas" is the group's name.
  - Kuba's line **"can we have a bigger one?"**. Slip it in, but **never mention or imply weed**, and never pair it with a bong photo.
  - **Tim's beer-pong rule:** hit a certain cup and your pants come off. `1000052356.jpg` is Gabriel in his underwear in an armchair.
- **Credit lines (Sam's own, use verbatim):**
  - Gabriel: "Still hoping for our Texel trip"
  - Maria: "Future latina soccer mom"
  - Tim: "'You need to take your pants off'"
  - Daria: "Best photographer"
  - Esra: "The OG baddest banana 😎"
  - Jakub: "professional 'banana' eater 🍑🍌"
  - Maja: "Don't trust her with piggyback rides" (she and Esra fell on their faces walking home)
  - Sam (4th-wall button): "edited by Sam — 'I have too much time on my hands guys'"
- **Thank-you note (end of a film, in silence after the song):**
  > to my new, loving friend group — / thank you for the late nights, the deep talks, / the bridge dates and every flash in between. / wherever life takes you now, / there's always a couch for you in amsterdam ♥ / — sam
- **Story order:** boat tour + bridge day → attic party (19 Sept) → restaurant → karaoke (Elevate starts here) → hotel suite → club → night bus → harbour → foggy street (28 Sept).
- Bong photos are OK (group chat). A **PG version** is in the backlog.

## This folder
- `photos/`: 94 jpgs + `1000053594.mp4` (16.5 s terrace hand-dance video, used in Time to Pretend). `img00xx` are the disposable scans (rotation fixes in `cache/rotation_overrides.json`); `1000…` are phone shots.
- `music/`: the three songs. Slugs: `cool_kids`, `time_to_pretend`, `sweet_disposition`.
- `build_cool_kids.py`, `build_time_to_pretend.py`: the film builders (and the studio's reference builders).
- `cache/`: photos.json, cast.json (person ids above), shotlog_notes.json/shotlog.json, audio/, stems/, graded/, render/, qa/.
- `out/`:
  - each film's `.mp4` final, `_edl.json`, `_notes.md`, previews and share copies
  - `shot_log.md` / `shot_log.html`: per-photo descriptions and hero ratings
  - `treatments.md`: the original 3 treatments, superseded in part by the rules

## The films
- **Cool Kids: "COOL KIDS / 27 EXPOSURES"**: final, `out/cool_kids.mp4` (Echosmith, 2:55). This is the house-style reference; read `out/cool_kids_notes.md`.
  - Devices:
    - a film leader countdown and the camera-box label with flag stickers
    - FLASH + shutter on the big downbeats
    - an exposure counter and orange 7-segment date stamp
    - polaroids that develop, with hellos in each person's language, flags and passport stamps
    - stamps landing in the song's stop-time silences
    - a heartbeat grid pulsing on the kick
    - photo-booth strips, phone|film twins, a triptych
    - contact-sheet credits under a loupe
    - a watercolour map with dashed flights every 2 beats
    - "shot in amsterdam. developed in six countries."
    - a film burn into the 4th-wall button, then the silent thank-you page
- **Time to Pretend: "THE BAD BANANAS: FATED TO PRETEND"**: final, `out/time_to_pretend.mp4` (2:53, approved by Sam). The group-chat copy is `out/time_to_pretend_share.mp4`; notes are in `out/time_to_pretend_notes.md`.
  - v2 fixed his v1 notes: late or rushed captions, the house-rule arrow, the "hi mom" joke, and a rushed "where are they now".
  - Join: bar 49 → 93 (115.683 → 220.231, "fated to | pretend").
  - The song has drug lines ("shoot some heroin", "cocaine"): never caption or illustrate them. They play under the band roll call.
  - Devices: the VHS tape and VCR display, closed captions, the roll call, a vinyl single, the banana censor, "where are they now", a tour poster, and a tape stop.
- **Sweet Disposition: "A MOMENT, A LOVE"** (planned: bittersweet, cinematic, minimal text, `golden` grade).
  - Analysis is done. It's a live band (tempo-following grid) with two irregular bars at 112.56 / 117.82. Words are force-aligned (2026-10-24).
  - **Directions proposed (2026-10-24), waiting for Sam's pick** in the studio (*Make the film → Directions*): A "Won't stop 'til it's over" (cinematic Super 8, the original plan below), B "A kiss, a cry" (black-and-white knockout type), C "Blood's still young" (riso tour zine). `out/directions.json`, frames in `out/directions/`, mock-up builder `directions/build_frames.py`.
  - `find_joins` best: **bar 53 → 97, cut at 99.017 → 180.455 (vocal gap −41 dB, mel corr 0.954), ~2:33 edit**.
    - The song plays intact through the intro, verse 1, the first "A moment, a love, a dream, aloud, a kiss, a cry, our rights, our wrongs" (one photo per sung word, small serif italic) and "So stay there…".
    - It then joins into the final "won't stop 'til it's over" climax → departures board → outro.
  - Plan:
    - **Letterbox (2.39:1)** that snaps open to full frame at the climax. Needs animated letterbox keyframes in `frame.draw_overlay`.
    - **Light leaks and dissolves.**
    - **Split-flap departures board**, one row per bar, with flap-clack SFX. Rows: Maria AMS→BRU (via Spain), Gabriel →MADRID, Maja & Kuba →POLAND, Tim & Daria →FRANKFURT, Esra →TÜRKİYE, Sam AMS · STAYING ♥.
    - **Ending:** harbour sunset / foggy street → end card → the thank-you note in silence.
  - Engine: animated letterbox (`letterbox` fx with `keys`) and light leaks now exist; still needed: split-flap board layer, flap SFX.
  - Use only the 8 Bad Bananas for boards and credits.
