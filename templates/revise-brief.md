This is a review round for the aftermovie in this folder. I watched version {{version}} ({{video}}) and left notes at moments in it{{captions_part}}. Make the next round.

My notes on {{version}} (film time · bar:beat · section · what is sung there · the shot there · my note):
{{notes}}
{{vetoed}}{{direction}}

- Address every note and every vetoed line. Read out/{{version}}_notes.md, out/director_log.md (if there is one) and the builder first: they say what was made and why; keep what works. Map each note to its shot (the storyboard out/{{version}}_board.json has every shot's time and bar).
- Fix root causes, not symptoms (late captions: the alignment or the cue; rushed: reading time and screen time; a vetoed fact: find where it came from and fix the source too). Fix the film, not the frame: when a note changes timing (a shot held longer, a photo moved), the rest of the film shifts against the music, so re-think the sections downstream as a whole instead of squeezing the fix in locally. Small fixes stay small. Keep your full creative range: where a note asks for more, go further than it asks; never answer a note by making the film safer.
- Follow the skill's §8 "Review round" ({{skill}}) and its house rules. Rebuild in place (the same version name) unless a note asks to compare; the studio keeps every preview round for comparing.
- Deliver: `{{python}} {{tools}}/studio.py preview {{project}} {{version}}` with every QA gate clean, and update out/{{version}}_notes.md (what changed per note, the timestamps I should check, by ear too). Never run `studio.py final`: it waits for my approval.
- Mark each note you addressed done with a one-line fix, what changed (I read it under my note): `{{note_done}}` (each note above has its id). Not by editing review/notes.json: I may add notes to it while you work.
- You have about {{budget}}; check the clock. Work on your own; don't stop to ask me. Keep all your work inside this project folder. You can't hear the audio or watch the video: when you say something is right, it's because you looked at frames.

---
Notes from the studio (how this machine works):
- This folder is the project `{{project}}`. Run the studio's commands as `{{python}} {{tools}}/studio.py <cmd> {{project}} ...` (the skill writes them from the studio folder). The studio's own folders, photos/, music/ and my review files are read-only in an unattended run: the engine can't be changed here.
- The clock: you started at {{started}}; the budget ends at **{{deadline}}** (`{{python}} {{tools}}/studio.py clock {{project}}`). The studio messages you as time runs down and stops the session a few minutes after the deadline. A preview takes {{render_time}}.
- Keep your log in out/director_log.md.{{critic}}
- I may leave more notes while you work; they come to you as messages: treat them like these.
- You have full reign, as in the first run: fix it all yourself, or deploy agents where that makes this round better or faster; nothing requires them. The Agent tool runs one (in the background with `run_in_background: true`: you're told when it finishes); give each its `model` and a narrow brief (the note, the files it may change, what it must not settle for, never "read the song folder"); {{looking_short}}. Renders queue one at a time on this machine, and what agents cost is part of this round.{{ultracode}}
