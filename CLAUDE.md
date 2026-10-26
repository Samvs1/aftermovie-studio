# Aftermovie Studio — CLAUDE.md

Music-locked aftermovies made from real photos (disposable-camera scans plus phone shots): no AI generation, no animated photos, no AI voices. The user uploads photos + one song + a brief in the local web app; Claude Code directs the film. The user reviews every preview; ask them whenever creative direction, people or jokes are unclear. (If a git-ignored `CLAUDE.local.md` exists, it says who the user is and lists their projects.)

This folder is the **studio** (the app + engine). Each film lives in its own project under `projects/`. A project may have its own **`CLAUDE.md`** with the people, inside jokes, credit lines and each film's status and plan: read it before touching that film.

**The house standard is craft, not a look.** Sync, readability, pacing and no reuse are fixed (rules below). The look is chosen per film from the song's and photos' vibe: see the director's **stylebook** (`.claude/skills/aftermovie/stylebook.md`, 18 visual languages). The disposable scrapbook (Cool Kids) and the VHS rockumentary (Time to Pretend) are two entries in it, not the default. Aim for indie, very creative, high effort. `projects/elevate-2026/build_time_to_pretend.py` is still the most complete builder, with the `cue()`/`sung()` timing and the reading-time lint.

Trips can be imported from a Polarsteps data export (`studio.py polarsteps <p> <zip>`, or in the web app): see section 2b of the skill. The user's own per-step context in `project.json` always wins over the export.

## Layout
- `app/`: local web app (`server.py`, standard library only, 127.0.0.1; `static/index.html`). Start it with **`Aftermovie Studio.bat`** or `tools/studio.py serve` (http://127.0.0.1:8765).
- `tools/`: the pipeline and engine. **`tools/README.md` has the full EDL / layer / effect reference.**
  - `studio.py`: every command, run per project. It sets `AM_PROJECT`, so each tool reads and writes inside `projects/<p>/`.
    - Set up: `new`, `list`, `polarsteps`, `ingest`, `cast`. Plain `python tools/studio.py …` works too: it re-runs itself with `.venv`.
    - Look at photos and pick music: `sheets`, `shotlog`, `moodboard`, `songs`, `vibe`, `gallery`.
    - Make the film: `draft`, `build <p> [film]`, `board`, `preview`, `stills`, `final`.
    - Anything else: `run <p> <tool.py> …`, `serve`, `doctor`, `check` (regression check of every finished film).
  - `am/`: the engine.
    - `common.py`: project paths, fonts, metadata.
    - `grade.py`: grading presets `consumer_film` / `golden` / `punchy`.
    - `photo.py`: face-safe crops.
    - `draw.py`: text, flags, stamps, doodles, bubbles, paper notes.
    - `props.py`: polaroids, strips, leader, camera box, sprockets, map.
    - `vhs.py`: VHS look, halftone, video, cassette, vinyl, stickers.
    - `frame.py`: the compositor.
    - `music.py`: song events mapped to film time.
    - `audio.py`: segments, crossfades, synthesized SFX.
    - `builder.py`: EDL authoring helpers.
    - `kit.py`: the builder kit (`Film`).
    - `checks.py`: the EDL checks shared by the build lint and QA (reading time, captions + their sources, must-haves, near-duplicates, treatments).
  - Analysis tools: `analyze_photos.py`, `cluster_faces.py`, `cast.py`, `shotlog.py`, `separate.py`, `fetch_lyrics.py`, `analyze_audio.py`, `align_words.py`, `find_joins.py`, `song_map.py`, `import_polarsteps.py`, `song_check.py`.
  - Lyric repairs: `fix_lyrics.py` (applies project.json `lyrics_fix`; `align_words.py` runs it after every ingest).
  - Output: `render.py` (chunk cache for previews), `board.py` (storyboard + caption board), `qa.py`, `check.py`, `templates/build_template.py`.
- `.claude/skills/`: `aftermovie` (the director workflow and house rules) and `aftermovie-songs` (song suggestions).
- `assets/`: fonts (OFL / Apache) and the Natural Earth map. `models/`: OpenCV YuNet + SFace.
- `setup.ps1`, `requirements.txt`, `Aftermovie Studio.bat`: install and launch.

A project folder holds:
- `project.json`: the brief, the song, status, chapters, per-step context (`label`, `note`, `who`, `skip`), song suggestions, must-haves (`must_use`, `order`), `lyrics_fix` and the review `rounds`.
- `photos/`: stills and clips. `music/`: the song.
- `cache/`: photos.json, cast.json, shotlog, audio/<slug>.json + png, stems, graded, render, qa, and for trips `trip.json`.
- `out/`: EDLs, previews, finals, notes, treatment, shot log, `<v>_board.json` + `board/` (storyboard), `<v>_changes.json` (what the last build changed), `rounds/` (each preview round's small video).
- `review/notes.json`: the user's timestamped notes from the web app. `review/captions.json`: the lines they ticked or vetoed on the caption board.
- `build.py` or `build_<film>.py`: the film builders.

**In git** (see `.gitignore`): the studio, plus each project's small files (`project.json`, builders, its `CLAUDE.md`, `review/`, `directions/`, and the `.md`/`.json` in `out/`). Photos, music, `cache/` and rendered video stay local; share finished films as GitHub Release assets, never as commits (GitHub rejects files over 100 MB).

## House rules (learned from real review rounds; follow them strictly)
1. **Music flow comes first.** Play the song continuously from the first note. Use **at most ONE join**, and only between musically identical passages: same lyric, same bar position, high stem similarity, cut inside a vocal gap. Use `find_joins.py`. Beat-aligned cuts that skip phrases still feel wrong. After the song ends: silence. Don't reprise music.
2. **Every cut, pulse, flash, drop, stamp and caption lands on a musical event:** a beat, an 8th, a downbeat, a stop-time break or a sung word.
   - A caption tied to a lyric appears at the start of its sung phrase. Use the beat or 8th at or just before the *aligned* onset (`align_words.py`), never after it.
   - Every caption must stay readable before it goes or the shot cuts: ~0.8 s + 55 ms per character, 1.4–3 s (QA §4b).
   - Never reveal anything in a shot's last beat. Fewer gags with room beat crammed ones.
3. **Pacing:** about **one photo per bar** (~1.8–2 s), with holds on landscapes. 2-beat cutting felt rushed. If a section feels like "filler", add character, not more cuts.
4. **No photo used twice in a film**, crops included. `use()` enforces this and QA re-checks it.
5. **Character:** lyric-literal ideas land best, for example circling a girl with "her!" on "she's just in the background", or crossing out "fast cars" → night bus. Express them **in the film's own visual language**: kinetic type on the hook, a word as a window onto a photo, a shape landing on the beat, a look that flips at the drop. Handwritten paper notes only when the film is a scrapbook. Arrows must point at the thing they name. Avoid jokes that need explaining.
6. **Portraits are never carelessly cropped.** Show them whole (prints, diptychs, film strips, grids) or treat them graphically on purpose (knockout type, masks, slices, collage cut-outs, double exposure), never as a lazy 16:9 band. Don't over-zoom faces.
7. **Text must never clip** off screen or collide with graphics. Keep contrast ≥ 3:1 using plates, outlines or a look that makes room, in the film's own typography.
8. **Cast balance:** one person (often the user) can be in a lot of the photos. Keep them present, not dominant.
9. **One committed look per film.** Grain stays light unless the language is gritty on purpose (xerox, riso, VHS, Super 8). The film-reel and scrapbook feel are options, not the default.
10. Each film must feel like its own film: different structure, photo order and effect palette.
11. **Previews only until the user approves.** Never render the 1080p final straight away.
12. **Every line is true of the photo it sits on:** no facts borrowed from a neighbouring photo, no jokes that are factually off, and actions attributed only from the step's `who` or the user's own answer (their notes are in their voice even when they're about someone else). Label every caption's source with `F.said()` so they can check it on the caption board. A joke built on a story shows the whole story.
13. **The user's must-haves are checks**: starred photos (`must_use`), story-order rules (`order`), favourite clips, both friends in a scene. The lint and QA hold the edit to them.
14. **Fix the film, not the frame:** when a note changes timing (a shot leaves too fast), the rest of the film shifts against the music. Re-think the downstream sections as a whole instead of squeezing the fix in locally. The render cache only reuses chunks when the timeline is identical; never limit an edit to keep it.

## Making a film
Follow the `/aftermovie <project>` skill. In short:
1. Song: drop it in or pick one with `/aftermovie-songs`, then `studio.py ingest` (stems, beats, lyrics, `align_words`, joins).
2. People: the who's-who page, then `cast`. Look at every photo with `sheets` and write the shot log.
3. Keep the interview short. Write `out/treatment.md` and check in with the user.
4. Builder: `templates/build_template.py` + `am.kit.Film`, or copy a reference builder. Render stills, then `preview` (it also runs QA).
5. Address their notes from `review/notes.json`. Run `final` only after approval.

## Environment (Windows)
- **Python:** always run tools with `.venv\Scripts\python`, which has librosa 1.0, opencv 5, torch (CPU), torchaudio, demucs, beat_this and pillow-heif. Prefix with `PYTHONIOENCODING=utf-8` (the console is cp1252) and use `-W ignore`.
- **ffmpeg and GPU:** ffmpeg 8.1 is on PATH. An NVIDIA GPU is used for `h264_nvenc`; without one it falls back to x264. Render workers scale to the CPU.
- **Bash heredocs mangle quotes and backslashes.** For non-trivial code patches, write a small `.py` patch script with the Write tool and run it.
- **Timing:**
  - A preview (960×540) takes ~1–2 min; a final 1080p ~6 min for 3 min of film. A preview whose timeline is unchanged (only text, photos or looks changed) re-renders just the changed chunks (seconds); any timing change renders it whole. Finals always render in one fresh pass.
  - `studio.py preview` makes a share copy of under 30 MB, and `final` a 720p share copy.
  - The headless song suggestion takes ~3 min.
- **Secrets:** never read, print, commit or upload a key file (`*api*.txt`, `.env`). None is needed.

## Privacy
These are private friend-group films. Photos, names, jokes and briefs stay in `projects/` and in a private repo at most; never upload them anywhere public. The web app only listens on 127.0.0.1.

## Visual language
Each film picks its language from the stylebook, after the vibe read (`studio.py vibe`) and three directions with style frames that the user chooses from (*Make the film → Directions* in the studio). The vocabulary:
- **looks** (`am/looks.py`): bw, duotone, tritone, gradient, cyanotype, sepia, riso, xerox, infrared, bleach, chrome, faded, selective, negative, posterize, gameboy, thermal, sketch (pencil drawing that blooms into colour)
- **layers** (`am/graphic.py`): type_mask (knockout / zoom-through), shape, slices, lyric_type (kinetic type), filmstrip
- **photo options**: `blend` (multiply / screen / overlay / lighten / difference), `opacity`, `feather`, `edge: torn`
- **transitions**: iris, slices, zoom, strobe, luma, spin, page (sketchbook page turn), plus dissolve / dip / whip / burn / glitch / flash
- **shot fx**: look, strobe, mirror, kaleido, light_leak, letterbox (keyed), zoom_blur, torch, rotate, vhs, rgb_split, flash_on; shot keys `echo`, `stutter`
- **props**: polaroids, prints, notes, stamps, map, route map, cassette, vinyl, stickers

To see everything on a project's own photos: `studio.py gallery <p>` → `out/style_gallery.jpg` (also a button on the brief page).
The brief page shows a sample frame per style (`app/static/styles/`, rendered by `tools/templates/style_samples.py` on the public-domain photos in the hidden project `projects/_style-samples`; licences in `app/static/styles/CREDITS.md`). Re-run it when a style changes: `studio.py run _style-samples templates/style_samples.py [keys]`. The user's picks land in project.json `style_leanings` (the style names). Projects starting with `_` are internal and hidden.

### The scrapbook look (Cool Kids; one entry in the stylebook)
- **Grade** `consumer_film`: warm consumer film, lifted greenish blacks, halation, phone shots softened. **Finish:** grain 0.012, vignette 0.28, halation 0.07, flicker 0.006, weave 0.35.
- **Fonts:** Caveat (handwriting), Permanent Marker, Anton/Bebas (titles), Special Elite (typewriter), Space Mono (labels), Playfair (cinematic serif). Ink `#1f2a44`, red `#c8371f` (darker `#9e2410` for small text on paper).
- **Synthesized SFX only** (`am/audio.py`): shutter, wind, stamp, drop, charge, rewind, runout, projector, clunk, static, page, pencil. Keep them subtle (−15 to −25 dB), louder inside musical silences.
- The devices each Elevate film used are listed in `projects/elevate-2026/CLAUDE.md`. Trips add the route map and count-up stats.

## QA gates (`studio.py preview` runs `qa.py`; read `cache/qa/<v>/report.md` and the `cuts_*.jpg` sheets)
- **Sync:** shot boundaries and frame-difference events in the rendered video are within 1 frame of a musical event. Centred transitions are judged at their centre, and the felt pulse is extrapolated through ring-outs using the closing tempo.
- **Variety:** no adjacent shots with the same layout/motion/transition signature or near-identical colour.
- **Photo reuse = 0.**
- **Faces:** no crop keyframe cuts a face.
- **Readability:** captions ≥ 3:1 contrast and ≥ 34 px at 1080p. **Reading time:** every caption shown long enough (§4b).
- **Screen time:** every photo stays up ≥ 1.8 s from when it lands to the cut (§4c; the build prints it as a lint too). A second photo landing late on a page counts from its landing. Mark a deliberate flash frame `quick`.
- **Near-duplicates (§2c):** no two photos of the same view (burst or reframed; ORB feature match) close together.
- **Photo visibility (§4d)** and **treatments (§4e):** no faint photo; no sketch/bloom that never arrives.
- **Must-haves (§6)** and **caption board (§7):** starred photos in, order rules hold, no vetoed line, every line's source listed.
- **Audio joints:** level step and HF-click check.
- **QA can't hear:** it can't catch phrase-level musical awkwardness, so tell the user which timestamp to check by ear.
- **Regression (`studio.py check`):** run it before and after engine changes. Every finished film must still rebuild the same EDL and look the same as its reference stills (`cache/golden/`, local only); `--update` after an intended change.
