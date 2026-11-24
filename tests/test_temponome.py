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
