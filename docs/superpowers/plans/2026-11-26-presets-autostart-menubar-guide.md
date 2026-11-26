# Presets, Start by itself, Menu bar, First-run guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add presets, an optional "start by itself when a music app plays", a menu bar icon, and a first-run guide.

**Architecture:** Engine-side logic (presets, auto-start watcher) in `temponome.py` with pure, testable helpers; which apps play sound comes from CoreAudio in `audio_route.py`; the menu bar lives in a new `app/menubar.py` (PyObjC, already bundled); UI in the existing pages.

**Tech Stack:** Python 3 stdlib + ctypes CoreAudio, PyObjC AppKit, pywebview 6.2.1, plain HTML/JS.

**Spec:** `docs/superpowers/specs/2026-11-26-presets-autostart-menubar-guide-design.md`

## Global Constraints
- Start by itself is **off by default**, music apps only, **never stops by itself**.
- Plain words; no caption touches or crosses a line; the main window never scrolls.
- Never commit or print `settings.json`. Keep `Start Tapo Music.command` working (no menu bar there).
- Tests: `python3 -m unittest tests.test_temponome` and `python3 tests/simulate.py` stay green.

## Review Focus
- User presses Stop while Spotify still plays → must not restart until the music apps were quiet 3 s.
- A preset that names a light that's no longer in the list → applies to the others, no error.
- Settings page loaded before a preset was applied sends old values → `apply_config` still validates everything.
- ⌘Q while the window is hidden → lights put back, app quits (not just hidden).
- Reading the app list fails (older macOS, CoreAudio error) → watcher does nothing, no crash.

---

### Task 1: Presets (engine + API)
**Files:** `temponome.py`, `tests/test_temponome.py`
**Produces:** `PRESET_KEYS`, `STARTER_PRESETS`, `make_preset(cfg, name) -> dict`, `apply_preset(cfg, preset) -> dict` (a body for `apply_config`), `current_preset(cfg) -> str` ("" = custom), `clean_presets(list) -> list`; config key `presets` (default = starters); `POST /api/preset {action: apply|save|delete|rename, name, new?}`; `/api/state` gains `preset`.
- [ ] Tests: save → current_preset returns its name; changing maxB → ""; apply with a missing light IP ignores it; save over an existing name replaces it; delete/rename; bad data cleaned.
- [ ] Implement, run tests, commit.

### Task 2: Start by itself
**Files:** `audio_route.py`, `temponome.py`, tests
**Produces:** `audio_route.playing_apps() -> set[str]` (bundle IDs playing output, not our own pid); `app_matches(bundle, wanted) -> bool`; `AutoStart` with `tick(now, playing: set)` (START_AFTER 2 s, REARM_AFTER 3 s) and a 1 s thread; config `autostart` (False), `music_apps` (list of {id, name}); `GET /api/playing` → [{id, name}].
- [ ] Tests: off → never starts; plays 2 s → start once; Stop while playing → no restart until 3 s quiet then playing again; helper bundle matches; browser doesn't.
- [ ] Implement, run tests, commit.

### Task 3: Menu bar icon + hide on close
**Files:** `app/menubar.py`, `app/temponome_app.py`, tests
**Produces:** `menu_model(state) -> list[(title, action, enabled, checked)]` (pure, tested); `MenuBar` (NSStatusItem, rebuilt on open); closing the main window hides it; ⌘Q / Quit → `on_main_closed`; Dock click shows the window.
- [ ] Tests for `menu_model`; app shell tests updated for hide-on-close.
- [ ] Implement, try in the real app, commit.

### Task 4: UI (presets picker, presets card, Start by itself, first-run guide)
**Files:** `ui/main.html`, `ui/settings.html`, `ui/settings.js`, `deck.css`, `temponome.py` (`guide_done` config)
- [ ] Main: preset select top right; guide overlay (3 steps). Settings → Colors: Presets card. Settings → Sound: Start by itself + app list. Settings → Lights: "Show the welcome guide".
- [ ] Check in headless screenshots (light + dark, no line crossings), commit.

### Task 5: Verify and hand over
- [ ] Full tests + simulate; build test app; update README/CLAUDE.md; owner tries it.
