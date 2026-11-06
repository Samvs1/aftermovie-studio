"""Tests for the song kit's lyric side (tools/align_lyrics.py, the LRC readers in tools/analyze_audio.py) and, with
--e2e, the song part of ingest on a synthetic song (tests/make_test_song.py) with the offline fallbacks.

  python tests/test_song_kit.py            unit tests (seconds; standard library + the analyze_audio imports)
  python tests/test_song_kit.py --e2e      + ingest --song-only --fallback on the synthetic song in a throwaway
                                             project (projects/_test-songkit-e2e, deleted afterwards; ~1-2 min)
No model is needed: Whisper is faked with word lists, Demucs and beat_this fall back to their offline estimates.
"""
import json, os, shutil, subprocess, sys, tempfile

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ENGINE, "tools"))
import align_lyrics as AL  # noqa: E402

FAILS = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        FAILS.append(what)


def heard(spec):
    """[(word, t)] -> Whisper-like words [{w, t, end}]."""
    return [{"w": w, "t": t, "end": t + 0.3} for w, t in spec]


def sung(text, t0, step=0.4):
    return [(w, round(t0 + step * k, 3)) for k, w in enumerate(text.split())]


def test_anchor():
    texts = ["neon rain is falling down", "every window glows", "hold the light", "never let it go", "into the morning"]
    W = (sung("neo rain is falling down", 8.3) + sung("every window", 12.3) + sung("hold the light", 24.3) +
         sung("hold the light", 28.3) +                      # sung again, written once: a repeat
         sung("never let it go", 32.3) + sung("oh yeah baby yeah", 40.0) +   # heard, not in the lyrics
         sung("into the morning", 49.2))
    W += [("hold", 33.0), ("the", 33.01), ("light", 33.02)] * 4                # stuck Whisper: one moment, again and again
    res = AL.anchor(texts, heard(sorted(W, key=lambda x: x[1])))
    by = {x["text"]: x for x in res["lines"] if x["i"] is not None}
    check(abs(by["neon rain is falling down"]["t"] - 8.3) < 0.05, "a misheard word still places its line")
    check(abs(by["every window glows"]["t"] - 12.3) < 0.05 and by["every window glows"]["heard"] < 1,
          "a line with a word Whisper missed is placed, heard < 1")
    check(abs(by["never let it go"]["t"] - 32.3) < 0.05, "lines after a repeat stay on their own words")
    reps = [x for x in res["lines"] if x["src"] == "repeat"]
    check(len(reps) == 1 and abs(reps[0]["t"] - 28.3) < 0.05, f"a line written once comes back as one repeat ({len(reps)})")
    check(not any(32.9 < x["t"] < 33.1 for x in res["lines"]), "nothing from the stuck loop lands as a line")
    check([h["text"] for h in res["heard_only"]] == ["oh yeah baby yeah"], f"heard_only lists what is in no line: {res['heard_only']}")
    ts = [x["t"] for x in res["lines"]]
    check(ts == sorted(ts) and all(a["end"] <= b["t"] + 1e-6 for a, b in zip(res["lines"], res["lines"][1:])),
          "lines in order, no overlaps")
    check(res["stats"]["usable"] and res["stats"]["lines_heard"] == 5, f"stats {res['stats']}")
    # a line nobody heard goes between its neighbours
    res = AL.anchor(["hold the light", "a line nobody sang here", "never let it go"],
                    heard(sung("hold the light", 10.0) + sung("never let it go", 20.0)))
    mid = res["lines"][1]
    check(mid["src"] == "between" and 10.5 < mid["t"] < 20.0, f"an unheard line goes between ({mid['t']})")
    # the wrong language: nothing matches, not usable
    res = AL.anchor(["hold the light tonight", "never let it go"], heard(sung("je ne sais pas pourquoi mon amour", 5)))
    check(not res["stats"]["usable"], "words that don't match: not usable (the analysis falls back and says so)")


def test_drop_stuck():
    ws = heard([("a", 1.0), ("b", 1.5), ("a", 1.5), ("b", 1.5), ("c", 1.2), ("d", 2.0)])
    out = [w["w"] for w in AL.drop_stuck(ws)]
    check(out == ["a", "b", "a", "d"], f"drop_stuck: same word again at the same moment / going back in time ({out})")


def test_walk():
    text = "[ar: Someone]\n[Verse 1]\n[00:01.00] one two\n[00:02.00] three\n\n[00:03.00] four\n[Male vocal]\n[Chorus]\n" \
           "[00:05.00][00:15.00] la la\n# a comment\n[Outro]\nbye"
    xs = AL.walk(text)
    check([x["text"] for x in xs] == ["one two", "three", "four", "la la", "bye"], f"walk texts {[x['text'] for x in xs]}")
    check([x["part"] for x in xs] == ["Verse 1", "Verse 1", "Verse 1", "Chorus", "Outro"], "walk parts (LRC header and a non-section tag skipped)")
    check([x["stanza"] for x in xs] == [0, 0, 1, 2, 3], f"walk stanzas {[x['stanza'] for x in xs]}")
    check(xs[3]["stamps"] == [5.0, 15.0], "a line with two stamps is sung twice")
    check(AL.lrc_map(text)[15.0] == ("Chorus", 2), "lrc_map")
    check(AL.kind("Final Chorus") == "chorus" and AL.kind("Pre-Chorus") == "pre-chorus" and AL.kind("Male vocal") is None,
          "kind()")
    check(AL.tagged([{"part": "Verse", "stanza": 0}, {"part": "Chorus", "stanza": 1}]) and
          not AL.tagged([{"part": None, "stanza": 0}, {"part": "Chorus", "stanza": 1}]), "tagged(): only when the lyric starts tagged")


def test_entry():
    pj = {"song": {"file": "a.mp3", "slug": "a", "lyrics": "x\ny"}, "songs": {"b": {"lyrics": "[00:01.00] p\n[00:02.00] q\n[00:03.00] r",
                                                                          "lyrics_synced": True, "lyrics_set": [1.0]}}}
    check(AL.lyrics_entry(pj, "a", "a.mp3") is pj["song"], "the project's song: song.lyrics")
    check(AL.lyrics_entry(pj, "b", "b.mp3") is pj["songs"]["b"], "another song: songs.<slug>.lyrics")
    check(AL.lyrics_entry(pj, "c", "c.mp3") == {}, "a song without lyrics: {}")
    check(AL.lyrics_entry({"song": {"file": "a.mp3"}}, "a", "a.mp3") == {"file": "a.mp3"}, "before the first analysis: by file")
    check(AL.lyrics_kind(pj["song"]) == "plain" and AL.lyrics_kind(pj["songs"]["b"]) == "partly" and
          AL.lyrics_kind({}) is None, "lyrics_kind plain / partly / none")
    e = AL.lyrics_entry({}, "z", "z.mp3", create=True)
    check(e == {}, "create=True makes an entry")


def test_lrc_readers():
    import analyze_audio as AA
    t = "[00:12.00] hold the light <00:14.10>\n[00:15.00] <00:15.00> every <00:15.50> window\n[00:20.00][00:40.00] la"
    check(AA.parse_lrc(t) == [(12.0, "hold the light"), (15.0, "every window"), (20.0, "la"), (40.0, "la")], "parse_lrc")
    e = AA.lrc_ends(t)
    check(list(e) == [12.0] and abs(e[12.0] - 14.1) < 1e-6, f"lrc_ends {e}")
    check(AA.lrc_words(t) == {15.0: [("every", 15.0), ("window", 15.5)]}, f"lrc_words {AA.lrc_words(t)}")
    check(AA.parse_lrc("[00:01.00] one\n[00:02.50] two") == [(1.0, "one"), (2.5, "two")], "plain LRCLIB-style LRC unchanged")


def test_server_structure():
    sys.path.insert(0, os.path.join(ENGINE, "app"))
    import server
    rows = [(1, "[00:01.00] a", True, "Verse", 0), (2, "[00:02.00] b", False, "Verse", 0), (3, "[00:03.00] c", False, "Verse", 1),
            (4, "[00:04.00] d", False, "Chorus", 2), (5, "[00:05.00] d", False, None, None)]
    out = server.lyric_structure(rows)
    check(out == ["[Verse]", "[00:01.00] a", "[00:02.00] b", "", "[00:03.00] c", "", "[Chorus]", "[00:04.00] d", "[00:05.00] d"],
          f"lyric_structure puts tags and stanzas back {out}")
    xs = AL.walk("\n".join(out))
    check([(x["part"], x["stanza"]) for x in xs] == [("Verse", 0), ("Verse", 0), ("Verse", 1), ("Chorus", 2), ("Chorus", 2)],
          "... and walk reads them back")
    check(server.lrc_time(61.234) == "01:01.23", "lrc_time")


def test_e2e():
    py = os.path.join(ENGINE, ".venv", "Scripts" if os.name == "nt" else "bin", "python.exe" if os.name == "nt" else "python")
    py = py if os.path.exists(py) else sys.executable
    name = "_test-songkit-e2e"
    pdir = os.path.join(ENGINE, "projects", name)
    tmp = tempfile.mkdtemp()
    try:
        subprocess.run([py, os.path.join(ENGINE, "tests", "make_test_song.py"), tmp], check=True)
        truth = json.load(open(os.path.join(tmp, "test_song_truth.json")))
        lrc = open(os.path.join(tmp, "test_song.lrc"), encoding="utf-8").read().splitlines()
        shutil.rmtree(pdir, ignore_errors=True)
        for d in ("photos", "music", "cache", "out", "review"):
            os.makedirs(os.path.join(pdir, d))
        fn = "Studio Test - Hold the Light.mp3"
        shutil.copyfile(os.path.join(tmp, "test_song.mp3"), os.path.join(pdir, "music", fn))
        lyr = "[Verse 1]\n" + "\n".join(lrc[:4]) + "\n\n[Chorus]\n" + "\n".join(lrc[4:8]) + "\n\n[Bridge]\n" + "\n".join(lrc[8:]) + "\n"
        json.dump({"title": "test", "song": {"file": fn, "lyrics": lyr}, "status": {"stage": "new"}},
                  open(os.path.join(pdir, "project.json"), "w"))
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        r = subprocess.run([py, os.path.join(ENGINE, "tools", "studio.py"), "ingest", name, "--song-only", "--fallback"],
                           env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        check(r.returncode == 0, "ingest --song-only --fallback runs" + ("" if not r.returncode else ": " + r.stdout[-600:] + r.stderr[-600:]))
        slug = "studio_test_hold_the_light"
        sd = os.path.join(pdir, "song", slug)
        for f in ("README.md", "song-map.md", "lyrics.md", "song-story.md", "song-map.json", "envelopes.json", "report.json", "overview.png"):
            check(os.path.exists(os.path.join(sd, f)), f"song folder has {f}")
        m = json.load(open(os.path.join(sd, "song-map.json"), encoding="utf-8"))
        rep = json.load(open(os.path.join(sd, "report.json"), encoding="utf-8"))
        check(m["sections_from"].startswith("the lyric's"), "sections from the lyric's tags")
        want = {s["name"]: s["t"] for s in truth["sections"]}
        got = {s["name"]: s["t0"] for s in m["sections"]}
        check(abs(got.get("verse 1", -9) - want["verse"]) < 0.1 and abs(got.get("chorus", -9) - want["chorus"]) < 0.1 and
              abs(got.get("bridge", -9) - want["drive"]) < 0.1, f"tagged sections start on their first lines {got}")
        check(any("tempo change" in e["kind"] and abs(e["t"] - truth["tempo_change"]) < 2.5 for e in m["moments"]),
              "a tempo-change moment near the real one")
        check(any("ESTIMATED" in w for w in rep["warnings"]) and any("fallback tracker" in w for w in rep["warnings"]),
              "the report says the stems and beats are estimates")
        check(rep["models"]["stems"].startswith("fallback") and "fallback" in rep["models"]["beats"], "report models say fallback")
        lt = [x["t"] for x in m["lyrics"]]
        check(len(lt) == len(truth["lines"]) and max(abs(a - b["t"]) for a, b in zip(lt, truth["lines"])) < 0.1,
              "the user's LRC lines are where they're sung")
        md = open(os.path.join(sd, "song-map.md"), encoding="utf-8").read()
        check("not force-aligned" in md, "the song map says the words are not force-aligned")
        pj = json.load(open(os.path.join(pdir, "project.json"), encoding="utf-8"))
        check(pj["song"]["slug"] == slug and pj["analysis"]["lyrics_source"] == "user (LRC)", f"project.json analysis {pj.get('analysis')}")
    finally:
        shutil.rmtree(pdir, ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for fn in (test_anchor, test_drop_stuck, test_walk, test_entry, test_lrc_readers, test_server_structure):
        print(f"== {fn.__name__}")
        fn()
    if "--e2e" in sys.argv:
        print("== test_e2e")
        test_e2e()
    print(f"\n{'all passed' if not FAILS else f'{len(FAILS)} FAILED'}")
    sys.exit(1 if FAILS else 0)
