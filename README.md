# Aftermovie Studio

Turn a pile of photos and one song into an aftermovie where every cut, caption and photo lands on the music.
You bring the photos, the song and the stories; **Claude** (in Claude Code) directs the film with you.

## Install (Windows 10/11, once)
1. Get the code somewhere with a few GB free (e.g. `Documents\Aftermovie Studio`):
   `git clone <this repo's URL> "Aftermovie Studio"` (or *Code → Download ZIP* on GitHub and unzip it).
2. Double-click **`Aftermovie Studio.bat`**. The first start installs Python packages, ffmpeg and the face
   models (5-15 min, ~3 GB). After that it starts in seconds.
3. Install **Claude Code** (the director; needs a Claude plan): open PowerShell and run
   `irm https://claude.ai/install.ps1 | iex`, then run `claude` once to log in.

An NVIDIA graphics card makes rendering and the song analysis much faster (setup installs the CUDA build of PyTorch
when it finds one), but it isn't required. To update later: `git pull`.

## How Claude "hears" the song
Claude can't listen, so the studio writes the song down for it: `projects/<project>/song/<slug>/` holds a song map
(named sections, the big moments, and every bar with its chord, loudness, what the voice / drums / bass / other
instruments do and which words are sung), the timed lyric with its melody, and a picture of the whole song in lanes.
Claude reads it, writes `song-story.md` (what the song is about and how its arc can carry your trip) with you, and
cuts to it. `studio.py song <project>` remakes it.

The lyrics come from you first (the brief page: plain text, LRC, or a `.lrc` / `.txt` file; `[Verse 1]` / `[Chorus]`
tags above the parts name the song's sections), else LRCLIB, else Whisper listening to the vocals. Plain-text lyrics
are placed where Whisper hears the words. On **The song** page, *Fix the timing* opens a lyric timing editor: press
Enter as each line starts (hold it for the line's end), drag lines in the lyrics lane, nudge them, let Whisper place
the rest, add lines it heard that aren't in your lyrics; saving analyses the song again. Without the model downloads
(Demucs, beat_this, Whisper) the analysis still runs on estimates and says so in the song folder and the web app.

## What's in the repo
The studio (app, engine, skills, fonts, face models) plus each project's small files: `project.json`, the
builders, notes, treatments and EDLs. **Photos, songs, caches and rendered videos are not in git.** The finished
films (and, where shared, a project's photos) are attached to the repo's **Releases** page. To rebuild a film,
unzip its photos/music into `projects/<project>/` and run `Analyse` in the studio (or `studio.py ingest`) first.

## Make a film
1. Double-click **`Aftermovie Studio.bat`** → the studio opens in your browser.
2. **Start an aftermovie**, then work through the steps on the left:
   - **Photos & song**: drop in photos (JPG/PNG/HEIC), short clips, and the song (MP3). Fill in artist + title.
   - **Travelled with Polarsteps?** On the same page, drop your Polarsteps export (polarsteps.com →
     Account settings → *Download my data*, they email you a .zip) and pick the trip: its photos, route,
     places, dates and step texts come in. Then on **The trip** page give each step a short name for the
     screen and a line about what happened (empty is fine; Claude asks about the important ones), or leave
     a step out. You get a route map that draws itself to the music and a "days · countries · km" card.
   - **Need a song?** Once your photos are in, press *Suggest songs*: Claude looks at the photos (and the trip
     or brief) and suggests 8 real songs that fit, each with why, how it would cut, and Listen links. Pick one
     with *Use this one* and drop its MP3 in. (Or in Claude Code: `/aftermovie-songs <your-project>`.)
   - **The brief**: what it was, the vibe, story order, the people, inside jokes, what to never show,
     credit lines, an ending note. Rough notes are fine.
   - **Analyse**: straightens scans, finds faces, analyses the song (stems, beats, lyrics, melody, chords, sections:
     the song folder). A few minutes. Songs without synced lyrics online are transcribed from the vocals (check the text),
     unless you put the lyrics on the brief page.
   - **The song**: see the song the way Claude reads it, playing along: sections, loud and quiet, the big moments,
     melody and bass notes, chords, every beat and bar, what the voice / drums / bass / other do, and each sung word.
     Listen to one instrument alone (M V D B O), switch on a beat click (K), slow it down, click anywhere to jump.
     *Fix the timing* (next to the lyrics) to time the lyric lines yourself, or let Whisper place them.
   - **Who's who**: name the face groups; mark the main cast.
   - **Make the film**: open Claude Code in this folder and type `/aftermovie <your-project>`. Claude looks at
     every photo, asks a few questions, writes a plan, builds the edit and sends previews back to the studio.
     (Or press *Quick automatic draft* for an instant, simpler version without Claude.)
   - **Review**: watch the preview, press **N** to leave a note at that moment, then tell Claude
     "I left notes". When it's right, press **Approve this cut** and ask Claude for the final.
   - **Direct** (optional): let Claude direct it **on its own** for a time budget you set (e.g. 90 min): the model
     (Opus by default), the effort (max), the **critic** (Sonnet by default; Haiku is cheaper, Opus sharper, or off),
     **Ultracode** (off by default: multi-agent workflows, more tokens), an optional cost cap in dollars and a note for
     the run. It does what it would do with you (the shot log, the song story, three directions with style frames
     unless you picked one, a treatment, the build, storyboards and previews) but decides alone from your brief, and
     delivers a **preview round** for you to review (never the final: that still waits for your approval). Watch it
     work on the same page: the live log, its agents, the critic's notes, the cost per model. With notes on the newest
     preview, tick **Review round** and it addresses them (each note gets its fix written under it).
     **When your Claude plan's usage limit stops it mid-run**: with **Continue by itself when Claude's usage limit
     resets** ticked, the run waits with its clock stopped and carries on where it was once the limit resets. Unticked,
     the run ends there; **Continue the last run** (on the Direct page) picks it up later in the same conversation,
     with the minutes it had left.
   - **The critic**: a cheaper model with fresh eyes that looks at a preview's frames (a tile per shot with the song
     and the captions) against the treatment, your brief and the house rules, and writes notes with scores (ambition,
     song fit, story, craft, readability), ambition first: it pushes the film to be bolder, never safer. It runs by
     itself during a **Direct** run; on the Review page **Ask the critic** looks at any preview (2-4 min, a few cents with
     Haiku). It can't hear either: your ears are still the judge.
3. The finished film is in `projects/<your-project>/out/`: a 1080p master and a small copy for group chats.

## Good to know
- Everything stays on your PC. The studio only listens on this computer (127.0.0.1).
- Your own notes for Claude (who you are, your projects) can go in a `CLAUDE.local.md` next to `CLAUDE.md`;
  git ignores it.
- Use each photo once; 40-120 photos for a 2-4 minute song works well.
- Command line (optional): `.venv\Scripts\python tools\studio.py --help`. The director and the critic from there:
  `studio.py direct <p> --budget 90m [--revise] [--continue] [--auto-continue] [--critic-model haiku] [--max-usd 20]`,
  `studio.py critique <p> out/<v>_preview.mp4`, `studio.py story <p>` (Claude drafts the song story),
  `studio.py clock <p>` / `stop <p>`, `studio.py permtest <p>` (checks the unattended director's sandbox with the
  real Claude Code, a few cents with Haiku).
- Tests: `python tests/test_director.py` (the director's runner, the critic, the usage limit; a stand-in for Claude,
  no usage spent; `--e2e` adds a whole run on a synthetic project).
