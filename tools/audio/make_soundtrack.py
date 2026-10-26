"""Synthesize the Physio Buddy film soundtrack and sound effects (no samples, no third-party audio: licence-clean).

    hub/.venv/Scripts/python.exe tools/audio/make_soundtrack.py [--out video/public/audio] [--seconds 35]

120 BPM, so one beat is 15 video frames at 30 fps and the music lines up with the edit in video/src/timeline.ts:
    0-12 s   intro: pad + arpeggio, filter slowly opening, riser into the drop
    12-30 s  main: the patient appears; kick, hats, clap, bass under the same chords
    30-35 s  outro: drums out, last chord rings into the reverb, fade
Also writes whoosh.wav (scene transitions), click.wav (PB-rail latch) and tick.wav (callouts).
"""

import argparse
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, fftconvolve, sosfilt

SR = 44100
BPM = 120
BEAT = 60 / BPM
BAR = 4 * BEAT
RNG = np.random.default_rng(31)

# A minor colour: Am9 | Fmaj7 | C(add9) | G6, one chord per bar
CHORDS = [[57, 60, 64, 67, 71], [53, 57, 60, 64, 69], [48, 55, 60, 62, 64], [55, 59, 62, 64, 67]]
ROOTS = [45, 41, 48, 43]


def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def lp(x, fc, order=2):
    return sosfilt(butter(order, min(fc, SR * 0.45), "low", fs=SR, output="sos"), x)


def hp(x, fc, order=2):
    return sosfilt(butter(order, fc, "high", fs=SR, output="sos"), x)


def bp(x, lo, hi, order=2):
    return sosfilt(butter(order, [lo, hi], "band", fs=SR, output="sos"), x)


def saw(f, n, phase=0.0):
    """Band-limited sawtooth (additive)."""
    t = np.arange(n) / SR
    out = np.zeros(n)
    for k in range(1, int(min(40, (SR / 2) / f)) + 1):
        out += np.sin(2 * np.pi * k * f * t + phase * k) / k
    return out * (2 / np.pi)


def env_adsr(n, a, d, s, r):
    e = np.full(n, s)
    na, nd, nr = int(a * SR), int(d * SR), int(r * SR)
    e[:na] = np.linspace(0, 1, na, endpoint=False)
    e[na:na + nd] = np.linspace(1, s, len(e[na:na + nd]), endpoint=False)
    if nr:
        e[-nr:] *= np.linspace(1, 0, nr)
    return e


def place(buf, x, t0, gain=1.0):
    i = int(t0 * SR)
    if i >= len(buf):
        return
    j = min(len(buf), i + len(x))
    buf[i:j] += gain * x[:j - i]


def opening(n_total, t_open_end):
    """0..1 curve: how far the intro filter has opened (fully open after t_open_end)."""
    t = np.arange(n_total) / SR
    return np.clip(t / t_open_end, 0, 1) ** 1.5


# ------------------------------------------------------------------------------------------------ instruments
def pad(total):
    L, R = np.zeros(total), np.zeros(total)
    n_bar = int(BAR * SR)
    bars = int(np.ceil(total / n_bar))
    for b in range(bars):
        chord = CHORDS[b % 4]
        n = n_bar + int(0.9 * SR)                     # overlap into the next bar (release)
        voice_l, voice_r = np.zeros(n), np.zeros(n)
        for m in chord:
            f = hz(m)
            voice_l += saw(f * 2 ** (-7 / 1200), n, RNG.uniform(0, 6)) + 0.6 * saw(f * 2 ** (5 / 1200), n, RNG.uniform(0, 6))
            voice_r += saw(f * 2 ** (7 / 1200), n, RNG.uniform(0, 6)) + 0.6 * saw(f * 2 ** (-5 / 1200), n, RNG.uniform(0, 6))
        e = env_adsr(n, 0.35, 0.6, 0.8, 0.9)
        place(L, voice_l * e, b * BAR)
        place(R, voice_r * e, b * BAR)
    o = opening(total, 12.0)
    dark_l, dark_r, bright_l, bright_r = lp(L, 500, 4), lp(R, 500, 4), lp(L, 2600, 4), lp(R, 2600, 4)
    return (dark_l * (1 - o) + bright_l * o) * 0.09, (dark_r * (1 - o) + bright_r * o) * 0.09


def pluck(f, n):
    t = np.arange(n) / SR
    x = 0.7 * saw(f, n) + 0.3 * np.sign(np.sin(2 * np.pi * f * t))
    return lp(x, 3200) * np.exp(-t / 0.11)


def arp(total):
    L, R = np.zeros(total), np.zeros(total)
    step = BEAT / 4
    pattern = [0, 2, 4, 1, 3, 4, 2, 1]
    n_note = int(0.45 * SR)
    for i in range(int(total / SR / step)):
        t0 = i * step
        chord = CHORDS[int(t0 / BAR) % 4]
        m = sorted(chord)[pattern[i % 8] % len(chord)] + 12
        x = pluck(hz(m), n_note) * (0.85 if i % 4 == 0 else 0.6)
        pan = 0.5 + 0.25 * np.sin(i * 0.7)
        place(L, x * (1 - pan), t0)
        place(R, x * pan, t0)
    o = opening(total, 10.0)
    L = lp(L, 900, 2) * (1 - o) + L * o
    R = lp(R, 900, 2) * (1 - o) + R * o
    # ping-pong delay, dotted eighth
    d = int(0.75 * BEAT * SR)
    for k, g in ((1, 0.35), (2, 0.2), (3, 0.11)):
        src = R if k % 2 else L
        dst = L if k % 2 else R
        dst[d * k:] += g * src[:-d * k]
    return L * 0.17, R * 0.17


def kick():
    n = int(0.45 * SR)
    t = np.arange(n) / SR
    f = 46 + 120 * np.exp(-t * 28)
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph) * np.exp(-t * 7.5)
    x[:200] += np.hanning(400)[:200] * 0.4 * RNG.standard_normal(200)
    return np.tanh(1.6 * x)


def hat(decay=0.035):
    n = int(0.12 * SR)
    t = np.arange(n) / SR
    return hp(RNG.standard_normal(n), 7500, 4) * np.exp(-t / decay)


def clap():
    n = int(0.3 * SR)
    t = np.arange(n) / SR
    noise = bp(RNG.standard_normal(n), 900, 3200, 2)
    e = np.exp(-t / 0.12)
    for off in (0.0, 0.011, 0.022):
        i = int(off * SR)
        e[i:i + 300] += np.exp(-np.arange(300) / 60) * 0.6
    return noise * e * 0.6


def drums(total, start, end):
    L, R = np.zeros(total), np.zeros(total)
    duck = np.ones(total)
    k, h, c = kick(), hat(), clap()
    beats = int((end - start) / BEAT)
    for b in range(beats):
        t0 = start + b * BEAT
        place(L, k, t0, 0.42)
        place(R, k, t0, 0.42)
        i = int(t0 * SR)
        nd = int(0.28 * SR)
        j = min(total, i + nd)
        duck[i:j] = np.minimum(duck[i:j], 1 - 0.45 * np.exp(-np.arange(j - i) / SR / 0.09))
        place(L, h, t0 + BEAT / 2, 0.16)
        place(R, h, t0 + BEAT / 2, 0.20)
        if b % 2 == 1:
            place(L, c, t0, 0.22)
            place(R, c, t0, 0.22)
        if b % 4 == 3:                                   # little 16th hat fill at the end of each bar
            place(R, hat(0.02), t0 + 3 * BEAT / 4, 0.09)
    return L, R, duck


def bass(total, start, end):
    x = np.zeros(total)
    step = BEAT / 2
    n = int(step * SR * 0.95)
    t = np.arange(n) / SR
    for i in range(int((end - start) / step)):
        t0 = start + i * step
        f = hz(ROOTS[int(t0 / BAR) % 4])
        note = np.sin(2 * np.pi * f * t) + 0.25 * saw(f, n)
        note *= env_adsr(n, 0.005, 0.08, 0.7, 0.05)
        place(x, note, t0)
    return lp(x, 400) * 0.22


def riser(total, t_end, length=2.0):
    n = int(length * SR)
    t = np.arange(n) / SR
    noise = RNG.standard_normal(n)
    out = np.zeros(n)
    blk = 1024
    for i in range(0, n, blk):                       # band-pass sweeping up
        fc = 400 + 6000 * (i / n) ** 2
        seg = noise[max(0, i - 2048):i + blk]
        out[i:i + blk] = bp(seg, fc * 0.7, min(fc * 1.4, SR * 0.45), 2)[-len(out[i:i + blk]):]
    swell = (t / length) ** 2
    tone = np.sin(2 * np.pi * np.cumsum(220 + 660 * (t / length) ** 2) / SR) * 0.15
    x = (out * 0.5 + tone) * swell
    buf = np.zeros(total)
    place(buf, x, t_end - length)
    return buf * 0.25


def impact(total, t0):
    n = int(2.5 * SR)
    t = np.arange(n) / SR
    boom = np.sin(2 * np.pi * np.cumsum(38 + 50 * np.exp(-t * 6)) / SR) * np.exp(-t * 1.8)
    air = lp(RNG.standard_normal(n), 3000) * np.exp(-t * 4) * 0.25
    buf = np.zeros(total)
    place(buf, boom + air, t0)
    return buf * 0.4


def reverb(L, R, seconds=2.6, mix=0.28):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    decay = np.exp(-t * 6.9 / seconds)
    ir_l = lp(RNG.standard_normal(n), 5000) * decay
    ir_r = lp(RNG.standard_normal(n), 5000) * decay
    ir_l[: int(0.012 * SR)] = 0
    ir_r[: int(0.017 * SR)] = 0
    ir_l /= np.sqrt(np.sum(ir_l ** 2))
    ir_r /= np.sqrt(np.sum(ir_r ** 2))
    wl = fftconvolve(L, ir_l)[: len(L)]
    wr = fftconvolve(R, ir_r)[: len(R)]
    return L + mix * wl, R + mix * wr


# ------------------------------------------------------------------------------------------------ mix
def soundtrack(seconds):
    total = int(seconds * SR)
    drop, outro = 12.0, 30.0
    pl, pr = pad(total)
    al, ar = arp(total)
    dl, dr, duck = drums(total, drop, outro)
    b = bass(total, drop, outro)
    rs = riser(total, drop)
    im = impact(total, drop)
    # music bus (pad + arp) through the reverb, ducked by the kick
    ml, mr = reverb(pl + al, pr + ar, mix=0.35)
    ml *= duck
    mr *= duck
    L = ml + dl + b * duck + rs + im
    R = mr + dr + b * duck + rs + im
    # outro: last chord swells, everything fades out by the end
    t = np.arange(total) / SR
    fade = np.clip((seconds - t) / 3.5, 0, 1) ** 1.3
    fade_in = np.clip(t / 0.6, 0, 1)
    L, R = L * fade * fade_in, R * fade * fade_in
    # glue: gentle saturation and peak normalisation to -1 dBFS
    L, R = np.tanh(L * 1.4) / 1.4, np.tanh(R * 1.4) / 1.4
    peak = max(np.abs(L).max(), np.abs(R).max())
    g = 10 ** (-1 / 20) / peak
    return L * g, R * g


def whoosh(seconds=0.7):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    noise = RNG.standard_normal(n)
    out = np.zeros(n)
    blk = 512
    for i in range(0, n, blk):
        u = i / n
        fc = 300 + 3500 * np.sin(np.pi * u) ** 2
        seg = noise[max(0, i - 2048):i + blk]
        out[i:i + blk] = bp(seg, fc * 0.6, min(fc * 1.6, SR * 0.45), 2)[-len(out[i:i + blk]):]
    e = np.sin(np.pi * np.clip(t / seconds, 0, 1)) ** 2
    pan = np.clip(t / seconds, 0, 1)
    x = out * e
    return x * (1 - 0.6 * pan), x * (0.4 + 0.6 * pan)


def click():
    n = int(0.16 * SR)
    t = np.arange(n) / SR
    snap = hp(RNG.standard_normal(n), 2500, 2) * np.exp(-t / 0.004)
    body = np.sin(2 * np.pi * 180 * t) * np.exp(-t / 0.03) * 0.6
    second = np.zeros(n)
    i = int(0.045 * SR)
    second[i:] = hp(RNG.standard_normal(n - i), 3500, 2) * np.exp(-(t[i:] - t[i]) / 0.003) * 0.5
    x = snap + body + second
    return x, x


def tick():
    n = int(0.09 * SR)
    t = np.arange(n) / SR
    f = 1500 + 900 * np.exp(-t * 60)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.018)
    return x * 0.8, x * 0.8


def write_wav(path, L, R, peak_db=-1.0):
    peak = max(np.abs(L).max(), np.abs(R).max(), 1e-9)
    g = 10 ** (peak_db / 20) / peak
    data = np.stack([L * g, R * g], axis=1)
    pcm = np.clip(data * 32767, -32768, 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print("wrote", path, f"{len(L) / SR:.2f} s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="video/public/audio")
    ap.add_argument("--seconds", type=float, default=35.0)
    a = ap.parse_args()
    out = Path(a.out)
    write_wav(out / "bgm.wav", *soundtrack(a.seconds))
    write_wav(out / "whoosh.wav", *whoosh(), peak_db=-3)
    write_wav(out / "click.wav", *click(), peak_db=-2)
    write_wav(out / "tick.wav", *tick(), peak_db=-6)


if __name__ == "__main__":
    main()
