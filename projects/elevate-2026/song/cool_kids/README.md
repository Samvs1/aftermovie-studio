# The song folder: how to read it

Made by `tools/song_kit.py` from the mix, the Demucs stems and the aligned lyrics (`studio.py song <project>` remakes it).
The AI can't hear the song: these files are what a good editor hears, written down. Start with `song-map.md`,
look at `overview.png`, read `lyrics.md`, then write `song-story.md` with the user.

| file | what |
|---|---|
| `song-map.md` | at a glance → sections → moments → every bar (chord, loudness, voice/drums/bass/other, sung words, events) |
| `lyrics.md` | the lyric by section: when each line is sung, `bar:beat`, the hook, melody (contour, peak note, held words) |
| `song-story.md` | what the song is about and how its arc can carry the film: written by the director, never overwritten |
| `overview.png` | the whole song in lanes, the way an editor sees a timeline |
| `pages/bars_*.png` | 16 bars per picture: every word, chord and beat readable |
| `song-map.json` | everything as data: `beats`, `bars`, `sections`, `moments`, `lyrics` (words with sung time, note, held), `notes` (vocal + bass), `chords` |
| `envelopes.json` | 10 Hz curves: `loudness_lufs` (momentary), `short_lufs` (3 s), `voice`, `drums`, `bass`, `other` (0-1), `brightness_hz` |
| `report.json` | models, device, timings, confidence and warnings: check it when something looks wrong |

## Notation
- **Time**: seconds in the song file (`m:ss.s`). Film time = song time − segment in + segment at (`F.song2film`).
- **bar:beat**: `17:2.5` = `F.beat(17, 2.5)`: bar 17 (bar 0 = the first downbeat, as `F.bar(n)`), beat 2.5 counted
  from that downbeat (0 = the downbeat itself; .5 = the 8th after a beat). Negative beats = pickups before bar 0.
- **LUFS**: loudness as ears hear it (EBU R128, K-weighted). −8 is very loud, −14 normal, −25 quiet. Differences
  matter more than values: +3 LU is clearly louder, +6 LU is a big lift.
- **V D B O** (0-9): **V** = how much of the bar is sung (9 = sung all through); **D / B / O** = how loud the drums,
  bass and *other* (guitars, keys, synths, strings) are against their own loudest bars (0 = not playing, 9 = full).
- **Sections**: names come from repetition (the *sound* letter: sections with the same letter share chords and
  texture) and the lyric (lines that come back = chorus). A *sound* letter like `AB` = merged from two classes.
- **Moments**: ★ (cut on it if it's handy) → ★★★ (the song's own peaks and turns: build the film's big ideas here).

## Caveats
- Section names are inferred: if the bar map says otherwise (who sings what, where the hook is), trust your reading
  and say so in `song-story.md`.
- Chords are major/minor triads from the *other* + *bass* stems (no 7ths/sus): good for where harmony changes,
  approximate for spelling. Key: Ab major (fit 0.92 vs F minor 0.74).
- Notes come from pitch tracking (CREPE) on the vocal / bass stems: reliable for contour, highest notes and holds;
  backing vocals and bleed can add stray notes.
- What fills a stretch without a beat (film, talking, ambience, silence) comes from a zero-shot audio tagger (CLAP).
  Genre, mood and instrument tags were tested and left out: too often wrong. The song's character is for you to
  read from the measurements, the lyric and the user.
- Made 2026-10-26 21:43 on NVIDIA GeForce RTX 4060; stems: htdemucs (no model.txt: made before the GPU separation).
