# georgia: preview v1 notes (2026-10-24)

**Files:** `out/georgia_preview.mp4` (960×540) and `out/georgia_preview_share.mp4` (18 MB, the one the studio's Review tab plays).
**Length:** 3:34.5. The song plays 0:00.9–3:26 from its first strum, with no join; the last chord fades by 3:26 and the thank-you plays in silence.
**Built from:** `build.py` → `out/georgia_edl.json`. 68 shots, 76 photos + 3 clips, none used twice.

## Structure
| film | music | picture |
|---|---|---|
| 0:00–0:08 | intro strums | Title card on paper, Georgian flag, "Tom & Sam · October 2026" |
| 0:08–0:21 | verse 1 | Tbilisi: the rooftops "valley", the sun, the Chronicles, the two of you on the stairs + "Thx Keti for the tour!", Sameba at night |
| 0:21–0:36 | verse 1 (food) | "~~no~~ food" on the khachapuri, "meat-eater" arrow at Sam, "khinkali (again)", Sam asleep: "defeated." |
| 0:36–0:58 | chorus 1 | Rental contract "Rule 1: NO OFFROAD." → "Yes, no offroad." → the pothole: "the main road." → "Gamarjoba!" with the cats → Gudauri mural → selfie with **Tom** on "my", **Sam** on "name" → flag |
| 0:58–1:11 | interlude (kick in) | Route map 1: the 🚗 drives Tbilisi → Kazbegi. Gudauri canyon, Gergeti under Kazbek, Dariali |
| 1:11–1:38 | verse 2 | Sam lying on the rocks; the stone heads "yours" / "mine"; sleeping dogs "refreshing."; "The border" + RU flag + "post" arrow; icons; Sam leaping the river; the larches + horse |
| 1:38–2:00 | chorus 2 | "Gori · Stalin top G ⚒️" (Sam thumbs-up + Tom hand-on-heart), the carriage, the statue, "Crazy city · Uplistsikhe", the rock tunnel down |
| 2:00–2:34 | verse 3 | Prometheus cave on "cave" → the stalactite print **turns upside down** on "upside down" → Khoni falls + Tom on the rock → clip: Tom under the icy waterfall, "AAAAH!" → clip: priests singing on "sing" → market: ბლა ბლა ბლა? / "Madloba!" → clip: Tom + the stray dog on "freedom" → "Yes, no entry." |
| 2:34–2:37 | "to live my life…" | Sam in the sanatorium window |
| 2:37–2:59 | brass climax | One photo per bar: the rotunda tree, Tom on the stairs, "Batumi: still upside down", the moon + the telescopes, Vardzia, Borjomi, "Big chill", "Sword mountain" |
| 2:59–3:06 | final chorus | Route map 2: the 🚗 drives the whole loop |
| 3:06–3:11 | | Stats count up: 15 days · 1,560 km · 26 stops · "khinkali: every day" · "Georgian words known: 2" |
| 3:11–3:21 | "find strength / know my name" | The swords: "found it.", then the Gergeti selfie with the names tagged again |
| 3:21–3:27 | last chord | Didgori hill, held |
| 3:27–3:34 | silence | **Madloba!**, "Thank you Georgia", "— Tom + Sam" |

## QA (`cache/qa/georgia/report.md`): all gates clean
- 67/67 shot boundaries and 111/111 visual hits within one frame of a musical event.
- 0 adjacent look-alikes, 0 reused photos, 0 faces cut by crops.
- 0 captions under 3:1 contrast, 0 captions too short to read (builder lint also 0).
- No join, so no audio joints. The opening is silent until the first strum; the ring-out fades to silence by 3:26.

## Check by ear / eye
- **0:00–0:02:** the song starts on its first strum. The MP3's 40 s spoken video intro and 30 s outro ambience are cut out.
- **0:58:** the kick drum entry, with the flash into the route map.
- **2:07–2:09:** the print turning upside down on "up-side-down".
- **2:14–2:20:** Tom's waterfall clip, with the "AAAAH!" on "make your siren's call".
- **3:21–3:27:** the last chord's fade, then the silent thank-you.

## Jokes I invented (veto any)
- "defeated." on Sam asleep in the car (read as a food coma after the food run).
- "x Tom x Sam" signatures on the rental contract.
- "refreshing." on the two sleeping stray dogs ("refresh my broken mind").
- "post" + an arrow at the border-zone sign post ("tie me to a post").
- "found it." on the swords ("I'll find strength").
- The stats: 15 days (Polarsteps), 1,560 km (GPS inside Georgia), 26 stops (your Polarsteps steps).

## Known limits
- The Polarsteps export gives 1280 px photos, so full-frame shots are a little soft at 1080p. If you have the originals, drop them in under the same names before the final.

## Studio changes made for this film
- `kit.beat()` counts the song's own beat grid. This fixes the one-click draft crash on live and half-time songs; the Elevate EDLs are unchanged.
- The template's chapter notes hold until they're readable.
- The lyric offset search now covers ±60 s. Music-video MP3s with long intros were 3 s off.
- Contact sheets get numbered short labels.
- New engine features:
  - `turn` animation on photos;
  - GE and RU flags;
  - a `georgian` font (Sylfaen);
  - a route-map car;
  - `route_map(labels=, bounds=, car=)`, which drops flight legs from the route;
  - prints thump in on the cut frame instead of one frame later.

## Final (2026-10-24, approved by Sam in chat)
- `out/georgia.mp4`: 1920×1080, 30 fps, 3:34.5, 826 MB master.
- `out/georgia_share.mp4`: 1280×720, 28 MB, for group chats.
- QA on the master: 67/67 cuts and 111/111 visual hits on the music; 0 look-alikes, 0 reused photos, 0 cut faces, 0 low-contrast or rushed captions.
- Since the preview, the only change is the removal of an SFX that the song's fade-out already muted.
