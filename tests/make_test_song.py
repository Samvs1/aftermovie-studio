"""Generate the synthetic test song (nothing downloaded, nothing copyrighted): drums with a clear tempo change and a
stop, a bass line, pads, synth stabs and a synthetic "voice" singing a short lyric, in stereo.

  python tests/make_test_song.py [out_dir]       -> test_song.mp3, test_song.lrc (line times), test_song_words.lrc
                                                    (word times, enhanced LRC), test_song_truth.json

Structure (~65 s): intro 4 bars @120 (pads + hats) · verse 8 bars @120 (drums, bass, voice) · chorus 8 bars @120
(louder, four on the floor, crash) · a one-bar STOP (near silence) · drive 8 bars @140 (tempo change, 16th hats,
stabs) · outro 4 bars @140 ending on a final hit that rings out.
The truth file lists every beat, downbeat, section start, the stop, the tempo change and each sung word, so a test can
check what the analysis found (tests/test_song_kit.py). Carried over from Music Video Studio unchanged.
"""
import json, os, subprocess, sys
import numpy as np

SR = 44100
RNG = np.random.default_rng(7)
NOTE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def hz(name):
    """'C4' -> Hz."""
    n, octv = name[:-1], int(name[-1])
    semi = NOTE[n[0]] + (1 if "#" in n else -1 if n.endswith("b") else 0)
    return 440.0 * 2 ** ((semi + 12 * (octv + 1) - 69) / 12)


def env(n, a=0.005, d=0.2, sustain=0.0, r=0.05):
    t = np.arange(n) / SR
    e = np.minimum(1, t / max(a, 1e-4)) * (sustain + (1 - sustain) * np.exp(-np.maximum(0, t - a) / max(d, 1e-4)))
    tail = int(r * SR)
    if tail and n > tail:
        e[-tail:] *= np.linspace(1, 0, tail)
    return e


def lowpass(x, fc):
    from scipy.signal import lfilter
    a = np.exp(-2 * np.pi * fc / SR)
    return lfilter([1 - a], [1, -a], x)          # one-pole: fine for these sounds


def highpass(x, fc):
    return x - lowpass(x, fc)


def kick():
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    f = 45 + 90 * np.exp(-t / 0.04)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.18)
    x[:200] += np.linspace(0.6, 0, 200)                         # click
    return x * 0.9


def snare():
    n = int(0.22 * SR)
    t = np.arange(n) / SR
    nz = highpass(RNG.standard_normal(n), 1200) * np.exp(-t / 0.07)
    tone = np.sin(2 * np.pi * 185 * t) * np.exp(-t / 0.05)
    return (0.55 * nz + 0.45 * tone) * 0.8


def hat(open_=False):
    n = int((0.22 if open_ else 0.05) * SR)
    t = np.arange(n) / SR
    return highpass(RNG.standard_normal(n), 7000) * np.exp(-t / (0.08 if open_ else 0.015)) * 0.35


def crash():
    n = int(1.8 * SR)
    t = np.arange(n) / SR
    a = highpass(RNG.standard_normal(n), 4500) * np.exp(-t / 0.6)
    b = highpass(RNG.standard_normal(n), 4500) * np.exp(-t / 0.6)
    return np.stack([a, b]) * 0.4


def saw(f, n, detune=0.0):
    t = np.arange(n) / SR
    ph = (t * f * (1 + detune)) % 1.0
    return 2 * ph - 1


def bass_note(f, dur):
    n = int(dur * SR)
    x = 0.7 * np.sin(2 * np.pi * f * np.arange(n) / SR) + 0.3 * lowpass(saw(f, n), 500)
    return x * env(n, 0.005, dur * 0.8, 0.5, 0.04) * 0.75


def pad(freqs, dur):
    n = int(dur * SR)
    L = sum(lowpass(saw(f, n, -0.004), 1800) for f in freqs)
    R = sum(lowpass(saw(f, n, 0.004), 1800) for f in freqs)
    e = env(n, 0.35, 10.0, 1.0, 0.3)
    return np.stack([L * e, R * e]) * 0.12


def stab(freqs, dur=0.12):
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = sum(np.sign(np.sin(2 * np.pi * f * t)) for f in freqs) / len(freqs)
    return lowpass(x, 2500) * env(n, 0.003, 0.06, 0.0, 0.02) * 0.4


def voice(f, dur, vowel="a"):
    """A sung syllable: a vibrato saw through three formants, with a breathy consonant at the onset."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    vib = 1 + 0.006 * np.sin(2 * np.pi * 5.5 * t) * np.minimum(1, t / 0.25)
    src = 2 * ((np.cumsum(f * vib) / SR) % 1.0) - 1
    form = {"a": (730, 1090, 2440), "o": (570, 840, 2410), "i": (390, 1990, 2550), "e": (530, 1840, 2480)}[vowel]
    from scipy.signal import lfilter
    out = np.zeros(n)
    for k, fc in enumerate(form):                               # crude two-pole resonators
        w = 2 * np.pi * fc / SR
        r = 0.985
        out += lfilter([1.0], [1, -2 * r * np.cos(w), r * r], src) * (0.5 ** k)
    out /= np.max(np.abs(out)) + 1e-9
    m = min(n, int(0.03 * SR))
    out[:m] += highpass(RNG.standard_normal(m), 3000) * 0.5 * np.linspace(1, 0, m)
    return out * env(n, 0.02, dur, 0.8, 0.06) * 0.5


class Mix:
    def __init__(self, dur):
        self.buf = np.zeros((2, int(dur * SR) + SR))

    def add(self, t, x, gain=1.0, pan=0.0):
        i = int(round(t * SR))
        if x.ndim == 1:
            x = np.stack([x * np.sqrt((1 - pan) / 2), x * np.sqrt((1 + pan) / 2)]) * np.sqrt(2)
        n = min(x.shape[1], self.buf.shape[1] - i)
        if n > 0:
            self.buf[:, i:i + n] += gain * x[:, :n]


PROG = [("C3", ["C4", "E4", "G4"]), ("A2", ["A3", "C4", "E4"]), ("F2", ["F3", "A3", "C4"]), ("G2", ["G3", "B3", "D4"])]
LYRIC = {
    "verse": [(0, ["neon", "rain", "is", "falling", "down"], ["E4", "G4", "G4", "A4", "G4"], [0, 1, 1.5, 2, 3]),
              (2, ["every", "window", "glows"], ["E4", "D4", "C4"], [0, 1, 2]),
              (4, ["count", "the", "lights", "and", "breathe"], ["E4", "G4", "A4", "G4", "E4"], [0, 1, 1.5, 2, 3]),
              (6, ["nobody", "knows"], ["D4", "C4"], [0, 1.5])],
    "chorus": [(0, ["hold", "the", "light"], ["C5", "B4", "G4"], [0, 1, 2]),
               (2, ["hold", "the", "light", "tonight"], ["C5", "B4", "G4", "A4"], [0, 1, 2, 3]),
               (4, ["hold", "the", "light"], ["C5", "B4", "G4"], [0, 1, 2]),
               (6, ["never", "let", "it", "go"], ["A4", "G4", "E4", "C4"], [0, 1, 2, 2.5])],
    "drive": [(0, ["run", "run", "run"], ["G4", "G4", "A4"], [0, 1, 2]),
              (4, ["into", "the", "morning"], ["A4", "G4", "E4"], [0, 1, 2])],
}
VOWEL = {"neon": "e", "rain": "e", "is": "i", "falling": "a", "down": "a", "every": "e", "window": "i", "glows": "o",
         "count": "a", "the": "e", "lights": "a", "and": "a", "breathe": "i", "nobody": "o", "knows": "o", "hold": "o",
         "light": "a", "tonight": "a", "never": "e", "let": "e", "it": "i", "go": "o", "run": "a", "into": "i",
         "morning": "o"}


def build():
    lead = 0.25
    plan = [("intro", 4, 120), ("verse", 8, 120), ("chorus", 8, 120), ("stop", 1, 120), ("drive", 8, 140), ("outro", 4, 140)]
    total = lead + sum(n * 240 / bpm for _, n, bpm in plan) + 2.6
    M = Mix(total)
    truth = {"beats": [], "downbeats": [], "sections": [], "words": [], "lines": []}
    t = lead
    bar_no = 0
    for name, nbars, bpm in plan:
        beat = 60 / bpm
        truth["sections"].append({"name": name, "t": round(t, 4), "bpm": bpm, "bars": nbars})
        if name == "stop":
            truth["stop"] = {"t0": round(t, 4), "t1": round(t + 4 * beat, 4)}
            M.add(t + 0.0, kick(), 0.25)                           # the band stops dead after one soft hit
            for k in range(4):
                truth["beats"].append(round(t + k * beat, 4))
            truth["downbeats"].append(round(t, 4))
            t += 4 * beat
            bar_no += 1
            continue
        if name == "drive":
            truth["tempo_change"] = round(t, 4)
        g = {"intro": 0.35, "verse": 0.7, "chorus": 1.0, "drive": 1.0, "outro": 0.75}[name]
        for b in range(nbars):
            bt0 = t + b * 4 * beat
            root, chord = PROG[b % 4]
            truth["downbeats"].append(round(bt0, 4))
            for k in range(4):
                truth["beats"].append(round(bt0 + k * beat, 4))
            last_outro = name == "outro" and b == nbars - 1
            if name in ("intro", "verse", "chorus"):
                M.add(bt0, pad([hz(x) for x in chord], 4 * beat + 0.3), g * (1.4 if name == "intro" else 1.0))
            if name == "intro":
                for k in range(8):
                    M.add(bt0 + k * beat / 2, hat(), 0.5 * g, 0.4)
                continue
            if last_outro:                                          # the final hit, then it rings out
                M.add(bt0, kick(), 1.0)
                M.add(bt0, crash(), 1.0)
                M.add(bt0, bass_note(hz(root.replace("2", "1").replace("3", "2")), 2.4), 1.0)
                M.add(bt0, pad([hz(x) for x in PROG[0][1]], 2.5), 1.2)
                truth["final_hit"] = round(bt0, 4)
                break
            kicks = [0, 1, 2, 3] if name == "chorus" else [0, 2]
            for k in kicks:
                M.add(bt0 + k * beat, kick(), g)
            for k in (1, 3):
                M.add(bt0 + k * beat, snare(), g)
            sub = 4 if name == "drive" else 2
            for k in range(4 * sub):
                M.add(bt0 + k * beat / sub, hat(open_=(name == "chorus" and k % 2 == 1)), g * 0.8, 0.45)
            if b == 0 and name in ("chorus", "drive"):
                M.add(bt0, crash(), g)
            for k, dur in ((0, 1.4), (1.5, 0.45), (2, 0.9), (3, 0.45)):
                M.add(bt0 + k * beat, bass_note(hz(root), dur * beat), g)
            if name == "drive":
                for k in (0.5, 1.5, 2.5, 3.5):
                    M.add(bt0 + k * beat, stab([hz(x) for x in chord]), g, -0.5 if k % 2 < 1 else 0.5)
            if name == "outro" and b < nbars - 1:
                M.add(bt0, pad([hz(x) for x in chord], 4 * beat), 0.8)
        for bar_off, words, notes, beats in LYRIC.get(name, []):
            lt = t + bar_off * 4 * beat
            line = {"t": round(lt + beats[0] * beat, 4), "text": " ".join(words)}
            truth["lines"].append(line)
            for i, (w, nm, bb) in enumerate(zip(words, notes, beats)):
                wt = lt + bb * beat
                nxt = (lt + beats[i + 1] * beat) if i + 1 < len(beats) else wt + 1.6 * beat
                M.add(wt, voice(hz(nm), min(nxt - wt - 0.04, 1.5 * beat), VOWEL.get(w, "a")), 0.9 * (1.0 if name != "verse" else 0.95))
                truth["words"].append({"w": w, "t": round(wt, 4)})
        t += nbars * 4 * beat
        bar_no += nbars
    truth["duration"] = round(total, 4)
    y = M.buf[:, :int(total * SR)]
    y = y / (np.max(np.abs(y)) + 1e-9) * 0.89
    return y, truth


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    import soundfile as sf
    y, truth = build()
    wav = os.path.join(out, "test_song.wav")
    sf.write(wav, y.T, SR, subtype="PCM_16")
    mp3 = os.path.join(out, "test_song.mp3")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", wav, "-c:a", "libmp3lame", "-b:a", "192k",
                    "-metadata", "artist=Studio Test", "-metadata", "title=Hold the Light", mp3], check=True)
    os.remove(wav)
    lrc = []
    for x in truth["lines"]:
        m, s = divmod(x["t"], 60)
        lrc.append(f"[{int(m):02d}:{s:05.2f}] {x['text']}")
    open(os.path.join(out, "test_song.lrc"), "w", encoding="utf-8").write("\n".join(lrc) + "\n")
    enh = []                                       # enhanced LRC: every word with its own time (word-timed lyrics)
    for x in truth["lines"]:
        ws = [w for w in truth["words"] if w["t"] >= x["t"] - 1e-3][:len(x["text"].split())]
        m, s = divmod(x["t"], 60)
        enh.append(f"[{int(m):02d}:{s:05.2f}] " + " ".join(f"<{int(w['t'] // 60):02d}:{w['t'] % 60:05.2f}> {w['w']}" for w in ws))
    open(os.path.join(out, "test_song_words.lrc"), "w", encoding="utf-8").write("\n".join(enh) + "\n")
    json.dump(truth, open(os.path.join(out, "test_song_truth.json"), "w"), indent=1)
    print(f"{mp3}  ({truth['duration']:.1f} s, {len(truth['beats'])} beats, {len(truth['words'])} sung words)")


if __name__ == "__main__":
    main()
