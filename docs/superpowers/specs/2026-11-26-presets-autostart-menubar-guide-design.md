# Presets, Start by itself, Menu bar icon, First-run guide (design)

Approved by the owner on 2026-11-26 ("Add 1-3 and 7", then "Start by Itself: make it off by
default, dont make it auto stop, only on music apps. The rest of the new things sound great").

## Why
Make Temponome easier to live with every day (switch moods in one click, no need to press
Play, no window in the way) and easier for a new person to set up.

## Approaches considered
- **Start by itself, by listening** to the audio input while stopped: rejected. With the
  microphone the orange mic dot would stay on; with *Play music through Temponome* the music
  only reaches BlackHole after Play, so nothing would be heard.
- **Start by itself, by asking macOS which apps are playing sound** (CoreAudio process
  list, macOS 14.2+, `prs#` / `pbid` / `piro`): chosen. No microphone, no permission prompt
  (checked on the owner's Mac), and it can tell music apps from browsers and calls.
- Menu bar icon with a separate helper app or `rumps`: rejected; pywebview already runs
  AppKit through PyObjC (bundled), so an `NSStatusItem` in the same app is enough.

## The four parts
1. **Presets.** A preset stores: colorA, colorB, mode, pulse, accent, bar_shift, drops,
   maxB, minB, smooth, multi, and what each light follows (`sound`, `color`, by IP). Lights,
   login, sound input and speakers are never part of a preset. Two starters, *Party* and
   *Chill* (global settings only, lights keep their own choice). The main window shows a
   preset picker at the top right ("Custom" when the settings match no preset); choosing one
   applies it. Settings → Colors has a Presets card: save the current settings under a name,
   apply, rename, delete. A preset with the same name is replaced.
2. **Start by itself** (Settings → Sound, **off by default**). When a music app on the list
   plays sound for 2 s while Temponome is stopped, it presses Play. It **never stops by
   itself**. After the owner presses Stop while music is still playing, it waits until the
   music apps have been quiet for 3 s before it may start again. The list starts with Music,
   Spotify, TIDAL, Deezer and Amazon Music; "Add an app playing sound now" adds others. An app
   matches its bundle ID or a helper under it (`com.spotify.client.helper`).
3. **Menu bar icon**: a small lamp (template image, drawn in code). Menu: a status line,
   Play/Stop, Presets (tick on the current one), Open Temponome, Settings…, Quit Temponome.
   Closing the main window hides it and Temponome keeps running; Quit (menu bar or ⌘Q) stops
   the lights, puts them back and quits. Clicking the Dock icon shows the window again.
4. **First-run guide** in the main window, shown when no light is set up and the guide was
   never finished; reopened from Settings → Lights. Steps: (1) hear your music: checks for
   BlackHole and selects it, or "Use the microphone instead"; (2) find your lights: opens
   Settings → Lights and ticks itself when a light is added; (3) try it: put on a song and
   press Play. The last step mentions the menu bar icon and Start by itself.

## Left to the builder
Exact layout and wording within the owner's rules (plain words; no caption touches or
crosses a line; window never scrolls), starter preset colors, test coverage.
