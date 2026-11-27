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
- `ui/`: the pages, served from disk. `main.html` = the "Stage of lamps" (2026-11-26 redesign, owner
  picked mockup C of https://claude.ai/artifact/HR9YHuV126qx3V4HjBj2Z4): one lamp shade per light
  (the logo's shape), filled from the bottom to the bulb's brightness in its live color, with what
  it reacts to under its name (`/api/state` `lamps` carry `sound`); tempo + the logo whose arm
  ticks on each beat at the top; play, brightness, pulse and Together/Chase (shown only with 2+
  lights on the beat) at the bottom; status strip. Colors come from the logo (deck.css: cream
  shade, golden glow, brown arm; light = warm paper, dark = near-black). Owner rule: **no
  caption may touch or cross a line**; `settings.html` + `settings.js` = Settings
  window (Lights, Colors, Sound, Timing tabs; finder and webcam calibration live here);
  `deck.css` (shared color tokens from the logo; accent = brown #6b4f2a in light mode, gold #ffd27a in dark);
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
- **Title bar** (`merge_title_bar`): see-through and drawn over the page in both windows
  (full-size content view, hidden title); pages start with a `.titlebar` strip (30 px,
  class `pywebview-drag-region`, drags the window). Turning this on shrinks the window by
  the title bar, so it resets the frame to the full size. pywebview paints the
  `NSTitlebarContainerView` gray (windowBackgroundColor), which showed as a separate bar
  in 1.1.0; it is now set to clear and the title bar separator is turned off. Checked in real windows: pages
  get 600x432 and 680x672.
- **Window sizes** (`app/temponome_app.py`): window sizes include `TITLE_BAR` (32 pt). Measured page needs: deck 600x400, Settings 680x640; minimums 440x330 and
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
  detection or light timing: `python3 tests/simulate.py` should print `20/20 passed`
  (7 music scenarios, calibration / on-beat, Govee with a fake lamp on 127.0.0.1, live
  light-list changes, a Tapo bulb that takes 30 s to answer, a light unplugged mid-song,
  Stop putting the lights back, pass-through landing the light on the heard kick,
  color pulse, one light per drum on a clean drum loop, a stronger beat 1, colors turning
  every 4 bars, a breakdown followed by a drop, and sound bars plus pitch to color). It needs numpy and scipy. Stop any other Temponome first:
  only one program can hold UDP port 4002 (Govee replies).
- `tests/test_temponome.py`: unit tests (stdlib unittest; pytest isn't installed):
  `python3 -m unittest tests.test_temponome` → OK (162 tests: settings migration and safe
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
   Steadiness (2026-11-24, setting `steady`, Settings → Sound "Smooth out tempo jumps",
   default on; off = the old rules exactly): the first tempo reading replaces the 110 placeholder at once;
   later big changes need 4 estimates in a row (2 s), double/half/3:2 jumps need 8 (4 s).
   Phase corrections glide (`GLIDE_RATE` 0.1 beat per beat) instead of snapping, except in
   the first `SNAP_SECONDS` (8 s) of a grid, which also pulls harder onto hits.
5. **Lights:** each light has its own envelope (jumps to 1 on a beat, then decays
   by the "pulse length" half-life). Its brightness is rounded to 10% steps, and a
   command is sent only when the value changed. Sends run in parallel, one in flight
   per light, with a 3 s timeout. Each light's round trip is measured live.
   Uncalibrated: beats fire early by `lead` (the "timing nudge") + half the light's
   latency difference from the average + its offset. Calibrated (device `calib` set):
   early by live round trip + `calib` + nudge + offset. `LOOKAHEAD` = 0.7 s caps the lead.
6. **Color:** blends calm (A) → energetic (B) by tempo (60→180 BPM) **around the color
   wheel** (shortest hue path, saturation linear; white takes the other color's hue) so the
   middle stays vivid, or a fixed A/B per light. The hue glides toward its target.
   Settings → Colors: tempo strip + one segmented wheel (24 hues × 6 rings, HSL s 90→65 %,
   l 50→86 %, white center); every piece is a hue/saturation the lamps accept (outer ring
   sends 95 % saturation, inner 19 %). `POST /api/preview {"color"}` shows a color on all
   lights at max brightness for 1.5 s (needs Play).
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
8. **Put back on Stop:** while connecting (before `on()`), `take_snapshot` reads each light's
   look (Tapo `get_device_info`: on, brightness, hue/sat or `color_temp` for white; Govee: the
   `devStatus` read in `connect`) into `Engine.saved` by IP. When `_run` ends (Stop, quit or an
   error) `_put_back` waits for in-flight sends, then `put_back` restores each light (off stays
   off, white stays white), 2.5 s cap each. A background restart (light list edited while
   playing) only restores lights that left the list and keeps the first snapshot of the rest.
   Effects from the Tapo/Govee apps can't be read; their last plain color comes back. Failures
   show "Couldn't put back the earlier look of: …". Quitting waits up to 4.5 s for this.
9. **Fallbacks:** with no beats for 2.5 s, brightness follows loudness. After 3 s of
   true silence the status says "Can't hear any music…". "Flash lights" (Settings →
   Lights) pulses all lights once. A second running copy (e.g. old launcher + app) gets a
   plain "Another copy of Temponome…" message: the Govee socket deliberately has no
   SO_REUSEPORT.
10. **Status line:** `status_text()` turns state into one sentence + level
   (ok/wait/warn/error/idle), e.g. "Listening · 3 lights · on the beat". Raw errors stay
   in `error` (shown as a tooltip). The severity key is `status_level` because `level`
   is the music loudness.
11. **Play music through Temponome** (pass-through, Settings > Sound, setting `passthru`,
   spec `docs/superpowers/specs/2026-11-24-pass-through-design.md`): on Play, `audio_route`
   (CoreAudio via ctypes) saves the current output UID in settings (`restore_out`, for crash
   recovery at launch: `recover_sound_output`), switches the Mac's output to BlackHole, and
   moves the volume: BlackHole scales its signal (half volume = -32 dB of its -64..0 dB range,
   measured), so BlackHole gets the speaker's level in dB and the speaker goes to full
   (`restore_vol`); volume keys then work. `passthrough.Player` plays a `DelayLine` (stereo,
   44.1 kHz) to the chosen speaker (`out_device`, "" = the one used before) D late:
   D = max light lead + 0.04 + 0.06 spare − speaker delay, clamped 0.1–0.6 s, fixed per Play.
   The tracker runs on "heard time" (input time + D + speaker delay), so `poll_events(...,
   snap=True)` returns grid beats moved onto real hits within ±15 % of a beat (unlocked: the
   hit itself), and the normal per-light lead fires each light on time. Real-Mac findings:
   BlackHole delivers in bursts (±50 ms), so drift correction uses a ~2 s average and settles
   in ~15 s; the Mac's two volume converters are not inverses, so `level_for_db` bisects
   'v2db' only; a stream that runs dry refills to the full delay. Speaker vanishes → plays on
   the built-in speakers, status "Your speaker disconnected · playing on …".

12. **Color pulse** (setting `pulse`: "brightness" | "color", Settings > Colors "On each
   beat"): brightness stays at maxB and the beat moves the color from A to B, fading back in
   `PULSE_STEPS` = 4 steps (`pulse_color`, around the wheel like the tempo blend). The tempo
   blend and per-light A/B are hidden then. The "keep the bulb free before a peak" guard
   treats any non-beat update as a fade step in this mode.
13. **One drum per light** (device `sound`: beat | kick | snare | hats, Settings > Lights):
   `BeatTracker` keeps hit times per drum in `hits` (kick 40–150 Hz, snare 1–5 kHz, hi-hats
   7–16 kHz): a hit = band energy > `HIT_RISE` (3×) its last 0.3 s and > 8 % of its ~10 s
   peak; hi-hats also need more energy than the snare band (snares sizzle up there too).
   Times are "heard time" with pass-through, so lights land on the hits; without it they are
   one round trip late. `next_hit_in` guesses the next hit from regular spacing so the bulb
   is kept free before it. On 8 real songs kicks came at about the beat rate; the snare
   band also catches some guitar/voice; 2× rise gave more false hits (kept 3×).

14. **Bars** (Settings > Colors > Extras): every scheduled beat is counted in fours
   (`_count_beat`; skipped beats in a quiet moment are counted too, so the bar keeps its place).
   Once heard, each beat's bass is scored by position (decay 0.99 per beat); beat 1 = the
   position that keeps hitting hardest, and it only moves when another is 20 % stronger
   (`BAR_MARGIN`). On 8 real songs beat 1 moved 0–11 times per song (was 30–170 before the
   skip counting and margin). `accent`: beats 2–4 flash at `ACCENT_SOFT` = 0.55.
   `bar_shift` (0/4/8): both colors turn `BAR_TURN` = 45° every N bars (`turn_colors`).
15. **Build-ups and drops** (`drops`): `_watch_drops` compares the bass level (0.5 s average)
   with its usual level (15 s average, learned for 4 s first). Below 30 % for 2 s =
   breakdown: lights dim (peak 0.15–0.4, rising with loudness). Back above 60 % of the level
   before the breakdown = drop: every light bursts to full and fades slowly for 1 s.
   A breakdown longer than 90 s (`BREAK_MAX`) is just a quiet part. Found on real tracks,
   e.g. the long synth break in "Won't Get Fooled Again" (drop at 7:45). Lesson: a clock
   that starts at 0 broke `now or time.time()` style checks; use `is None`.

16. **Sound bars and pitch to color** (device `sound`: low | mid | high | pitch, Settings >
   Lights): `BeatTracker._shape` measures bass 40–250 Hz, middle 250–2000 Hz, treble
   2–12 kHz each block as 0..1 like an EQ bar (dB against the band's own ~10 s loudest, over
   `BAR_RANGE` 20 dB, but never against less than the loudest band − `BAR_FLOOR` 25 dB, so a
   band holding only noise stays dark); bars rise at once and fall with a 0.1 s half-life.
   A bar light's brightness = its band's level. Pitch to color: hue 0 (red, bass) → 120
   (green) → 240 (blue, treble) from the bands weighted by how far each is above its usual
   (~4 s) level, `PITCH_PUSH` 12; brightness = overall loudness over 30 dB. A plain average
   stayed green 70–97 % of the time on 8 real songs (all bands always play); the "above usual"
   weighting gives ~23 % red / 58 % green / 20 % blue. `shape_at(now + light latency)` reads the
   value that will be heard when the command lands (history 1.5 s, needed for pass-through).
   The owner's Govee H6052 has no separately colorable zones (checked 2026-11-25: camera
   tests of razer/ptReal segment commands, Govee app data `sku_ic.json` lists it with 0 ICs),
   so an EQ display on one lamp isn't possible; sound bars spread the bands across lights.
   Its LAN API does accept `ptReal` BLE packets (power 33 01, colour 33 05 0D RGB).
   Review fixes (2026-11-26): `shape_at` copies the history first (`list(deque)`), because
   walking a deque while the audio thread appends raises "deque mutated during iteration";
   Flash lights and a drop's burst lift shape lights (`L.boost`, `shape_level`) and a build-up
   dims them; Chase takes turns among lights on the beat only (`beat_positions`, `chase_turn`).

17. **Presets, Start by itself, menu bar, first-run guide** (2026-11-26, spec
   `docs/superpowers/specs/2026-11-26-presets-autostart-menubar-guide-design.md`):
   - Presets (`presets`, `PRESET_KEYS`, starters Party/Chill): colors, extras, maxB/minB, smooth,
     multi, and each light's `sound`/`color` by IP. `POST /api/preset` apply|save|rename|delete;
     `current_preset` (state `preset`, "" = Custom) prefers `preset_last` when several match.
     Applying bumps `CFG_REV` (state `cfg_rev`) so an open Settings page reloads instead of
     saving stale values back. Picker top right of main.html; list in Settings → Colors.
   - Start by itself (`autostart`, off by default; `music_apps`): owner rule: only music apps,
     **never stops by itself**. `audio_route.playing_apps()` reads CoreAudio's process list
     (`prs#`/`piro`/`pbid`, macOS 14.2+, no permission, no microphone). `AutoStart.tick`: 2 s of
     a listed app → Play; after Play/Stop it waits for 3 s of quiet before it may start again.
     Listening while stopped was rejected (mic dot; pass-through only routes music after Play).
   - Menu bar (`app/menubar.py`, `menu_model` tested): lamp icon, Play/Stop, presets, Open,
     Settings, Quit. The red close button only hides the main window (`Shell.on_closing`);
     ⌘Q/Quit go through `TemponomeAppDelegate.applicationShouldTerminate_` → `on_main_closed`
     (lights put back). pywebview re-sets the app delegate for every new window, so ours is
     stored in `BrowserView._shared_app_delegate`. Not shown with the old launcher.
     Optional (owner, 2026-11-27): setting `menubar` (default on, Settings → Lights → App); a
     watcher adds/removes the lamp within 1 s; with it off the close button quits.
   - First-run guide (main.html `#guide`, `guide_done`): shown when no light is set up;
     Settings → Lights "Show the welcome guide" (`Api.show_guide`, or `/#guide` in a browser).
     `GET /api/devices?fresh=1` re-asks PortAudio so a just-installed BlackHole shows up.
18. **White light warmth** (2026-11-27, owner asked): when calm or energetic is white, Settings →
   Colors shows a Warm ↔ Cool slider (`kelvinA` / `kelvinB`, 2500–6500 K, default 4000, in presets).
   White travels through the color code as `(kelvin, 0)` (`is_white`: sat 0 and "hue" ≥ 1000), and is
   sent as a real color temperature: Tapo `color_temperature(k)` (its white LEDs), Govee `colorwc`
   with `colorTemInKelvin`. No hue glide for white. Two whites blend by temperature; white to a
   color goes through pale tints and lands on the white temperature at the calm end. Screen tint:
   `kelvin_hex` (same numbers in settings.js `kelvinHex`).

## History and lessons
- Nov 2026 real-bulb test: "off the beat" had two causes. The owner's settings (max
  brightness 32%, long pulse) made each pulse a 20%↔30% wobble, and the grid locked onto
  the off-beat (fixed by the phase check).
- v1 fired on every bass spike at about 8 updates/s: jittery and laggy.
- Sending only on change and dropping stale beats helped. The tempo-locked grid
  fixed jitter from the mic.
- "Stuck at minimum brightness" was caused by no or very quiet input. That led to
  auto-gain, the second detector, the silence warning and the test-flash button.
- Nov 2026 "uneven, stutters": measured on 8 of the owner's real songs offline
  (BeatTracker fed with a simulated clock). 10.6% of beats were doubled or missing, ~95%
  of them right after a tempo flip (often to double) or a half-beat phase snap. The
  tempo/phase changes above cut it to 2.0% with the same on-beat score. Real Tapo round
  trips were 95–220 ms (median 100–145), so bulb jitter is a smaller, separate effect.
- Widening the flux band to 4 kHz broke tempo on clean music (hi-hats pulled it to
  80 or 148 BPM), so it was reverted. Keep the tempo band low.
- Bulb command round trip is about 50–150 ms over Wi-Fi, so it can never be
  sample-accurate. The goal is to feel on-beat.

## Not verified on real hardware yet
- Presets, Start by itself, menu bar (and its off switch), first-run guide and white warmth:
  owner tried the test build on 2026-11-27, no problems found.
- The Stage of lamps look tried by the owner on 2026-11-26 (test build) and approved for 1.7.0.
- Sound bars and pitch to color confirmed by the owner on 2026-11-25 (test build, real lights).
- Color pulse and one-drum-per-light confirmed working by the owner on 2026-11-24 (test
  build, real lights).
- Pass-through confirmed by the owner on 2026-11-24 (test build, MacBook speakers, real
  Tapo + Govee lights): lights on time, sound fine, Play and Stop put everything back.
  Not yet tried: Bluetooth speakers, a speaker disconnecting mid-song, recovery after a crash.
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
  2026-11-26: porting only the sound analysis was measured and skipped: `BeatTracker`
  analyses 60 s of a real song in 0.22 s (0.4 % of one core), and numpy must stay anyway
  (sounddevice needs it), so Rust would save neither noticeable CPU nor app size. If battery
  matters, measure the whole running app first (light loop, window polling).
- Use the L920/L930 strip segments for per-segment effects.
- Presets for colors and behavior.
