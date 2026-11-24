# Temponome

(Formerly "Tapo Music Sync"; the folder keeps its old name.) Makes TP-Link Tapo and Govee
lights pulse and change color to music, live, on macOS. Design: `docs/temponome-design.md`;
build plan and its ledger of decisions: `docs/superpowers/plans/2026-11-24-temponome.md`.
The owner is not a programmer: explain things in plain words, give exact steps for
anything they must do on their Mac, and keep the double-click launcher working.

## Publishing
- Public repo https://github.com/petroskon18/temponome (GPL-3.0), commits use the GitHub
  noreply email. Releases attach `dist/Temponome.dmg` (`gh release create vX.Y.Z dist/Temponome.dmg`).
  Before pushing, check that no IP addresses, light names, emails or settings files are included.

## Owner's setup
- **Final goal: a macOS `.pkg` installer whose only outside requirement is BlackHole**
  (system-audio loopback). Everything else (Python or another runtime, packages) must be
  bundled. The owner is fine with leaving Python if something else works better.
- For now, music is picked up by the **Mac's microphone** (music plays from a speaker);
  BlackHole 2ch is supported too and will be the input in the final app.
- Lights: **TP-Link Tapo L530** bulbs and a **Govee Aura table lamp** (model H6052,
  LAN Control on; answered status in about 17 ms). The app supports several lights at
  once, mixing brands. "Find my lights" found all of them on the owner's network,
  including light names written in Greek (non-Latin names display fine).
- **Finding lights:** the "Find my lights" button (`GET /api/scan` → `scan_all`) runs the
  tapo library's `discover_devices("255.255.255.255", 3)` (needs the Tapo login; keeps
  only color lights/strips, maps "L530 Series" → `l530`) and the Govee multicast search in
  parallel, about 3 s. The page shows a tick-box list; ticking adds a device with its
  `name` (stored per device and shown above its row), unticking removes it. A slow
  bulb may miss one search, so pressing it again can find more.
- Lights are controlled over local Wi-Fi with the unofficial `tapo` Python library
  (`pip install tapo`, https://github.com/mihai-dinculescu/tapo), logging in with the
  owner's Tapo app email and password.
- Govee lamps use Govee's **LAN Control API** (JSON over UDP, standard library only,
  no Govee login): commands to the lamp's port 4003, replies to our port 4002, search by
  multicast to 239.255.255.250:4001. Code: `GoveeBus` (one shared socket on 4002) and
  `GoveeLamp`. UDP has no acknowledgement, so a Govee light's measured round trip is ~0
  and the webcam calibration supplies its real delay. Updates are spaced ≥ 80 ms
  (`min_gap`). The Tapo login is only required when a Tapo light is in the list.

## Files
- `temponome.py`: engine and local web server (Engine, BeatTracker, Tapo/Govee control,
  finder, calibration API, `status_text()` plain-words status, `apply_config()` which
  restarts the engine when the light list changes while playing, `make_server(port)`).
- `ui/`: the pages, served from disk. `main.html` = the compact turntable "deck" (Play,
  Brightness, Pulse, Together/Chase, status); `settings.html` + `settings.js` = Settings
  window (Lights, Colors, Sound, Timing tabs; finder and webcam calibration live here);
  `deck.css` (LP60-style look, dark = black deck, light = white deck; accent #e2531b);
  `common.js` (`T.api`, `T.saveCfg`, `T.openSettings`).
- `app/temponome_app.py`: the Mac app shell. Picks a free port (8765 if free), starts the
  server and opens native WebKit windows with pywebview; Settings is a second window;
  closing the main window stops the engine and quits.
- `build/build_dmg.sh`: builds `Temponome.app` (PyInstaller, `build/temponome.spec`,
  Python and all packages bundled, arm64, ad-hoc signed) and the drag-to-install disk
  image `dist/Temponome.dmg` (dmgbuild; layout in `build/dmg/settings.py`, background
  `build/dmg/background.svg` drawn on a square canvas because qlmanage renders squares,
  then the middle 1200x800 is kept and marked 144 dpi; `build/dmg/Read Me.txt`). It builds
  in `~/Library/Caches/temponome-build/` because ~/Documents is synced by iCloud Drive,
  whose file metadata makes `codesign` fail. With an Apple Developer account pass
  `--sign "Developer ID Application: …"` and optionally `--notary-profile <profile>`
  (uses `build/entitlements.plist`; untested without an account). Uses `build/.venv`.
  The owner asked for a .dmg instead of the earlier .pkg (2026-11-24).
- **Window sizes** (`app/temponome_app.py`): pywebview sizes include the 32 pt title bar
  (`TITLE_BAR`). Measured page needs: deck 600x400, Settings 680x640; minimums 440x330 and
  480x420. The deck layout shrinks the record with the window (`--s` in main.html) so it
  never scrolls; Settings scrolls under a sticky tab bar. Settings opens beside the main
  window (`settings_position`: right, else left, else the main window slides over; only
  a very small screen overlaps), checked in real windows on a 1470x956 screen.
- **Design-critique fixes (2026-11-24):** orange buttons with text use `--accent-fill`
  #c2410c (5.2:1 with white); light-mode `--mut` is #5e5e63; Together | Chase is a two-part
  radio control (`.seg`); Stop shows a square; the Timing slider runs Earlier (left) →
  Later (right) and stores `lead = -slider`; per-light offsets moved to the Timing tab
  ("One light out of step", shown with 2+ lights).
- `assets/icon.svg` (+ `icon-small.svg` for 16/32 px) → `assets/Temponome.icns`: logo 2,
  a metronome-shaped table lamp. Rebuild with qlmanage → sips → iconutil (see ledger).
- `tapo_music_ui.py`: 3-line shim so the old launcher keeps working.
- `Start Tapo Music.command`: old double-click launcher (browser version). Keep it
  working until the owner has used the installed app for a while.
- `tests/simulate.py`: runs the real `Engine` against fake lights and synthetic
  music (it mocks `tapo` and `sounddevice`). Use it to check any change to beat
  detection or light timing: `python3 tests/simulate.py` should print `12/12 passed`
  (7 music scenarios, calibration / on-beat, Govee with a fake lamp on 127.0.0.1, live
  light-list changes, a Tapo bulb that takes 30 s to answer, and a light unplugged mid-song). It needs numpy and scipy. Stop any other Temponome first:
  only one program can hold UDP port 4002 (Govee replies).
- `tests/test_temponome.py`: unit tests (stdlib unittest; pytest isn't installed):
  `python3 -m unittest tests.test_temponome` → OK (42 tests: settings migration and safe
  saving, page routes and the foreign-request check, status wording, deck state, app shell
  port/shutdown, second-copy message).
- **Robustness rules (from the final review):** settings are written atomically under
  `CONFIG_LOCK` and an unreadable file falls back to the old one; a page that loaded
  before a calibration can't wipe measured `calib` values (`apply_config` keeps them);
  each light connect is capped at `CONNECT_TIMEOUT` = 5 s; `Engine.want_running` is what
  the user asked for (Play/Stop), and a background restart never overrides Stop; the
  server rejects other Host names (403) and non-JSON POSTs (415), so other websites
  can't drive it, and the pages send `Content-Type: application/json` (`T.api`).
- Settings (including the Tapo password) are saved in
  `~/Library/Application Support/Temponome/settings.json` (chmod 600), copied once from
  the old `~/.tapo_music_ui.json` (left in place). Never commit or print them.

## How it works
1. **Audio:** `sounddevice` delivers 512-sample blocks at 44.1 kHz to
   `BeatTracker.process`, which runs on the audio thread.
2. **Beat detection:** two onset detectors, OR-ed together:
   - a bass-energy jump (40–150 Hz) above its 1-second average × sensitivity;
   - spectral flux (40–250 Hz) above mean + (sens−1)·4·std over the last 1.5 s.
   **Auto-gain:** `peak_rms` follows the loudest recent level (about 10 s decay),
   and onsets only count when the block is above 12% of that. This replaced a fixed
   `rms > 0.002` gate that silenced quiet mics.
3. **Tempo:** autocorrelation of 8 s of flux, searched over 70–170 BPM and weighted
   toward 115. A large tempo change is accepted only after 3 consistent readings.
   **Phase check** (`_check_phase`, every 0.5 s): sums low-band flux along every possible
   grid position over the last 8 s and moves the grid if another position clearly wins
   twice in a row. Without it the grid could lock half a beat off, onto hi-hats between
   kicks, and stay there, because each hi-hat reset the "8 misses → restart" counter.
4. **Lock to tempo** (default on): instead of firing on every onset, it fires on a
   steady beat grid (`t0` + k·period) that real onsets nudge into place. This
   removed jitter from noisy mic input.
5. **Lights:** each light has its own envelope (jumps to 1 on a beat, then decays
   by the "pulse length" half-life). Its brightness is rounded to 10% steps, and a
   command is sent only when the value changed. Sends run in parallel, one in flight
   per light, with a 3 s timeout. Each light's round trip is measured live.
   Uncalibrated: beats fire early by `lead` (the "timing nudge") + half the light's
   latency difference from the average + its offset. Calibrated (device `calib` set):
   early by live round trip + `calib` + nudge + offset. `LOOKAHEAD` = 0.7 s caps the lead.
6. **Color:** blends Color A → Color B by tempo (60→180 BPM), or a fixed A/B per
   light. The hue glides toward its target.
7. **Webcam timing calibration** (Settings → Timing): runs in the page with
   `getUserMedia`, so no extra package. It starts the engine itself if needed. Inside the
   app window WebKit may not offer the camera (pywebview has no media-capture delegate;
   in a dev run `navigator.mediaDevices` was undefined); then it opens the same page in
   the default browser instead (`Api.open_in_browser`). The page first flashes the screen black/white to measure the
   camera's own delay, then for each light sends dim→bright 8 times through
   `POST /api/calib` (`begin` / `flash` / `end` / `save`; music output pauses meanwhile).
   `calAnalyze` (JS) picks the 3% of pixels that change most and finds when they are
   halfway brighter. `calib` = seen − camera delay − round trip, saved per device in ms;
   the nudge is reset to 0. Changing a light's IP clears its calibration.
8. **Fallbacks:** with no beats for 2.5 s, brightness follows loudness. After 3 s of
   true silence the status says "Can't hear any music…". "Flash lights" (Settings →
   Lights) pulses all lights once. A second running copy (e.g. old launcher + app) gets a
   plain "Another copy of Temponome…" message: the Govee socket deliberately has no
   SO_REUSEPORT.
9. **Status line:** `status_text()` turns state into one sentence + level
   (ok/wait/warn/error/idle), e.g. "Listening · 3 lights · on the beat". Raw errors stay
   in `error` (shown as a tooltip). The severity key is `status_level` because `level`
   is the music loudness.

## History and lessons
- Nov 2026 real-bulb test: "off the beat" had two causes. The owner's settings (max
  brightness 32%, long pulse) made each pulse a 20%↔30% wobble, and the grid locked onto
  the off-beat (fixed by the phase check).
- v1 fired on every bass spike at about 8 updates/s: jittery and laggy.
- Sending only on change and dropping stale beats helped. The tempo-locked grid
  fixed jitter from the mic.
- "Stuck at minimum brightness" was caused by no or very quiet input. That led to
  auto-gain, the second detector, the silence warning and the test-flash button.
- Widening the flux band to 4 kHz broke tempo on clean music (hi-hats pulled it to
  80 or 148 BPM), so it was reverted. Keep the tempo band low.
- Bulb command round trip is about 50–150 ms over Wi-Fi, so it can never be
  sample-accurate. The goal is to feel on-beat.

## Not verified on real hardware yet
- Webcam calibration worked on the owner's real lights (2026-11-23): Tapo L530
  calib −55 ms (lights up ~100 ms after a send, round trip ~156 ms) and Govee H6052
  calib +188 ms (UDP round trip reads 0). The phase check is only simulation-tested.
- With BlackHole, the app hears the music *before* it leaves the speaker. Bluetooth
  speakers add roughly 150–250 ms, so lights may then flash early; the nudge slider goes
  down to −150 ms for that. Measuring speaker delay automatically is a possible next step.
- Govee: the owner's real H6052 pulses to music (confirmed 2026-11-23, together with
  the Tapo bulb). How many updates per second it accepts before lagging is not
  measured. If it lags, a possible next step is Govee's undocumented fast-streaming
  ("razer"/DreamView) command.
- Temponome.app (2026-11-24): built and run on the owner's Mac with no Python available;
  it migrated the settings and its finder found all 4 lights. Not yet tried: installing
  the .pkg, playing real music through BlackHole in the app, the camera inside the app
  window, and the first-launch permission prompts (microphone, camera, local network).
- The latest auto-gain and silence-warning version had not yet been tried on the
  owner's Mac.
- The L535/L630/L900/L920/L930 entries exist but have never been tested. The L9xx
  strips may need the `RgbicLightStripHandler` API.

## Ideas the owner may want next
- Port to Rust (smaller app, faster start); the owner asked and chose to keep Python
  for now (2026-11-24). The tapo library is already Rust underneath.
- Use the L920/L930 strip segments for per-segment effects.
- Presets for colors and behavior.
