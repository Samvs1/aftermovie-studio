---
name: aftermovie-songs
description: Suggest songs for an Aftermovie Studio project by looking at its photos, clips, brief and trip - verified real songs that fit the vibe, length and editing style. Use when the user runs /aftermovie-songs <project>, asks which song to use, or wants more/different song ideas.
---

# Song suggestions for an aftermovie

The web app's "Need a song?" button runs this headlessly (`tools/studio.py songs <p>`: moodboard → Claude reads it
read-only → every song checked on LRCLIB → `project.json` `song_suggestions`). This skill is the interactive
version: same job, but you can talk with the user and refine ("more upbeat", "no English", "something like X").

Argument: the project name (`python tools/studio.py list` if missing). Run tools with `.venv\Scripts\python`.

1. `studio.py moodboard <p>` → read `projects/<p>/cache/moodboard/context.md` (brief, trip steps + the user's
   notes, music taste, photo count and length guidance) and look at **every** `sheet_*.jpg` (photos in story
   order; red CLIP tiles are videos). Also read any existing `song_suggestions` in project.json so you don't
   repeat them unless asked.
2. Pick 8 songs: 3 strong obvious fits, 3 less obvious indie/alternative, 1 high-energy party option, 1 wildcard
   (for trips: from or about the place, only if you're sure it exists). Base the vibe on what you actually see and
   name concrete photos in each reason. Respect the brief's avoid list and the music taste.
3. Editing fit (this is a music-locked editor, one photo per bar): follow the length guidance; prefer an intro that
   can carry a title, a build/drop for a reveal, an ending that lands; say where one clean cut (chorus to chorus)
   would shorten it. Avoid songs whose hook is about drugs if the film is for a wide audience.
4. **Only real songs.** Check each one: `studio.py run <p> song_check.py "<artist>" "<title>"` (LRCLIB: found,
   duration, synced lyrics). Drop or replace anything not found; prefer songs with synced lyrics when lyric gags
   matter.
5. Save into `projects/<p>/project.json` → `"song_suggestions": {"at": "<YYYY-MM-DD HH:MM>", "items": [...]}`, each item
   `{artist, title, why, tags, energy, structure, fit, lyric_hooks, check}` (`check` = the song_check output), so
   the studio's Photos & song page shows them with Listen links and a "Use this one" button.
6. Tell the user your top 3 in two lines each and that the full list is in the studio. Never download music:
   they add the MP3 themselves; then the analysis takes it from there.
