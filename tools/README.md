# Aftermovie Studio tools

Everything runs from the studio folder with its own Python: `.venv\Scripts\python`. The director workflow is `.claude/skills/aftermovie/SKILL.md`.

## Studio (projects)
`tools/studio.py` drives a project in `projects/<name>/`. It sets `AM_PROJECT`, so every tool below reads and writes inside that project (paths below like `cache/` and `out/` are inside the project). The Elevate films are `projects/elevate-2026` (alias `elevate`).
```
studio.py new <name>            studio.py ingest <p>            studio.py cast <p>
studio.py sheets <p>            studio.py shotlog <p>           studio.py draft <p>
studio.py build <p> [film]      studio.py preview <p> [v]       studio.py stills <p> <v> t1,t2
studio.py final <p> [v]         studio.py run <p> <tool.py> ... studio.py serve / doctor
studio.py board <p> [v]         studio.py check [p ...] [--update]
studio.py polarsteps <p> <export.zip> [--list | --trip ID]     import a Polarsteps trip
```
- Builder kit: `am/kit.py` (`Film`: bar/beat/cue/sung/at timing, prints, `page()`, notes, captions, `said()` sources,
  `ph(n)`, `face_uv()` + `arrow()`, and the lints on save: reading time, screen time, must-haves, treatments,
  near-duplicates, caption board). The checks themselves live in `am/checks.py` (QA uses the same code).
- Storyboard + caption board: `board.py` → `out/<v>_board.json` + `out/board/<v>/<shot>.jpg` (the studio's Review →
  Storyboard tab, where the user ticks or vetoes each line → `review/captions.json`).
- Change log: every build that changes the EDL writes `out/<v>_changes.json` (shots new / changed / retimed / removed).
- Regression: `check.py` rebuilds every finished film into `cache/check/` and compares stills with `cache/golden/`.
- First-draft builder: `templates/build_template.py`.
- Planning: the song folder `song/<slug>/` (`song_kit.py`); `song_map.py <slug> --segments ...` for film time per bar.

## Rebuild and re-render a film
```
.venv\Scripts\python tools\studio.py build elevate cool_kids          # builder -> out\cool_kids_edl.json
.venv\Scripts\python tools\studio.py stills elevate cool_kids 12.5,34.6   # single frames -> cache\render\
.venv\Scripts\python tools\studio.py preview elevate cool_kids        # 960x540 preview + share copy + QA report
.venv\Scripts\python tools\studio.py final elevate cool_kids          # 1920x1080 -> out\cool_kids.mp4 (after approval)
```
Any single tool: `studio.py run <p> render.py projects/<p>/out/<v>_edl.json --preview --start 30 --end 50`.

Previews go through a chunk cache (`cache/render/chunks/`, chunks of whole shots, encoded without B-frames so they join
frame-exact). Same timeline as the last render (every shot boundary, transition, the audio edit, length, fps): only
chunks whose shots, neighbours, photos, look or engine code changed are rendered again. Any timing change renders the
whole film. `--full` ignores the cache; finals always render in one pass.

## Pipeline (already run; results cached in `cache/`)
| step | script | output |
|---|---|---|
| photo rotation, faces, embeddings | `analyze_photos.py` | `cache/photos.json` (+ manual `cache/rotation_overrides.json`) |
| face clusters → people | `cluster_faces.py`, `cast.py` | `cache/face_clusters.json`, `cache/cast.json` (names), `cache/faces_people.json` |
| shot log | `shotlog.py` | `out/shot_log.md`, `out/shot_log.html` |
| stems (analysis only) | `separate.py` (htdemucs_ft on the GPU, htdemucs on the CPU) | `cache/stems/<song>/` + `model.txt` |
| synced lyrics (LRCLIB) | `fetch_lyrics.py <slug> "<artist>" "<title>"` | `cache/lyrics/<slug>_search.json` |
| lyrics when LRCLIB has none | `transcribe_lyrics.py <slug> [--language nl]` (Whisper on the vocal stem) | `cache/lyrics/<slug>_transcribed.json` |
| music analysis | `analyze_audio.py` (applies `lyrics_fix.text`) | `cache/audio/<song>.json` + `.png` |
| sung word onsets | `align_words.py <slug>` (forced alignment on the vocal stem) | rewrites `lyrics[].words[].t` (keeps `t_lrc`), then applies project.json `lyrics_fix` (`fix_lyrics.py`) |
| single-join finder | `find_joins.py <slug>` | ranked joins between identical passages + vocal-gap cut points |
| the song folder | `song_kit.py [slug]` (`studio.py song <p>`) | `song/<slug>/`: README, song-map.md/.json, lyrics.md, song-story.md, overview.png, pages/, envelopes.json, report.json |

## EDL reference
All coordinates are in 1920×1080 design pixels, and all times are in film seconds.

```jsonc
{
  "meta":   {"version": "cool_kids", "song": "music/...mp3", "analysis": "cool_kids", "fps": 30, "duration": 82.99},
  "audio":  {"segments": [{"src": [songIn, songOut], "at": filmTime, "xfade": 0.04}, ...],
             "sfx": [{"type": "shutter|wind|stamp|drop|charge|rewind|runout|projector", "t": 10.57, "db": -12}],
             "fx":  [{"type": "lowpass", "t0":0, "t1":8, "f0":400, "f1":18000}, {"type": "tape_stop", "t": 70, "dur": 0.8}],
             "fade_out": [82.2, 82.99]},
  "grade":  {"preset": "consumer_film|golden|punchy", "overrides": {"img0016.jpg": {"wb": 0}}},
  "finish": {"grain": 0.02, "vignette": 0.3, "halation": 0.07, "flicker": 0.008, "weave": 0.4},
  "overlays": [{"type": "counter", "steps": [[t, 27], ...]}, {"type": "letterbox", "h": 140}],
  "shots": [{
     "id": "S004", "t0": 10.572, "t1": 11.033, "sync": "band entry downbeat",
     "in": {"type": "cut|flash|dissolve|dip_white|dip_black|whip|burn", "dur": 0.2},
     "bg": "#000000 | paper",
     "freeze": [[16.81, 17.50]],          // time stops for moving photos (stop-time breaks)
     "fx": [{"type": "flash_on", "on": "cymbals"}, {"type": "rgb_split", "on": "snares"}],
     "layers": [ ...see below... ]
  }]
}
```
**Layers** are drawn in order:
- `photo`: `src`, `box`, `zoom` `[start, end]` or `"auto:0.45"`, `focus` (`faces` | `person:<id>` | `face:<n>` | `[x, y]`), `drift`, `ease`, `pulse` `{on: kicks, amount}`, `shake` `{on: bass_hits}`, `freeze_at`, `rot`, `turn` `{t, dur, deg}` (the print turns over on a beat), `border`, `shadow`, `enter` / `exit` (`drop` | `slide` | `pop` | `fade` | `thump`), `quick` (a deliberate flash frame: skipped by the ≥ 1.8 s screen-time check).
- `polaroid`: `src`, `cx`, `cy`, `w`, `rot`, `caption`, `develop` `{t, dur}`, `enter`.
- `strip`: photo-booth strip of `srcs`; `label` = text printed in its foot (none by default).
- `grid`: `rows`, `cols`, `cells` `[{src, t}]`, `pulse`.
- `text`: `text`, `font` (`caveat` | `marker` | `anton` | `bebas` | `playfair` | `mono` | `elite` | `georgian` | `georgian_black` / `_bold` / `_light` (Noto Sans Georgian, for Mkhedruli knockouts) | …), `size`, `color`, `x`, `y`, `t0`, `t1`, `anim` (`pop` | `write` | `type` | `fade` | `rise`), `panel` (taped paper note), `boil`.
- `marker`: `circle` | `arrow` | `line`, or `follow` a face in another layer.
- `flag`: `ES` | `BE` | `NL` | `DE` | `PL` | `TR` | `RU` | `GE`.
- `stamp`: passport stamp.
- `seven`: 7-segment date or number.
- `label`: single-use camera box panel; set its texts with `title`, `sub`, `count`, `edition` (defaults are generic: "SINGLE USE").
- `leader`, `contact`, `map`, `fill` (`grid: {kind: dots|squares, step, color, alpha}` makes a sketchbook page).
- Time to Pretend additions (`am/vhs.py`):
  - `photo` option `halftone` `{cell, mode: color|mono, paper, ink, t?, dur?}`: print-dot poster look.
  - `video`: a clip from `photos/` (`src`, `start` in source seconds, `box`, `zoom`, `focus` `[x, y]`), graded like the phone shots;
    also `look`, `feather` and `blend` like a photo.
  - `rect`: flat colour block or gaffer-tape strip (`x, y, w, h, color, alpha, rot, enter`); `"show": [t0, t1]` limits any layer to a time range.
  - `cassette`: a VHS tape with a blank label (write on it with `text` layers).
  - `vinyl`: a 7" record that spins (`d`, `label` colour, `text` (default "SIDE A / 45 RPM"), `spin` deg/s); draw it before its sleeve so it slides out from behind.
  - `sticker`: die-cut text or emoji (`🍌`) slapped on at `t`; `follow` a face with `off` in face widths/heights.
  - `osd`: VCR icon + word (`icon`: play | pause | stop | rec | eject | rew; `blink`).

Creative vocabulary (see `.claude/skills/aftermovie/stylebook.md`):
- **Looks** (`am/looks.py`): `"look"` on a photo / `type_mask` / `slices` / `filmstrip` layer, or shot fx
  `{"type": "look", "look": ...}`. Names: bw, duotone, tritone, gradient, cyanotype, sepia, riso, xerox,
  infrared, bleach, chrome, faded, selective, negative, posterize, gameboy, thermal, sketch (dict form takes colours,
  `amount`, `t`/`dur`, `keys` [[t, amount]...]). `sketch` draws the photo in graphite on paper (`draw`: 0..1 or keyframes, the lines drawing
  themselves in); its `color` (0..1 or keyframes) floods the real colour back in like watercolour blooms, from the middle
  out. On a paper page use `blend: multiply` with `paper: #ffffff` (night pages: `screen` with black paper).
- **Photo layer:** `blend` (multiply|screen|overlay|lighten|difference), `opacity`, `feather` (px soft edge),
  `edge: "torn"` (+ `tear`, `seed`).
- **Layers** (`am/graphic.py`): `type_mask`, `shape` (also `kind: poly` with `rings` of design px, `soft`, `blend`: a
  watercolour wash on a hand-drawn map), `slices`, `lyric_type`, `filmstrip`. Their parameters are in
  the module docstring; `am/kit.py` has the helpers.
- **Transitions:** iris (`close` for a silent-film iris), slices, zoom, strobe, luma, spin, page (a sketchbook page
  turning over the spine; `dir`: next | back).
- **Shot fx:** look, strobe, mirror (x|y|quad), kaleido (n), light_leak, letterbox (`keys` [[t, h]...]),
  zoom_blur, torch (a flickering pool of warm light: `amount`, `cx`, `cy`, `r`, `color`, `on`), rotate (the whole
  frame turns: `keys` [[t, deg]...], e.g. 180 for upside down; `scale_keys`, `bg` = the desk colour around it).
- **Shot keys:** `"echo": {n, dt, decay}` (trails), `"stutter": seconds` (motion in steps).
- **Any layer:** `"post": true` draws it after the shot fx (a title that stays sharp above a kaleido, strobe or look).
- **Any layer with words** (the renderer ignores these; the caption board, the lint and QA read them):
  `"origin"` (lyric | credit | brief | name | place = trusted; answer | note | fact | invented = the user checks),
  `"basis"` (what it rests on), `"joke"` (groups a joke's setup and payoff). Set them with `F.said(...)`.
- **Photo layers:** `"twin": true` marks a deliberate pair of look-alike photos (skipped by the near-duplicate check).

project.json keys the checks read: `must_use` [photo or clip names, starred in the studio], `order`
[{"first", "then": [...], "why"}], `steps[id].who` (who's in it / who did what), `lyrics_fix` {held_lines, words}.

Trips (`import_polarsteps.py`, `cache/trip.json`): the `map` layer takes `bounds` [lon0, lon1, lat0, lat1], `highlight` (ISO country codes), a self-drawing `route` {points [[lon, lat]...], keys [[point index, time]...], color, width, dashed, car (an emoji that drives the route head)} and `pins` [{lon, lat, t, label, off, size}] (`F.route_map(trip, pin_times, labels=, bounds=, car=)` builds all of it and leaves the flights out; fewer pin times than steps draws the trip so far). `text` with `count: N` counts "{n}" up to N (stats cards).

Shot `fx` also include `vhs` (`amount`, `band`, optional `ramp`), `static` (`t0`, `t1`) and `wobble` (tape slowing down: `t0`, `dur`). Transitions include `glitch`. Overlays include `osd`: a persistent VCR display with `states` `[[t, icon, word, blink?], …]`, a tape counter from `counter_t0`, and `hide` ranges. SFX include `clunk` (VCR mechanism) and `static` (tape snow).

Person ids for `focus` (`person:<id>`) come from the project's `cache/cast.json` (the web app's Who's who page; for the Elevate films see CLAUDE.md).

Effects reference musical events by name: `beats`, `downbeats`, `kicks`, `snares`, `cymbals`, `bass_hits`, `onsets`, `vocal_onsets`. These are mapped from the song through the audio segments automatically, so if you move a segment, the pulses follow it.
