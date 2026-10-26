# Stylebook: visual languages for aftermovies

A film should feel *authored*: one strong visual language that grows out of **this song** and **these photos**,
executed with total commitment, plus 3-5 signature moments where the idea peaks on the music. The languages below
are starting points, not a menu to stay inside: mix two, bend one, or invent a new one when the vibe asks for it.
The craft rules (sync, readability, pacing, no reuse) never change; the look does.

**Anti-defaults.** The scrapbook (taped paper notes, gaffer-taped prints, handwritten captions) is ONE language
(#1), right for some films and wrong for most. Never reach for it by habit. Text speaks in the film's own
typographic voice: kinetic type, knockouts, editorial serif, subtitles, stamps, or no text at all.

Engine names: looks = `look` on a photo or `{"type": "look"}` shot fx (`am/looks.py`); layers / transitions / fx
in `am/graphic.py`, `am/vhs.py`, `am/props.py`; builder helpers in `am/kit.py` (`F.lyric_type`, `F.lyric_words`,
`F.type_mask`, `F.shape`, `F.slices`, `F.filmstrip`, `F.pr`, `F.full`, `F.note`, ...). Run
`studio.py gallery <p>` (→ `out/style_gallery.jpg`) to see every technique on the project's own photos. A sample frame
of each language below is in `app/static/styles/<key>.jpg` (made by `tools/templates/style_samples.py`: its build
functions are compact recipes for each look). The user picks favourites on the brief page (`style_leanings`).

| # | Language | Fits | Look | Type | Motion & cuts | Signature devices |
|---|---|---|---|---|---|---|
| 1 | **Disposable scrapbook** | warm indie-pop, friend groups, disposables | `consumer_film` grade, light grain | Caveat notes on taped paper, Marker | one photo/bar, flash on downbeats | polaroids developing, stamps in stop-times, contact-sheet credits (Cool Kids) |
| 2 | **VHS rockumentary** | jokey rock, ironic lyrics, band myth | `punchy` + `vhs` fx | mono closed captions, Anton slams | glitch cuts, roll call | cassette, REC, tape stop, tour poster (Time to Pretend) |
| 3 | **Kinetic lyric video** | wordy songs, singalongs, strong hooks | any; often `bw` or `duotone` behind type | `lyric_type` replace/stack, Anton or Playfair italic | words punch on syllables; photos change per line | the hook line filling the screen, a word as a `type_mask` window |
| 4 | **Swiss editorial / magazine** | cool, confident, electronic or minimal pop | clean, `bleach` or natural, white walls | Inter/Archivo Narrow, strict grid, numbers | hard cuts on downbeats, `slices`, grids that rebuild | huge index numbers, captions as data (date · place · coords), `type_mask` headline |
| 5 | **Risograph zine** | DIY, punk-pop, scrappy summers | `riso` (pick 2 inks), `xerox` for contrast | Anton/Bebas stamped, mono labels | collage builds per beat, torn cut-outs (`edge: torn`) | misregistered two-ink frames, ransom-note type, zine page numbers |
| 6 | **Super 8 home movie** | nostalgic folk, slow builds, family/old friends | `golden` grade, `faded`, heavy halation | almost none; Playfair italic lower thirds | slow drifts, `dissolve`, `burn`, `light_leak` on downbeats | flicker, letterbox opening up at the chorus, sprockets/`filmstrip` |
| 7 | **French New Wave** | melancholic, French/indie, black & white photos | `bw` contrast 1.5 | serif title cards on black (Playfair), intertitles | jump cuts, `iris` close/open, freeze frames | a title card per chapter, iris on the ending, "FIN" |
| 8 | **Saul Bass / travel poster** | jazzy, upbeat, trips, cities | `duotone` multiply into flat colour | big Anton/Bebas, cut-out letters | `shape` circles/stripes growing on beats, photos as shapes | each chapter a poster: shapes + duotone photo + destination name |
| 9 | **Dream pop / shoegaze haze** | dreamy, reverb-heavy, slow tempos | `faded`, `bleach`, overexposed, `light_leak` | thin Playfair italic, small, rare | `echo` trails, double exposures (`blend: screen`, `feather`), long dissolves | two summers overlapping, faces fading into skies |
| 10 | **Club / rave strobe** | dance, house, techno, high BPM | `bw` hard, `thermal`, `chrome`, `negative` flashes | huge Anton words on beats, minimal | `strobe` on snares, `zoom_blur` on kicks, `kaleido`/`mirror`, `stutter` 1/16 | the drop: kaleidoscope + strobe; photos cut every beat only there |
| 11 | **Cyanotype darkroom** | gentle acoustic, sea, summer light | `cyanotype`, `sepia` | typewriter (Special Elite), handwritten pencil | photos "develop" in (`develop`), slow | contact sheets, prints drying, sun-print blues |
| 12 | **Infrared / false-colour dream** | psychedelic, warm guitar, nature trips | `infrared`, `selective` | sparse, rounded | slow pushes, `luma` reveals | landscapes turning pink, one colour kept (`selective`) |
| 13 | **Y2K digital camera** | 2000s pop, nostalgia, party | `chrome`, flash-blown, date stamp (`seven`) | chrome/Anton, mono, LCD | snappy cuts, `zoom` punches, `strobe` white | the 7-seg date stamp, camera-screen framing, "low battery" gag |
| 14 | **Collage chaos** | maximalist, punk, hyperpop, big friend groups | mixed looks per layer | ransom-note (mixed fonts), stickers | layers pile up per 8th, `slices`, `shape` blocks | the frame fills to bursting then cuts to one quiet photo |
| 15 | **Wes-ish symmetry** | whimsical, orchestral pop, road trips | pastel `faded` + warm | centred Futura-like titles (Bebas), chapter cards | symmetrical framing, `mirror` on purpose, whip pans | chapter title cards ("Part III: The Train"), centred everything |
| 16 | **Cinematic minimal** | big emotional builds, ballads, endings | `golden`, `bleach` | small serif lower thirds or none | letterbox (animated), slow push, dissolves; one huge cut at the climax | the letterbox snapping open on the drop |
| 17 | **Diary / sketchbook** | intimate, singer-songwriter, solo trips | paper wall, `sepia`/soft | handwriting, pencil lines, dates | pages turn per chapter, doodles draw on beats | route map drawn by hand, a page per stop (trips) |
| 18 | **Map & motion graphics** | travel, many places, data-ish | clean, flat | mono coordinates, Anton numbers | route draws itself, count-ups, `slices` | stats card, route map, place-name knockouts (trips) |

## How to choose
1. Read `cache/vibe.md` (`studio.py vibe <p>`): tempo, energy shape, stops, ending; light, palette, people.
2. Match on **feel**, not genre: a slow song with dark photos can still be a joyful film, but its *energy shape*
   (builds, drops, stops, ending) must drive the structure.
3. Let the photos vote: muted stone-and-sky palettes suit riso/duotone/cyanotype; neon nights suit
   chrome/strobe/kaleido; many solo portraits suit editorial grids and knockouts; many landscapes suit maps,
   posters and haze.
4. Propose three **contrasting** directions (one close to the brief, one bold, one wild), never three flavours of
   the same idea. Each must have a name, a one-line concept, references (films, music videos, design movements),
   its look / type / motion / transitions, and its signature moment tied to the song's biggest musical event.
5. Commit: once chosen, the language governs every shot. Variety comes *within* the language (scale, framing,
   rhythm, density), not by switching styles mid-film (except one deliberate rupture, e.g. a colour burst at the drop).

## Device budget (in the treatment)
List the devices you'll use with a rough share of screen time. No single device over ~30% of shots; at least
one device the studio hasn't used in this group's previous films; text density as the brief asks (`none` is a
valid answer: let the photos and cuts carry it).
