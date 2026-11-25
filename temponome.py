#!/usr/bin/env python3
"""
Temponome: makes Tapo and Govee lights pulse to music (macOS).

Run:  python3 temponome.py   (or the double-click launcher / Temponome.app)
It opens a page in your browser (served only on your own Mac) where you pick
colors, choose the audio input, and press Start.

Install once:  pip3 install tapo sounddevice numpy
"""
import asyncio
import colorsys
import copy
import errno
import json
import os
import re
import socket
import sys
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

import audio_route
import passthrough

PORT = 8765
SAMPLE_RATE = 44100
BLOCK = 512
CONNECT_TIMEOUT = 5.0   # s: give up on a light that doesn't answer (the tapo default is 30 s)
LOOKAHEAD = 0.7         # s: how far ahead beats are scheduled (max useful light lead)
CONFIG_DIR = os.path.expanduser("~/Library/Application Support/Temponome")
CONFIG_PATH = os.path.join(CONFIG_DIR, "settings.json")
OLD_CONFIG_PATH = os.path.expanduser("~/.tapo_music_ui.json")   # before the rename
# the ui/ folder: next to this file, or inside the bundle when packaged by PyInstaller
UI_DIR = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "ui")

DEFAULTS = {
    "email": "",
    "password": "",
    "device": "",
    "devices": [{"ip": "", "model": "l530", "color": "blend", "offset": 0, "calib": None}],
    "multi": "sync",        # "sync" = all pulse together, "chase" = take turns
    "colorA": "#2a5bff",   # calm / slow tempo
    "colorB": "#ff2a4d",   # energetic / fast tempo
    "mode": "tempo",       # "tempo" = blend A->B by tempo, "fixed" = only color A
    "minB": 15,
    "maxB": 100,
    "sensitivity": 1.5,
    "lock": True,          # steady tempo grid (recommended for microphone)
    "steady": True,        # ignore brief tempo flips and slide the grid instead of jumping
    "passthru": False,     # play the music through Temponome, delayed, so lights land on the hits
    "out_device": "",      # speaker UID for pass-through ("" = the one used before Play)
    "spk_delay": {},       # speaker UID -> its own delay in ms (wireless speakers play late)
    "restore_out": "",     # output to put back after pass-through (kept in case of a crash)
    "restore_vol": False,  # True while BlackHole holds the speaker's volume (see take_over_volume)
    "lead": 60,            # ms to fire early to cover bulb lag
    "smooth": 0.4,         # 0 = snappy short pulses, 1 = long smooth pulses
    "pulse": "brightness", # what a beat changes: "brightness" or "color" (calm A -> energetic B)
    "accent": False,       # stronger flash on the first beat of each bar
    "bar_shift": 0,        # turn the colors around the wheel every 4 or 8 bars (0 = off)
    "drops": False,        # dim during build-ups, burst when the beat drops
}


SOUNDS = ("beat", "kick", "snare", "hats", "low", "mid", "high", "pitch")   # what a light reacts to
BARS = ("low", "mid", "high")   # sound bars: the light's brightness follows that band's level
SHAPE_BANDS = {"low": (40, 250), "mid": (250, 2000), "high": (2000, 12000)}   # Hz
BAR_RANGE = 20.0     # dB from an empty bar to a full one
BAR_FLOOR = 25.0     # dB: a band is never compared with less than the loudest band minus this
LOUD_RANGE = 30.0    # dB from dark to full brightness for "pitch to color"
BAR_FALL = 0.1       # s: half-life of a falling bar (it rises at once)
PITCH_PUSH = 12.0    # pitch to color: how strongly a band louder than its usual level pulls the color
PITCH_USUAL = 4.0    # s: what counts as "usual" for each band
MODELS = ("l530", "l535", "l630", "l900", "l920", "l930", "govee")


def clean_devices(devs):
    out = []
    for d in devs if isinstance(devs, list) else []:
        if not isinstance(d, dict):
            continue
        model = d.get("model", "l530")
        color = d.get("color", "blend")
        out.append({"ip": str(d.get("ip", "")).strip(),
                    "model": model if model in MODELS else "l530",
                    "color": color if color in ("blend", "A", "B") else "blend",
                    "sound": d.get("sound") if d.get("sound") in SOUNDS else "beat",
                    "offset": max(-200, min(300, int(d.get("offset", 0) or 0))),
                    # webcam-measured delay (ms) between the command finishing its round trip
                    # and the bulb visibly lighting up; None = not calibrated
                    "calib": None if d.get("calib") is None else max(-150, min(600, int(d["calib"]))),
                    "name": str(d.get("name", "") or "")[:60]})   # label from the light finder
    return out or copy.deepcopy(DEFAULTS["devices"])


def migrate_config():
    """Copy settings from the old pre-rename file once. Never overwrites the new file;
    the old file is left in place. Returns True if it copied."""
    if os.path.exists(CONFIG_PATH) or not os.path.exists(OLD_CONFIG_PATH):
        return False
    try:
        with open(OLD_CONFIG_PATH) as f:
            data = json.load(f)
    except Exception:
        return False
    save_config(data)
    return os.path.exists(CONFIG_PATH)


def _read_json(path):
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def load_config():
    migrate_config()
    cfg = copy.deepcopy(DEFAULTS)
    saved = _read_json(CONFIG_PATH)
    if saved is None:            # unreadable: fall back to the pre-rename file rather than lose everything
        saved = _read_json(OLD_CONFIG_PATH) or {}
    cfg.update({k: v for k, v in saved.items() if k in DEFAULTS})
    cfg["devices"] = clean_devices(cfg["devices"])
    if saved.get("ip") and not any(d["ip"] for d in cfg["devices"]):  # old single-bulb config
        cfg["devices"][0]["ip"] = saved["ip"]
    return cfg


CONFIG_LOCK = threading.RLock()   # settings are changed from several web-request threads


def save_config(cfg):
    """Write atomically (temp file, then rename) so a crash or quit mid-write can't leave
    a half-written file; the file is never world-readable."""
    with CONFIG_LOCK:
        tmp = CONFIG_PATH + ".tmp"
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(cfg, f)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, CONFIG_PATH)
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass


SECOND_COPY_MSG = ("Another copy of Temponome (or the old Tapo Music launcher) is already running "
                   "and using the Govee connection. Quit it, then press Play again.")


class GoveeBus:
    """Govee "LAN Control" API: JSON over UDP, no account or extra package needed.
    Commands go to the lamp's port 4003; lamps answer (scan, devStatus) to our port 4002.
    Discovery is a multicast "scan" to 239.255.255.250:4001. LAN Control must be switched
    on for each lamp in the Govee Home app. One shared socket on 4002 receives all replies."""
    CMD_PORT, REPLY_PORT = 4003, 4002
    SCAN_ADDR = ("239.255.255.250", 4001)

    def __init__(self):
        self.sock = None
        self.lock = threading.Lock()
        self.waiters = []          # [(predicate(ip, msg), list_to_fill, threading.Event)]

    def _ensure(self):
        with self.lock:
            if self.sock:
                return
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # no SO_REUSEPORT on purpose: a second Temponome (or the old launcher) must fail
            # here instead of silently sharing the port and losing half the lamps' replies
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            try:
                s.bind(("", self.REPLY_PORT))
            except OSError:
                s.close()
                raise OSError(errno.EADDRINUSE, SECOND_COPY_MSG)
            self.sock = s
            threading.Thread(target=self._recv_loop, daemon=True).start()

    def close(self):
        """Release port 4002 (on quit, or before a test loads a fresh copy)."""
        with self.lock:
            s, self.sock = self.sock, None
        if s:
            s.close()

    def _recv_loop(self):
        sock = self.sock
        while True:
            try:
                data, addr = sock.recvfrom(4096)
            except OSError:
                if self.sock is not sock:   # closed: stop this thread
                    return
                time.sleep(0.05)            # a lasting network error must not spin the CPU
                continue
            try:
                msg = json.loads(data.decode("utf-8", "replace")).get("msg", {})
            except Exception:
                continue
            for pred, items, evt in list(self.waiters):
                if pred(addr[0], msg):
                    items.append((addr[0], msg))
                    evt.set()

    def send(self, ip, cmd, data, addr=None):
        self._ensure()
        payload = json.dumps({"msg": {"cmd": cmd, "data": data}}).encode()
        self.sock.sendto(payload, addr or (ip, self.CMD_PORT))

    def _collect(self, pred, send, timeout, first_only):
        items, evt = [], threading.Event()
        w = (pred, items, evt)
        self.waiters.append(w)
        try:
            send()
            if first_only:
                evt.wait(timeout)
            else:
                time.sleep(timeout)
        finally:
            self.waiters.remove(w)
        return items

    def status(self, ip, timeout=2.0):
        """Ask one lamp for its state; None if it does not answer (LAN Control off / wrong IP)."""
        got = self._collect(lambda a, m: a == ip and m.get("cmd") == "devStatus",
                            lambda: self.send(ip, "devStatus", {}), timeout, True)
        return got[0][1].get("data", {}) if got else None

    @staticmethod
    def _local_ips():
        ips = []
        try:   # the address this Mac uses on the home network (no packet is sent)
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("10.255.255.255", 1))
            ips.append(s.getsockname()[0])
            s.close()
        except OSError:
            pass
        return ips + ["127.0.0.1"]

    def scan(self, timeout=2.5):
        """Find Govee lamps with LAN Control on. Returns [{"ip", "sku", "device"}].
        The search is sent out of each local interface; if every send is refused
        (usually macOS Local Network permission), raises OSError."""
        self._ensure()
        payload = json.dumps({"msg": {"cmd": "scan", "data": {"account_topic": "reserve"}}}).encode()
        errors = []

        def send_all():
            sent = 0
            for ip in self._local_ips():
                try:
                    self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
                    self.sock.sendto(payload, self.SCAN_ADDR)
                    sent += 1
                except OSError as e:
                    errors.append(f"{ip}: {e.strerror or e}")
            if not sent:
                raise OSError("could not send the search (" + "; ".join(errors) + "). Allow Terminal under "
                              "System Settings > Privacy & Security > Local Network")

        got = self._collect(lambda a, m: m.get("cmd") == "scan", send_all, timeout, False)
        out = {}
        for ip, m in got:
            d = m.get("data", {})
            out[d.get("ip") or ip] = {"ip": d.get("ip") or ip, "sku": d.get("sku", ""), "device": d.get("device", "")}
        return list(out.values())


GOVEE = GoveeBus()


def scan_tapo(email, password, timeout=3):
    """Find Tapo color lights on the home network with the tapo library's broadcast
    discovery (it logs in to each device, so it needs the Tapo account).
    Returns [{"ip", "model", "name"}] for lights this app can drive."""
    import re
    from tapo import ApiClient

    async def run():
        out = {}
        client = ApiClient(email, password)
        async for r in await client.discover_devices("255.255.255.255", timeout):
            try:
                d = r.get()
            except Exception:
                continue          # a device that refused the login or is not supported
            kind = type(d).__name__
            if kind not in ("ColorLight", "RgbLightStrip", "RgbicLightStrip"):
                continue          # plugs, cameras, white-only bulbs: no color to pulse
            m = re.search(r"l\d{3}", str(d.model).lower())
            model = m.group(0) if m and m.group(0) in MODELS else {
                "ColorLight": "l530", "RgbLightStrip": "l900", "RgbicLightStrip": "l920"}[kind]
            ip = d.address[0]
            out[ip] = {"ip": ip, "model": model, "name": str(d.nickname or "")}
        return list(out.values())

    return asyncio.run(run())


def scan_all(cfg):
    """Search for Tapo and Govee lights at the same time (about 3 s).
    Returns {"lights": [{"brand", "ip", "model", "name"}], "notes": [str]}."""
    lights, notes = [], []
    res = {}

    def tapo():
        if not (cfg.get("email") and cfg.get("password")):
            res["tapo_note"] = "To find Tapo lights, enter your Tapo email and password in Setup first."
            return
        try:
            res["tapo"] = scan_tapo(cfg["email"], cfg["password"])
        except Exception as e:
            res["tapo_note"] = f"Tapo search failed: {e}"

    def govee():
        try:
            res["govee"] = GOVEE.scan()
        except OSError as e:
            res["govee_note"] = SECOND_COPY_MSG if e.errno == errno.EADDRINUSE else f"Govee search failed: {e}"
        except Exception as e:
            res["govee_note"] = f"Govee search failed: {e}"

    threads = [threading.Thread(target=f) for f in (tapo, govee)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(15)
    for l in res.get("tapo", []):
        lights.append({"brand": "Tapo", **l})
    for l in res.get("govee", []):
        lights.append({"brand": "Govee", "ip": l["ip"], "model": "govee",
                       "name": f"Govee {l.get('sku') or 'lamp'}"})
    notes += [res[k] for k in ("tapo_note", "govee_note") if k in res]
    return {"lights": lights, "notes": notes}


class GoveeLamp:
    """Async handle with the same role as a tapo handle. UDP is fire-and-forget, so a send
    returns at once; the real delay is found by the webcam calibration."""
    min_gap = 0.08          # s between updates, so the lamp's Wi-Fi chip is not flooded

    def __init__(self, ip):
        self.ip = ip
        self.last_b = None
        self.last_rgb = None
        self.status = None

    async def connect(self):
        try:
            st = await asyncio.get_running_loop().run_in_executor(None, GOVEE.status, self.ip)
        except OSError as e:
            if e.errno == errno.EADDRINUSE:
                raise ConnectionError(SECOND_COPY_MSG)
            raise ConnectionError(f"Could not reach the Govee lamp ({e.strerror or e}). Check its IP address, "
                                  "and allow Terminal under System Settings > Privacy & Security > "
                                  "Local Network. LAN Control must be on in the Govee Home app.")
        if st is None:
            raise ConnectionError("Govee lamp did not answer. In the Govee Home app open the lamp, "
                                  "Settings, and switch on LAN Control; also check its IP address.")
        self.status = st          # how the lamp looked before Play (put back on Stop)
        return self

    async def on(self):
        GOVEE.send(self.ip, "turn", {"value": 1})

    async def send_state(self, b, hue, sat):
        r, g, bl = colorsys.hsv_to_rgb((hue % 360) / 360.0, max(0, min(100, sat)) / 100.0, 1.0)
        rgb = (int(round(r * 255)), int(round(g * 255)), int(round(bl * 255)))
        if b != self.last_b:          # brightness first: it carries the beat
            GOVEE.send(self.ip, "brightness", {"value": int(max(1, min(100, b)))})
            self.last_b = b
        if rgb != self.last_rgb:
            GOVEE.send(self.ip, "colorwc", {"color": {"r": rgb[0], "g": rgb[1], "b": rgb[2]},
                                            "colorTemInKelvin": 0})
            self.last_rgb = rgb


RESTORE_MSG = "Couldn't put back the earlier look of: "
RESTORE_TIMEOUT = 2.5   # s per light; quitting waits for this


async def take_snapshot(h):
    """How a light looks right now (on/off, brightness, color or white), read before Play
    takes it over. None if it can't be read; that light is then left as the music left it.
    Animated effects from the Tapo/Govee apps can't be read back: their last plain color is used."""
    try:
        if isinstance(h, GoveeLamp):
            st = h.status
            if not st:
                return None
            c = st.get("color") or {}
            return {"on": st.get("onOff", 1) == 1, "b": int(st.get("brightness", 100)),
                    "rgb": (int(c.get("r", 255)), int(c.get("g", 255)), int(c.get("b", 255))),
                    "kelvin": int(st.get("colorTemInKelvin") or 0)}
        info = await asyncio.wait_for(h.get_device_info(), CONNECT_TIMEOUT)
        return {"on": bool(info.device_on), "b": int(info.brightness),
                "hue": info.hue, "sat": info.saturation, "ct": int(info.color_temp or 0)}
    except Exception:
        return None


async def put_back(h, snap):
    """Return a light to a snapshot from take_snapshot."""
    if isinstance(h, GoveeLamp):
        if not snap["on"]:
            GOVEE.send(h.ip, "turn", {"value": 0})
            return
        GOVEE.send(h.ip, "brightness", {"value": max(1, min(100, snap["b"]))})
        if snap["kelvin"]:
            GOVEE.send(h.ip, "colorwc", {"color": {"r": 0, "g": 0, "b": 0}, "colorTemInKelvin": snap["kelvin"]})
        else:
            r, g, b = snap["rgb"]
            GOVEE.send(h.ip, "colorwc", {"color": {"r": r, "g": g, "b": b}, "colorTemInKelvin": 0})
        return
    if not snap["on"]:
        await h.off()
        return
    b = max(1, min(100, snap["b"]))
    try:
        req = h.set().brightness(b)
        if snap["ct"]:                         # it was in white mode
            req = req.color_temperature(snap["ct"])
        elif snap["hue"] is not None:
            req = req.hue_saturation(int(snap["hue"]), int(snap["sat"] or 0))
        await req.send(h)
    except AttributeError:                     # older tapo versions: one setting per command
        await h.set_brightness(b)
        if snap["ct"]:
            await h.set_color_temperature(snap["ct"])
        elif snap["hue"] is not None:
            await h.set_hue_saturation(int(snap["hue"]), int(snap["sat"] or 0))


class BeatTracker:
    """Onset detection + tempo estimation + a steady beat grid (good for noisy mic input)."""
    FPS = SAMPLE_RATE / BLOCK
    HIT_GAP = {"kick": 0.2, "snare": 0.15, "hats": 0.08}   # s: shortest time between two hits
    HIT_RISE = 3.0     # a hit's energy is this many times the band's last 0.3 s

    def __init__(self):
        self.win = 1024
        self.freqs = np.fft.rfftfreq(self.win, 1 / SAMPLE_RATE)
        self.mask = (self.freqs >= 40) & (self.freqs <= 250)
        self.bass_mask = (self.freqs >= 40) & (self.freqs <= 150)
        # separate sounds, so a light can follow just one: snare crack and hi-hat sizzle
        self.band_masks = {"kick": self.bass_mask,
                           "snare": (self.freqs >= 1000) & (self.freqs <= 5000),
                           "hats": (self.freqs >= 7000) & (self.freqs <= 16000)}
        self.band_hist = {b: deque(maxlen=int(self.FPS * 0.3)) for b in self.band_masks}
        self.band_peak = {b: 1e-12 for b in self.band_masks}
        self.hits = {b: deque(maxlen=32) for b in self.HIT_GAP}    # recent hit times per sound
        self.last_hit = {b: 0.0 for b in self.HIT_GAP}
        self.ring = np.zeros(self.win, dtype=np.float32)
        self.prev = None
        self.flux_hist = deque(maxlen=int(self.FPS * 8))
        self.flux_t = deque(maxlen=int(self.FPS * 8))   # time of each flux_hist entry
        self.phase_votes = 0
        self.bass_hist = deque(maxlen=int(self.FPS * 1.0))
        self.lflux_hist = deque(maxlen=int(self.FPS * 1.5))
        self.peak_rms = 1e-4       # auto-gain: recent loudest level
        self.rms = 0.0             # raw input level (for the meter / silence check)
        self.level = 0.0           # loudness relative to recent peak, 0..1
        self.bpm = 110.0
        self.last_onset = 0.0
        self.onset_total = 0
        self.last_est = 0.0
        self.t0 = None
        self.off_grid = 0
        self.last_fired = 0.0
        self.onset_flag = False
        self.onset_count = 0
        self.recent = deque(maxlen=8)   # times of the latest hits (for snapping in pass-through)
        # bars: count beats in fours and learn which of the four hits hardest (= beat 1)
        self.beat_count = 0
        self.last_counted = 0.0
        self.pos_score = [0.0] * 4
        self.down = 0
        self.last_downbeat = False   # was the last scheduled beat the first of its bar?
        self.bar_n = 0               # bars so far
        self.pending = deque()       # (beat time, position) waiting to be measured
        self.bass_t = deque(maxlen=int(self.FPS * 1.0))   # (time, bass energy)
        # build-ups and drops: the kick drum goes away for a while, then comes back hard
        self.bass_fast = self.bass_slow = 0.0
        self.breakdown = False
        self.low_since = None
        self.drop_ref = 0.0
        self.break_t = 0.0
        self.drops = deque(maxlen=8)   # times of drops (as heard)
        self.drop_t0 = None      # when listening started (for the warm-up)
        self.cand, self.cand_n = 0.0, 0
        self.shift_left = 0.0      # phase correction still to apply, gently (s)
        self.grid_t = 0.0          # when the current grid was started
        self.tempo_known = False   # False while bpm is still the 110 placeholder
        self.steady = True         # setting "Smooth out tempo jumps"; off = the pre-Nov-24 rules
        self.glide_t = None
        # sound bars and pitch to color: each band's level against its own recent loudest
        self.shape_masks = {b: (self.freqs >= lo) & (self.freqs < hi) for b, (lo, hi) in SHAPE_BANDS.items()}
        self.shape_peak = {b: 1e-12 for b in SHAPE_BANDS}
        self.shape_lv = {b: 0.0 for b in SHAPE_BANDS}
        self.shape_avg = {b: 0.0 for b in SHAPE_BANDS}   # each band's usual level (~4 s)
        self.loud_peak, self.loud = 1e-12, 0.0
        self.pitch = 0.0
        self.shape_hist = deque(maxlen=int(self.FPS * 1.5))   # (time, snapshot), for shape_at

    # called from the audio thread for every block
    def process(self, block, sens, now=None):
        now = time.time() if now is None else now
        self.ring = np.concatenate([self.ring[len(block):], block])
        mag = np.abs(np.fft.rfft(self.ring * np.hanning(self.win)))
        band = np.log1p(mag[self.mask] * 10.0)
        flux = 0.0 if self.prev is None else float(np.maximum(band - self.prev, 0).sum())
        self.prev = band
        bass = float(mag[self.bass_mask].sum())
        rms = float(np.sqrt(np.mean(block ** 2)))
        self.rms = 0.8 * self.rms + 0.2 * rms
        # auto-gain: follow the loudest recent level (slow ~10 s decay), so quiet mics work too
        self.peak_rms = max(rms, self.peak_rms * 0.9989, 1e-5)
        rel = rms / self.peak_rms
        self.level = 0.9 * self.level + 0.1 * min(rel * 1.4, 1.0)
        self.flux_hist.append(flux)
        self.flux_t.append(now)
        audible = rms > 1e-5 and rel > 0.12

        # detector 1: bass energy jumps above its recent average
        avg = float(np.mean(self.bass_hist)) if len(self.bass_hist) > 10 else 0.0
        self.bass_hist.append(bass)
        self.bass_t.append((now, bass))
        self._learn_bar(now)
        self._watch_drops(bass, rms > 1e-5, now)
        hit_bass = avg > 0 and bass > avg * sens
        # detector 2: sudden rise in low/mid energy (works when the mic cuts deep bass)
        hit_flux = False
        if len(self.lflux_hist) > 20:
            arr = np.asarray(self.lflux_hist)
            hit_flux = flux > arr.mean() + (sens - 1.0) * 4.0 * arr.std() and flux > 1e-3
        self.lflux_hist.append(flux)
        energy = {b: float((mag[m] ** 2).sum()) for b, m in self.band_masks.items()}
        for b, e in energy.items():
            # a hit = this band's energy jumps well above its last 0.3 s, and is loud for this
            # band (compared with its recent loudest, ~10 s memory)
            self.band_peak[b] = max(e, self.band_peak[b] * 0.9989)
            hist = self.band_hist[b]
            if len(hist) >= 8:
                rise = e > self.HIT_RISE * (sum(hist) / len(hist))
                ok = audible and rise and e > 0.08 * self.band_peak[b]
                if b == "hats":      # a snare's sizzle reaches up here too; hi-hats are mostly up here
                    ok = ok and e >= energy["snare"]
                self._hit(b, ok, now)
            hist.append(e)
        self._shape(mag, now)
        onset = (audible and (hit_bass or hit_flux)
                 and now - self.last_onset > 0.22)
        if onset:
            self.last_onset = now
            self.onset_total += 1
            self.onset_flag = True
            self.onset_count += 1
            self.recent.append(now)
            self._align(now)
        self._glide(now)
        if now - self.last_est > 0.5 and len(self.flux_hist) > self.FPS * 4:
            self.last_est = now
            self._estimate_tempo(now)

    def _shape(self, mag, now):
        """Levels of bass / middle / treble (0..1, like the bars of an EQ display), overall
        loudness, and where the sound sits (0 = deep bass .. 1 = treble)."""
        fall = 0.5 ** (1.0 / (self.FPS * BAR_FALL))
        pw = mag ** 2
        energy = {b: float(pw[m].sum()) for b, m in self.shape_masks.items()}
        for b, e in energy.items():
            self.shape_peak[b] = max(e, self.shape_peak[b] * 0.9989, 1e-12)
        top = max(self.shape_peak.values())
        for b, e in energy.items():
            ref = max(self.shape_peak[b], top * 10 ** (-BAR_FLOOR / 10))
            v = min(1.0, max(0.0, 1.0 + 10 * np.log10(max(e, 1e-20) / ref) / BAR_RANGE))
            self.shape_lv[b] = v if v > self.shape_lv[b] else self.shape_lv[b] * fall + v * (1 - fall)
        total = sum(energy.values())
        self.loud_peak = max(total, self.loud_peak * 0.9989, 1e-12)
        v = min(1.0, max(0.0, 1.0 + 10 * np.log10(max(total, 1e-20) / self.loud_peak) / LOUD_RANGE))
        self.loud = v if v > self.loud else self.loud * fall + v * (1 - fall)
        # where the sound sits: real music always has some bass, middle and treble, so a plain
        # average stays green; weight each band by how far it is above its usual level instead
        a = 1.0 / (self.FPS * PITCH_USUAL)
        w = {}
        for b, lv in self.shape_lv.items():
            self.shape_avg[b] += (lv - self.shape_avg[b]) * a
            w[b] = lv * float(np.exp(PITCH_PUSH * (lv - self.shape_avg[b])))
        if sum(w.values()) > 0.02:               # hold the last color while it's quiet
            p = (0.5 * w["mid"] + w["high"]) / sum(w.values())
            self.pitch += (p - self.pitch) * 0.15
        self.shape_hist.append((now, {"levels": dict(self.shape_lv), "pitch": self.pitch, "loud": self.loud}))

    def shape_at(self, t):
        """The sound bars / pitch / loudness as they were at time t (the latest before it)."""
        if not self.shape_hist:
            return {"levels": {b: 0.0 for b in SHAPE_BANDS}, "pitch": 0.0, "loud": 0.0}
        snap = self.shape_hist[0][1]
        for ts, s in self.shape_hist:
            if ts > t:
                break
            snap = s
        return snap

    def _hit(self, band, yes, now):
        if yes and now - self.last_hit[band] > self.HIT_GAP[band]:
            self.last_hit[band] = now
            self.hits[band].append(now)

    def _align(self, now):
        T = 60.0 / self.bpm
        if self.t0 is None:
            self.t0 = self.grid_t = now
            return
        k = round((now - self.t0) / T)
        err = now - (self.t0 + k * T)
        if abs(err) < 0.3 * T:
            young = self.steady and now - self.grid_t < self.SNAP_SECONDS
            self.t0 += (0.5 if young else 0.25) * err   # pull the grid onto the real hits
            self.off_grid = 0
        else:
            self.off_grid += 1         # off-beat / noise: ignore it
            if self.off_grid >= 8:     # grid is clearly wrong: restart from here
                self.t0, self.off_grid, self.grid_t = now, 0, now

    def _estimate_tempo(self, now):
        x = np.array(self.flux_hist, dtype=np.float64)
        x -= x.mean()
        if x.std() < 1e-6:
            return
        n = len(x)
        f = np.fft.rfft(x, 2 * n)
        ac = np.fft.irfft(f * np.conj(f))[:n]
        lo, hi = int(self.FPS * 60 / 170), int(self.FPS * 60 / 70)
        lags = np.arange(lo, hi)
        bpms = 60.0 * self.FPS / lags
        weight = np.exp(-0.5 * (np.log2(bpms / 115.0) / 0.8) ** 2)
        score = ac[lo:hi] * weight
        i = int(np.argmax(score))
        if 0 < i < len(score) - 1:     # parabolic refine
            y0, y1, y2 = score[i - 1], score[i], score[i + 1]
            den = y0 - 2 * y1 + y2
            off = 0.5 * (y0 - y2) / den if den else 0.0
        else:
            off = 0.0
        self._consider_tempo(60.0 * self.FPS / (lags[i] + off), now)
        self._check_phase()

    # How many estimates in a row (one every 0.5 s) a big tempo change needs before it's used.
    # Songs often read as double or half (or 3:2) their tempo for a moment; flipping to it
    # breaks the flash rhythm, so those need twice the proof of a real tempo change.
    NEW_TEMPO_PROOF, RELATED_TEMPO_PROOF = 4, 8

    def _consider_tempo(self, new, now):
        if not self.tempo_known and self.steady:   # replacing the placeholder needs no proof
            self.tempo_known = True
            self._set_bpm(new, now)
            self.grid_t = now
            return
        if abs(np.log(new / self.bpm)) < 0.08:
            self._set_bpm(0.8 * self.bpm + 0.2 * new, now)
            self.cand_n = 0
            return
        if self.cand and abs(np.log(new / self.cand)) < 0.05:
            self.cand_n += 1
        else:
            self.cand, self.cand_n = new, 1
        ratio = new / self.bpm
        related = min(abs(np.log(ratio / m)) for m in (2.0, 0.5, 1.5, 2 / 3)) < 0.06
        need = (self.RELATED_TEMPO_PROOF if related else self.NEW_TEMPO_PROOF) if self.steady else 3
        if self.cand_n >= need:
            self._set_bpm(new, now)
            self.cand_n = 0

    # Phase corrections slide the grid by at most this fraction of a beat per beat, so moving
    # onto the right beat never shows as a double flash or a gap.
    GLIDE_RATE = 0.1
    PHASE_VOTES = 2            # checks in a row (0.5 s apart) that must agree before moving

    SNAP_SECONDS = 8.0          # a grid younger than this jumps straight into place

    def _shift_phase(self, err, now):
        if not self.steady or now - self.grid_t < self.SNAP_SECONDS:
            self.t0 += err
            self.shift_left = 0.0
        else:
            self.shift_left = err

    def _glide(self, now):
        dt = 0.0 if self.glide_t is None else min(0.1, max(0.0, now - self.glide_t))
        self.glide_t = now
        if self.shift_left and self.t0 is not None:
            step = max(-self.GLIDE_RATE * dt, min(self.GLIDE_RATE * dt, self.shift_left))
            self.t0 += step
            self.shift_left -= step
            if abs(self.shift_left) < 1e-4:
                self.shift_left = 0.0

    def _check_phase(self):
        """Make sure the grid sits on the strong beats, not between them.
        Onsets alone can lock it half a beat off (e.g. onto hi-hats between kicks), so
        compare the summed low-band flux along every possible grid position over the
        last few seconds and move the grid if a clearly different position wins twice."""
        if self.t0 is None or self.shift_left or len(self.flux_hist) < self.FPS * 4:
            return
        x = np.asarray(self.flux_hist, dtype=np.float64)
        ts = np.asarray(self.flux_t)
        lag = self.FPS * 60.0 / self.bpm
        n = len(x)
        ks = np.arange(int((n - 1) / lag))
        if len(ks) < 4:
            return
        phis = np.arange(int(lag))
        idx = (n - 1 - phis[:, None] - ks[None, :] * lag).round().astype(int)
        # take the local max within +-1 frame so small timing wobble doesn't matter
        lo, hi = np.clip(idx - 1, 0, n - 1), np.clip(idx + 1, 0, n - 1)
        score = np.maximum(np.maximum(x[lo], x[np.clip(idx, 0, n - 1)]), x[hi]).sum(axis=1)
        best = int(np.argmax(score))
        beat = ts[n - 1 - best]
        T = 60.0 / self.bpm
        err = (beat - self.t0 + T / 2) % T - T / 2
        cur = int(round(((ts[-1] - self.t0) % T) * self.FPS)) % len(phis)   # current grid position
        if abs(err) > 0.2 * T and score[best] > 1.15 * score[cur]:
            self.phase_votes += 1
            if self.phase_votes >= self.PHASE_VOTES:
                self._shift_phase(err, ts[-1])
                self.off_grid = 0
                self.phase_votes = 0
        else:
            self.phase_votes = 0

    def _set_bpm(self, new, now):
        if self.t0 is not None:        # keep the grid phase when the period changes
            T = 60.0 / self.bpm
            k = np.floor((now - self.t0) / T)
            self.t0 += k * T
        self.bpm = new

    # Beat events: each is the time at which a beat will (or did) land.
    # Locked mode looks ahead so every light can be scheduled at its own lead time.
    SNAP = 0.15     # pass-through: a grid beat moves to a real hit this close (fraction of a beat)

    def poll_events(self, now, lookahead, locked, snap=False):
        """Beat times (when each will be heard). `snap`: with pass-through the real hits are
        already known before they are heard, so a grid beat moves onto a nearby real hit."""
        if not locked:
            fire, self.onset_flag = self.onset_flag, False
            return [self._count_beat(self.last_onset)] if fire else []
        self.onset_flag = False
        if self.t0 is None or now - self.last_onset > 2.5:
            return []
        T = 60.0 / self.bpm
        tt = now + lookahead
        beat = self.t0 + np.floor((tt - self.t0) / T) * T
        if beat > self.last_fired + 0.5 * T:
            self.last_fired = beat
            if snap:
                near = [h for h in self.recent if abs(h - beat) <= self.SNAP * T]
                if near:
                    beat = min(near, key=lambda h: abs(h - beat))
            return [self._count_beat(beat)]
        return []

    def _count_beat(self, t):
        T = 60.0 / self.bpm
        if self.last_counted and t - self.last_counted > 1.5 * T:
            # beats were skipped (a quiet moment): count them, so the bar keeps its place
            self.beat_count += int(round((t - self.last_counted) / T)) - 1
        self.last_counted = t
        pos = self.beat_count % 4
        self.beat_count += 1
        self.pending.append((t, pos))
        self.last_downbeat = pos == self.down
        if self.last_downbeat:
            self.bar_n += 1
        return t

    def _learn_bar(self, now):
        """Once a scheduled beat has been heard, score how hard the bass hit at that moment;
        the position (of four) that keeps hitting hardest is taken as beat 1."""
        while self.pending and self.pending[0][0] < now - 0.06:
            t, pos = self.pending.popleft()
            near = [b for bt, b in self.bass_t if abs(bt - t) < 0.06]
            if not near:
                continue
            self.pos_score = [0.99 * x for x in self.pos_score]
            self.pos_score[pos] += max(near)
            best = int(np.argmax(self.pos_score))
            if self.pos_score[best] > self.BAR_MARGIN * self.pos_score[self.down]:
                self.down = best           # only move beat 1 when another beat is clearly stronger

    BAR_MARGIN = 1.2
    BREAK_LOW, BREAK_SECONDS, DROP_BACK = 0.3, 2.0, 0.6
    BREAK_MAX = 90.0    # s: a longer "breakdown" is just a quiet part of the song

    def _watch_drops(self, bass, audible, now):
        """Breakdown: the bass falls below 30 % of its usual level for 2 s. Drop: it comes
        back to 60 % of the level before the breakdown."""
        a_fast, a_slow = 1.0 / (self.FPS * 0.5), 1.0 / (self.FPS * 15.0)
        self.bass_fast += a_fast * (bass - self.bass_fast)
        if not self.breakdown:
            if self.drop_t0 is None:
                self.drop_t0 = now
            if now - self.drop_t0 < 4.0:          # warming up: learn the usual level first
                self.bass_slow = self.bass_fast
                return
            self.bass_slow += a_slow * (bass - self.bass_slow)
            if audible and self.bass_fast < self.BREAK_LOW * self.bass_slow:
                self.low_since = self.low_since or now
                if now - self.low_since > self.BREAK_SECONDS:
                    self.breakdown, self.drop_ref, self.break_t = True, self.bass_slow, now
            else:
                self.low_since = None
        elif self.bass_fast > self.DROP_BACK * self.drop_ref:
            kick = self.last_hit.get("kick", 0.0)
            self.drops.append(kick if now - kick < 0.5 else now)   # the hit that brought it back
            self.breakdown, self.low_since = False, None
        elif now - self.break_t > self.BREAK_MAX:
            self.breakdown, self.low_since = False, None

    def time_to_next(self, now):
        if self.t0 is None or now - self.last_onset > 2.5:
            return None
        T = 60.0 / self.bpm
        return T - ((now - self.t0) % T)


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def live_color_hex(cfg, bpm):
    """The lights' current blended colour at full brightness, as #rrggbb (for the platter)."""
    return hsv_hex(*pick_color(cfg, bpm))


def hue_sat(hex_color):
    """#rrggbb -> (hue 0-359, saturation 0-100) as the lamps take it (brightness is separate)."""
    h, s, _ = colorsys.rgb_to_hsv(*hex_to_rgb(hex_color))
    return int(round(h * 360)) % 360, int(round(s * 100))


def pick_color(cfg, bpm, which="blend"):
    """The color a light should show now, as (hue, saturation).

    Blending calm (A) -> energetic (B) by tempo goes around the color wheel (shortest way)
    with saturation changing evenly, so the middle stays vivid; mixing red/green/blue
    directly would turn opposite colors into white halfway. White (saturation 0) has no
    hue of its own, so it takes the other color's."""
    if which == "A" or (which == "blend" and cfg["mode"] == "fixed"):
        return hue_sat(cfg["colorA"])
    if which == "B":
        return hue_sat(cfg["colorB"])
    return blend_colors(cfg, (bpm - 60) / 120)


def blend_colors(cfg, t):
    """Calm (A) at t=0 to energetic (B) at t=1, around the color wheel (see pick_color)."""
    (ha, sa), (hb, sb) = hue_sat(cfg["colorA"]), hue_sat(cfg["colorB"])
    if sa == 0:
        ha = hb
    if sb == 0:
        hb = ha
    t = min(max(t, 0.0), 1.0)
    diff = ((hb - ha + 180) % 360) - 180
    return int(round(ha + diff * t)) % 360, int(round(sa + (sb - sa) * t))


ACCENT_SOFT = 0.55      # beats 2-4 flash this hard when beat 1 is stronger
BURST_SECONDS, BURST_HALF_LIFE = 1.0, 0.6   # the burst when the beat drops: full, then a slow fade
BAR_TURN = 45      # degrees the colors turn around the wheel every few bars


def turn_colors(cfg, steps):
    """cfg with colors A and B both turned `steps` x BAR_TURN degrees around the wheel
    (white stays white), for "change colors every few bars"."""
    out = dict(cfg)
    for k in ("colorA", "colorB"):
        r, g, b = hex_to_rgb(cfg[k])
        h, sat, v = colorsys.rgb_to_hsv(r, g, b)
        if sat > 0:
            r, g, b = colorsys.hsv_to_rgb((h + steps * BAR_TURN / 360.0) % 1.0, sat, v)
            out[k] = "#%02x%02x%02x" % tuple(int(round(c * 255)) for c in (r, g, b))
    return out


PULSE_STEPS = 4     # color pulse fades through A, 3 colors between, and B


def pulse_color(cfg, env):
    """Color pulse: the light shows B on a beat (env 1) and fades back to A (env 0), in a
    few steps so a slow bulb isn't flooded with commands."""
    return blend_colors(cfg, round(env * PULSE_STEPS) / PULSE_STEPS)


def hsv_hex(hue, sat):
    r, g, b = colorsys.hsv_to_rgb((hue % 360) / 360.0, max(0, min(100, sat)) / 100.0, 1.0)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


PREVIEW_SECONDS = 1.5
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def pitch_hue(p):
    """Where the sound sits -> hue: deep bass red (0), voices green (120), treble blue (240)."""
    return int(round(240 * min(1.0, max(0.0, p))))


def preview_color(hex_color):
    """Show one color on every connected light for a moment (Settings -> Colors)."""
    if not isinstance(hex_color, str) or not HEX_COLOR.match(hex_color):
        return {"ok": False, "error": "That isn't a color."}
    if not ENGINE.running:
        return {"ok": False, "error": "Press Play first so Temponome is connected to your lights."}
    hue, sat = hue_sat(hex_color)
    ENGINE.preview = (hue, sat, time.time() + PREVIEW_SECONDS)
    return {"ok": True}


PASS_SPARE = 0.06


def pass_delay(leads, spk_s):
    """How long pass-through holds the music back (s): long enough for the slowest light
    to light up on the hit, after allowing 40 ms to spot the hit and the speaker's own delay.
    PASS_SPARE covers a light answering slower later on (real Tapo replies vary by ~90 ms)."""
    need = (max(leads) if leads else 0.0) + 0.04 + PASS_SPARE - spk_s
    return round(max(0.10, min(0.60, need)), 3)


def light_lead(L, dcfg, cfg, mean_lat):
    """How early (s) a light's command must go out so the light is seen on the beat."""
    nudge = cfg["lead"] / 1000.0 + dcfg.get("offset", 0) / 1000.0
    if dcfg.get("calib") is not None:
        # calibrated: its live round trip plus the webcam-measured time it takes to visibly brighten
        lead = L.lat + dcfg["calib"] / 1000.0 + nudge
    else:
        # slower-than-average lights fire earlier, faster ones later, so they land together
        lead = nudge + max(-0.15, min(0.25, 0.5 * (L.lat - mean_lat)))
    return max(-0.2, min(LOOKAHEAD - 0.05, lead))


def next_hit_in(hits, now):
    """Seconds until a drum's next hit, guessed from the spacing of its last few hits when
    they come regularly (most drum parts repeat); None when they don't."""
    times = [t for t, _ in hits][-5:]
    if len(times) < 4:
        return None
    gaps = np.diff(times)
    gap = float(np.median(gaps))
    if gap <= 0 or np.max(np.abs(gaps - gap)) > 0.15 * gap:
        return None
    nxt = times[-1] + gap
    while nxt <= now:
        nxt += gap
    return nxt - now


def outputs_info():
    """For Settings > Sound: the speakers pass-through can play to, and whether BlackHole exists."""
    try:
        outs = audio_route.list_outputs()
        prev = ENGINE.cfg.get("restore_out") or audio_route.default_output()
        cur = audio_route.pick_speaker("", prev)
    except Exception:
        return {"outputs": [], "blackhole": False, "current": ""}
    return {"outputs": [{"uid": o["uid"], "name": o["name"], "latency_ms": o["latency_ms"],
                         "builtin": o["builtin"]} for o in outs if not o["blackhole"]],
            "blackhole": any(o["blackhole"] for o in outs), "current": cur["uid"] if cur else ""}


class Engine:
    def __init__(self):
        self.cfg = load_config()
        self.running = False
        self.error = ""
        self.bpm = 0.0
        self.brightness = 0
        self.lights = 0
        self.lat = []
        self.level = 0.0
        self.onsets = 0
        self.locked = None
        self.tasks = set()
        self.flash = False
        self.rms = 0.0
        self.stop_evt = threading.Event()
        self.thread = None
        # webcam calibration: while calib_until is in the future, music output pauses and
        # the page drives the lights one command at a time through calib_q
        self.calib_until = 0.0
        self.calib_q = deque()
        self.calib_log = {}
        self.calib_n = 0
        self.light_info = []    # [{"pos", "idx", "ip"}] for the connected lights
        self.lamps = []         # [{"name", "b", "hex", "ok"}]: what each light shows now (deck lamps)
        self.saved = {}         # ip -> how that light looked before Play (take_snapshot); kept across restarts
        self.preview = None     # (hue, sat, until): a color shown on all lights from Settings
        self.missing = []       # names (or IPs) of lights that did not answer at the last start
        self.restarts = 0
        self.beats = 0          # counts fired beats; the page pulses the platter when it changes
        self.restart_lock = threading.Lock()
        self.want_running = False   # what the user asked for (Play/Stop); a restart honours it
        self.connecting = False     # True while connecting to the lights
        self.audio_open = False     # True once the audio input is open
        self.dropped = []           # names of lights that stopped answering while playing
        self.pass_delay = 0.0       # s the music is held back by pass-through (0 = off)
        self.speaker = ""           # speaker pass-through plays to
        self.speaker_lost = ""      # speaker it fell back to after the chosen one went away

    def restart(self):
        """Stop, wait until the engine thread has really finished, then start again —
        unless the user pressed Stop meanwhile."""
        with self.restart_lock:
            self.restarts += 1
            self.stop_evt.set()
            t = self.thread
            if t:
                t.join(15.0)      # connects are capped at CONNECT_TIMEOUT, so this ends quickly
            if self.want_running and not (t and t.is_alive()):
                self._start_thread()

    def start(self):
        """User pressed Play."""
        self.want_running = True
        self._start_thread()

    def stop(self):
        """User pressed Stop (or the app is quitting)."""
        self.want_running = False
        self.stop_evt.set()

    def _start_thread(self):
        if self.running:
            return
        self.error = ""
        self.stop_evt.clear()
        self.running = True
        self.thread = threading.Thread(target=self._thread, daemon=True)
        self.thread.start()

    def _thread(self):
        try:
            asyncio.run(self._run())
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
        finally:
            self.connecting = False
            self.audio_open = False
            self.dropped = []
            self.lamps = []
            self.preview = None
            self.pass_delay = 0.0
            self.speaker = self.speaker_lost = ""
            self.running = False

    async def _send(self, light, b, hue, sat):
        t_start = time.time()
        try:
            h = light.handle
            if isinstance(h, GoveeLamp):
                await h.send_state(b, hue, sat)
            else:
                await self._send_tapo(h, b, hue, sat)
            light.last_sent = (b, hue, sat)
            light.lat = 0.7 * light.lat + 0.3 * (time.time() - t_start)
            light.fails = 0
        except Exception as e:
            light.fails += 1          # 3 failures in a row = the light stopped answering
            self.error = f"{light.ip}: {e}"
        finally:
            light.last_send_t = time.time()
            light.busy = False

    @staticmethod
    async def _send_tapo(h, b, hue, sat):
        try:
            await asyncio.wait_for(h.set().brightness(b).hue_saturation(hue, sat).send(h), 3.0)
        except AttributeError:
            await asyncio.wait_for(h.set_brightness(b), 3.0)
            await asyncio.wait_for(h.set_hue_saturation(hue, sat), 3.0)

    def calib_flash(self, pos, b, timeout=5.0):
        """Called from a web request: set light `pos` to brightness b and wait for the command.
        Returns {"t": ms when the command started, "lat": round trip ms, "ok": bool}."""
        self.calib_n += 1
        rid = self.calib_n
        self.calib_q.append((rid, pos, b))
        end = time.time() + timeout
        while time.time() < end:
            r = self.calib_log.pop(rid, None)
            if r:
                return r
            time.sleep(0.005)
        return {"ok": False, "t": 0, "lat": 0}

    async def _calib_send(self, light, rid, b):
        while light.busy:
            await asyncio.sleep(0.003)
        light.busy = True
        t = time.time()
        await self._send(light, b, 0, 1)     # near-white, only brightness changes
        self.calib_log[rid] = {"ok": light.last_sent[0] == b, "t": t * 1000.0,
                               "lat": (time.time() - t) * 1000.0}

    async def _run(self):
        import sounddevice as sd

        c = self.cfg
        devs = [(i, d) for i, d in enumerate(c["devices"]) if d["ip"]]
        if not devs:
            raise ValueError("Add at least one light.")
        client = None
        if any(d["model"] != "govee" for _, d in devs):
            if not (c["email"] and c["password"]):
                raise ValueError("Tapo lights need your Tapo account email and password (Setup section).")
            from tapo import ApiClient
            try:
                client = ApiClient(c["email"], c["password"], timeout_s=int(CONNECT_TIMEOUT))
            except TypeError:       # older tapo versions have no timeout option
                client = ApiClient(c["email"], c["password"])

        async def connect(i, d):
            if d["model"] == "govee":
                h = await GoveeLamp(d["ip"]).connect()
            else:
                h = await getattr(client, d["model"])(d["ip"])
            if d["ip"] not in self.saved:   # a background restart keeps the first snapshot
                snap = await take_snapshot(h)
                if snap:
                    self.saved[d["ip"]] = snap
            await h.on()
            L = Light(h, i, d["ip"])
            L.name = d.get("name") or d["ip"]
            L.min_gap = getattr(h, "min_gap", 0.07)
            return L

        async def connect_capped(i, d):   # a switched-off bulb must not hold up the others
            return await asyncio.wait_for(connect(i, d), CONNECT_TIMEOUT)

        self.connecting = True
        try:
            results = await asyncio.gather(*[connect_capped(i, d) for i, d in devs],
                                           return_exceptions=True)
        finally:
            self.connecting = False
        lights, problems, missing = [], [], []
        for (i, d), r in zip(devs, results):
            if isinstance(r, Exception):
                problems.append(f"{d['ip']}: " + ("did not answer in time" if isinstance(r, asyncio.TimeoutError)
                                                  else f"{type(r).__name__}: {r}" if not str(r) else str(r)))
                missing.append(d.get("name") or d["ip"])
            else:
                lights.append(r)
        try:
            await self._play(lights, problems, missing, c, sd)
        finally:
            await self._put_back(lights)

    async def _put_back(self, lights):
        """After playing: return each light to how it looked before Play. A background
        restart (light list changed while playing) only puts back lights that left the list."""
        for _ in range(100):                    # let commands already on their way land first
            if not any(L.busy for L in lights):
                break
            await asyncio.sleep(0.01)
        restarting = self.want_running and self.stop_evt.is_set()   # not Stop, not a crash
        keep = {d["ip"] for d in self.cfg["devices"] if d["ip"]} if restarting else set()
        todo = [(L, self.saved.pop(L.ip)) for L in lights if L.ip not in keep and L.ip in self.saved]
        results = await asyncio.gather(*[asyncio.wait_for(put_back(L.handle, snap), RESTORE_TIMEOUT)
                                         for L, snap in todo], return_exceptions=True)
        failed = [L.name for (L, _), r in zip(todo, results) if isinstance(r, Exception)]
        if not restarting:
            self.saved.clear()
        if not self.want_running:              # the user pressed Stop: say only what matters now
            self.error = (RESTORE_MSG + ", ".join(failed)) if failed else ""

    async def _play(self, lights, problems, missing, c, sd):
        if self.stop_evt.is_set():          # Stop or a newer restart arrived while connecting
            return
        self.missing = missing
        if not lights:
            raise ValueError("Could not connect to any light. " + " | ".join(problems))
        self.lights = len(lights)
        self.light_info = [{"pos": k, "idx": L.idx, "ip": L.ip} for k, L in enumerate(lights)]
        if problems:
            self.error = "Skipped: " + " | ".join(problems)

        pt = self._start_passthrough(c, lights, sd) if c.get("passthru") else None
        try:
            await self._listen(lights, c, sd, pt)
        finally:
            self._stop_passthrough(pt)

    def _save_restore(self, uid):
        """Remember (in settings, so it survives a crash) which output to put back."""
        with CONFIG_LOCK:
            self.cfg = dict(self.cfg, restore_out=uid)
            if not uid:
                self.cfg["restore_vol"] = False
            save_config(self.cfg)

    def _save_vol(self, moved):
        with CONFIG_LOCK:
            self.cfg = dict(self.cfg, restore_vol=bool(moved))
            save_config(self.cfg)

    def _start_passthrough(self, c, lights, sd):
        """Send the Mac's sound to BlackHole and start playing it, delayed, to the speaker.
        Returns what _listen and _stop_passthrough need."""
        live = c["devices"]
        mean_lat = sum(L.lat for L in lights) / len(lights)
        leads = [light_lead(L, live[L.idx] if L.idx < len(live) else {}, c, mean_lat) for L in lights]
        bh_in = next((i for i, d in enumerate(sd.query_devices())
                      if d["name"].startswith("BlackHole") and d["max_input_channels"] >= 2), None)
        if bh_in is None:
            raise RuntimeError(audio_route.NO_BLACKHOLE_MSG)
        prev = audio_route.switch_to_blackhole(self._save_restore)
        pt = {"prev": prev, "vol": None, "player": None}
        try:
            spk = audio_route.pick_speaker(c.get("out_device", ""), prev)
            if spk is None:
                raise RuntimeError("No speaker found to play the music on.")
            spk_s = c.get("spk_delay", {}).get(spk["uid"], spk["latency_ms"]) / 1000.0
            delay = pass_delay(leads, spk_s)
            builtin = audio_route.pick_speaker("", "")
            fallback = builtin["name"] if builtin and builtin["uid"] != spk["uid"] else None
            line = passthrough.DelayLine(SAMPLE_RATE, delay)
            pt["vol"] = audio_route.take_over_volume(spk["uid"])
            if pt["vol"]:
                self._save_vol(True)
            pt["player"] = player = passthrough.Player(sd, spk["name"], fallback, line, SAMPLE_RATE)
            player.start()
            out_lat = float(getattr(player.stream, "latency", 0.0) or 0.0)
        except BaseException:
            self._stop_passthrough(pt)
            raise
        # the moment a sound coming in now will be heard
        pt.update(line=line, dev=bh_in, offset=delay + max(spk_s, out_lat))
        self.pass_delay, self.speaker = delay, spk["name"]
        return pt

    def _stop_passthrough(self, pt):
        if not pt:
            return
        for step in (lambda: pt["player"] and pt["player"].close(),
                     lambda: audio_route.give_back_volume(pt["vol"]),
                     lambda: audio_route.restore_output(pt["prev"], self._save_restore)):
            try:
                step()
            except Exception as e:
                self.error = f"Couldn't put the sound back to your speaker: {e}"
        self.pass_delay, self.speaker, self.speaker_lost = 0.0, "", ""

    async def _listen(self, lights, c, sd, pt):
        tracker = BeatTracker()

        def callback(indata, frames, t, status):
            tracker.steady = self.cfg.get("steady", True)
            if pt:
                pt["line"].push(indata)
                tracker.process(indata.mean(axis=1).astype(np.float32), self.cfg["sensitivity"],
                                now=time.time() + pt["offset"])
            else:
                tracker.process(indata[:, 0].astype(np.float32), self.cfg["sensitivity"])

        if pt:
            dev, channels = pt["dev"], 2
        else:
            dev, channels = c["device"], 1
            dev = int(dev) if str(dev).isdigit() else (dev or None)
        look = pt["offset"] - 0.04 if pt else LOOKAHEAD
        beat_n = 0
        events = deque(maxlen=16)
        hits = {b: deque(maxlen=16) for b in tracker.hits}    # (time, number) per sound
        drop_q = deque(maxlen=4)       # drop times (as heard) not yet shown by every light
        bar_heard = 0                  # bar of the last beat heard (for turning colors)
        hit_n = 0
        ui_beats = deque(maxlen=16)
        last_t = time.time()
        t_start = time.time()
        loud_t = time.time()
        with sd.InputStream(device=dev, channels=channels, samplerate=SAMPLE_RATE,
                            blocksize=BLOCK, callback=callback):
            self.audio_open = True
            while not self.stop_evt.is_set():
                cfg = self.cfg  # re-read each loop so UI changes apply live
                now = time.time()
                dt = now - last_t
                last_t = now

                if now < self.calib_until:          # webcam calibration owns the lights
                    while self.calib_q:
                        rid, pos, b = self.calib_q.popleft()
                        if 0 <= pos < len(lights):
                            task = asyncio.create_task(self._calib_send(lights[pos], rid, b))
                            self.tasks.add(task)
                            task.add_done_callback(self.tasks.discard)
                        else:
                            self.calib_log[rid] = {"ok": False, "t": 0, "lat": 0}
                    self.lat = [int(L.lat * 1000) for L in lights]
                    await asyncio.sleep(0.003)
                    continue
                self.calib_q.clear()

                if pt:
                    pt["player"].check()
                    self.speaker_lost = pt["player"].fell_back or ""
                for bt in tracker.poll_events(now, look, cfg["lock"], snap=bool(pt)):
                    beat_n += 1
                    events.append((bt, beat_n, tracker.last_downbeat))
                    ui_beats.append((bt, tracker.bar_n))
                while tracker.drops:                   # the beat came back after a breakdown
                    drop_q.append(tracker.drops.popleft())
                for b, q in tracker.hits.items():      # kick / snare / hi-hat hits for lights that follow one
                    while q:
                        hit_n += 1
                        hits[b].append((q.popleft(), hit_n))
                while ui_beats and ui_beats[0][0] <= now:   # count a beat when it lands, for the platter
                    bar_heard = ui_beats.popleft()[1]
                    self.beats += 1
                self.level, self.onsets, self.rms = tracker.level, tracker.onset_count, tracker.rms
                if tracker.rms > 2e-5:
                    loud_t = now
                    if self.error == SILENT_MSG:
                        self.error = ""
                elif now - loud_t > 3 and now - t_start > 3:
                    self.error = SILENT_MSG
                manual = self.flash
                self.flash = False
                no_beats = now - tracker.last_onset > 2.5
                n = len(lights)
                half_life = 0.08 + 0.45 * float(cfg["smooth"])
                span = cfg["maxB"] - cfg["minB"]
                peak = 0.6 + 0.4 * min(tracker.level * 1.5, 1.0)  # quiet music -> softer peaks
                if cfg.get("drops") and tracker.breakdown:
                    peak = 0.15 + 0.25 * min(tracker.level * 1.5, 1.0)  # build-up: dim, rising with the music
                ccfg = turn_colors(cfg, bar_heard // cfg["bar_shift"]) if cfg.get("bar_shift") else cfg
                mean_lat = sum(L.lat for L in lights) / n
                tn = tracker.time_to_next(now) if cfg["lock"] else None
                live = cfg["devices"]
                self.lat = [int(L.lat * 1000) for L in lights]
                self.dropped = [L.name for L in lights if L.fails >= 3]
                self.locked = (tn is not None) if cfg["lock"] else None

                lamps = []
                for k, L in enumerate(lights):
                    dcfg = live[L.idx] if L.idx < len(live) else {}
                    lead = light_lead(L, dcfg, cfg, mean_lat)

                    fired = False
                    sound = dcfg.get("sound", "beat")
                    shape = sound in BARS or sound == "pitch"
                    if shape:
                        tn_l = None      # follows the sound itself: no beat to keep the bulb free for
                    elif sound in hits:
                        # this light follows one sound: flash on each of its hits (as heard)
                        for ht, idx in hits[sound]:
                            if idx > L.last_hit and ht - lead <= now:
                                L.last_hit, L.last_bt, fired = idx, ht, True
                        ahead = [ht for ht, _ in hits[sound] if ht > now]
                        tn_l = (min(ahead) - now) if ahead else next_hit_in(hits[sound], now)
                    else:
                        for bt, idx, first in events:
                            if idx > L.last_idx and bt - lead <= now:
                                L.last_idx, L.last_bt = idx, bt
                                if cfg["multi"] == "sync" or n == 1 or (idx - 1) % n == k:
                                    fired = True
                                    # stronger flash on beat 1 of each bar, softer on 2-4
                                    L.hit = 1.0 if first or not cfg.get("accent") else ACCENT_SOFT
                        tn_l = tn
                    burst = False
                    if cfg.get("drops"):
                        for d in drop_q:
                            if d > L.last_drop and d - lead <= now:
                                L.last_drop, L.burst_until, burst = d, d + BURST_SECONDS, True
                    in_burst = now < L.burst_until
                    if burst or manual:
                        L.env = 1.0
                    elif fired:
                        L.env = 1.0 if sound in hits else L.hit
                    else:
                        L.env *= 0.5 ** (dt / (BURST_HALF_LIFE if in_burst else half_life))
                        if no_beats and tracker.rms > 2e-5:   # fallback: follow loudness so the light never just sits
                            L.env = max(L.env, 0.7 * min(tracker.level * 2.0, 1.0))
                    b = int(round((cfg["minB"] + span * L.env * (1.0 if in_burst else peak)) / 10.0) * 10)
                    b = max(1, min(100, b))

                    if cfg.get("pulse") == "color":
                        # color pulse: steady brightness, the beat moves the color A -> B and back
                        b = max(1, min(100, int(cfg["maxB"])))
                        hue, sat = pulse_color(ccfg, L.env)
                        sat = max(1, min(100, sat))
                        L.hue_now = float(hue)
                    else:
                        which = dcfg.get("color", "blend")
                        target_hue, sat = pick_color(ccfg, tracker.bpm, which)
                        sat = max(1, min(100, sat))
                        if L.hue_now is None:
                            L.hue_now = float(target_hue)
                        diff = ((target_hue - L.hue_now + 180) % 360) - 180
                        L.hue_now = (L.hue_now + diff * min(1.0, dt * 1.5)) % 360
                        hue = int(round(L.hue_now / 4.0) * 4) % 360
                    if shape:
                        # what will be heard when this command reaches the bulb
                        sh = tracker.shape_at(now + L.lat)
                        if sound == "pitch":     # color = where the sound sits, brightness = loudness
                            hue, sat = int(round(pitch_hue(sh["pitch"]) / 8.0) * 8), 100
                            L.hue_now = float(hue)
                            lv = sh["loud"]
                        else:                    # sound bar: brightness = this band's level
                            lv = sh["levels"][sound]
                        b = max(1, min(100, int(round((cfg["minB"] + span * lv) / 10.0) * 10)))
                    pv = self.preview
                    if pv and now < pv[2]:            # Settings is previewing a color: show it plainly
                        hue, sat, b = pv[0], max(1, pv[1]), max(1, min(100, int(cfg["maxB"])))
                        L.hue_now = float(hue)
                    lamps.append({"name": L.name, "b": b, "hex": hsv_hex(hue, sat), "ok": L.fails < 3, "sound": sound})

                    if k == 0:
                        self.bpm, self.brightness = tracker.bpm, b
                    changed = (b, hue, sat) != L.last_sent
                    # keep the link free just before this light's next peak so the peak isn't queued behind a fade step
                    # (also when that beat is due but not yet announced, which happens with
                    # pass-through if a light's replies got slower; not if it already flashed for it)
                    fading = (not (fired or manual)) if cfg.get("pulse") == "color" else b < L.last_sent[0]
                    soon = (tn_l is not None and tn_l - lead < L.lat + 0.04 and fading
                            and abs(L.last_bt - (now + tn_l)) > 0.08)
                    if changed and not soon and not L.busy and now - L.last_send_t >= L.min_gap:
                        L.busy = True   # each light sends on its own, in parallel
                        task = asyncio.create_task(self._send(L, b, hue, sat))
                        self.tasks.add(task)               # keep a reference so it can't be garbage-collected
                        task.add_done_callback(self.tasks.discard)
                self.lamps = lamps
                if self.preview and now >= self.preview[2]:
                    self.preview = None
                await asyncio.sleep(0.01)


class Light:
    def __init__(self, handle, idx, ip):
        self.handle, self.idx, self.ip = handle, idx, ip
        self.env = 0.0
        self.lat = 0.10      # measured command round-trip, seconds
        self.last_idx = 0
        self.busy_since = 0.0
        self.hue_now = None
        self.last_sent = (-1, -1, -1)
        self.last_send_t = 0.0
        self.last_bt = 0.0   # time of the last beat this light flashed for
        self.last_hit = 0    # number of the last kick/snare/hi-hat hit it flashed for
        self.hit = 1.0       # how hard the next beat flash is (beat 1 vs 2-4)
        self.last_drop = 0.0
        self.burst_until = 0.0
        self.busy = False
        self.min_gap = 0.07  # s between commands
        self.fails = 0       # commands failed in a row
        self.name = ip


ENGINE = Engine()


def list_inputs():
    try:
        import sounddevice as sd
        out = []
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                out.append({"id": str(i), "name": d["name"]})
        return out
    except Exception as e:
        return [{"id": "", "name": f"(could not list inputs: {e})"}]


SILENT_MSG = ("No sound is reaching Temponome. If you use the microphone, allow Temponome "
              "(or Terminal) in System Settings > Privacy & Security > Microphone. "
              "Also check the audio input in Settings > Sound.")


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def status_text(st):
    """One plain-words line for the status bar, and its level:
    "ok" | "wait" | "warn" | "error" | "idle". Raw errors stay in st["error"] for details."""
    err = st.get("error") or ""
    if not st.get("running"):
        devices = (st.get("cfg") or {}).get("devices")
        if devices is not None and not any(d.get("ip") for d in devices):
            return "No lights yet · find them in Settings", "idle"
        if not err or err == SILENT_MSG:
            return "Ready · press Play", "idle"
        if err.startswith(RESTORE_MSG):
            return err, "warn"
        if audio_route.NO_BLACKHOLE_MSG in err:
            return audio_route.NO_BLACKHOLE_MSG, "error"
        if SECOND_COPY_MSG in err:
            return SECOND_COPY_MSG, "error"
        if "need your Tapo account" in err:
            return "Enter your Tapo email and password in Settings > Lights.", "error"
        if "credential" in err.lower():
            return ("Your Tapo login was refused. Check the email and password in Settings > Lights.",
                    "error")
        if "Could not connect to any light" in err:
            return ("None of your lights answered. Check they're switched on and on the same Wi-Fi, "
                    "then press Play.", "error")
        if "PortAudio" in err or "querying device" in err or "Invalid device" in err:
            return ("No audio input found. Install BlackHole, or choose the microphone in "
                    "Settings > Sound.", "error")
        return "Something went wrong. Press Play to try again.", "error"
    if st.get("connecting"):
        return "Connecting to your lights…", "wait"
    if not st.get("audio_open", True):
        return "Starting to listen…", "wait"
    if err == SILENT_MSG or st.get("db", 0) <= -90:
        return "Can't hear any music. Check the audio input in Settings > Sound.", "warn"
    if st.get("speaker_lost"):
        return f"Your speaker disconnected · playing on {st['speaker_lost']}", "warn"
    dropped = st.get("dropped") or []
    if dropped:
        names = dropped[0] if len(dropped) == 1 else ", ".join(dropped[:-1]) + " and " + dropped[-1]
        playing = max(0, st["lights"] - len(dropped))
        return f"{names} stopped answering · {_plural(playing, 'light')} playing", "warn"
    missing = st.get("missing") or []
    if missing:
        names = missing[0] if len(missing) == 1 else ", ".join(missing[:-1]) + " and " + missing[-1]
        return f"{names} didn't answer · {_plural(st['lights'], 'light')} playing", "warn"
    late = f" · sound delayed {st['pass_delay']:.1f} s" if st.get("pass_delay") else ""
    if st.get("locked") and st.get("onsets"):
        return f"Listening · {_plural(st['lights'], 'light')} · on the beat{late}", "ok"
    return f"Finding the beat · {_plural(st['lights'], 'light')}{late}", "wait"


def _light_set(devices):
    return [(d["ip"], d["model"]) for d in devices if d["ip"]]


def apply_config(body):
    """Validate and save settings from the page. If the set of lights changed while
    playing, restart the engine in the background so the change applies at once."""
    with CONFIG_LOCK:
        relist = _apply_config_locked(body)
    if relist and ENGINE.want_running:
        threading.Thread(target=ENGINE.restart, daemon=True).start()


def _apply_config_locked(body):
    new = dict(ENGINE.cfg)
    for k in DEFAULTS:
        if k in body and not (k == "password" and not body[k]):
            new[k] = body[k]
    new["devices"] = clean_devices(new["devices"])
    # a page that loaded before a calibration sends calib=None; keep the measured value
    # (only the calibration screen clears it, through /api/calib)
    measured = {d["ip"]: d["calib"] for d in ENGINE.cfg["devices"] if d["ip"] and d.get("calib") is not None}
    for d in new["devices"]:
        if d["calib"] is None and d["ip"] in measured:
            d["calib"] = measured[d["ip"]]
    if new["multi"] not in ("sync", "chase"):
        new["multi"] = "sync"
    new["minB"] = int(new["minB"])
    new["maxB"] = int(new["maxB"])
    new["sensitivity"] = float(new["sensitivity"])
    new["smooth"] = float(new["smooth"])
    new["lock"] = bool(new["lock"])
    new["accent"] = bool(new["accent"])
    new["drops"] = bool(new["drops"])
    new["bar_shift"] = new["bar_shift"] if new["bar_shift"] in (0, 4, 8) else 0
    if new["pulse"] not in ("brightness", "color"):
        new["pulse"] = "brightness"
    new["steady"] = bool(new["steady"])
    new["lead"] = max(-150, min(250, int(new["lead"])))
    new["passthru"] = bool(new["passthru"])
    new["out_device"] = str(new["out_device"] or "")
    spk = {}
    for uid, ms in (new["spk_delay"] if isinstance(new["spk_delay"], dict) else {}).items():
        try:
            if uid:
                spk[str(uid)] = max(0, min(400, int(ms)))
        except (TypeError, ValueError):
            pass
    new["spk_delay"] = spk
    new["restore_out"] = ENGINE.cfg.get("restore_out", "")    # only the engine writes these
    new["restore_vol"] = ENGINE.cfg.get("restore_vol", False)
    relist = (_light_set(new["devices"]) != _light_set(ENGINE.cfg["devices"])
              or new["passthru"] != ENGINE.cfg.get("passthru", False)
              or (new["passthru"] and new["out_device"] != ENGINE.cfg.get("out_device", "")))
    ENGINE.cfg = new
    save_config(new)
    return relist


UI_FILE = re.compile(r"^[a-z0-9_-]+\.(css|js|svg|png|html)$")
UI_TYPES = {"css": "text/css; charset=utf-8", "js": "text/javascript; charset=utf-8",
            "svg": "image/svg+xml", "png": "image/png", "html": "text/html; charset=utf-8"}


def serve_ui(name):
    """Bytes of a file in ui/ (names are checked by the caller / are constants)."""
    with open(os.path.join(UI_DIR, name), "rb") as f:
        return f.read()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _state(self):
        c = dict(ENGINE.cfg)
        c["has_password"] = bool(c.get("password"))
        c.pop("password", None)
        out = {"cfg": c, "running": ENGINE.running, "error": ENGINE.error,
                "bpm": round(ENGINE.bpm, 1), "brightness": ENGINE.brightness,
                "lights": ENGINE.lights, "lat": ENGINE.lat,
                "level": round(ENGINE.level, 2), "onsets": ENGINE.onsets,
                "db": round(20 * np.log10(max(ENGINE.rms, 1e-7)), 1),
                "connecting": ENGINE.connecting, "audio_open": ENGINE.audio_open,
                "dropped": ENGINE.dropped,
                "locked": ENGINE.locked, "missing": ENGINE.missing,
                "beats": ENGINE.beats, "color": live_color_hex(ENGINE.cfg, ENGINE.bpm or 110),
                "lamps": ENGINE.lamps, "pass_delay": ENGINE.pass_delay,
                "speaker": ENGINE.speaker, "speaker_lost": ENGINE.speaker_lost}
        out["status"], out["status_level"] = status_text(out)
        return out

    def _refuse_foreign(self):
        """Only Temponome's own pages may talk to this server: reject other Host names
        (DNS rebinding) and non-JSON posts (other websites can't send JSON without a
        CORS preflight, which this server never approves)."""
        port = self.server.server_address[1]
        if self.headers.get("Host", "") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            self._send(403, "{}")
            return True
        if self.command == "POST" and not self.headers.get("Content-Type", "").startswith("application/json"):
            self._send(415, "{}")
            return True
        return False

    def do_GET(self):
        if self._refuse_foreign():
            return
        if self.path == "/":
            self._send(200, serve_ui("main.html"), "text/html; charset=utf-8")
        elif self.path.split("#")[0] == "/settings":
            self._send(200, serve_ui("settings.html"), "text/html; charset=utf-8")
        elif self.path.startswith("/ui/"):
            name = self.path[4:].split("?")[0]
            if not UI_FILE.match(name) or not os.path.exists(os.path.join(UI_DIR, name)):
                self._send(404, "{}")
                return
            self._send(200, serve_ui(name), UI_TYPES[name.rsplit(".", 1)[1]])
        elif self.path == "/api/state":
            self._send(200, json.dumps(self._state()))
        elif self.path == "/api/outputs":
            self._send(200, json.dumps(outputs_info()))
        elif self.path == "/api/devices":
            self._send(200, json.dumps(list_inputs()))
        elif self.path == "/api/scan":
            self._send(200, json.dumps(scan_all(ENGINE.cfg)))
        else:
            self._send(404, "{}")

    def do_POST(self):
        if self._refuse_foreign():
            return
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or "{}")
        if self.path == "/api/config":
            apply_config(body)
            self._send(200, json.dumps(self._state()))
        elif self.path == "/api/start":
            ENGINE.start()
            self._send(200, json.dumps(self._state()))
        elif self.path == "/api/preview":
            self._send(200, json.dumps(preview_color(body.get("color"))))
        elif self.path == "/api/flash":
            ENGINE.flash = True
            self._send(200, json.dumps(self._state()))
        elif self.path == "/api/stop":
            ENGINE.stop()
            self._send(200, json.dumps(self._state()))
        elif self.path == "/api/calib":
            # webcam calibration, driven by the page: begin / flash / end / save
            act = body.get("action")
            if act == "begin":
                if not ENGINE.running or not ENGINE.light_info:
                    self._send(200, json.dumps({"ok": False, "error": "Press Start first so the app is connected to your lights."}))
                    return
                ENGINE.calib_until = time.time() + 120
                self._send(200, json.dumps({"ok": True, "lights": ENGINE.light_info}))
            elif act == "flash":
                ENGINE.calib_until = max(ENGINE.calib_until, time.time() + 20)
                r = ENGINE.calib_flash(int(body.get("pos", 0)), max(1, min(100, int(body.get("b", 100)))))
                self._send(200, json.dumps(r))
            elif act == "end":
                ENGINE.calib_until = 0.0
                self._send(200, json.dumps({"ok": True}))
            elif act == "save":
                new = dict(ENGINE.cfg)
                devs = copy.deepcopy(new["devices"])
                for r in body.get("results", []):
                    i = int(r.get("idx", -1))
                    if 0 <= i < len(devs):
                        devs[i]["calib"] = None if r.get("calib") is None else int(round(r["calib"]))
                new["devices"] = clean_devices(devs)
                if body.get("reset_nudge"):
                    new["lead"] = 0      # the old nudge was a guess at the bulb delay, now measured
                ENGINE.cfg = new
                save_config(new)
                self._send(200, json.dumps(self._state()))
            else:
                self._send(400, "{}")
        else:
            self._send(404, "{}")





def recover_sound_output():
    """At launch: if Temponome last stopped without putting the Mac's sound back (a crash
    while playing music through it), put it back now."""
    try:
        audio_route.recover(ENGINE.cfg, ENGINE._save_restore)
    except Exception:
        pass


def make_server(port):
    """The local web server the windows talk to (only reachable from this Mac)."""
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    recover_sound_output()
    server = make_server(PORT)
    url = f"http://127.0.0.1:{PORT}"
    print(f"Temponome running at {url}  (Ctrl+C to quit)")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        ENGINE.stop()
        print("\nBye.")


if __name__ == "__main__":
    main()
