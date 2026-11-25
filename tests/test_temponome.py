#!/usr/bin/env python3
"""Unit tests for Temponome (stdlib unittest; pytest is not installed).

Run:  python3 -m unittest tests.test_temponome -v
HOME is pointed at a temporary folder before importing, so the real settings are never touched.
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.request

import numpy as np

TMP_HOME = tempfile.mkdtemp()
os.environ["HOME"] = TMP_HOME
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import temponome as T  # noqa: E402


def reset_home():
    for name in os.listdir(TMP_HOME):
        p = os.path.join(TMP_HOME, name)
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)


class ConfigMigration(unittest.TestCase):
    def setUp(self):
        reset_home()

    def write_old(self, data):
        with open(T.OLD_CONFIG_PATH, "w") as f:
            json.dump(data, f)

    def test_migrates_old_file(self):
        self.write_old({"email": "e", "password": "p",
                        "devices": [{"ip": "1.2.3.4", "model": "l530", "calib": -55}]})
        self.assertTrue(T.migrate_config())
        with open(T.CONFIG_PATH) as f:
            new = json.load(f)
        self.assertEqual(new["email"], "e")
        self.assertEqual(new["password"], "p")
        self.assertEqual(new["devices"][0]["calib"], -55)
        self.assertEqual(os.stat(T.CONFIG_PATH).st_mode & 0o777, 0o600)
        self.assertTrue(os.path.exists(T.OLD_CONFIG_PATH))   # old file is left in place

    def test_never_overwrites_new_file(self):
        self.write_old({"email": "old"})
        os.makedirs(T.CONFIG_DIR, exist_ok=True)
        with open(T.CONFIG_PATH, "w") as f:
            json.dump({"email": "new"}, f)
        self.assertFalse(T.migrate_config())
        with open(T.CONFIG_PATH) as f:
            self.assertEqual(json.load(f)["email"], "new")

    def test_load_config_uses_migrated_settings(self):
        self.write_old({"email": "kept@example.com", "maxB": 30})
        cfg = T.load_config()
        self.assertEqual(cfg["email"], "kept@example.com")
        self.assertEqual(cfg["maxB"], 30)


class SafeSettings(unittest.TestCase):
    def setUp(self):
        reset_home()

    def test_save_is_atomic_and_private(self):
        T.save_config({"email": "a"})
        self.assertFalse(os.path.exists(T.CONFIG_PATH + ".tmp"))
        self.assertEqual(os.stat(T.CONFIG_PATH).st_mode & 0o777, 0o600)

    def test_unreadable_settings_fall_back_to_old_file(self):
        with open(T.OLD_CONFIG_PATH, "w") as f:
            json.dump({"email": "old@example.com"}, f)
        os.makedirs(T.CONFIG_DIR, exist_ok=True)
        with open(T.CONFIG_PATH, "w") as f:
            f.write('{"email": "broken')          # cut off mid-write
        self.assertEqual(T.load_config()["email"], "old@example.com")

    def test_stale_device_list_keeps_measured_timing(self):
        T.ENGINE.running = False
        T.ENGINE.cfg = T.load_config()
        T.ENGINE.cfg["devices"] = T.clean_devices([{"ip": "1.2.3.4", "model": "l530", "calib": 120}])
        T.apply_config({"devices": [{"ip": "1.2.3.4", "model": "l530", "color": "A", "calib": None}]})
        d = T.ENGINE.cfg["devices"][0]
        self.assertEqual((d["color"], d["calib"]), ("A", 120))


class UiRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), T.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def get(self, path):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            e.close()
            return e.code, b""

    def test_serve_ui_main_page(self):
        self.assertTrue(T.serve_ui("main.html").lower().startswith(b"<!doctype html>"))

    def test_root_serves_main_page_named_temponome(self):
        code, body = self.get("/")
        self.assertEqual(code, 200)
        self.assertIn(b"<title>Temponome", body)

    def test_settings_page_and_its_files(self):
        code, body = self.get("/settings")
        self.assertEqual((code, b"<title>Temponome Settings" in body), (200, True))
        for f in ("settings.js", "common.js", "deck.css"):
            self.assertEqual(self.get("/ui/" + f)[0], 200, f)

    def req(self, path, method="GET", body=None, headers=None):
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=body, method=method,
                                   headers=headers or {})
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status
        except urllib.error.HTTPError as e:
            e.close()
            return e.code

    def test_other_websites_are_refused(self):
        self.assertEqual(self.req("/api/state", headers={"Host": "evil.example:8765"}), 403)

    def test_post_needs_json_content_type(self):
        self.assertEqual(self.req("/api/flash", "POST", b"{}", {"Content-Type": "text/plain"}), 415)
        self.assertEqual(self.req("/api/flash", "POST", b"{}", {"Content-Type": "application/json"}), 200)

    def test_ui_path_traversal_refused(self):
        code, _ = self.get("/ui/../temponome.py")
        self.assertEqual(code, 404)
        code, _ = self.get("/ui/%2e%2e/temponome.py")
        self.assertEqual(code, 404)


def st(**kw):
    base = {"running": True, "lights": 1, "locked": False, "onsets": 0, "db": -50.0,
            "missing": [], "error": "", "connecting": False, "audio_open": True}
    base.update(kw)
    return base


class StatusText(unittest.TestCase):
    def test_idle(self):
        self.assertEqual(T.status_text(st(running=False)), ("Ready · press Play", "idle"))

    def test_no_lights_yet(self):
        self.assertEqual(T.status_text(st(running=False, cfg={"devices": [{"ip": ""}]})),
                         ("No lights yet · find them in Settings", "idle"))

    def test_connecting(self):
        self.assertEqual(T.status_text(st(connecting=True, db=-140.0)), ("Connecting to your lights…", "wait"))

    def test_no_silence_warning_before_audio_opens(self):
        self.assertEqual(T.status_text(st(audio_open=False, db=-140.0))[1], "wait")

    def test_missing_tapo_login(self):
        err = "ValueError: Tapo lights need your Tapo account email and password (Setup section)."
        self.assertEqual(T.status_text(st(running=False, error=err)),
                         ("Enter your Tapo email and password in Settings > Lights.", "error"))

    def test_tapo_login_refused(self):
        err = "ValueError: Could not connect to any light. 1.2.3.4: Tapo(InvalidCredentials)"
        self.assertEqual(T.status_text(st(running=False, error=err)),
                         ("Your Tapo login was refused. Check the email and password in Settings > Lights.", "error"))

    def test_light_stopped_answering_mid_play(self):
        self.assertEqual(T.status_text(st(lights=3, locked=True, onsets=4, dropped=["Kitchen lamp"])),
                         ("Kitchen lamp stopped answering · 2 lights playing", "warn"))

    def test_on_the_beat(self):
        self.assertEqual(T.status_text(st(lights=3, locked=True, onsets=12)),
                         ("Listening · 3 lights · on the beat", "ok"))

    def test_finding_the_beat(self):
        self.assertEqual(T.status_text(st(lights=1)), ("Finding the beat · 1 light", "wait"))

    def test_silence(self):
        self.assertEqual(T.status_text(st(db=-95.0)),
                         ("Can't hear any music. Check the audio input in Settings > Sound.", "warn"))

    def test_engine_silence_warning_maps_to_same_text(self):
        self.assertEqual(T.status_text(st(error=T.SILENT_MSG))[1], "warn")

    def test_one_light_missing(self):
        self.assertEqual(T.status_text(st(lights=2, locked=True, onsets=5, missing=["Kitchen lamp"])),
                         ("Kitchen lamp didn't answer · 2 lights playing", "warn"))

    def test_two_lights_missing(self):
        self.assertEqual(T.status_text(st(lights=1, missing=["Kitchen lamp", "Desk"]))[0],
                         "Kitchen lamp and Desk didn't answer · 1 light playing")

    def test_no_light_answered(self):
        self.assertEqual(T.status_text(st(running=False, error="ValueError: Could not connect to any light. x")),
                         ("None of your lights answered. Check they're switched on and on the same Wi-Fi, "
                          "then press Play.", "error"))

    def test_second_copy_running(self):
        err = "ValueError: Could not connect to any light. 1.2.3.4: " + T.SECOND_COPY_MSG
        self.assertEqual(T.status_text(st(running=False, error=err)), (T.SECOND_COPY_MSG, "error"))

    def test_no_audio_input(self):
        self.assertEqual(T.status_text(st(running=False, error="PortAudioError: Error querying device -1")),
                         ("No audio input found. Install BlackHole, or choose the microphone in "
                          "Settings > Sound.", "error"))

    def test_other_error(self):
        self.assertEqual(T.status_text(st(running=False, error="KeyError: 'x'")),
                         ("Something went wrong. Press Play to try again.", "error"))

    def test_state_includes_status(self):
        T.ENGINE.running = False
        T.ENGINE.error = ""
        T.ENGINE.cfg["devices"] = [{"ip": "1.2.3.4", "model": "l530"}]
        s = T.Handler._state(None)
        self.assertEqual((s["status"], s["status_level"]), ("Ready · press Play", "idle"))
        self.assertEqual(s["missing"], [])


class DeckState(unittest.TestCase):
    def test_state_has_live_color_hex(self):
        T.ENGINE.cfg.update(colorA="#ff0000", colorB="#0000ff", mode="fixed")
        s = T.Handler._state(None)
        self.assertEqual(s["color"], "#ff0000")

    def test_state_has_beat_counter(self):
        T.ENGINE.beats = 7
        self.assertEqual(T.Handler._state(None)["beats"], 7)

    def test_state_has_lamps_list(self):
        T.ENGINE.lamps = [{"name": "Desk", "b": 80, "hex": "#ff0000", "ok": True}]
        try:
            self.assertEqual(T.Handler._state(None)["lamps"][0]["name"], "Desk")
        finally:
            T.ENGINE.lamps = []


class BeatSteadiness(unittest.TestCase):
    """Real songs made the grid flip tempo (often to double) and snap half a beat at a time,
    which showed as double flashes and gaps."""

    def tracker(self, bpm=90.0, now=100.0):
        tr = T.BeatTracker()
        tr.bpm, tr.t0, tr.last_onset = bpm, now, now
        tr.tempo_known = True
        return tr

    def test_first_tempo_is_taken_at_once(self):
        tr = T.BeatTracker()                          # 110 is only a placeholder guess
        tr._consider_tempo(128.0, 100.0)
        self.assertAlmostEqual(tr.bpm, 128.0)

    def test_grid_locks_on_faster_once_the_first_tempo_is_found(self):
        tr = T.BeatTracker()
        tr.t0, tr.last_onset = 100.0, 100.0
        tr._consider_tempo(150.0, 102.5)
        self.assertAlmostEqual(tr.grid_t, 102.5)
        t0 = tr.t0
        tr._align(t0 + 2 * 0.4 + 0.1)                    # a hit 100 ms after the grid
        self.assertAlmostEqual(tr.t0 - t0, 0.05)         # young grid: pulled halfway
        tr.grid_t = 0.0
        t0 = tr.t0
        tr._align(t0 + 2 * 0.4 + 0.1)
        self.assertAlmostEqual(tr.t0 - t0, 0.025)        # settled grid: a quarter

    def test_switched_off_behaves_like_before(self):
        tr = self.tracker(90.0)
        tr.steady = False
        for k in range(3):
            tr._consider_tempo(180.0, 100.0 + 0.5 * k)
        self.assertAlmostEqual(tr.bpm, 180.0)         # old rule: 3 estimates, any jump
        tr._shift_phase(0.2, now=200.0)
        self.assertEqual(tr.shift_left, 0.0)          # old rule: snaps at once
        fresh = T.BeatTracker()
        fresh.steady = False
        fresh._consider_tempo(128.0, 100.0)
        self.assertAlmostEqual(fresh.bpm, 110.0)      # old rule: even the first needs proof

    def test_setting_defaults_on_and_is_saved(self):
        self.assertIs(T.DEFAULTS["steady"], True)
        reset_home()
        old = T.ENGINE.cfg
        try:
            T.ENGINE.cfg = T.load_config()
            T.apply_config({"steady": 0})
            self.assertIs(T.ENGINE.cfg["steady"], False)
        finally:
            T.ENGINE.cfg = old

    def test_double_tempo_needs_longer_proof(self):
        tr = self.tracker(90.0)
        for k in range(4):
            tr._consider_tempo(180.0, 100.0 + 0.5 * k)
        self.assertAlmostEqual(tr.bpm, 90.0)          # 2 s of "double" is not enough
        for k in range(4, 8):
            tr._consider_tempo(180.0, 100.0 + 0.5 * k)
        self.assertAlmostEqual(tr.bpm, 180.0)         # 4 s of it is

    def test_new_tempo_is_followed_within_two_seconds(self):
        tr = self.tracker(90.0)
        for k in range(4):
            tr._consider_tempo(126.0, 100.0 + 0.5 * k)
        self.assertAlmostEqual(tr.bpm, 126.0)

    def test_small_tempo_drift_is_smoothed(self):
        tr = self.tracker(120.0)
        tr._consider_tempo(122.0, 100.0)
        self.assertAlmostEqual(tr.bpm, 120.4)

    def test_phase_correction_glides_without_double_flash_or_gap(self):
        tr = self.tracker(120.0, now=100.0)           # beats at 100.0, 100.5, ...
        tr._shift_phase(0.2, now=120.0)               # settled grid; the hits are really at 100.2, ...
        beats, now = [], 100.0
        while now < 106.0:
            tr.last_onset = now
            tr._glide(now)
            beats += tr.poll_events(now, 0.0, True)
            now += 0.01
        gaps = [b - a for a, b in zip(beats, beats[1:])]
        self.assertTrue(all(0.4 <= g <= 0.6 for g in gaps), gaps)
        self.assertAlmostEqual((beats[-1] - 100.2) % 0.5, 0.0, delta=0.02)   # ends on the hits

    def test_new_grid_snaps_straight_into_place(self):
        tr = self.tracker(120.0, now=100.0)
        tr.grid_t = 100.0                              # grid only just found
        tr._shift_phase(0.2, now=101.0)
        self.assertAlmostEqual(tr.t0, 100.2)
        self.assertEqual(tr.shift_left, 0.0)

    def test_settled_grid_glides(self):
        tr = self.tracker(120.0, now=100.0)
        tr.grid_t = 100.0
        tr._shift_phase(0.2, now=120.0)
        self.assertAlmostEqual(tr.t0, 100.0)
        self.assertAlmostEqual(tr.shift_left, 0.2)

    def test_no_new_phase_vote_while_gliding(self):
        tr = self.tracker(120.0)
        tr._shift_phase(0.2, now=120.0)
        tr.phase_votes = 5
        tr._check_phase()
        self.assertAlmostEqual(tr.shift_left, 0.2)


class FakeBackend:
    """Stands in for CoreAudio: three outputs, MacBook speakers are the default."""
    def __init__(self, with_blackhole=True):
        self.devs = [{"id": 2, "uid": "MBA", "name": "MacBook Air Speakers", "transport": "bltn", "latency_ms": 14.0},
                     {"id": 3, "uid": "JBL", "name": "JBL Flip", "transport": "blue", "latency_ms": 160.0}]
        if with_blackhole:
            self.devs.insert(0, {"id": 1, "uid": "BlackHole2ch_UID", "name": "BlackHole 2ch",
                                 "transport": "virt", "latency_ms": 0.0})
        self.cur = 2
        self.vols = {d["id"]: 1.0 for d in self.devs}
        self.dbs = {d["id"]: 0.0 for d in self.devs}
        self.dbs[2] = -12.0                     # MacBook speakers turned down a bit

    def devices(self):
        return [dict(d) for d in self.devs]

    def default(self):
        return self.cur

    def set_default(self, dev_id):
        self.cur = dev_id

    def volume(self, dev_id):
        return self.vols.get(dev_id)

    def set_volume(self, dev_id, v):
        self.vols[dev_id] = v

    def volume_db(self, dev_id):
        return self.dbs.get(dev_id)

    def set_volume_db(self, dev_id, db):
        self.dbs[dev_id] = db


class AudioRoute(unittest.TestCase):
    def setUp(self):
        import audio_route as AR
        self.AR = AR
        self.old = AR.BACKEND
        AR.BACKEND = self.fake = FakeBackend()
        self.saved = []

    def tearDown(self):
        self.AR.BACKEND = self.old

    def save(self, uid):
        self.saved.append(uid)

    def test_lists_outputs(self):
        outs = {o["uid"]: o for o in self.AR.list_outputs()}
        self.assertTrue(outs["BlackHole2ch_UID"]["blackhole"])
        self.assertTrue(outs["MBA"]["builtin"])
        self.assertEqual(outs["JBL"]["latency_ms"], 160.0)
        self.assertEqual(self.AR.default_output(), "MBA")

    def test_switch_and_restore(self):
        prev = self.AR.switch_to_blackhole(self.save)
        self.assertEqual(prev, "MBA")
        self.assertEqual(self.saved, ["MBA"])
        self.assertEqual(self.fake.cur, 1)
        self.AR.restore_output(prev, self.save)
        self.assertEqual(self.fake.cur, 2)
        self.assertEqual(self.saved, ["MBA", ""])

    def test_restore_to_vanished_device_uses_builtin(self):
        self.fake.cur = 3
        prev = self.AR.switch_to_blackhole(self.save)
        self.fake.devs = [d for d in self.fake.devs if d["uid"] != "JBL"]
        self.AR.restore_output(prev, self.save)
        self.assertEqual(self.fake.cur, 2)

    def test_no_blackhole_leaves_output_alone(self):
        self.AR.BACKEND = self.fake = FakeBackend(with_blackhole=False)
        with self.assertRaises(RuntimeError) as cm:
            self.AR.switch_to_blackhole(self.save)
        self.assertIn("BlackHole", str(cm.exception))
        self.assertEqual(self.fake.cur, 2)
        self.assertEqual(self.saved, [])

    def test_recover_on_launch(self):
        self.fake.cur = 1                         # left on BlackHole by a crash
        self.assertTrue(self.AR.recover({"restore_out": "MBA"}, self.save))
        self.assertEqual(self.fake.cur, 2)
        self.assertEqual(self.saved, [""])

    def test_recover_gives_volume_back_after_a_crash(self):
        self.AR.take_over_volume("MBA")              # speaker at full, BlackHole at -12 dB
        self.fake.cur, self.fake.dbs[1] = 1, -20.0    # crashed while on BlackHole, owner turned it down
        self.assertTrue(self.AR.recover({"restore_out": "MBA", "restore_vol": True}, self.save))
        self.assertEqual(self.fake.dbs[2], -20.0)     # speaker not left at full volume
        self.assertEqual(self.fake.vols[1], 1.0)

    def test_recover_leaves_volume_alone_if_it_was_not_moved(self):
        self.fake.cur = 1
        self.AR.recover({"restore_out": "MBA", "restore_vol": False}, self.save)
        self.assertEqual(self.fake.dbs[2], -12.0)

    def test_recover_does_nothing_when_user_changed_it(self):
        self.fake.cur = 3
        self.assertFalse(self.AR.recover({"restore_out": "MBA"}, self.save))
        self.assertEqual(self.fake.cur, 3)
        self.assertEqual(self.saved, [""])        # stale note is cleared
        self.assertFalse(self.AR.recover({"restore_out": ""}, self.save))

    def test_previous_blackhole_means_builtin(self):
        self.assertEqual(self.AR.pick_speaker("", "BlackHole2ch_UID")["uid"], "MBA")

    def test_volume_moves_to_blackhole_and_back(self):
        state = self.AR.take_over_volume("MBA")
        self.assertEqual(self.fake.dbs[1], -12.0)      # BlackHole now sets the loudness
        self.assertEqual(self.fake.vols[2], 1.0)       # speaker at full
        self.fake.dbs[1] = -20.0                       # owner pressed volume down
        self.AR.give_back_volume(state)
        self.assertEqual(self.fake.dbs[2], -20.0)      # speaker keeps the last level
        self.assertEqual(self.fake.vols[1], 1.0)       # BlackHole back to full

    def test_level_for_decibels(self):
        curve = lambda v: -63.5 * (1 - v) ** 2                 # any rising curve
        v = self.AR.level_for_db(curve, -4.0)
        self.assertAlmostEqual(curve(v), -4.0, delta=0.05)
        self.assertEqual(self.AR.level_for_db(curve, 5.0), 1.0)    # louder than possible: full
        self.assertEqual(self.AR.level_for_db(curve, -90.0), 0.0)

    def test_chosen_missing_falls_back_to_previous(self):
        self.assertEqual(self.AR.pick_speaker("GONE", "JBL")["uid"], "JBL")
        self.assertEqual(self.AR.pick_speaker("JBL", "MBA")["uid"], "JBL")


class FakeOut:
    """sounddevice.OutputStream stand-in."""
    made = []

    def __init__(self, device, channels, samplerate, blocksize, callback, finished_callback):
        self.device, self.cb, self.fin = device, callback, finished_callback
        self.active = True
        FakeOut.made.append(self)

    def start(self):
        pass

    def close(self):
        self.active = False


class FakeSd:
    OutputStream = FakeOut

    @staticmethod
    def query_devices():
        return [{"name": "BlackHole 2ch", "max_output_channels": 2},
                {"name": "MacBook Air Speakers", "max_output_channels": 2},
                {"name": "JBL Flip", "max_output_channels": 2}]


class DelayedSound(unittest.TestCase):
    def setUp(self):
        import passthrough as P
        self.P = P

    def pull_all(self, line, n, block=512):
        out = [line.pull(block) for _ in range(n // block)]
        return np.concatenate(out)

    def test_delay_is_exact(self):
        line = self.P.DelayLine(44100, 0.3)
        x = np.zeros((44100, 2), np.float32)
        x[0] = 1.0
        out = []
        for k in range(0, 44032, 512):                   # sound in and out at the same pace
            line.push(x[k:k + 512])
            out.append(line.pull(512))
        y = np.concatenate(out)
        self.assertEqual(int(np.argmax(y[:, 0])), round(0.3 * 44100))

    def test_delay_comes_back_after_running_dry(self):
        line = self.P.DelayLine(44100, 0.1)
        for _ in range(40):                              # speaker started before any sound came in
            line.pull(512)
        x = np.zeros((44032, 2), np.float32)
        x[0] = 1.0
        out = []
        for k in range(0, 44032, 512):
            line.push(x[k:k + 512])
            out.append(line.pull(512))
        y = np.concatenate(out)
        self.assertEqual(int(np.argmax(y[:, 0])), round(0.1 * 44100))

    def test_stereo_kept(self):
        line = self.P.DelayLine(44100, 0.1)
        x = np.zeros((8192, 2), np.float32)
        x[:, 0], x[:, 1] = 0.5, -0.25
        line.push(x)
        y = line.pull(8192)
        self.assertAlmostEqual(float(y[-1, 0]), 0.5)
        self.assertAlmostEqual(float(y[-1, 1]), -0.25)

    def test_underflow_is_silence(self):
        line = self.P.DelayLine(44100, 0.1)
        y = line.pull(512)
        self.assertEqual(y.shape, (512, 2))
        self.assertEqual(float(np.abs(y).max()), 0.0)

    def test_drift_is_corrected(self):
        rate, line = 44100, self.P.DelayLine(44100, 0.3)
        written, pushed = 0.0, 0
        worst = 0.0
        for k in range(int(60 * rate / 512)):           # 60 s, input clock 0.05 % fast (13 ms drift)
            written += 512 * 1.0005
            n = int(written) - pushed
            pushed += n
            line.push(np.zeros((n, 2), np.float32))
            line.pull(512)
            if k > 100:
                worst = max(worst, abs(line.buffered() / rate - 0.3))
        self.assertLess(worst, 0.006)

    def test_bursty_input_is_not_mistaken_for_drift(self):
        rate, line = 44100, self.P.DelayLine(44100, 0.2)
        block = np.zeros((512, 2), np.float32)
        settled = None
        for k in range(int(30 * rate / 512)):            # BlackHole delivers 4 blocks at a time
            if k % 4 == 0:
                for _ in range(4):
                    line.push(block)
            line.pull(512)
            if k == int(15 * rate / 512):
                settled = line.adjusted                   # a one-off settle at the start is fine
        self.assertEqual(line.adjusted, settled)         # after that, no frames dropped or repeated
        self.assertLess(settled, 0.03 * rate)

    def test_lost_speaker_falls_back(self):
        FakeOut.made = []
        line = self.P.DelayLine(44100, 0.3)
        pl = self.P.Player(FakeSd, "JBL Flip", "MacBook Air Speakers", line, 44100)
        pl.start()
        self.assertEqual(FakeOut.made[0].device, 2)
        FakeOut.made[0].active = False                  # Bluetooth switched off
        FakeOut.made[0].fin()
        pl.check()
        self.assertEqual(FakeOut.made[1].device, 1)
        self.assertEqual(pl.fell_back, "MacBook Air Speakers")
        pl.close()
        pl.check()
        self.assertEqual(len(FakeOut.made), 2)          # a deliberate close is not a loss

    def test_player_plays_the_delay_line(self):
        FakeOut.made = []
        line = self.P.DelayLine(44100, 0.0)
        line.push(np.full((512, 2), 0.25, np.float32))
        pl = self.P.Player(FakeSd, "MacBook Air Speakers", None, line, 44100)
        pl.start()
        out = np.zeros((512, 2), np.float32)
        FakeOut.made[0].cb(out, 512, None, None)
        self.assertAlmostEqual(float(out[-1, 1]), 0.25)


class PassThroughEngine(unittest.TestCase):
    def test_pass_delay_formula(self):
        self.assertAlmostEqual(T.pass_delay([0.10, 0.31], 0.014), 0.396)   # 60 ms spare for slower replies
        self.assertAlmostEqual(T.pass_delay([0.0], 0.2), 0.10)      # never shorter than 0.1 s
        self.assertAlmostEqual(T.pass_delay([0.9], 0.0), 0.60)      # never longer than 0.6 s
        self.assertAlmostEqual(T.pass_delay([], 0.0), 0.10)

    def test_unlocked_emits_onset_time(self):
        tr = T.BeatTracker()
        tr.onset_flag, tr.last_onset = True, 105.3        # hit heard at 105.3 (sound delayed)
        self.assertEqual(tr.poll_events(105.0, 0.3, False), [105.3])

    def grid(self):
        tr = T.BeatTracker()
        tr.bpm, tr.t0, tr.last_onset, tr.last_fired = 120.0, 100.0, 100.0, 100.0
        return tr

    def test_snap_moves_beat_to_real_hit(self):
        tr = self.grid()
        tr.recent.append(100.56)
        self.assertAlmostEqual(tr.poll_events(100.0, 0.6, True, snap=True)[0], 100.56)

    def test_snap_ignores_far_hits(self):
        tr = self.grid()
        tr.recent.append(100.7)
        self.assertAlmostEqual(tr.poll_events(100.0, 0.6, True, snap=True)[0], 100.5)

    def test_no_snap_without_pass_through(self):
        tr = self.grid()
        tr.recent.append(100.56)
        self.assertAlmostEqual(tr.poll_events(100.0, 0.6, True)[0], 100.5)

    def apply(self, body, playing=False, start=None):
        reset_home()
        old_cfg, old_want, old_restart = T.ENGINE.cfg, T.ENGINE.want_running, T.ENGINE.restart
        calls = []
        try:
            T.ENGINE.cfg = T.load_config()
            T.ENGINE.cfg["restore_out"] = "MBA"
            T.ENGINE.cfg.update(start or {})
            T.ENGINE.want_running = playing
            T.ENGINE.restart = lambda: calls.append(1)
            T.apply_config(body)
            time.sleep(0.05)
            return dict(T.ENGINE.cfg), calls
        finally:
            T.ENGINE.cfg, T.ENGINE.want_running, T.ENGINE.restart = old_cfg, old_want, old_restart

    def test_settings_validate(self):
        cfg, _ = self.apply({"passthru": 1, "out_device": 5, "restore_out": "EVIL",
                             "spk_delay": {"MBA": 999, "JBL": -5, "X": "a", "": 3}})
        self.assertIs(cfg["passthru"], True)
        self.assertEqual(cfg["out_device"], "5")
        self.assertEqual(cfg["spk_delay"], {"MBA": 400, "JBL": 0})
        self.assertEqual(cfg["restore_out"], "MBA")          # pages can't change this

    def test_defaults(self):
        self.assertIs(T.DEFAULTS["passthru"], False)
        self.assertEqual(T.DEFAULTS["spk_delay"], {})

    def test_toggle_while_playing_restarts(self):
        self.assertEqual(self.apply({"passthru": True}, playing=True)[1], [1])
        self.assertEqual(self.apply({"out_device": "JBL"}, playing=True, start={"passthru": True})[1], [1])
        self.assertEqual(self.apply({"out_device": "JBL"}, playing=True)[1], [])    # pass-through off
        self.assertEqual(self.apply({"spk_delay": {"MBA": 50}}, playing=True, start={"passthru": True})[1], [])
        self.assertEqual(self.apply({"passthru": True}, playing=False)[1], [])

    def st(self, **kw):
        base = {"running": True, "lights": 3, "locked": True, "onsets": 5, "audio_open": True,
                "connecting": False, "db": -20}
        base.update(kw)
        return T.status_text(base)

    def test_status_mentions_delay(self):
        self.assertEqual(self.st(pass_delay=0.336),
                         ("Listening · 3 lights · on the beat · sound delayed 0.3 s", "ok"))
        self.assertEqual(self.st(), ("Listening · 3 lights · on the beat", "ok"))

    def test_status_speaker_lost(self):
        self.assertEqual(self.st(pass_delay=0.3, speaker_lost="MacBook Air Speakers"),
                         ("Your speaker disconnected · playing on MacBook Air Speakers", "warn"))

    def test_status_no_blackhole(self):
        import audio_route
        self.assertEqual(T.status_text({"running": False, "error": audio_route.NO_BLACKHOLE_MSG}),
                         (audio_route.NO_BLACKHOLE_MSG, "error"))
        # how the engine thread actually stores it
        self.assertEqual(T.status_text({"running": False, "error": "RuntimeError: " + audio_route.NO_BLACKHOLE_MSG}),
                         (audio_route.NO_BLACKHOLE_MSG, "error"))

    def test_launch_puts_sound_back_after_a_crash(self):
        import audio_route as AR
        reset_home()
        old, AR.BACKEND = AR.BACKEND, FakeBackend()
        old_cfg = T.ENGINE.cfg
        try:
            T.ENGINE.cfg = dict(T.load_config(), restore_out="MBA")
            AR.BACKEND.cur = 1                              # still on BlackHole
            T.recover_sound_output()
            self.assertEqual(AR.BACKEND.cur, 2)
            self.assertEqual(T.load_config()["restore_out"], "")
        finally:
            AR.BACKEND, T.ENGINE.cfg = old, old_cfg

    def test_outputs_route_hides_blackhole(self):
        import audio_route as AR
        old, AR.BACKEND = AR.BACKEND, FakeBackend()
        try:
            out = T.outputs_info()
        finally:
            AR.BACKEND = old
        self.assertTrue(out["blackhole"])
        self.assertEqual([o["uid"] for o in out["outputs"]], ["MBA", "JBL"])
        self.assertEqual(out["outputs"][1]["latency_ms"], 160.0)
        self.assertEqual(out["current"], "MBA")         # what "Same as before" would use now


class ColorPulse(unittest.TestCase):
    """"On each beat: Color" — the light jumps from calm A to energetic B and fades back."""
    cfg = {"colorA": "#ff0000", "colorB": "#0000ff", "mode": "tempo"}

    def test_rests_on_a_and_peaks_on_b(self):
        self.assertEqual(T.pulse_color(self.cfg, 0.0), T.hue_sat("#ff0000"))
        self.assertEqual(T.pulse_color(self.cfg, 1.0), T.hue_sat("#0000ff"))

    def test_fades_around_the_wheel(self):
        self.assertEqual(T.pulse_color(self.cfg, 0.5), (300, 100))   # red -> magenta -> blue

    def test_fade_moves_in_steps(self):
        # few distinct colors, so a slow bulb isn't flooded with commands during the fade
        self.assertEqual(T.pulse_color(self.cfg, 0.55), T.pulse_color(self.cfg, 0.5))
        self.assertEqual(len({T.pulse_color(self.cfg, k / 100) for k in range(101)}), 5)

    def test_setting_is_checked(self):
        self.assertEqual(T.DEFAULTS["pulse"], "brightness")
        reset_home()
        old = T.ENGINE.cfg
        try:
            T.ENGINE.cfg = T.load_config()
            T.apply_config({"pulse": "color"})
            self.assertEqual(T.ENGINE.cfg["pulse"], "color")
            T.apply_config({"pulse": "disco"})
            self.assertEqual(T.ENGINE.cfg["pulse"], "brightness")
        finally:
            T.ENGINE.cfg = old


def drum(kind, n, sr=44100, rng=np.random.default_rng(1)):
    """A made-up drum hit `n` samples long: kick = falling low tone, snare = 200 Hz body plus
    1-5 kHz noise, hats = noise above 7 kHz."""
    t = np.arange(n) / sr
    if kind == "kick":
        return np.sin(2 * np.pi * (50 + 80 * np.exp(-t * 30)) * t) * np.exp(-t * 14)
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / sr)
    if kind == "snare":
        spec[(f < 1000) | (f > 5000)] = 0
        noise = np.fft.irfft(spec, n) / np.sqrt(n)
        return (0.8 * noise / noise.std() + 0.4 * np.sin(2 * np.pi * 200 * t)) * np.exp(-t * 25)
    spec[f < 7000] = 0
    noise = np.fft.irfft(spec, n)
    return 0.5 * noise / noise.std() * np.exp(-t * 60)


def play(pattern, seconds=8, sr=44100):
    """Feed BeatTracker a loop of drum hits: pattern = [(time in s within a 1 s bar, kind)]."""
    x = 0.01 * np.random.default_rng(2).standard_normal(int(seconds * sr))    # quiet room noise
    for bar in range(seconds):
        for at, kind in pattern:
            i = int((bar + at) * sr)
            hit = drum(kind, min(int(0.3 * sr), len(x) - i))
            x[i:i + len(hit)] += 0.3 * hit
    tr = T.BeatTracker()
    for k in range(len(x) // T.BLOCK):
        tr.process(x[k * T.BLOCK:(k + 1) * T.BLOCK].astype(np.float32), 1.5, now=100.0 + k * T.BLOCK / sr)
    return {band: len([h for h in tr.hits[band] if h > 102.0]) for band in ("kick", "snare", "hats")}


class SoundsApart(unittest.TestCase):
    """Each light can follow one sound: kick drum, snare or hi-hats."""

    def test_hats_alone(self):
        got = play([(0.0, "hats"), (0.25, "hats"), (0.5, "hats"), (0.75, "hats")])
        self.assertAlmostEqual(got["hats"], 24, delta=3)      # 4 a second for the last 6 s
        self.assertLessEqual(got["kick"], 1)

    def test_kick_alone(self):
        got = play([(0.0, "kick"), (0.5, "kick")])
        self.assertAlmostEqual(got["kick"], 12, delta=2)
        self.assertLessEqual(got["hats"], 1)

    def test_snare_alone(self):
        got = play([(0.25, "snare"), (0.75, "snare")])
        self.assertAlmostEqual(got["snare"], 12, delta=2)
        self.assertLessEqual(got["hats"], 1)

    def test_full_kit_keeps_them_apart(self):
        got = play([(0.0, "kick"), (0.125, "hats"), (0.25, "snare"), (0.375, "hats"),
                    (0.5, "kick"), (0.625, "hats"), (0.75, "snare"), (0.875, "hats")])
        self.assertAlmostEqual(got["kick"], 12, delta=2)
        self.assertAlmostEqual(got["snare"], 12, delta=2)
        self.assertAlmostEqual(got["hats"], 24, delta=4)

    def test_next_hit_guessed_from_regular_hits(self):
        hits = [(10.0, 1), (10.5, 2), (11.0, 3), (11.5, 4)]
        self.assertAlmostEqual(T.next_hit_in(hits, 11.6), 0.4)
        self.assertAlmostEqual(T.next_hit_in(hits, 12.1), 0.4)          # one missed: the one after
        self.assertIsNone(T.next_hit_in([(10.0, 1), (10.2, 2), (11.0, 3), (11.1, 4)], 11.2))
        self.assertIsNone(T.next_hit_in(hits[:3], 11.2))

    def test_light_setting_is_checked(self):
        devs = T.clean_devices([{"ip": "1.2.3.4", "sound": "hats"}, {"ip": "1.2.3.5", "sound": "cowbell"},
                                {"ip": "1.2.3.6"}])
        self.assertEqual([d["sound"] for d in devs], ["hats", "beat", "beat"])


def feed(parts, sr=44100):
    """Feed BeatTracker a list of (seconds, signal function of t) parts; returns the tracker
    and the (time, levels, pitch, loud) snapshot taken at the end of each part."""
    tr = T.BeatTracker()
    snaps, t0 = [], 100.0
    rng = np.random.default_rng(5)
    for secs, fn in parts:
        t = np.arange(int(secs * sr)) / sr
        x = (fn(t, rng) + 0.002 * rng.standard_normal(len(t))).astype(np.float32)
        for k in range(len(x) // T.BLOCK):
            tr.process(x[k * T.BLOCK:(k + 1) * T.BLOCK], 1.5, now=t0 + k * T.BLOCK / sr)
        t0 += secs
        snaps.append(tr.shape_at(t0))
    return tr, snaps


def tone(f, a=0.3):
    return lambda t, rng: a * np.sin(2 * np.pi * f * t)


def hiss(lo, a=0.3):
    def fn(t, rng):
        spec = np.fft.rfft(rng.standard_normal(len(t)))
        spec[np.fft.rfftfreq(len(t), 1 / 44100) < lo] = 0
        n = np.fft.irfft(spec, len(t))
        return a * n / n.std()
    return fn


SILENT = lambda t, rng: 0 * t


class SoundShape(unittest.TestCase):
    """Sound bars (one light per band: bass, middle, treble) and pitch to color."""

    def test_bass_tone_fills_the_bass_bar(self):
        _, s = feed([(3, tone(80))])
        lv = s[-1]["levels"]
        self.assertGreater(lv["low"], 0.8)
        self.assertLess(lv["high"], 0.3)

    def test_treble_hiss_fills_the_treble_bar(self):
        _, s = feed([(3, hiss(4000))])
        lv = s[-1]["levels"]
        self.assertGreater(lv["high"], 0.8)
        self.assertLess(lv["low"], 0.3)

    def test_voice_range_fills_the_middle_bar(self):
        _, s = feed([(3, tone(700))])
        lv = s[-1]["levels"]
        self.assertGreater(lv["mid"], 0.8)
        self.assertLess(lv["low"], 0.3)
        self.assertLess(lv["high"], 0.3)

    def test_bars_fall_when_the_sound_stops(self):
        _, s = feed([(3, tone(80)), (1, SILENT)])
        self.assertLess(s[-1]["levels"]["low"], 0.2)

    def test_bar_follows_its_own_loudness(self):
        # a bass that gets quieter by half (-6 dB) shows a lower bar, not still full
        _, s = feed([(3, tone(80, 0.3)), (1.5, tone(80, 0.15)), (1.5, tone(80, 0.04))])
        self.assertGreater(s[0]["levels"]["low"], s[1]["levels"]["low"] + 0.08)
        self.assertGreater(s[1]["levels"]["low"], s[2]["levels"]["low"] + 0.15)

    def test_pitch_low_to_high(self):
        _, s = feed([(2, tone(90)), (2, tone(800)), (2, hiss(5000))])
        p = [x["pitch"] for x in s]
        self.assertLess(p[0], 0.2)
        self.assertTrue(0.3 < p[1] < 0.7, p[1])
        self.assertGreater(p[2], 0.8)

    def test_loudness_follows_volume(self):
        _, s = feed([(3, tone(300, 0.3)), (1.5, tone(300, 0.03)), (1, SILENT)])
        self.assertGreater(s[0]["loud"], 0.8)
        self.assertLess(s[1]["loud"], s[0]["loud"] - 0.3)
        self.assertLess(s[2]["loud"], 0.15)

    def test_shape_at_picks_the_moment_asked(self):
        # with pass-through the tracker runs ahead (heard time); a light shows what is heard then
        tr, _ = feed([(2, tone(80)), (0.6, hiss(5000))])     # 1.5 s of history is kept
        self.assertLess(tr.shape_at(101.9)["pitch"], 0.3)
        self.assertGreater(tr.shape_at(102.55)["pitch"], 0.7)

    def test_pitch_colors_run_red_to_blue(self):
        self.assertEqual(T.pitch_hue(0.0), 0)
        self.assertEqual(T.pitch_hue(0.5), 120)
        self.assertEqual(T.pitch_hue(1.0), 240)
        self.assertEqual(T.pitch_hue(1.7), 240)

    def test_new_choices_are_kept(self):
        devs = T.clean_devices([{"ip": "1.2.3.4", "sound": s} for s in ("low", "mid", "high", "pitch")])
        self.assertEqual([d["sound"] for d in devs], ["low", "mid", "high", "pitch"])


def run_tracker(x, sr=44100, start=100.0):
    """Feed audio to BeatTracker and poll it like the engine does; returns the tracker and the
    beats it scheduled as (time, first beat of the bar?, bar number)."""
    tr = T.BeatTracker()
    beats = []
    for k in range(len(x) // T.BLOCK):
        now = start + k * T.BLOCK / sr
        tr.process(x[k * T.BLOCK:(k + 1) * T.BLOCK].astype(np.float32), 1.5, now=now)
        for bt in tr.poll_events(now, 0.0, True):
            beats.append((bt, tr.last_downbeat, tr.bar_n))
    return tr, beats


def kick_loop(seconds, loud_first=True, gap=None, sr=44100, wobble=0.0):
    """Kicks at 120 BPM (4 to a 2 s bar), the first of each bar twice as loud; `gap` = (from, to)
    seconds with no drums (a breakdown), only a quiet pad."""
    x = 0.01 * np.random.default_rng(4).standard_normal(int(seconds * sr))
    x += 0.05 * np.sin(2 * np.pi * 330 * np.arange(len(x)) / sr)
    for k in range(int(seconds / 0.5)):
        at = k * 0.5
        if gap and gap[0] <= at < gap[1]:
            continue
        i = int(at * sr)
        hit = drum("kick", min(int(0.3 * sr), len(x) - i))
        vary = 1 + wobble * (np.random.default_rng(k).random() * 2 - 1)    # real kicks vary a little
        x[i:i + len(hit)] += (0.6 if loud_first and k % 4 == 0 else 0.3) * vary * hit
    return x


class Bars(unittest.TestCase):
    """Stronger flash on beat 1 of each bar, colors that move every few bars."""

    def test_finds_the_first_beat_of_the_bar(self):
        tr, beats = run_tracker(kick_loop(24))
        late = [(t, d) for t, d, _ in beats if t > 112]          # after it has settled
        firsts = [t for t, d in late if d]
        self.assertGreaterEqual(len(firsts), 4)
        on_loud = [t for t in firsts if abs(((t - 100.0) + 0.25) % 2.0 - 0.25) < 0.08]
        self.assertGreaterEqual(len(on_loud), 0.8 * len(firsts))  # the loud kick is beat 1
        self.assertAlmostEqual(len(firsts), len(late) / 4, delta=1.5)

    def test_beat_one_stays_put_when_all_kicks_are_equal(self):
        tr, beats = run_tracker(kick_loop(40, loud_first=False, wobble=0.15))
        firsts = [round((t - 100.0) % 2.0, 1) % 2.0 for t, d, _ in beats if d and t > 112]
        self.assertLessEqual(len(set(firsts)), 1, firsts)       # no wandering

    def test_beat_one_survives_a_short_pause(self):
        tr, beats = run_tracker(kick_loop(32, gap=(16, 19.5)))
        firsts = [t for t, d, _ in beats if d and 120 < t < 126]   # right after the pause
        on_loud = [t for t in firsts if abs(((t - 100.0) + 0.25) % 2.0 - 0.25) < 0.08]
        self.assertTrue(firsts and len(on_loud) == len(firsts), firsts)

    def test_bar_count_goes_up_once_per_bar(self):
        tr, beats = run_tracker(kick_loop(24))
        bars = [b for t, _, b in beats if t > 112]
        self.assertAlmostEqual(bars[-1] - bars[0], 6, delta=1)

    def test_colors_turn_together(self):
        cfg = {"colorA": "#ff0000", "colorB": "#0000ff", "mode": "tempo"}
        c = T.turn_colors(cfg, 1)
        self.assertEqual(T.hue_sat(c["colorA"])[0], 45)
        self.assertEqual(T.hue_sat(c["colorB"])[0], 285)
        self.assertEqual(T.turn_colors(cfg, 8)["colorA"], cfg["colorA"])     # full circle
        self.assertEqual(T.turn_colors({"colorA": "#ffffff", "colorB": "#0000ff"}, 1)["colorA"], "#ffffff")

    def test_settings_checked(self):
        reset_home()
        old = T.ENGINE.cfg
        try:
            T.ENGINE.cfg = T.load_config()
            self.assertEqual((T.ENGINE.cfg["accent"], T.ENGINE.cfg["bar_shift"], T.ENGINE.cfg["drops"]), (False, 0, False))
            T.apply_config({"accent": 1, "bar_shift": 8, "drops": 1})
            self.assertEqual((T.ENGINE.cfg["accent"], T.ENGINE.cfg["bar_shift"], T.ENGINE.cfg["drops"]), (True, 8, True))
            T.apply_config({"bar_shift": 5})
            self.assertEqual(T.ENGINE.cfg["bar_shift"], 0)
        finally:
            T.ENGINE.cfg = old


class Drops(unittest.TestCase):
    """The drums stop (a breakdown), then come back hard (the drop)."""

    def test_breakdown_and_drop_are_found(self):
        tr, _ = run_tracker(kick_loop(36, gap=(16, 24)))
        drops = list(tr.drops)
        self.assertEqual(len(drops), 1, drops)
        self.assertAlmostEqual(drops[0], 124.0, delta=0.6)        # the first kick after the gap

    def test_works_when_the_clock_starts_at_zero(self):
        tr, _ = run_tracker(kick_loop(36, gap=(16, 24)), start=0.0)
        self.assertEqual(len(tr.drops), 1)

    def test_long_break_still_counts(self):
        tr, _ = run_tracker(kick_loop(100, gap=(16, 79)))      # a 63 s break, like a long synth solo
        self.assertEqual(len(tr.drops), 1)
        self.assertAlmostEqual(tr.drops[0], 179.0, delta=0.6)

    def test_steady_song_has_no_drop(self):
        tr, _ = run_tracker(kick_loop(36))
        self.assertEqual(len(tr.drops), 0)
        self.assertFalse(tr.breakdown)

    def test_short_pause_is_not_a_breakdown(self):
        tr, _ = run_tracker(kick_loop(36, gap=(16, 17)))
        self.assertEqual(len(tr.drops), 0)


class ColorBlend(unittest.TestCase):
    """Calm -> energetic blends go around the color wheel, so the middle stays vivid."""

    def cfg(self, a, b):
        return {"colorA": a, "colorB": b, "mode": "tempo"}

    def test_blend_goes_around_the_wheel(self):
        hue, sat = T.pick_color(self.cfg("#0000ff", "#ff8000"), 120)   # halfway
        self.assertGreaterEqual(sat, 90)               # not a washed-out gray/white
        self.assertTrue(hue >= 270 or hue <= 30, hue)  # blue -> magenta/red side -> orange

    def test_blend_from_white_keeps_other_hue(self):
        hue, sat = T.pick_color(self.cfg("#ffffff", "#ff0000"), 120)
        self.assertEqual((hue, sat), (0, 50))

    def test_ends_are_exact(self):
        self.assertEqual(T.pick_color(self.cfg("#00ff00", "#ff0000"), 60), (120, 100))
        self.assertEqual(T.pick_color(self.cfg("#00ff00", "#ff0000"), 180), (0, 100))

    def test_opposite_colors_pick_one_direction(self):
        a = T.pick_color(self.cfg("#ff0000", "#00ffff"), 119)
        b = T.pick_color(self.cfg("#ff0000", "#00ffff"), 121)
        self.assertLess(abs(((a[0] - b[0] + 180) % 360) - 180), 10)   # no jump across the wheel

    def test_live_hex_uses_the_wheel_blend(self):
        self.assertNotIn(T.live_color_hex(self.cfg("#0000ff", "#ff8000"), 120), ("#ffffff", "#808080"))


class FakeTapoInfo:
    def __init__(self, **kw):
        self.device_on, self.brightness, self.hue, self.saturation = True, 40, 200, 60
        self.color_temp, self.dynamic_light_effect_enable = 0, False
        self.__dict__.update(kw)


class FakeTapoBulb:
    """Records what put_back sends, the way the tapo library's builder is used."""
    def __init__(self, info):
        self.info, self.calls = info, []

    async def get_device_info(self):
        return self.info

    async def off(self):
        self.calls.append(("off",))

    def set(self):
        bulb, parts = self, []

        class Builder:
            def brightness(s, b): parts.append(("brightness", b)); return s
            def hue_saturation(s, h, sat): parts.append(("hue_saturation", h, sat)); return s
            def color_temperature(s, ct): parts.append(("color_temperature", ct)); return s
            async def send(s, handler): bulb.calls.append(tuple(parts))
        return Builder()


class RestoreLights(unittest.TestCase):
    """Play remembers each light's look; Stop puts it back."""

    def run_async(self, coro):
        import asyncio
        return asyncio.run(coro)

    def test_tapo_color_is_put_back(self):
        bulb = FakeTapoBulb(FakeTapoInfo())
        snap = self.run_async(T.take_snapshot(bulb))
        self.run_async(T.put_back(bulb, snap))
        self.assertEqual(bulb.calls, [(("brightness", 40), ("hue_saturation", 200, 60))])

    def test_tapo_white_is_put_back_as_white(self):
        bulb = FakeTapoBulb(FakeTapoInfo(color_temp=2700, brightness=70))
        self.run_async(T.put_back(bulb, self.run_async(T.take_snapshot(bulb))))
        self.assertEqual(bulb.calls, [(("brightness", 70), ("color_temperature", 2700))])

    def test_tapo_that_was_off_goes_off_again(self):
        bulb = FakeTapoBulb(FakeTapoInfo(device_on=False))
        self.run_async(T.put_back(bulb, self.run_async(T.take_snapshot(bulb))))
        self.assertEqual(bulb.calls, [("off",)])

    def test_govee_state_is_put_back(self):
        lamp = T.GoveeLamp("127.0.0.9")
        lamp.status = {"onOff": 1, "brightness": 35, "color": {"r": 10, "g": 20, "b": 30}, "colorTemInKelvin": 0}
        snap = self.run_async(T.take_snapshot(lamp))
        sent = []
        old = T.GOVEE.send
        T.GOVEE.send = lambda ip, cmd, data: sent.append((cmd, data))
        try:
            self.run_async(T.put_back(lamp, snap))
            lamp.status = {"onOff": 0, "brightness": 35, "color": {"r": 0, "g": 0, "b": 0}, "colorTemInKelvin": 0}
            self.run_async(T.put_back(lamp, self.run_async(T.take_snapshot(lamp))))
        finally:
            T.GOVEE.send = old
        self.assertEqual(sent[:2], [("brightness", {"value": 35}),
                                    ("colorwc", {"color": {"r": 10, "g": 20, "b": 30}, "colorTemInKelvin": 0})])
        self.assertEqual(sent[2:], [("turn", {"value": 0})])

    def test_list_change_while_playing_only_puts_back_removed_lights(self):
        e = T.Engine()
        kept, gone = FakeTapoBulb(FakeTapoInfo()), FakeTapoBulb(FakeTapoInfo(hue=10))
        lights = [T.Light(kept, 0, "1.1.1.1"), T.Light(gone, 1, "1.1.1.2")]
        e.saved = {"1.1.1.1": self.run_async(T.take_snapshot(kept)), "1.1.1.2": self.run_async(T.take_snapshot(gone))}
        e.cfg = dict(e.cfg, devices=[{"ip": "1.1.1.1"}])
        e.want_running = True
        e.stop_evt.set()                       # a background restart, not Stop
        self.run_async(e._put_back(lights))
        self.assertEqual((kept.calls, len(gone.calls)), ([], 1))
        self.assertEqual(list(e.saved), ["1.1.1.1"])   # the kept light's first snapshot survives

    def test_unreadable_light_gives_no_snapshot(self):
        class Broken:
            async def get_device_info(self):
                raise OSError("no answer")
        self.assertIsNone(self.run_async(T.take_snapshot(Broken())))

    def test_failed_put_back_says_which_light(self):
        self.assertIn("Kitchen", T.status_text({"running": False, "error": T.RESTORE_MSG + "Kitchen",
                                                "cfg": {"devices": [{"ip": "x"}]}})[0])


class Preview(unittest.TestCase):
    def test_preview_needs_play(self):
        was = T.ENGINE.running
        T.ENGINE.running = False
        try:
            r = T.preview_color("#ff0000")
            self.assertFalse(r["ok"])
            self.assertIn("Play", r["error"])
        finally:
            T.ENGINE.running = was

    def test_preview_rejects_bad_color(self):
        self.assertFalse(T.preview_color("red; drop")["ok"])

    def test_preview_sets_engine_override(self):
        was = T.ENGINE.running
        T.ENGINE.running = True
        try:
            self.assertTrue(T.preview_color("#00ff00")["ok"])
            self.assertEqual(T.ENGINE.preview[:2], (120, 100))
        finally:
            T.ENGINE.running = was
            T.ENGINE.preview = None


class AppShell(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, os.path.join(ROOT, "app"))
        import temponome_app
        self.A = temponome_app

    def test_free_port_skips_busy_port(self):
        import socket
        held = socket.socket()
        held.bind(("127.0.0.1", 0))
        held.listen()
        busy = held.getsockname()[1]
        try:
            self.assertNotEqual(self.A.free_port(busy), busy)
        finally:
            held.close()

    def test_server_starts_and_shutdown_frees_everything(self):
        port = self.A.free_port(8765)
        srv = T.make_server(port)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state") as r:
            self.assertEqual(r.status, 200)
        T.ENGINE.running = True          # pretend it was playing
        self.A.shutdown_all(srv)
        self.assertFalse(T.ENGINE.running)
        self.assertEqual(self.A.free_port(port), port)   # the port is free again


class AppShellMinors(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, os.path.join(ROOT, "app"))
        import temponome_app
        self.A = temponome_app

    def test_start_server_falls_back_when_port_taken(self):
        import socket
        held = socket.socket()
        held.bind(("127.0.0.1", 0))
        held.listen()
        busy = held.getsockname()[1]
        try:
            srv = self.A.start_server(busy)
            self.assertNotEqual(srv.server_address[1], busy)
            srv.server_close()
        finally:
            held.close()

    def test_windows_leave_room_for_the_title_bar(self):
        # measured in the real windows: the deck needs 600x400 and Settings 680x640 of page
        A = self.A
        self.assertEqual(A.MAIN_SIZE, (600, 400 + A.TITLE_BAR))
        self.assertEqual(A.SETTINGS_SIZE, (680, 640 + A.TITLE_BAR))
        self.assertGreaterEqual(A.MAIN_MIN[1] - A.TITLE_BAR, 330)   # smallest size checked in the browser

    def test_settings_opens_beside_the_main_window(self):
        pos, W = self.A.settings_position, self.A.SETTINGS_SIZE[0]
        # room on the right: Settings sits right of the main window, same top edge
        self.assertEqual(pos((100, 200, 600, 432), (1800, 1100)), (712, 200, None))
        # main window on the right of the screen: Settings goes to its left
        x, y, moved = pos((1000, 200, 600, 432), (1728, 1117))
        self.assertEqual((x + W + self.A.GAP, moved), (1000, None))
        # centered on a 1470-wide MacBook screen: the main window slides over to make room
        x, y, moved = pos((435, 300, 600, 432), (1470, 956))
        self.assertIsNotNone(moved)
        self.assertGreaterEqual(x, moved + 600)            # no overlap
        self.assertLessEqual(x + W, 1470)                  # still on screen
        # tiny screen: some overlap, but the window stays on screen and below the menu bar
        x, y, moved = pos((340, 0, 600, 432), (1280, 600))
        self.assertTrue(0 <= x <= 1280 - W and y >= self.A.MENU_BAR)

    def test_api_exposes_only_methods(self):
        api = self.A.Api("http://127.0.0.1:1")
        public = [k for k in vars(api) if not k.startswith("_")]
        self.assertEqual(public, [])

    def test_close_handler_exits_even_if_shutdown_fails(self):
        calls = []
        def boom(_):
            raise RuntimeError("x")
        with self.assertRaises(RuntimeError):     # the real os._exit never returns; this stand-in does
            self.A.on_main_closed(object(), shutdown=boom, exit=lambda code: calls.append(code))
        self.assertEqual(calls, [0])

    def test_reopen_settings_after_window_closed_underneath(self):
        class Dead:
            def evaluate_js(self, js):
                raise RuntimeError("window closed")
        api = self.A.Api("http://127.0.0.1:1")
        api._settings = Dead()
        made = []
        api._create_settings = lambda tab: made.append(tab)
        api.open_settings("sound")
        self.assertEqual(made, ["sound"])


class GoveeLoop(unittest.TestCase):
    def test_receive_loop_does_not_spin_on_errors(self):
        bus = T.GoveeBus()
        calls = []
        class BadSock:
            def recvfrom(self, n):
                calls.append(1)
                if len(calls) > 2000:
                    bus.sock = None
                raise OSError("network down")
        bus.sock = BadSock()
        t = threading.Thread(target=bus._recv_loop, daemon=True)
        t.start()
        t.join(0.5)
        bus.sock = None
        self.assertLess(len(calls), 50)


class GoveeSecondCopy(unittest.TestCase):
    def test_second_copy_gets_plain_message(self):
        import asyncio
        import socket
        T.GOVEE.close()
        other = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)   # another program holds 4002
        other.bind(("", T.GoveeBus.REPLY_PORT))
        try:
            with self.assertRaises(ConnectionError) as cm:
                asyncio.run(T.GoveeLamp("127.0.0.1").connect())
            self.assertIn("Another copy of Temponome", str(cm.exception))
        finally:
            other.close()
            T.GOVEE.close()


if __name__ == "__main__":
    unittest.main()
