# Music Pass-Through Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** With "Play music through Temponome" on, the Mac's sound goes to BlackHole, Temponome plays it to the chosen speaker D seconds late, and each light fires on the real hit as heard.

**Architecture:** `audio_route.py` switches the Mac's default output through CoreAudio (ctypes) and remembers the old one in settings for crash recovery. `passthrough.py` holds a stereo `DelayLine` (with clock-drift correction) and a `Player` that plays it to a speaker. The engine feeds `BeatTracker` a clock shifted by the time until the sound is heard, so hits and grid beats come out in "heard time" and the existing per-light lead logic fires each light on time.

**Tech Stack:** Python 3, ctypes + CoreAudio, sounddevice (already used), numpy, stdlib unittest.

**Spec:** `docs/superpowers/specs/2026-11-24-pass-through-design.md`

## Global Constraints
- No new dependency; the app still needs only BlackHole.
- Never leave the owner without sound: every exit path restores the output.
- Settings keys: `passthru` (bool, false), `out_device` (UID or ""), `spk_delay` ({UID: ms}, 0–400), `restore_out` (UID or "").
- D = clamp(max light lead + 0.04 s − speaker delay, 0.10, 0.60) s, fixed for one Play.
- "Follow a steady beat" on: grid beat moves to a real hit within ±15% of a beat; off: every hit.
- Plain-words UI; no label touches a line; never commit or print settings.

## Review Focus
1. Speaker unplugged / Bluetooth off mid-song → music continues on the built-in speakers, status says so (Task 2 test `test_lost_speaker_falls_back`).
2. App killed while playing → next launch puts the output back (Task 1 test `test_recover_on_launch`).
3. Hours of play with slightly different device clocks → no growing delay, no gaps (Task 2 test `test_drift_is_corrected`).
4. Pass-through on but BlackHole not installed → plain error, Mac output untouched (Task 3 test `test_no_blackhole_leaves_output_alone`).
5. Previous output was BlackHole itself → plays to built-in speakers, restores BlackHole on Stop (Task 1 test `test_previous_blackhole_means_builtin`).

---

### Task 1: Speaker switching (`audio_route.py`)

**Files:** Create `audio_route.py`; Test `tests/test_temponome.py` (class `AudioRoute`)

**Interfaces — Produces:**
- `list_outputs() -> list[dict]` → `{"uid", "name", "builtin": bool, "latency_ms": float, "blackhole": bool}`
- `default_output() -> str` (UID); `set_default_output(uid: str) -> None` (sets default and system output)
- `get_volume(uid) -> float | None`, `set_volume(uid, v: float) -> None`
- `pick_speaker(chosen_uid: str, previous_uid: str) -> dict | None` — chosen if present and not BlackHole, else previous if not BlackHole, else first built-in, else first non-BlackHole.
- `switch_to_blackhole(save: Callable[[str], None]) -> str` — saves the current default UID via `save`, switches to BlackHole, returns the previous UID. Raises `RuntimeError(NO_BLACKHOLE_MSG)` without touching anything if BlackHole is missing.
- `restore_output(prev_uid: str, save) -> None` — sets it back if that device exists (else built-in), then `save("")`.
- `recover(cfg, save) -> bool` — on launch: if `cfg["restore_out"]` and the default output is BlackHole, restore it.
- Backend seam: module-level `BACKEND` object with `devices()`, `default()`, `set_default(id)`, `volume(id)`, `set_volume(id, v)`; tests replace it with a fake.

- [ ] Step 1: Tests in `AudioRoute` with a `FakeBackend` (BlackHole, MacBook Air Speakers (builtin, 14 ms), "JBL" (bluetooth, 160 ms); default = MacBook): `test_switch_and_restore` (default becomes BlackHole, saved UID == MacBook, restore sets it back and saves ""), `test_no_blackhole_leaves_output_alone`, `test_recover_on_launch` (restore_out=MacBook, default BlackHole → True, default MacBook), `test_recover_does_nothing_when_user_changed_it` (default JBL → False, unchanged), `test_previous_blackhole_means_builtin` (`pick_speaker("", BH)` → MacBook), `test_chosen_missing_falls_back_to_previous`.
- [ ] Step 2: Run `python3 -m unittest tests.test_temponome.AudioRoute` → errors (module missing).
- [ ] Step 3: Implement with ctypes against CoreAudio (`kAudioHardwarePropertyDevices` 'dev#', `DefaultOutputDevice` 'dOut', `DefaultSystemOutputDevice` 'sOut', device UID 'uid ', name 'lnam', transport 'tran' ('bltn' = built-in), latency 'ltnc'+'saft'+stream 'ltnc' over 'nsrt', volume 'volm' output element 0). Probe script that already works: scratchpad `ca_probe.py`.
- [ ] Step 4: Tests pass; one read-only live check prints `list_outputs()` on the owner's Mac.
- [ ] Step 5: Commit "Speaker switching through CoreAudio".

### Task 2: Delayed sound player (`passthrough.py`)

**Files:** Create `passthrough.py`; Test `tests/test_temponome.py` (class `DelayedSound`)

**Interfaces — Produces:**
- `class DelayLine(rate: int, delay_s: float, channels=2)`: `push(block: ndarray[n, ch])`, `pull(n) -> ndarray[n, ch]` (silence before the delay has filled; drift correction: if the buffered amount drifts more than 5 ms from `delay_s`, drop or repeat one frame per pull until back within 1 ms).
- `class Player(sd, speaker_name: str, fallback_name: str | None, line: DelayLine, rate: int)`: `start()`, `close()`, `.fell_back: str | None` (name now used after the speaker vanished). Opens `sd.OutputStream(device=<index by name>, channels=2, samplerate=rate, blocksize=BLOCK, callback=…, finished_callback=…)`; on a stream error/finish not caused by `close()`, reopens on `fallback_name` and sets `fell_back`.
- Volume handling: measure first whether BlackHole scales its signal by its volume (Step 1b). If it does: on start remember speaker volume v, set BlackHole volume to v and speaker to 1.0; on close set speaker volume to BlackHole's volume and BlackHole to 1.0. If it does not: Player multiplies output by BlackHole's current volume (polled every 0.2 s), speaker untouched. Record the finding in CLAUDE.md.

- [ ] Step 1: Tests: `test_delay_is_exact` (impulse pushed at frame 0 comes out at round(0.3·rate) frames), `test_stereo_kept`, `test_underflow_is_silence`, `test_drift_is_corrected` (push 1.0001× as many frames as pulled for 60 s of audio → buffered delay stays within 6 ms of target), `test_lost_speaker_falls_back` (fake `sd` whose first stream calls finished_callback → second stream opened on fallback, `fell_back` == fallback name).
- [ ] Step 1b: Measure BlackHole volume scaling: play a 440 Hz tone into BlackHole at volume 1.0 and 0.5 (inaudible to the room), record from BlackHole, compare RMS; restore BlackHole volume to what it was.
- [ ] Step 2: Run tests → errors. Step 3: implement. Step 4: tests pass.
- [ ] Step 5: Commit "Delayed sound player".

### Task 3: Engine — lights on real hits

**Files:** Modify `temponome.py` (DEFAULTS, `_apply_config_locked`, `BeatTracker.poll_events`, `Engine._run/_play`, `status_text`, Handler `GET /api/outputs`, `main`); Modify `app/temponome_app.py` (call `audio_route.recover` at launch); Test `tests/test_temponome.py` (class `PassThroughEngine`), `tests/simulate.py` (new check).

**Interfaces — Consumes:** Task 1 and 2 names above. **Produces:**
- `pass_delay(leads: list[float], spk_s: float) -> float` (the D formula).
- `BeatTracker.poll_events(now, lookahead, locked, snap=False)`: unlocked returns `[self.last_onset]` (onset time, not `now`); with `snap=True` a grid beat within ±0.15·T of a recent onset (keep the last 8 onset times) is returned as that onset's time.
- Engine fields: `self.pass_delay` (s or 0), `self.speaker` (name or ""), `self.speaker_lost` (name or "").
- `GET /api/outputs` → `{"outputs": [...list_outputs minus BlackHole], "blackhole": bool}`.

Behaviour:
- When `passthru`: after lights connect, compute leads as `_play` does now (lat + calib + nudge, clamped), `spk = spk_delay[uid]/1000` (default: reported latency), `D = pass_delay(...)`. `switch_to_blackhole` (saving `restore_out`), input = BlackHole stereo at SAMPLE_RATE; the audio callback pushes the block to the DelayLine and gives the tracker `mono` with `now = time.time() + D + spk`; poll with `lookahead = D + spk − 0.04` and `snap=locked`. `restore_output` + `player.close()` in the same `finally` that puts the lights back (before `_put_back`, so sound returns at once).
- Changing `passthru` or `out_device` while playing restarts the engine (like a light-list change). A `spk_delay` change applies at the next Play (spec: D never changes mid-song).
- Status: ok lines gain " · sound delayed 0.3 s" (one decimal); `speaker_lost` → warn "Your speaker disconnected · playing on {name}"; missing BlackHole → error "Playing music through Temponome needs BlackHole 2ch. Install it, or turn this off in Settings > Sound.".
- Old behaviour is unchanged when `passthru` is off (all existing tests and 13/13 simulation).

- [ ] Step 1: Tests: `test_pass_delay_formula` (leads [0.10, 0.31], spk 0.014 → 0.336; clamps to 0.10 and 0.60), `test_unlocked_emits_onset_time`, `test_snap_moves_beat_to_real_hit` (grid beat 100.5, onset 100.56, T=0.5 → 100.56; onset 100.7 → 100.5), `test_settings_validate` (spk_delay clamped 0–400, unknown keys dropped, passthru bool), `test_toggle_while_playing_restarts` (passthru/out_device yes, spk_delay no), `test_status_mentions_delay`, `test_status_speaker_lost`, `test_no_blackhole_leaves_output_alone` (engine error text, fake backend default unchanged).
- [ ] Step 2: run → fail. Step 3: implement. Step 4: unit tests pass.
- [ ] Step 5: Simulation `run_passthrough_checks`: fake sounddevice with `InputStream` (stereo song) + `OutputStream`, fake audio_route backend, one Tapo fake (0.12 s) calibrated 100 ms and one Govee-like; expect bright commands to land within 30 ms of the kick's *heard* time (input + D + spk), output restored after Stop, and the existing 13 checks still pass → `14/14 passed`.
- [ ] Step 6: Commit "Lights fire on the real hits when music plays through Temponome".

### Task 4: Settings → Sound controls

**Files:** Modify `ui/settings.html`, `ui/settings.js`.
- New group under "Listen to": switch **Play music through Temponome** (hint: "Your Mac's sound goes to BlackHole and Temponome plays it to your speaker a moment later, so the lights land exactly on the beat. Videos will be slightly out of sync."), **Speaker** select ("Same as before" + `/api/outputs`), **Speaker delay** slider 0–400 ms for the selected speaker (value shown as "160 ms"; starts at the reported latency; hint: "Wireless speakers play late. Raise this if the lights flash before you hear the beat.").
- Switch disabled with hint "Choose BlackHole 2ch above to use this." when the audio input is a microphone; "Install BlackHole 2ch to use this." when `/api/outputs` says no BlackHole.
- [ ] Step 1: Check in the browser pane (temponome-shots server) at 680×672 and 480 wide, dark and light: controls save and reload; no label touches a line.
- [ ] Step 2: Commit "Settings for playing music through Temponome".

### Task 5: Whole check and try it on the Mac
- [ ] Unit tests all OK; `python3 tests/simulate.py` → 14/14.
- [ ] Live run with the owner's lights and MacBook speakers (owner present): Play with pass-through → hear music, lights on the hits; Stop → output back to MacBook speakers; kill the process while playing → relaunch restores output.
- [ ] Update CLAUDE.md (How it works item 11, tests count, volume finding). Commit.
