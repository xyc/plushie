"""Synthesizes plush Clawd's sound effects into assets/sounds, from nothing
but sine waves and noise: no samples, so nothing to license.

    python3 sounds/make_sounds.py
"""

import os
import wave

import numpy as np

RATE = 44_100
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "sounds")
rng = np.random.default_rng(7)


def t_of(seconds):
    return np.arange(int(seconds * RATE)) / RATE


def tone(freq, seconds, harmonics=(1.0,), phase=None):
    """A tone whose frequency may glide: `freq` is a number or an array."""
    t = t_of(seconds)
    f = np.broadcast_to(np.asarray(freq, dtype=np.float64), t.shape)
    phase = 2 * np.pi * np.cumsum(f) / RATE if phase is None else phase
    out = np.zeros_like(t)
    for n, amp in enumerate(harmonics, start=1):
        out += amp * np.sin(n * phase)
    return out


def envelope(n, attack=0.01, release=0.05, curve=4.0):
    """Quick attack, exponential-ish decay to silence at the end."""
    t = np.arange(n) / RATE
    total = n / RATE
    rise = np.clip(t / max(attack, 1e-4), 0, 1)
    fall = np.clip((total - t) / max(release, 1e-4), 0, 1)
    body = np.exp(-curve * t / total)
    return rise * fall * body


def lowpass(x, cutoff):
    """One-pole low-pass; `cutoff` may vary over time."""
    cutoff = np.broadcast_to(np.asarray(cutoff, dtype=np.float64), x.shape)
    a = 1 - np.exp(-2 * np.pi * cutoff / RATE)
    y = np.zeros_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc += a[i] * (x[i] - acc)
        y[i] = acc
    return y


def glide(f0, f1, seconds, shape=1.0):
    t = t_of(seconds) / seconds
    return f0 + (f1 - f0) * t**shape


def pad(x, before=0.0, after=0.0):
    return np.concatenate([np.zeros(int(before * RATE)), x, np.zeros(int(after * RATE))])


def mix(*parts):
    length = max(len(p) for p in parts)
    out = np.zeros(length)
    for p in parts:
        out[: len(p)] += p
    return out


def save(name, x, peak=0.6):
    x = x / max(1e-9, np.max(np.abs(x))) * peak
    data = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    os.makedirs(OUT, exist_ok=True)
    with wave.open(os.path.join(OUT, f"{name}.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(data.tobytes())
    print(f"{name}.wav  {len(x) / RATE:.2f}s")


def squeak():
    """A rubber-toy squeak: a quick bend up and back with a wobble."""
    s = 0.24
    t = t_of(s) / s
    f = 950 + 520 * np.sin(np.pi * t) + 40 * np.sin(2 * np.pi * 28 * t_of(s))
    x = tone(f, s, harmonics=(1.0, 0.35, 0.18, 0.08))
    return x * envelope(len(x), attack=0.008, release=0.03, curve=1.2)


def boing():
    """A spring: a low tone with a wide, fading wobble in pitch."""
    s = 0.65
    t = t_of(s)
    f = 220 * (1 + 0.45 * np.sin(2 * np.pi * 11 * t) * np.exp(-4 * t)) * (1 + 0.25 * t)
    x = tone(f, s, harmonics=(1.0, 0.25))
    return x * envelope(len(x), attack=0.005, release=0.08, curve=3.0)


def uh_oh():
    """Two falling boops, then the drip of the sweat drop."""
    one = tone(glide(700, 660, 0.13), 0.13, harmonics=(1.0, 0.3, 0.1))
    one *= envelope(len(one), attack=0.01, release=0.04, curve=1.5)
    two = tone(glide(470, 400, 0.24), 0.24, harmonics=(1.0, 0.3, 0.1))
    two *= envelope(len(two), attack=0.01, release=0.08, curve=2.0)
    drip = tone(glide(1300, 2600, 0.07, shape=0.5), 0.07)
    drip *= envelope(len(drip), attack=0.002, release=0.03, curve=3.0) * 0.6
    return mix(pad(one), pad(two, before=0.17), pad(drip, before=0.62))


def bell(freq, seconds):
    """A soft bell: a sine shaped by a decaying inharmonic partner."""
    t = t_of(seconds)
    mod = 2.0 * np.exp(-6 * t) * np.sin(2 * np.pi * freq * 3.5 * t)
    x = np.sin(2 * np.pi * freq * t + mod)
    return x * envelope(len(x), attack=0.004, release=0.1, curve=5.0)


def chime():
    """A shy sparkle: three bell notes going up (C6, E6, G6)."""
    return mix(pad(bell(1047, 0.6)), pad(bell(1319, 0.6), before=0.09), pad(bell(1568, 0.7), before=0.18)) * 0.8


def whee():
    """Being lifted: a rising glide."""
    s = 0.35
    x = tone(glide(380, 1150, s, shape=1.6), s, harmonics=(1.0, 0.2))
    return x * envelope(len(x), attack=0.02, release=0.08, curve=0.8)


def plop():
    """Landing soft: a low thump and a little boop."""
    s = 0.18
    thump = tone(glide(150, 55, s), s) * envelope(int(s * RATE), attack=0.002, release=0.05, curve=5.0)
    noise = lowpass(rng.standard_normal(int(0.08 * RATE)), 900) * envelope(int(0.08 * RATE), 0.001, 0.03, 6.0)
    boop = tone(glide(520, 600, 0.09), 0.09) * envelope(int(0.09 * RATE), 0.005, 0.04, 2.0) * 0.4
    return mix(thump, noise * 2.5, pad(boop, before=0.06))


def sigh():
    """Letting the stuffing out: breathy noise sinking in pitch, a low whistle under it."""
    s = 1.1
    t = t_of(s) / s
    air = lowpass(rng.standard_normal(int(s * RATE)), 2600 * (1 - 0.8 * t) + 200)
    air *= np.sin(np.pi * np.clip(t * 1.1, 0, 1)) ** 1.5
    whistle = tone(glide(480, 190, s, shape=0.8), s) * envelope(int(s * RATE), 0.08, 0.2, 1.5) * 0.25
    return mix(air * 1.6, whistle)


def drowsy():
    """Dozing off: two soft notes falling, slowly."""
    one = tone(523, 0.45, harmonics=(1.0, 0.15)) * envelope(int(0.45 * RATE), 0.06, 0.2, 1.5)
    two = tone(glide(392, 370, 0.7), 0.7, harmonics=(1.0, 0.15)) * envelope(int(0.7 * RATE), 0.08, 0.35, 1.5)
    return mix(pad(one), pad(two, before=0.38)) * 0.8


def pip():
    """A mini Clawd popping in: a tiny high blip."""
    s = 0.08
    x = tone(glide(1500, 2100, s, shape=0.6), s, harmonics=(1.0, 0.2))
    return x * envelope(len(x), attack=0.003, release=0.03, curve=2.0)


save("pat", squeak())
save("happy", boing())
save("oops", uh_oh())
save("blush", chime(), peak=0.45)
save("held", whee(), peak=0.45)
save("drop", plop())
save("deflate", sigh(), peak=0.5)
save("sleepy", drowsy(), peak=0.4)
save("mini", pip(), peak=0.4)
