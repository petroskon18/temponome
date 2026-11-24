# Temponome — design

Date: 2026-11-23. Status: waiting for the owner's approval.

## Intent

The app that makes the owner's lights pulse to music (until now "Tapo Music Sync") becomes
**Temponome**, a pun on *metronome*. It should feel like a finished Mac app, not a script:

- it has its own name and icon;
- it is easy to understand the first time, with no technical words on the main screen;
- it looks like a small piece of audio gear, inspired by the Audio-Technica AT-LP60
  turntable, while following Apple's Human Interface Guidelines (HIG);
- it installs from a `.pkg` and runs in its own window, with **nothing else to install
  except BlackHole**, so no Python, Terminal or browser.

## Goals

1. Rename everything the owner sees to Temponome: window title, app name, Dock and menu bar.
2. App icon: **logo option 2, "Metronome lamp"**. A metronome-shaped table-lamp shade
   with the pendulum inside and a pool of warm light below, on a dark macOS-style
   rounded square.
3. UI: **layout C, "Compact deck"** (details below).
4. A `Temponome.pkg` that installs `Temponome.app` into /Applications. The app bundles its
   own Python and all packages, and opens in a native window.

## Non-goals

- No change to beat detection, light timing, Tapo/Govee control or calibration logic.
  They work and are tested (9/9). Only how they are presented changes.
- No Spotify Connect, no Intel Mac build, no App Store.
- No rewrite in Swift.

## Anti-goals (would be a failure even if it works)

- Losing any feature the owner uses now: finder, calibration, colors, per-light settings.
- A pretty main screen that hides whether it is working. Status must be visible.
- Copying Audio-Technica branding. Borrow the look, never the name or logo.
- Breaking the current double-click launcher before the `.app` is proven on the owner's Mac.

## Approaches considered (for the packaged app)

| Approach | Trade-off | Decision |
|---|---|---|
| **A. Bundle the existing Python app** with PyInstaller; open the existing web UI in a native WebKit window (pywebview); wrap the `.app` in a `.pkg` with `pkgbuild` | Reuses all working code and tests; ~60–90 MB app; looks native from outside, web inside | **Chosen** (owner agreed with this plan) |
| B. Rewrite natively in Swift/SwiftUI | Most "Apple" result, small app; but the Tapo login protocol (KLAP) and Govee LAN would need re-implementing, and all tests rewritten | Rejected: weeks of work and new bugs for little visible gain |
| C. Keep the browser and only make an installer for the launcher | Fastest; still needs Python and still opens in a browser tab | Rejected: fails the "no Python, own window" goal |

## Main window (layout C, "Compact deck")

About 560 × 340 pt, resizable within limits. Looks like the top of a turntable:

```
┌──────────────────────────────────────────────────────────────┐
│ ● ● ●                     Temponome                          │
│   ╭─────────────╮   ╲                                        │
│  ╱  ░░░░░░░░░░░  ╲   ╲  tonearm          ( ▶ )  Play         │
│ │ ░░  ╭─────╮  ░░ │   ╲                                       │
│ │ ░░  │ 128 │  ░░ │    ●                 Brightness ───●──    │
│ │ ░░  │ BPM │  ░░ │                      Pulse      ─●────    │
│ │ ░░  ╰─────╯  ░░ │                                          │
│  ╲  ░░░░░░░░░░░  ╱                       [Together | Chase]   │
│   ╰─────────────╯                                            │
│  ● Listening · 3 lights · on the beat            ⚙ Settings  │
└──────────────────────────────────────────────────────────────┘
```

- **Platter**: a ribbed record. Its center label shows the live BPM and glows in the
  lights' current color, pulsing on each beat. This is the "is it working?" signal.
- **Tonearm**: rests aside when stopped and swings onto the record when playing.
  Purely visual, using the existing state.
- **Play/Stop**: one large round button, the only filled control (HIG: one primary
  action per view). Space bar toggles it.
- **Brightness**: one slider setting the brightest level on a beat (today's "Brightest
  level"). The dimmest level moves to Settings.
- **Pulse**: snappy ↔ smooth (today's "Pulse length").
- **Together | Chase**: a two-position slide switch like the LP60's speed switch.
  Shown only with 2+ lights.
- **Status line**: plain words, e.g. "Listening · 3 lights · on the beat",
  "Waiting for music", "Can't hear anything: check Audio input in Settings",
  "Kitchen lamp didn't answer". Errors are written for a person, not raw exceptions.
- **⚙ Settings** (also ⌘, and the app menu) opens the Settings window.

## Settings window

A standard Mac settings window with a toolbar of 4 tabs (HIG pattern), same styling:

1. **Lights**: "Find my lights" with tick boxes and names, plus "Add by IP"; per light:
   color (blend/A/B) and fine timing offset in ms, labeled clearly instead of a bare
   number box; Tapo account email and password (shown only when a Tapo light is ticked).
2. **Colors**: the two color wheels (A = calm/slow, B = energetic/fast) and the
   "blend by tempo / one color" choice.
3. **Sound**: audio input (BlackHole recommended and explained, microphone allowed),
   live level meter, "Follow a steady beat" (today's "Lock to tempo") as a switch,
   "Beat sensitivity" renamed "Which beats" (fewer, strong ↔ more, light), dimmest
   level.
4. **Timing**: webcam calibration (same flow as now), per-light calibration results,
   and "Fine-tune" (today's timing nudge, −150…+250 ms) with the hint "move right if
   lights feel late".

Changing the light list applies **immediately** (the engine restarts itself) instead of
needing Stop and Start.

First launch, with no lights saved: the main window shows a short empty state, "Find
your lights to get started", plus a button that opens Settings → Lights.

## Visual language

- **Look**: matte LP60 body. Dark appearance is the black LP60 (near-black #1b1b1c body,
  #2a2a2c platter, silver #c7c7cc tonearm and rim). Light appearance is the white/silver
  LP60 (#f2f2f0 body, #dcdcd8 platter, dark grey arm). It follows the Mac's
  Light/Dark setting (HIG).
- **Type**: the system font (SF Pro via `-apple-system`), small white/grey labels like
  printed gear markings; sentence case; no ALL CAPS.
- **Accent**: one warm orange (#ff6a2b) for Play and focus. The platter label uses
  the lights' live color.
- **Controls**: standard sizes (≥ 28 pt hit areas, full keyboard access, visible focus
  rings, VoiceOver labels). No skeuomorphic textures beyond the platter ribs (drawn
  as thin circles), flat fills.
- **Motion**: platter pulse ≤ 150 ms; tonearm swing 400 ms; honors "Reduce motion".

## Icon

Logo 2 at 1024 × 1024 on Apple's rounded-square grid, exported as an `.icns` with
all sizes (16–1024, @1x/@2x). Drawn as SVG in the repo (`assets/icon.svg`), converted
with standard macOS tools (`sips`/`iconutil`) during the build. Small sizes simplify
(no light pool below 32 px).

## Packaging (approach A)

- `app/temponome_app.py`: entry point. Starts the existing HTTP server on a free
  local port (not fixed 8765), then opens a native window with pywebview (WebKit) on
  it. Settings opens as a second pywebview window. Quitting the window quits the app.
  No browser and no Terminal.
- **PyInstaller** builds `Temponome.app` (arm64, Apple Silicon only, which is the
  owner's Mac), bundling Python 3.14, numpy, sounddevice (with PortAudio), tapo
  (compiled Rust module) and pywebview. scipy is test-only and not bundled.
- `Info.plist`: bundle id `local.temponome.app`, version 1.0, and permission texts the
  Mac shows when asking: microphone ("listens to the music"), camera ("timing
  calibration only; video stays on this Mac"), local network ("finds and controls your
  lights").
- **Settings file** moves from `~/.tapo_music_ui.json` to
  `~/Library/Application Support/Temponome/settings.json` (chmod 600). It is migrated
  automatically from the old file on first launch, so the owner keeps lights,
  login and calibrations.
- **`.pkg`**: `pkgbuild` → `productbuild` with a simple welcome text. Installs to
  /Applications. A readme in the installer says BlackHole is needed for Mac audio
  (link to the BlackHole download page; the pkg does not install it).
- **Signing**: no Apple Developer ID on this Mac, so the app is ad-hoc signed only. The
  owner opens it the first time with right-click → Open (documented in the installer).
  If they later get a Developer ID, the build script takes it as an option and also
  notarizes.
- **Build script**: `build/build_pkg.sh` does everything in a clean virtual
  environment; output in `dist/Temponome.pkg`.

## Testing and acceptance

- `tests/simulate.py` stays 9/9 (logic is unchanged).
- UI checked in the browser pane with the fake-lights server: main window and
  each Settings tab, dark and light appearance, a narrow window, keyboard only.
- Built app checked on this Mac. It launches with no Python on its path (run with a
  stripped environment), shows the window, finds the real lights, and its microphone and
  camera prompts name Temponome.
- The owner installs the `.pkg` and confirms the lights pulse, before the old launcher
  is retired.

## Risks and open points (builder's calls unless noted)

- **Camera inside the app window**: WebKit in an app needs the camera permission text,
  plus pywebview passing the permission request through. If it doesn't, the Timing tab
  falls back to opening calibration in the default browser. *Verify early.*
- **macOS 27 + Python 3.14 + PyInstaller 6.22**: new combination; if bundling fails,
  fall back to Python 3.13 in the build environment.
- **Local Network permission** in a bundled app may need `NSBonjourServices`/multicast
  entitlement for the Govee search; verify with the real lamp.
- Project folder stays `tapo-music-sync/` for now (renaming it is cosmetic, can be
  done later); the code file is renamed to `temponome.py`, keeping a small
  `tapo_music_ui.py` shim so the old launcher keeps working.
