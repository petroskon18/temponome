#!/usr/bin/env python3
"""
Offline simulation: runs the real Engine against fake Tapo lights and synthetic
music, so beat detection and light behavior can be tested without hardware.

Usage:
    python3 tests/simulate.py                       # run the standard scenario set
    python3 tests/simulate.py --amp 0.08 --bpm 120 --hp   # one scenario

--amp   signal amplitude (0.002 = very quiet mic, 0.3 = loud)
--bpm   tempo of the synthetic song
--hp    apply a 150 Hz high-pass, like a laptop microphone
--free  turn "Lock to tempo" off
--seconds  how long to run (default 10)

Needs: numpy, scipy (pip3 install numpy scipy). Does NOT need tapo or sounddevice.
"""
import argparse
import asyncio
import collections
import json
import os
import socket
import struct
import sys
import tempfile
import threading
import time
import types

import numpy as np
from scipy.signal import butter, lfilter, lfilter_zi

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
SR = 44100


CLOCK = {}   # wall time at which the synthetic song started
OUTPUTS = []  # fake speaker streams opened by pass-through
FAILING = set()   # fake Tapo IPs whose commands fail (a bulb unplugged mid-song)


def install_fakes(sent, song):
    class FakeSet:
        def __init__(s, ip): s.ip = ip
        def brightness(s, b): s.b = b; return s
        def hue_saturation(s, h, sat): s.h = h; return s
        def color_temperature(s, ct): s.h = ("white", ct); return s
        async def send(s, bulb):
            await asyncio.sleep(0.12)  # typical Wi-Fi round trip
            if s.ip in FAILING:
                raise OSError("host is down")
            sent[s.ip].append((time.time(), s.b, s.h))

    class Bulb:
        def __init__(s, ip): s.ip = ip
        async def on(s): pass
        async def off(s): sent[s.ip].append((time.time(), "off", None))
        def set(s): return FakeSet(s.ip)
        async def get_device_info(s):     # how the bulb looked before Play: green, 30 %
            return types.SimpleNamespace(device_on=True, brightness=30, hue=120, saturation=80,
                                         color_temp=0, dynamic_light_effect_enable=False)

    class Api:
        def __init__(s, *a, **kw): pass
        def __getattr__(s, model):
            async def connect(ip):
                if ip.startswith("10.9.9."):      # a bulb switched off at the wall: tapo waits ~30 s
                    await asyncio.sleep(30)
                return Bulb(ip)
            return connect

    class Stream:
        def __init__(s, device, channels, samplerate, blocksize, callback):
            s.cb, s.run, s.ch = callback, True, channels
        def __enter__(s):
            def feed():
                t0, k = time.time(), 0
                CLOCK["t0"] = t0
                while s.run:
                    s.cb(np.repeat(song(k * 512 / SR)[:, None], s.ch, axis=1), 512, None, None)
                    k += 1
                    d = t0 + k * 512 / SR - time.time()
                    if d > 0:
                        time.sleep(d)
            threading.Thread(target=feed, daemon=True).start()
            return s
        def __exit__(s, *a): s.run = False

    sys.modules["tapo"] = types.SimpleNamespace(ApiClient=Api)
    class OutStream:
        def __init__(s, device, channels, samplerate, blocksize, callback, finished_callback):
            s.device, s.cb, s.active, s.latency = device, callback, True, 0.01
            OUTPUTS.append(s)
        def start(s): pass
        def close(s): s.active = False

    devices = [{"name": "BlackHole 2ch", "max_input_channels": 2, "max_output_channels": 2},
               {"name": "MacBook Air Speakers", "max_input_channels": 0, "max_output_channels": 2}]
    sys.modules["sounddevice"] = types.SimpleNamespace(InputStream=Stream, OutputStream=OutStream,
                                                       query_devices=lambda: devices)


def make_drums(bpm):
    """A clean drum loop: kick on every beat, a hi-hat between beats, quiet hiss."""
    P = 60 / bpm
    n_loop = int(round(P * SR))
    t = np.arange(n_loop) / SR
    kick = np.sin(2 * np.pi * (50 + 80 * np.exp(-t * 30)) * t) * np.exp(-t * 14)
    spec = np.fft.rfft(np.random.default_rng(3).standard_normal(n_loop))
    spec[np.fft.rfftfreq(n_loop, 1 / SR) < 7000] = 0
    hiss = np.fft.irfft(spec, n_loop)
    th = (t - P / 2) % P
    hat = 0.5 * hiss / hiss.std() * np.exp(-th * 60) * (t >= P / 2)
    loop = 0.3 * (kick + hat)

    def song(t0):
        i = int(round(t0 * SR)) % n_loop
        idx = (i + np.arange(512)) % n_loop
        return (loop[idx] + 0.003 * np.random.randn(512)).astype(np.float32)
    return song


def make_bars(bpm, gap=None):
    """Kick on every beat, the first of each 4-beat bar louder; `gap` = (from, to) seconds of
    song time with no drums (a breakdown), only a soft pad."""
    P = 60 / bpm
    n = int(round(P * SR))
    t = np.arange(n) / SR
    kick = np.sin(2 * np.pi * (50 + 80 * np.exp(-t * 30)) * t) * np.exp(-t * 14)

    def song(t0):
        i0 = int(round(t0 * SR))
        idx = i0 + np.arange(512)
        beat = idx // n
        x = kick[idx % n] * np.where(beat % 4 == 0, 0.6, 0.3)
        if gap:
            x = np.where((idx / SR >= gap[0]) & (idx / SR < gap[1]), 0.0, x)
        pad = 0.05 * np.sin(2 * np.pi * 330 * idx / SR)
        return (x + pad + 0.003 * np.random.randn(512)).astype(np.float32)
    return song


def bars_engine(sent, song, **cfg):
    app = load_app(sent, song)
    import audio_route
    audio_route.BACKEND = FakeRoute()
    e = app.Engine()
    e.cfg.update(email="a", password="b", lock=True, minB=10, maxB=100, smooth=0.05, passthru=True,
                 devices=[{"ip": "1.1.1.1", "model": "l530", "color": "blend", "offset": 0, "calib": 100}])
    e.cfg.update(cfg)
    return e


def run_accent_checks(bpm=120):
    """Beat 1 of each bar flashes fully, beats 2-4 softer."""
    sent = collections.defaultdict(list)
    e = bars_engine(sent, make_bars(bpm), accent=True)
    e.start()
    time.sleep(16)
    rows = [b for t, b, h in sent["1.1.1.1"] if t > time.time() - 6]
    e.stop()
    time.sleep(0.4)
    peaks = [b for a, b, c in zip(rows, rows[1:], rows[2:]) if b > a and b >= c and b >= 40]
    strong = sum(1 for b in peaks if b >= 90)
    soft = sum(1 for b in peaks if b <= 70)
    ok = len(peaks) >= 8 and 0.15 <= strong / max(len(peaks), 1) <= 0.4 and soft >= 2 * strong - 1
    print(f"{'PASS' if ok else 'FAIL'}  stronger beat 1 -> {strong} full flashes, {soft} softer, of {len(peaks)} "
          f"(expect about 1 in 4 full): {peaks}")
    return ok


def run_bar_color_checks(bpm=120):
    """With colors turning every 4 bars (8 s at 120 BPM), the light's hue moves 45 degrees."""
    sent = collections.defaultdict(list)
    e = bars_engine(sent, make_bars(bpm), bar_shift=4, colorA="#ff0000", colorB="#ff0000", mode="fixed")
    e.start()
    time.sleep(22)
    hues = [h for t, b, h in sent["1.1.1.1"]]
    e.stop()
    time.sleep(0.4)
    seen = sorted(set(hues))
    ok = any(abs(h - 44) <= 4 or abs(h - 88) <= 4 for h in seen) and 0 in seen
    print(f"{'PASS' if ok else 'FAIL'}  colors turn every 4 bars -> hues seen {seen} (expect 0, then ~44)")
    return ok


def run_drop_checks(bpm=120):
    """Drums stop for 8 s (a breakdown) then come back: dim meanwhile, full burst on the drop."""
    sent = collections.defaultdict(list)
    e = bars_engine(sent, make_bars(bpm, gap=(14, 22)), drops=True)
    e.start()
    time.sleep(27)
    t0 = CLOCK["t0"]
    rows = [(t - t0, b) for t, b, h in sent["1.1.1.1"]]
    e.stop()
    time.sleep(0.4)
    during = [b for t, b in rows if 18 < t < 21.5]
    after = [(t, b) for t, b in rows if 22 < t < 23.5]
    burst = [t for t, b in after if b == 100]
    ok = during and max(during) <= 40 and burst and len([1 for t, b in after if b >= 90]) >= 2
    print(f"{'PASS' if ok else 'FAIL'}  build-up and drop -> brightest during the breakdown {max(during) if during else '-'} "
          f"(expect <= 40), after the drop {[b for _, b in after]} (expect a full, longer flash)")
    return ok


def make_song(amp, bpm, hp):
    hb, ha = butter(2, 150 / (SR / 2), "high")
    state = {"zi": lfilter_zi(hb, ha) * 0}

    def song(t):
        n = np.arange(512) / SR + t
        P = 60 / bpm
        ph = n % P
        kick = np.sin(2 * np.pi * (55 + 60 * np.exp(-ph * 30)) * ph) * np.exp(-ph * 12)
        bass = 0.5 * np.sin(2 * np.pi * 55 * n) * (0.6 + 0.4 * np.sin(2 * np.pi * n / (4 * P)))
        hph = (n + P / 2) % (P / 2)
        hat = 0.15 * np.random.randn(512) * np.exp(-hph * 60)
        chord = 0.3 * (np.sin(2 * np.pi * 220 * n) + np.sin(2 * np.pi * 277 * n) + np.sin(2 * np.pi * 330 * n))
        x = kick + bass + hat + chord + 0.15 * np.random.randn(512)
        if hp:
            x, state["zi"] = lfilter(hb, ha, x, zi=state["zi"])
        return (x / 2.0 * amp).astype(np.float32)
    return song


def load_app(sent, song):
    os.environ["HOME"] = tempfile.mkdtemp()  # never touch the real saved config
    install_fakes(sent, song)
    old = sys.modules.pop("temponome", None)
    if old is not None:
        old.ENGINE.stop()
        old.GOVEE.close()       # free port 4002 so the new copy gets the lamp's replies
    import temponome as app
    app.CONFIG_PATH = os.path.join(os.environ["HOME"], "cfg.json")
    return app


def run(amp, bpm, hp, lock, seconds):
    sent = collections.defaultdict(list)
    app = load_app(sent, make_song(amp, bpm, hp))

    e = app.Engine()
    e.cfg.update(email="a", password="b", lock=lock, minB=15, maxB=100,
                 devices=[{"ip": "1.1.1.1", "model": "l530", "color": "blend", "offset": 0}])
    e.start()
    time.sleep(seconds)
    vals = [b for t, b, h in sent["1.1.1.1"] if t > time.time() - 5]
    e.stop()
    time.sleep(0.3)
    ok = abs(e.bpm - bpm) / bpm < 0.05 and vals and max(vals) >= 90
    print(f"{'PASS' if ok else 'FAIL'}  amp={amp:<6} bpm={bpm:<4} hp={hp!s:<5} lock={lock!s:<5} "
          f"-> est {e.bpm:5.1f} BPM, beats {e.onsets}, max bright {max(vals) if vals else '-'}, err {e.error!r}")
    return ok


def beat_phase(calib, lead, bpm=120, seconds=10):
    """Median time (s) from each bright command's arrival at the fake bulb to the nearest real beat."""
    sent = collections.defaultdict(list)
    app = load_app(sent, make_song(0.08, bpm, False))
    e = app.Engine()
    e.cfg.update(email="a", password="b", lock=True, minB=10, maxB=100, smooth=0.1, lead=lead,
                 devices=[{"ip": "1.1.1.1", "model": "l530", "color": "blend", "offset": 0, "calib": calib}])
    e.start()
    time.sleep(seconds)
    P = 60 / bpm
    rows = [(t, b) for t, b, h in sent["1.1.1.1"] if t > time.time() - 5]
    e.stop()
    time.sleep(0.3)
    peaks = [t for (t, b), (_, pb) in zip(rows[1:], rows[:-1]) if b >= 90 and pb < 90]
    ph = [((t - CLOCK["t0"]) + P / 2) % P - P / 2 for t in peaks]   # + = after the beat
    return float(np.median(ph)) if ph else None


class FakeGovee:
    """A pretend Govee lamp with LAN Control on: listens on 127.0.0.1:4003 for commands,
    answers devStatus to the sender, and answers multicast scans on 4001."""
    def __init__(self, ip="127.0.0.1", sku="H6051"):
        self.ip, self.sku, self.log, self.run = ip, sku, [], True
        self.cmd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.cmd.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.cmd.bind((ip, 4003))
        self.cmd.settimeout(0.2)
        self.scan = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.scan.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            self.scan.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        self.scan.bind(("", 4001))
        mreq = struct.pack("4s4s", socket.inet_aton("239.255.255.250"), socket.inet_aton(ip))
        self.scan.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        self.scan.settimeout(0.2)
        for f in (self._cmd_loop, self._scan_loop):
            threading.Thread(target=f, daemon=True).start()

    def _cmd_loop(self):
        while self.run:
            try:
                data, addr = self.cmd.recvfrom(4096)
            except socket.timeout:
                continue
            msg = json.loads(data)["msg"]
            self.log.append((time.time(), msg["cmd"], msg["data"]))
            if msg["cmd"] == "devStatus":
                reply = {"msg": {"cmd": "devStatus", "data": {"onOff": 1, "brightness": 50,
                                 "color": {"r": 255, "g": 0, "b": 0}, "colorTemInKelvin": 0}}}
                self.cmd.sendto(json.dumps(reply).encode(), addr)

    def _scan_loop(self):
        while self.run:
            try:
                data, addr = self.scan.recvfrom(4096)
            except socket.timeout:
                continue
            if json.loads(data)["msg"]["cmd"] == "scan":
                reply = {"msg": {"cmd": "scan", "data": {"ip": self.ip, "device": "AA:BB:CC", "sku": self.sku}}}
                self.cmd.sendto(json.dumps(reply).encode(), (addr[0], 4002))

    def close(self):
        self.run = False
        time.sleep(0.3)
        self.cmd.close()
        self.scan.close()


def run_govee_checks(bpm=120):
    ok_all = True
    lamp = FakeGovee()
    try:
        sent = collections.defaultdict(list)
        app = load_app(sent, make_song(0.08, bpm, False))
        # 1) the "Find Govee lamps" search
        found = app.GOVEE.scan(timeout=1.5)
        ok = any(l["ip"] == "127.0.0.1" and l["sku"] == "H6051" for l in found)
        print(f"{'PASS' if ok else 'FAIL'}  govee search -> {found}")
        ok_all &= ok
        # 1b) "Find my lights" without a Tapo login: Govee still found, Tapo explains what is missing
        r = app.scan_all({"email": "", "password": ""})
        ok = (any(l["brand"] == "Govee" and l["ip"] == "127.0.0.1" and l["model"] == "govee" for l in r["lights"])
              and any("Tapo email and password" in n for n in r["notes"]))
        print(f"{'PASS' if ok else 'FAIL'}  find my lights (no Tapo login) -> {r}")
        ok_all &= ok
        # 2) a lamp that does not answer gives a clear message instead of hanging
        try:
            st = app.GOVEE.status("192.0.2.1", timeout=0.5)
        except OSError as err:     # blocked sandbox / no route: also a "not answering" lamp
            st = f"OSError {err.strerror}"
        ok = st is None or str(st).startswith("OSError")
        print(f"{'PASS' if ok else 'FAIL'}  silent govee lamp -> status {st}")
        ok_all &= ok
        # 3) music drives the lamp, on the beat, with no Tapo login
        e = app.Engine()
        e.cfg.update(email="", password="", lock=True, minB=10, maxB=100, smooth=0.1, lead=0,
                     devices=[{"ip": "127.0.0.1", "model": "govee", "color": "blend", "offset": 0, "calib": None}])
        e.start()
        time.sleep(10)
        P = 60 / bpm
        recent = [(t, c, d) for t, c, d in lamp.log if t > time.time() - 5]
        e.stop()
        time.sleep(0.3)
        cmds = {c for _, c, _ in lamp.log}
        bright = [(t, d["value"]) for t, c, d in recent if c == "brightness"]
        peaks = [t for (t, b), (_, pb) in zip(bright[1:], bright[:-1]) if b >= 90 and pb < 90]
        ph = [((t - CLOCK["t0"]) + P / 2) % P - P / 2 for t in peaks]
        med = float(np.median(ph)) if ph else None
        gaps = np.diff([t for t, _ in bright]) if len(bright) > 2 else [0]   # updates per lamp
        ok = (e.error == "" and {"devStatus", "turn", "brightness", "colorwc"} <= cmds
              and bright and max(b for _, b in bright) >= 90 and med is not None and abs(med) < 0.06
              and min(gaps) >= 0.07)
        print(f"{'PASS' if ok else 'FAIL'}  govee music -> commands {sorted(cmds)}, max bright "
              f"{max((b for _, b in bright), default='-')}, peaks land {"-" if med is None else f"{med*1000:+.0f}"} ms from the kick "
              f"(expect ~0), smallest gap {min(gaps)*1000:.0f} ms, err {e.error!r}")
        ok_all &= ok
        # 4) a missing lamp stops Start with the LAN Control hint
        e2 = app.Engine()
        e2.cfg.update(email="", password="",
                      devices=[{"ip": "192.0.2.1", "model": "govee", "color": "blend", "offset": 0, "calib": None}])
        e2.start()
        time.sleep(3)
        ok = "LAN Control" in e2.error and not e2.running    # same hint for silent or unreachable
        print(f"{'PASS' if ok else 'FAIL'}  missing govee lamp -> {e2.error[:90]!r}")
        ok_all &= ok
    finally:
        lamp.close()
    return ok_all


class FakeRoute:
    """CoreAudio stand-in: BlackHole and the MacBook speakers (default)."""
    def __init__(self):
        self.devs = [{"id": 1, "uid": "BH", "name": "BlackHole 2ch", "transport": "virt", "latency_ms": 0.0},
                     {"id": 2, "uid": "MBA", "name": "MacBook Air Speakers", "transport": "bltn", "latency_ms": 14.0}]
        self.cur, self.db = 2, {1: 0.0, 2: -10.0}
    def devices(self): return [dict(d) for d in self.devs]
    def default(self): return self.cur
    def set_default(self, i): self.cur = i
    def volume(self, i): return 1.0
    def set_volume(self, i, v): pass
    def volume_db(self, i): return self.db[i]
    def set_volume_db(self, i, d): self.db[i] = d


def run_passthrough_checks(bpm=120, calib=100):
    """Music plays through Temponome: the light lights up when the kick is heard."""
    sent = collections.defaultdict(list)
    app = load_app(sent, make_song(0.08, bpm, False))
    import audio_route
    route = audio_route.BACKEND = FakeRoute()
    OUTPUTS.clear()
    e = app.Engine()
    e.cfg.update(email="a", password="b", lock=True, minB=10, maxB=100, smooth=0.1, lead=0, passthru=True,
                 devices=[{"ip": "1.1.1.1", "model": "l530", "color": "blend", "offset": 0, "calib": calib}])
    e.start()
    time.sleep(3)
    switched, delay, speaker = route.cur, e.pass_delay, e.speaker
    out = OUTPUTS[-1] if OUTPUTS else None
    time.sleep(9)
    P = 60 / bpm
    rows = [(t, b) for t, b, h in sent["1.1.1.1"] if t > time.time() - 5]
    e.stop()
    time.sleep(0.5)
    heard = delay + 0.014                       # speaker delay (reported 14 ms) beats the 10 ms buffer
    peaks = [t for (t, b), (_, pb) in zip(rows[1:], rows[:-1]) if b >= 90 and pb < 90]
    # the command lands, then the bulb takes `calib` to visibly light up
    ph = [((t + calib / 1000 - heard - CLOCK["t0"]) + P / 2) % P - P / 2 for t in peaks]
    med = float(np.median(ph)) if ph else None
    ok = (switched == 1 and route.cur == 2 and speaker == "MacBook Air Speakers" and out is not None
          and not out.active and 0.1 <= delay <= 0.6 and med is not None and abs(med) < 0.03
          and e.cfg["restore_out"] == "" and route.db[2] == -10.0)
    print(f"{'PASS' if ok else 'FAIL'}  pass-through -> output switched to BlackHole {switched == 1}, put back {route.cur == 2}, "
          f"delay {delay * 1000:.0f} ms, light seen {'-' if med is None else f'{med * 1000:+.0f}'} ms from the heard kick "
          f"(expect ~0), {len(peaks)} flashes")
    return ok


def run_color_pulse_checks(bpm=120):
    """"On each beat: Color": brightness stays put, the color jumps to B on beats and fades to A."""
    sent = collections.defaultdict(list)
    app = load_app(sent, make_song(0.08, bpm, False))
    e = app.Engine()
    e.cfg.update(email="a", password="b", lock=True, minB=10, maxB=60, smooth=0.1, pulse="color",
                 colorA="#ff0000", colorB="#0000ff",
                 devices=[{"ip": "1.1.1.1", "model": "l530", "color": "blend", "offset": 0, "calib": None}])
    e.start()
    time.sleep(9)
    rows = [(t, b, h) for t, b, h in sent["1.1.1.1"] if t > time.time() - 5]
    e.stop()
    time.sleep(0.3)
    bright = {b for _, b, _ in rows}
    hues = [h for _, _, h in rows]
    peaks = sum(1 for a, b in zip(hues, hues[1:]) if b == 240 and a != 240)
    ok = bright == {60} and 0 in hues and peaks >= 0.7 * 5 * bpm / 60
    print(f"{'PASS' if ok else 'FAIL'}  color pulse -> brightness {sorted(bright)} (expect [60]), "
          f"hues seen {sorted(set(hues))}, jumps to blue {peaks} in 5 s (expect ~{5 * bpm // 60})")
    return ok


def make_bass_treble():
    """One second of a deep bass note, then one second of cymbal-like hiss, over and over."""
    n = SR * 2
    t = np.arange(n) / SR
    spec = np.fft.rfft(np.random.default_rng(6).standard_normal(n))
    spec[np.fft.rfftfreq(n, 1 / SR) < 5000] = 0
    hiss = np.fft.irfft(spec, n)
    loop = np.where(t < 1.0, 0.3 * np.sin(2 * np.pi * 70 * t), 0.3 * hiss / hiss.std())

    def song(t0):
        idx = (int(round(t0 * SR)) + np.arange(512)) % n
        return (loop[idx] + 0.002 * np.random.randn(512)).astype(np.float32)
    return song


def run_sound_shape_checks():
    """Sound bars: a bass light and a treble light take turns as the song moves between a bass
    note and hiss; pitch to color: the third light goes red for the bass, blue for the hiss."""
    sent = collections.defaultdict(list)
    app = load_app(sent, make_bass_treble())
    e = app.Engine()
    e.cfg.update(email="a", password="b", lock=True, minB=10, maxB=100, devices=[
        {"ip": "1.1.1.1", "model": "l530", "color": "blend", "offset": 0, "sound": "low"},
        {"ip": "1.1.1.2", "model": "l530", "color": "blend", "offset": 0, "sound": "high"},
        {"ip": "1.1.1.3", "model": "l530", "color": "blend", "offset": 0, "sound": "pitch"}])
    e.start()
    time.sleep(9)
    end = time.time()
    e.stop()
    time.sleep(0.3)

    def at(ip, t, i):           # what the light showed at time t (sends happen on change)
        rows = [r for r in sent[ip] if r[0] <= t]
        return rows[-1][i] if rows else None
    grid = np.arange(end - 6, end, 0.05)
    low = np.array([at("1.1.1.1", t, 1) or 0 for t in grid])
    high = np.array([at("1.1.1.2", t, 1) or 0 for t in grid])
    hue = np.array([at("1.1.1.3", t, 2) or 0 for t in grid])
    both = float(np.mean((low >= 70) & (high >= 70)))
    turns = float(np.mean((low >= 70) | (high >= 70)))
    red, blue = float(np.mean(hue <= 40)), float(np.mean(hue >= 200))
    # both bars are briefly up where the sound switches: each bulb answers in ~0.12 s, so one
    # hasn't dimmed yet while the other has brightened (4 switches in 6 s * ~0.2 s = ~13-17 %)
    ok = turns > 0.8 and both < 0.25 and red > 0.3 and blue > 0.3
    print(f"{'PASS' if ok else 'FAIL'}  sound bars and pitch color -> one bar up {turns:.0%} of the time, "
          f"both {both:.0%}; pitch light red {red:.0%}, blue {blue:.0%}")
    return ok


def run_sound_light_checks(bpm=120):
    """One light follows the kick drum, another the hi-hats (one between each beat)."""
    sent = collections.defaultdict(list)
    app = load_app(sent, make_drums(bpm))
    import audio_route
    audio_route.BACKEND = FakeRoute()
    e = app.Engine()
    e.cfg.update(email="a", password="b", lock=True, minB=10, maxB=100, smooth=0.05, passthru=True, devices=[
        {"ip": "1.1.1.1", "model": "l530", "color": "blend", "offset": 0, "calib": 100, "sound": "kick"},
        {"ip": "1.1.1.2", "model": "l530", "color": "blend", "offset": 0, "calib": 100, "sound": "hats"}])
    e.start()
    time.sleep(9)
    end = time.time()
    e.stop()
    time.sleep(0.3)
    def flashes(ip):
        rows = [b for t, b, h in sent[ip] if t > end - 5]
        return sum(1 for a, b in zip(rows, rows[1:]) if b >= 70 and a < 70)
    kick, hats = flashes("1.1.1.1"), flashes("1.1.1.2")
    want = 5 * bpm / 60
    ok = 0.7 * want <= kick <= 1.3 * want and 0.7 * want <= hats <= 1.3 * want
    print(f"{'PASS' if ok else 'FAIL'}  one sound per light -> kick light {kick} flashes in 5 s, "
          f"hi-hat light {hats} (expect ~{want:.0f} each)")
    return ok


def run_restore_checks():
    """Stop puts every light back the way it looked before Play."""
    lamp = FakeGovee()
    try:
        sent = collections.defaultdict(list)
        app = load_app(sent, make_song(0.08, 120, False))
        e = app.ENGINE
        e.cfg.update(email="a", password="b", devices=[
            {"ip": "1.1.1.5", "model": "l530", "color": "blend", "offset": 0, "calib": None, "name": "Kitchen"},
            {"ip": "127.0.0.1", "model": "govee", "color": "blend", "offset": 0, "calib": None, "name": "Desk"}])
        e.start()
        time.sleep(4)
        pulses = len(sent["1.1.1.5"])
        t_stop = time.time()
        e.stop()
        time.sleep(1.5)
        tapo_after = [(b, h) for t, b, h in sent["1.1.1.5"] if t > t_stop]
        govee_after = [(c, d) for t, c, d in lamp.log if t > t_stop]
        ok = (pulses > 5 and tapo_after and tapo_after[-1] == (30, 120)
              and ("brightness", {"value": 50}) in govee_after
              and ("colorwc", {"color": {"r": 255, "g": 0, "b": 0}, "colorTemInKelvin": 0}) in govee_after
              and not e.running and e.error == "" and e.saved == {})
        print(f"{'PASS' if ok else 'FAIL'}  stop puts lights back -> tapo {tapo_after[-1:] or '-'} (expect (30, 120)), "
              f"govee {[c for c, _ in govee_after]}, err {e.error!r}")
        return ok
    finally:
        lamp.close()


def run_live_relist_checks():
    """Changing the light list while playing applies at once; a light that does not answer
    is reported by name and does not stop the others or cause restart loops."""
    lamp = FakeGovee()
    try:
        app = load_app(collections.defaultdict(list), make_song(0.08, 120, False))
        e = app.ENGINE
        good = {"ip": "127.0.0.1", "model": "govee", "color": "blend", "offset": 0, "calib": None, "name": "Desk"}
        ghost = {"ip": "192.0.2.1", "model": "govee", "color": "blend", "offset": 0, "calib": None, "name": "Ghost"}
        e.cfg.update(email="", password="", devices=[good])
        e.start()
        time.sleep(3)
        app.apply_config({"devices": [good, ghost]})
        time.sleep(6)
        n_after = len(lamp.log)
        time.sleep(4)
        recent = [c for t, c, d in lamp.log[n_after:] if c == "brightness"]
        restarts = e.restarts
        ok = e.running and e.missing == ["Ghost"] and restarts == 1 and len(recent) > 5
        # a colour-only edit must not restart
        app.apply_config({"devices": [dict(good, color="A"), ghost]})
        time.sleep(1)
        ok = ok and e.restarts == 1
        print(f"{'PASS' if ok else 'FAIL'}  live light-list change -> running {e.running}, missing {e.missing}, "
              f"restarts {e.restarts} (expect 1), pulses after change {len(recent)}")
        e.stop()
        time.sleep(0.5)
        return ok
    finally:
        lamp.close()


def run_slow_light_checks():
    """A Tapo bulb that doesn't answer must not stop or darken the others, and Stop must win."""
    sent = collections.defaultdict(list)
    app = load_app(sent, make_song(0.08, 120, False))
    e = app.ENGINE
    dev = lambda ip, name="": {"ip": ip, "model": "l530", "color": "blend", "offset": 0, "calib": None, "name": name}
    e.cfg.update(email="a", password="b", devices=[dev("1.1.1.1")])
    e.start()
    time.sleep(3)
    app.apply_config({"devices": [dev("1.1.1.1"), dev("10.9.9.9", "Off at wall")]})
    time.sleep(1)
    app.apply_config({"devices": [dev("1.1.1.1"), dev("10.9.9.9", "Off at wall"), dev("1.1.1.2")]})
    time.sleep(12)
    recent = [t for t, b, h in sent["1.1.1.1"] if t > time.time() - 3]
    ok1 = e.running and e.missing == ["Off at wall"] and len(recent) > 3
    print(f"{'PASS' if ok1 else 'FAIL'}  slow bulb, two quick edits -> running {e.running}, missing {e.missing}, "
          f"pulses in last 3 s {len(recent)}, error {e.error[:60]!r}")
    app.apply_config({"devices": [dev("1.1.1.1"), dev("10.9.9.8")]})
    time.sleep(0.5)
    e.stop()                                   # user presses Stop while the restart is connecting
    time.sleep(12)
    ok2 = not e.running
    print(f"{'PASS' if ok2 else 'FAIL'}  Stop during a restart stays stopped -> running {e.running}")
    return ok1 and ok2


def run_dropout_checks():
    """A light that stops answering mid-song is named in the status; the other keeps going."""
    sent = collections.defaultdict(list)
    app = load_app(sent, make_song(0.08, 120, False))
    e = app.ENGINE
    dev = lambda ip, name: {"ip": ip, "model": "l530", "color": "blend", "offset": 0, "calib": None, "name": name}
    e.cfg.update(email="a", password="b", devices=[dev("1.1.1.1", "Desk"), dev("1.1.1.66", "Kitchen lamp")])
    e.start()
    time.sleep(4)
    FAILING.add("1.1.1.66")
    time.sleep(4)
    st = app.Handler._state(None)
    recent = [t for t, b, h in sent["1.1.1.1"] if t > time.time() - 2]
    ok = st["status"].startswith("Kitchen lamp stopped answering") and len(recent) > 2
    FAILING.discard("1.1.1.66")
    time.sleep(3)
    ok = ok and app.Handler._state(None)["dropped"] == []      # it recovers when the bulb is back
    print(f"{'PASS' if ok else 'FAIL'}  light drops out mid-song -> status {st['status']!r}, other light pulses {len(recent)}")
    e.stop()
    time.sleep(0.5)
    return ok


def run_calibration_checks():
    ok_all = True
    # 1) calibration commands reach the bulb and report timing
    sent = collections.defaultdict(list)
    app = load_app(sent, make_song(0.08, 120, False))
    e = app.Engine()
    e.cfg.update(email="a", password="b",
                 devices=[{"ip": "1.1.1.1", "model": "l530", "color": "blend", "offset": 0}])
    e.start()
    time.sleep(1.0)
    e.calib_until = time.time() + 10
    time.sleep(0.2)
    n0 = len(sent["1.1.1.1"])
    r1 = e.calib_flash(0, 1)
    r2 = e.calib_flash(0, 100)
    time.sleep(0.5)
    during = sent["1.1.1.1"][n0:]
    e.calib_until = 0
    e.stop()
    time.sleep(0.3)
    ok = (r1["ok"] and r2["ok"] and 100 <= r2["lat"] <= 200 and [b for _, b, _ in during] == [1, 100])
    print(f"{'PASS' if ok else 'FAIL'}  calibration flash -> {r1}, {r2}, sent during calib {[b for _, b, _ in during]}")
    ok_all &= ok
    # 2) a measured bulb delay makes the light fire that much earlier
    base = beat_phase(None, 0)
    cal = beat_phase(250, 0)
    # uncalibrated lead = 0 -> command lands one round trip (0.12 s) after the beat;
    # calibrated lead = round trip + 0.25 s -> command lands 0.25 s before the beat
    ok = base is not None and cal is not None and abs(base - 0.12) < 0.05 and abs(cal + 0.25) < 0.05
    print(f"{'PASS' if ok else 'FAIL'}  calibrated timing -> uncalibrated lands {"-" if base is None else f"{base*1000:+.0f}"} ms "
          f"from the beat (expect +120), calibrated 250 ms lands {"-" if cal is None else f"{cal*1000:+.0f}"} ms (expect -250)")
    ok_all &= ok
    # 3) the grid sits on the kicks, not on the hi-hats between them (old bug: half a beat off)
    for bpm in (95, 128, 140):
        ph = beat_phase(None, 0, bpm=bpm)
        ok = ph is not None and abs(ph - 0.12) < 0.06
        print(f"{'PASS' if ok else 'FAIL'}  on-beat at {bpm} BPM -> lands {"-" if ph is None else f"{ph*1000:+.0f}"} ms from the kick (expect +120)")
        ok_all &= ok
    return ok_all


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--amp", type=float)
    ap.add_argument("--bpm", type=float, default=120)
    ap.add_argument("--hp", action="store_true")
    ap.add_argument("--free", action="store_true")
    ap.add_argument("--seconds", type=float, default=10)
    a = ap.parse_args()
    if a.amp is not None:
        sys.exit(0 if run(a.amp, a.bpm, a.hp, not a.free, a.seconds) else 1)
    cases = [(0.08, 120, True), (0.08, 95, True), (0.004, 140, True),
             (0.08, 120, False), (0.3, 128, False), (0.02, 90, False), (0.002, 120, False)]
    results = [run(amp, bpm, hp, True, a.seconds) for amp, bpm, hp in cases]
    results.append(run_calibration_checks())
    results.append(run_govee_checks())
    results.append(run_live_relist_checks())
    results.append(run_slow_light_checks())
    results.append(run_dropout_checks())
    results.append(run_restore_checks())
    results.append(run_passthrough_checks())
    results.append(run_color_pulse_checks())
    results.append(run_sound_light_checks())
    results.append(run_accent_checks())
    results.append(run_bar_color_checks())
    results.append(run_drop_checks())
    results.append(run_sound_shape_checks())
    print(f"\n{sum(results)}/{len(results)} passed")
    sys.exit(0 if all(results) else 1)
