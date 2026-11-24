# Analog Deck Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the turntable deck with the analog VU-meter deck, merge the title bar into the panel, and give Settings → Colors a tempo strip plus one segmented wheel with white and a lamp preview.

**Architecture:** Engine changes in `temponome.py` (hue-path blending, per-light `lamps` state, `/api/preview`); pages in `ui/` (new `main.html` layout, `deck.css` tokens, Colors tab in `settings.html`/`settings.js`); window chrome in `app/temponome_app.py`.

**Tech Stack:** Python 3 stdlib + existing deps, pywebview (Cocoa via PyObjC), plain HTML/CSS/SVG/JS.

**Spec:** `docs/superpowers/specs/2026-11-24-analog-deck-design.md`

## Global Constraints
- No label may touch or cross a line (owner rule).
- No gradients, glare or textures; motion stops under `prefers-reduced-motion`.
- Page size stays 600×400 for the deck (title bar now inside it), minimum 440×330.
- No new dependencies; tests stay stdlib `unittest` + `tests/simulate.py` (12/12).

## Review Focus
- Calm = white (saturation 0) or energetic = white: blend must not jump hue; take the other color's hue.
- Calm and energetic exactly opposite (180° apart): blend picks one direction consistently.
- Preview pressed while stopped: plain message, nothing crashes.
- `lamps` while stopped or a light dropped: lamps show off / "not answering", no errors.
- Small window (440×330): nothing overlaps or scrolls.

---

### Task 1: Engine — hue-path blending, lamps state, preview
**Files:** Modify `temponome.py` (`pick_color`, `Engine` loop, `Light`, `_state`, `do_POST`); Test `tests/test_temponome.py`.
**Produces:** `pick_color(cfg, bpm, which) -> (hue:int, sat:int)` (blends hue along the shortest arc, sat linearly; sat 0 side uses the other hue); `/api/state` → `"lamps": [{"name": str, "b": int, "hex": "#rrggbb", "ok": bool}]`; `POST /api/preview {"color": "#rrggbb"}` → `{"ok": bool, "error"?: str}`; engine shows preview color at `maxB` for 1.5 s.
- [ ] Tests: `test_blend_goes_around_the_wheel` (A `#0000ff`, B `#ff8000`, bpm 120 → sat ≥ 90, hue between 240→390 mod 360 i.e. magenta/red side); `test_blend_from_white_keeps_other_hue` (A `#ffffff`, B `#ff0000`, bpm 120 → hue 0, sat 50); `test_preview_needs_play` (stopped → ok False with message).
- [ ] Implement, run unit tests + `python3 tests/simulate.py` (12/12), commit.

### Task 2: Main window — analog VU deck + merged title bar
**Files:** Rewrite `ui/main.html`; modify `ui/deck.css` (panel tokens dark + light silver); modify `app/temponome_app.py` (transparent full-size title bar on both windows; `TITLE_BAR` sizes reconsidered); Test `tests/test_temponome.py` size test.
**Consumes:** `lamps`, `bpm`, `beats`, `running`, `cfg.maxB/smooth/multi`.
- [ ] Meter SVG: scale 80–160 BPM over ±40°, needle rests at tempo and kicks +9° on each new beat; red zone 140–160; readout strip "124 bpm" / "on the beat".
- [ ] Lamps row from `lamps` (or configured lights when stopped, unlit); Stop/Play key; vertical flip toggle with radio semantics; Brightness = range input over 10 step cells; Pulse fader with ticks; nameplate with power light; status strip + Settings.
- [ ] Top 28 px strip with class `pywebview-drag-region`, traffic lights on panel; window uses `NSFullSizeContentViewWindowMask`, transparent titlebar, hidden title.
- [ ] Check in browser at 600×400, 440×330, light + dark: no overlaps; real window measured; commit.

### Task 3: Settings → Colors — tempo strip + segmented wheel
**Files:** Modify `ui/settings.html` (Colors section), `ui/settings.js` (replace the two canvas wheels).
**Consumes:** `pick_color` semantics mirrored in JS for the strip; `POST /api/preview`.
- [ ] One SVG wheel: 24 hues × 6 rings, HSL(h, 90→65 %, 50→86 %), no gaps, dark rim; center disc = white (`#ffffff`).
- [ ] "Set calm" / "Set energetic" selector, markers, legend; "One color" mode hides energetic marker and strip shows one block.
- [ ] Tempo strip 80→160 BPM using the same hue-path blend, marker at current BPM when playing.
- [ ] "Preview on lights" sends the selected color; shows the server message on failure.
- [ ] Browser check light + dark; commit.

### Task 4: Ship
- [ ] Unit tests + simulate pass; update `CLAUDE.md`, README screenshots (made-up lights); rebuild `dist/Temponome.dmg`; push; release v1.1.0 (owner asked to build; publishing follows the established release flow).
