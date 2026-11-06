# Aftermovie Studio internals: the autonomous director, the critic, the usage limit

How the studio works around a director, for working on the studio itself. A director needs `tools/README.md`, the
skill and its brief, not this. (Ported from Music Video Studio, which has the same runner; the differences are below.)

## The module map
- `director.py`: `studio.py story | direct | clock | stop | permtest`. The autonomous run (`Runner`, with its
  `CriticWatcher` and `UserNotes`), the briefs (`build_brief`: `templates/director-brief.md`, `templates/revise-brief.md`),
  the sandbox (`claude_args`, `deny_rules`), Continue the last run (`continuable`, `wait_for_reset`), the run's record
  (`append_settings`, `cost_rows`).
- `critic.py`: `studio.py critique`. One headless print-mode call on a cheaper model with read-only tools
  (`templates/critic-prompt.md`), its critiques in `review/critic/` (in git, next to the user's notes).
- `eyes.py`: the pictures the critic looks at (a sheet tile per shot with the song and its captions, the ★★★ moments,
  a beat sheet, strips; plus QA's cut sheets) in `cache/eyes/<video>/`, and `index.md` listing them.
- `am/session.py`: one long stream-json Claude Code session (start, send, events into a status, turn ends, stop with
  grace, the process tree killed; busy from a message to an idle session until its `result`, messages sent while busy
  join the running turn; working while its agents or background commands run; its cost the latest result's running
  total; Claude's usage limit read from Claude Code's own messages). Verified on the real CLI in Music Video Studio
  (Claude Code 2.1.311-2.1.317); copied unchanged.
- `am/claude.py`: the claude command (`AM_CLAUDE` overrides it: the tests use `tests/fake_claude.py`), one headless
  print-mode call (`claude_print`: the story step, the critic), `kill_tree`, a Windows-safe `pid_alive`.
- `am/notes.py`: `review/notes.json` written safely (a lock between threads and a lock file between processes, a
  re-read, an atomic replace): the web app adds notes, the runner forwards them, the director marks them done.
- `am/renderlock.py`: the render queue (one video render at a time on this machine; `render.py` takes it for previews
  and finals, not for stills or the board).
- `am/song.py`: the song folder as an object (`Song.at(t)`: bar:beat, section, chord, sung line and word, moments) and
  `FilmClock` (film time <-> song time through an EDL's audio segments: a film may have one join).
- `am/util.py`: stdlib-only helpers (atomic JSON, a lock file, project.json, the project's song slug).

## How a run differs from Music Video Studio's
- **It delivers a preview round, never the final** (house rule 11: previews only until the user approves). The cut
  the runner watches is the newest `out/<version>_preview.mp4` made in the run; the "no final yet" reminder became "no
  preview yet", the final-render warning "the last preview's time", the early-finish nudge says "never the final".
  `studio.py preview` records the round (`project.json` `rounds`, `out/rounds/`), so every preview a run makes is a
  round the user can compare on the Review page.
- **Nobody answers questions**: the brief skips the skill's interview (decide from the brief; never guess a name or an
  event; assumptions and open questions go into `out/<version>_notes.md`), and when the user hasn't picked a direction
  the director makes the three directions with style frames (so the user still sees them) and builds the one it
  believes in, saying which and why.
- **The sandbox** (`deny_rules`): the studio's folders (`tools/`, `assets/`, `.claude/`, `templates/`, `app/`,
  `models/`) are read-only, so the engine can't be changed in an unattended run (the brief says to build from its
  vocabulary and write any wished-for engine feature into the notes); so are the project's `photos/` and `music/`, the
  user's `review/notes.json` and `review/captions.json` (the director answers a note with `studio.py note-done`), and
  every other project (the reference builders in `projects/elevate-2026/` are readable through `--add-dir`).
  `studio.py permtest <p>` checks it with the real Claude Code (a few cents with Haiku).
- **Where things are**: the run's files in `cache/director/run-N/` (brief.md, command.json, events.jsonl,
  stderr.log, messages.md, status.json, runner_errors.log) and `cache/director/current.json` (for `clock`, `stop` and
  the web app), STOP at `cache/director/STOP`; the director's log `out/director_log.md` (what a continuation reads
  first); the run settings at the end of `out/<version>_notes.md` ("## Run settings (written by the studio)", replaced
  each run) and in project.json `runs`; the critiques in `review/critic/<video>_NN.md + .json` and `log.jsonl`, their
  pending markers in `cache/critic/pending/`.
- **The user's notes during a run**: any note made on the Review page after the run started (its id is when it was
  made, in ms), not done and not forwarded, goes to the director within ~5 s as one message with its context: film
  time, the song's bar:beat, section and sung line at that moment (through the EDL's audio segments), the shot there
  (its id, photos, text); marked `forwarded_run`. Not once the run is stopping, while it waits for the usage limit, or
  with less than 2 minutes left.
- **The critic's scores** add **story** (the order, the people, the jokes landing, every line true of its photo) to
  ambition, song fit, craft and readability. It reads the treatment and the chosen direction (the intent), the song
  map's overview and the song story, the brief and the people, the stylebook's anti-defaults and device budget, the
  skill's house rules, the QA report's verdicts and failures, and the caption board (every line, its source, the
  user's ticks and vetoes); not the director's notes, log or builder. A preview counts as ready for the watcher when
  its QA report is newer than it (`studio.py preview` writes it right after the render), or after 4 minutes.
- No pitch round, live preview, plan tools or versions/deliver: the aftermovie's directions, its builder + EDL with
  the chunk cache, and its review rounds already cover those jobs.

## The critic during an autonomous run
`director.CriticWatcher` critiques the newest ready preview of the run by itself, one at a time, never twice at one
cut: not at one that has a critique already (the path, size and mtime match) or is being critiqued (a marker in
`cache/critic/pending/`, which every critic.py run sets for its cut), nor at an older preview once a newer one is
ready. Such a critique made by the director itself goes into the run's status as it comes (`used`: "the director ran
it"), with no message. At most `--critic-max` critiques a run (default 6); none when its notes couldn't reach the
director in time (6 min left). When the director ends its turn with a preview delivered and time left, the runner waits
up to 4 minutes for the critic's notes on it so the early-finish nudge carries them. At the end of the run a critique
of the delivered preview still running may finish, and one that never started is made then (unless the user stopped
the run), so the Review page has the critic's notes on the cut the user watches.

## Agents in a run (the director's choice)
The same as Music Video Studio's (`tools/INTERNALS.md` there has the verification details): `--allowedTools` has
`Agent` and `TaskStop` and the to-do tools; `SendMessage` and `ListAgents` aren't allowed; `--ultracode` adds
`Workflow`. While any task runs the session is *working* even when the director's own turn has ended: no nudge, no
reminder, no closing (STOP and the deadline + grace still end it); the session starts a turn of its own when the last
one ends. `status.json` lists them (`agents`) with the costs per model (`model_usage`); the run's cost is the session's
latest running total plus the critic's calls. `--max-usd N` passes `--max-budget-usd N` (a hard cap on the session,
its agents included).

## Claude's usage limit, and Continue the last run
Unchanged from Music Video Studio (see `am/session.py` `limit_of` / `reset_at` and `director.Runner.check_limit`):
with `--auto-continue` (the Direct page's checkbox, project.json `director.auto_continue`) the run pauses (`state`
"paused"; nothing goes to the director; no new critique; the clock stopped) and at the reset plus a minute it carries
on (a message to the same session, or `claude --resume <session id>` when the session ended meanwhile, or a fresh
session whose brief says where the work is when that conversation can't be resumed). A reset more than a day away, or
refusals for more than a day, end the run. Without it the run ends at once and `cut_off` says what it had left.
`direct --continue` (the Direct page's Continue the last run) resumes the last run's conversation with the budget it
had left (at least 15 min), waiting first for a limit still to reset.

## The web app
`GET /api/p/<p>/director` (the run's status: the live log, the clock, the agents, the costs per model with the total,
the critiques, `continuable` once it's over), `POST /api/p/<p>/direct` (the Direct form → `studio.py direct` as the
job "direct"; refused while a run started from the command line is going on), `POST director-settings` (the form's
settings kept in project.json `director`), `POST critique` (the Review page's Ask the critic, job "critique"),
`POST story-draft` (the song story drafted headless, job "story"); `stop` asks a director run to wrap up (STOP; forced
after 3 minutes) and ends a critique or a story call with what it started. `project_state` carries `director` and
`critiques` (`review/critic/`, newest first, with which renders it is looking at now). Notes are written through
`am/notes.py`.

## Tests
`tests/test_director.py` (stand-in Claude: no usage spent): the session plumbing, the runner on a simulated clock,
the usage limit and Continue, the critic's parser and the sandbox; `--e2e` adds a synthetic project analysed with the
offline fallbacks and real runs of `direct`, `direct --revise`, a run the limit stops and `direct --continue`, `story`
and `critique`.
