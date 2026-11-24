# Temponome Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the app to Temponome, give it the metronome-lamp icon and the compact-deck UI with a Settings window, and ship it as a `.pkg` whose app runs in its own window with Python bundled.

**Architecture:** The engine and HTTP server stay in one Python module (renamed `temponome.py`). The two HTML pages move out of the Python string into `ui/` files served from disk. A small pywebview shell (`app/temponome_app.py`) starts the server on a free port and shows the pages in native WebKit windows. PyInstaller bundles it into `Temponome.app`, and `pkgbuild` + `productbuild` wrap that in `Temponome.pkg`.

**Tech Stack:** Python 3.14 (fallback 3.13 for the build env), numpy, sounddevice, tapo 0.13, pywebview 6.2, PyInstaller 6.22, macOS `pkgbuild`/`productbuild`/`iconutil`/`qlmanage`/`sips`. Tests: `tests/simulate.py` (existing) + stdlib `unittest` (pytest is not installed).

**Spec:** `docs/temponome-design.md`

**No git in this folder:** where a task says "Checkpoint", run the full test command and copy `temponome.py` + `ui/` to the scratchpad as a backup. Do not `git init` unless the owner asks.

## Global Constraints

- Owner-visible name is exactly `Temponome`. No "Tapo Music Sync" anywhere the owner sees it.
- No Audio-Technica name or logo anywhere. Borrow the look only.
- Behaviour of beat detection, light timing, Tapo/Govee control and calibration is unchanged. `python3 tests/simulate.py` must print `9/9 passed` after every task.
- Settings file: `~/Library/Application Support/Temponome/settings.json`, chmod 600; migrated from `~/.tapo_music_ui.json`.
- Bundle id `local.temponome.app`, version `1.0`, arm64 only; installs to `/Applications/Temponome.app`.
- Accent `#ff6a2b`. Dark body `#1b1b1c`, platter `#2a2a2c`, silver `#c7c7cc`. Light body `#f2f2f0`, platter `#dcdcd8`. Font `-apple-system`. Sentence case.
- Hit areas ≥ 28 pt; full keyboard access; visible focus rings; `prefers-reduced-motion` honoured; platter pulse ≤ 150 ms, tonearm swing 400 ms.
- Permission texts (Info.plist): mic "Temponome listens to the music to find the beat.", camera "Used only for timing calibration. The video stays on this Mac.", local network "Temponome finds and controls your lights on your Wi-Fi."
- The old double-click launcher `Start Tapo Music.command` keeps working until the owner confirms the `.app`.
- The Tapo password is never printed, logged or put in a URL.

## Review Focus

1. **Old and new settings files both exist**: never overwrite the new file from the old one; migrate only when the new one is missing; password and calibrations survive; mode 600. (Task 1 test.)
2. **Port 8765 already taken by the old launcher**: the app must still start, on another free port. (Task 6 test.)
3. **Light list edited while playing, and one light doesn't answer**: auto-restart must not loop or crash. The others keep pulsing, and the status names the missing light. (Task 2 test.)
4. **No usable audio input (BlackHole not installed, mic blocked)**: the status says so in plain words and Play doesn't crash. (Task 3 test.)
5. **Window closed while playing**: the engine stops and the process exits; no orphan server keeps the port or the lights. (Task 6 test.)

---

### Task 1: Rename the module, move settings, move the pages out

**Files:**
- Create: `temponome.py` (moved from `tapo_music_ui.py`), `ui/main.html`, `ui/settings.html` (temporary: current page, split later), `tests/test_temponome.py`
- Modify: `tapo_music_ui.py` → 3-line shim; `tests/simulate.py` (import `temponome`); `Start Tapo Music.command` (still runs `tapo_music_ui.py`)

**Interfaces:**
- Produces: `temponome.CONFIG_DIR: str`, `temponome.CONFIG_PATH: str`, `temponome.OLD_CONFIG_PATH: str`, `migrate_config() -> bool` (True if migrated), `UI_DIR: str` (folder of `ui/`, resolved via `sys._MEIPASS` when frozen), `serve_ui(name: str) -> bytes`. Handler routes: `/` → `ui/main.html`, `/settings` → `ui/settings.html`, `/ui/<file>` → static file from `UI_DIR` (only names matching `^[a-z0-9_-]+\.(css|js|svg|png)$`).

- [ ] **Step 1: Write failing tests** in `tests/test_temponome.py` (unittest, HOME pointed at a temp dir before import):
  - `test_migrates_old_file`: old file `{"email":"e","password":"p","devices":[{"ip":"1.2.3.4","model":"l530","calib":-55}]}` → `migrate_config()` is True; new file has the same email, password and `calib == -55`; `os.stat(...).st_mode & 0o777 == 0o600`.
  - `test_never_overwrites_new_file`: both exist with different emails → `migrate_config()` False; new file unchanged.
  - `test_ui_routes`: `serve_ui("main.html")` starts with `b"<!doctype html>"`; a request for `/ui/../temponome.py` gets 404.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_temponome -v` → FAIL (module `temponome` missing).
- [ ] **Step 3: Implement.** Move the code into `temponome.py`. `CONFIG_DIR = ~/Library/Application Support/Temponome`; `load_config()` calls `migrate_config()` first; the old file is left in place (not deleted). Write `PAGE` out to `ui/main.html` unchanged and serve it from disk. Replace "Tapo Music Sync" with "Temponome" in titles and messages. The shim `tapo_music_ui.py` is `from temponome import main` + `if __name__ == "__main__": main()`.
- [ ] **Step 4: Run** the unittest file → PASS; `python3 tests/simulate.py` → `9/9 passed`; `python3 tapo_music_ui.py` serves the page at 8765 (curl `/` returns 200).
- [ ] **Step 5: Checkpoint.**

### Task 2: Apply light-list changes immediately

**Files:** Modify `temponome.py` (Handler `/api/config`, `Engine`); Test: `tests/simulate.py` (new `run_live_relist_checks`)

**Interfaces:**
- Produces: `Engine.restart()`: stop, wait for the thread (≤ 3 s), start again; the config handler calls it when `devices` (ip/model set) changed and `ENGINE.running`. `Engine.missing: list[str]`: names (or IPs) of lights that failed to connect.

- [ ] **Step 1: Failing check** in `simulate.py`: engine running with fake Govee lamp A; POST-equivalent `config` update adds unreachable Govee `192.0.2.1` named "Ghost". Within 6 s: `e.running` is True, A still receives `brightness` commands, `e.missing == ["Ghost"]`, and `e.restart` was called once (no loop: count restarts over 10 s == 1).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the restart, plus a change check comparing `[(d["ip"], d["model"]) for d in devices]` only, so colour or offset edits don't restart.
- [ ] **Step 4: Run** `python3 tests/simulate.py` → `10/10 passed`.
- [ ] **Step 5: Checkpoint.**

### Task 3: Plain-words status

**Files:** Modify `temponome.py`; Test `tests/test_temponome.py`

**Interfaces:**
- Produces: `status_text(st: dict) -> tuple[str, str]` returning `(text, level)` with level in `{"ok","wait","warn","error","idle"}`; `_state()` adds `"status": text, "level": level, "missing": [...]`.

- [ ] **Step 1: Failing tests**, one assertion each (exact copy):
  - stopped → `("Stopped", "idle")`
  - running, 3 lights, locked, onsets > 0 → `("Listening · 3 lights · on the beat", "ok")`
  - running, 1 light, not locked, db > −70 → `("Finding the beat · 1 light", "wait")`
  - running, db ≤ −90 for silence → `("Can't hear anything. Check the audio input in Settings > Sound.", "warn")`
  - running, missing ["Kitchen lamp"] → text contains `"Kitchen lamp didn't answer"`, level `"warn"`
  - error "Could not connect to any light…" → `("None of your lights answered. Check they're switched on, then press Play again.", "error")`
  - error from no input device (`PortAudioError` text) → `("No audio input found. Install BlackHole or pick the microphone in Settings > Sound.", "error")`
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** with the above mapping; raw errors stay in `"error"` for a "Details" disclosure, never as the headline.
- [ ] **Step 4: Run** unittest + simulate → all pass.
- [ ] **Step 5: Checkpoint.**

### Task 4: Main window: compact deck (`ui/main.html`)

**Files:** Create `ui/main.html`, `ui/deck.css`, `ui/common.js`; Modify nothing in Python except routes if needed.

**Interfaces:**
- Consumes: `/api/state` (`status`, `level`, `bpm`, `running`, `cfg`, `lights`, plus new `color: "#rrggbb"` = current blended colour), `/api/config`, `/api/start`, `/api/stop`.
- Produces: `common.js` exports on `window.T`: `api(path, body?) -> Promise<json>`, `saveCfg(partial: object) -> Promise`, `openSettings(tab?: "lights"|"colors"|"sound"|"timing")`, which calls `window.pywebview.api.open_settings(tab)` when present, else `location.href="/settings#"+tab`.
- Python: `_state()` adds `color` (hex of `pick_color(cfg, bpm)` at full value).

- [ ] **Step 1:** Build the layout from the spec's sketch: platter SVG (ribs = 5 thin circles), centre label with BPM, glowing in `color` and scaling 1→1.06 on each beat (driven by polling `/api/state` every 100 ms and a `beat` counter added to `_state()`: `ENGINE.beats`, incremented when a beat fires); tonearm SVG rotating −28°→0° when `running`; round Play/Stop (`aria-label` toggles; Space key); Brightness slider → `maxB`; Pulse slider → `smooth`; Together/Chase switch → `multi`, hidden when `lights < 2`; status line coloured by `level`; ⚙ Settings button; empty state "Find your lights to get started" + button `openSettings("lights")` when no device has an IP.
- [ ] **Step 2:** Dark/light via `prefers-color-scheme` with the Global Constraints colours; reduced motion disables pulse/swing animation.
- [ ] **Step 3: Verify** in the browser pane with the fake-lights server (`.claude/launch.json` → scratchpad `fake_server.py`, as before): Play starts the fake engine; BPM shows ~120 within 6 s; tonearm moves; sliders change `/api/state` cfg; Space toggles; Tab reaches every control with a visible ring; screenshots in dark and light; at 420 pt width nothing overflows.
- [ ] **Step 4:** `python3 tests/simulate.py` → all pass. **Checkpoint.**

### Task 5: Settings window (`ui/settings.html`)

**Files:** Create `ui/settings.html`, `ui/settings.js`; reuse `ui/deck.css`, `ui/common.js`.

**Interfaces:**
- Consumes: everything the old page used (`/api/scan`, `/api/calib`, `/api/devices`, `/api/flash`, `/api/config`) and `T.*` from Task 4.
- Produces: tab is chosen from `location.hash` (`#lights` default).

- [ ] **Step 1:** Move the old page's features into four toolbar tabs, keeping all JS behaviour (finder tick-boxes, names, calibration, colour wheels):
  - **Lights**: Find my lights, list, Add by IP; per-light colour menu and "Timing offset (ms)" labelled field; Tapo email/password only when any device model ≠ `govee`.
  - **Colors**: wheels A/B, "Blend by tempo / One color".
  - **Sound**: input menu with the hint "BlackHole 2ch: plays your Mac's own sound to Temponome (recommended)"; level meter; "Follow a steady beat" switch (`lock`); "Which beats" slider (`sensitivity`, left label "More, lighter beats", right "Fewer, strong beats"); "Dimmest level" (`minB`).
  - **Timing**: calibration card (same flow); "Fine-tune" slider (`lead`, −150…250) with "Move right if the lights feel late".
- [ ] **Step 2: Verify** in the browser pane: each tab renders in dark and light; the finder adds and removes lights (canned scan, as in the earlier test); the fake-camera calibration run from the earlier session saves a `calib` value; edits persist after reload.
- [ ] **Step 3:** Delete the old monolithic page; `/` is the deck, `/settings` is this. `python3 tests/simulate.py` → all pass. **Checkpoint.**

### Task 6: Native window shell

**Files:** Create `app/temponome_app.py`; Test `tests/test_temponome.py` (shell helpers only)

**Interfaces:**
- Consumes: `temponome.make_server(port: int) -> ThreadingHTTPServer` (new; `main()` uses it), `temponome.ENGINE`.
- Produces: `free_port(preferred: int = 8765) -> int`; `class Api: open_settings(tab: str) -> None`; `run() -> None` (main window 560×340, min 420×300, title "Temponome"; settings window 640×520, created once, then shown and focused on later calls; closing the main window calls `ENGINE.stop()`, `server.shutdown()`, then exits).

- [ ] **Step 1: Failing tests:** `free_port(8765)` returns a port ≠ 8765 while a socket holds 8765; `make_server(p)` serves `/api/state` with 200; after `shutdown_all()` (the close handler body, factored out) the port is free again and `ENGINE.running` is False.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** with pywebview (`webview.create_window`, `js_api=Api()`, `events.closed`). Install pywebview in the build venv only (Task 7); for the test, import the shell helpers without importing `webview` at module top.
- [ ] **Step 4: Verify the camera early:** in a dev venv with pywebview, run the shell and open Timing → Calibrate; record whether WebKit grants `getUserMedia`. If it doesn't, make `Calibrate timing` call `Api.open_in_browser("/settings#timing")` (opens the default browser) and note this in CLAUDE.md.
- [ ] **Step 5:** All tests pass. **Checkpoint.**

### Task 7: Icon, bundle and installer

**Files:** Create `assets/icon.svg`, `build/build_pkg.sh`, `build/temponome.spec`, `build/welcome.txt`; Output `dist/Temponome.pkg` (not kept in the source folder's backups).

**Interfaces:**
- Consumes: `app/temponome_app.py:run`, `ui/`, `assets/icon.svg`.
- Produces: `build/build_pkg.sh [--sign "Developer ID Application: …"]` → `dist/Temponome.app`, `dist/Temponome.pkg`.

- [ ] **Step 1: Icon.** Draw logo 2 in `assets/icon.svg` at 1024×1024 (Apple rounded-rect grid: 824×824 body, 185.4 corner radius, centred), with a simplified variant without the light pool for ≤ 32 px. Rasterise with `qlmanage -t -s 1024 -o`, then `sips -z` to every iconset size, then `iconutil -c icns`. Check the 16, 32 and 1024 PNGs by eye (Read tool).
- [ ] **Step 2: Build script** (`set -euo pipefail`): fresh venv in `build/.venv` (python3.14; if PyInstaller fails, retry with `python3.13` when present), install `numpy sounddevice tapo pywebview pyinstaller`, run PyInstaller with `temponome.spec` (`--windowed`, `target_arch='arm64'`, datas `ui/`, icon, `info_plist` with the bundle id, version and the three permission texts from Global Constraints plus `NSBonjourServices: []` and `LSMinimumSystemVersion: 13.0`), ad-hoc `codesign --force --deep -s -`, then `pkgbuild --component dist/Temponome.app --install-location /Applications` + `productbuild` with `welcome.txt` (what Temponome does; BlackHole needed for Mac audio, with its download page; first open: right-click → Open).
- [ ] **Step 3: Verify the bundle runs without Python:** `env -i HOME="$HOME" /path/dist/Temponome.app/Contents/MacOS/Temponome` with `PATH=/usr/bin:/bin` starts, serves `/api/state`, and `otool -L` on the bundled `_sounddevice`/PortAudio shows only bundle or system paths. Then `open dist/Temponome.app`: the window shows; Find my lights finds the 3 Tapo lamps and the Govee H6052 (read-only search); the Dock and menu show "Temponome" with the icon.
- [ ] **Step 4: Verify the installer:** `pkgutil --payload-files dist/Temponome.pkg | head` lists `./Temponome.app/...`. Install only after the owner says yes.
- [ ] **Step 5: Checkpoint.**

### Task 8: Docs and hand-over

**Files:** Modify `README.md`, `CLAUDE.md`; memory note on the settings path.

- [ ] **Step 1:** README: install the pkg, first open (right-click → Open), BlackHole, where settings live, the launcher as a fallback. CLAUDE.md: new file map (`temponome.py`, `ui/`, `app/`, `build/`, `assets/`), the build command, test count, the camera outcome from Task 6, and the settings path.
- [ ] **Step 2:** Final run: unittest + `simulate.py` all pass; list for the owner what was verified on this Mac and what wasn't (install, real music through BlackHole in the bundled app).
