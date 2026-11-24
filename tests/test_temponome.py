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
import unittest
import urllib.request

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
