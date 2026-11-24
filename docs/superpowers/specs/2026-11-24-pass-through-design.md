# Music pass-through (sound delayed so lights land on the hits)

## Why
Lights flash slightly off the music. Today Temponome hears a song at the same moment the
speakers play it, so it has to predict each beat and fire early to cover each light's delay
(Tapo ~100 ms, Govee more). Predicting is where the remaining timing errors come from (tempo
flips, grid jumps, bulb jitter). If Temponome plays the music itself, a fraction of a second
late, it hears every hit before the listener does and can time each light to the real hit.
The owner asked for this after the "stutter" fix (2026-11-24), and picked approach A below.

## Goals
- A switch, **Play music through Temponome** (Settings → Sound), default **off**.
- When it is on and Play is pressed:
  1. Temponome remembers the Mac's current sound output and switches the Mac's output to
     **BlackHole 2ch** (default output and system/alert output).
  2. It listens to BlackHole as now, and also plays that sound (stereo, full quality) to the
     **chosen speaker**, held back by a delay **D**.
  3. Each light fires so it visibly changes at the moment the hit comes out of the speaker.
- On Stop, quit, or an error that ends playing, the Mac's output goes back to what it was
  (like Stop already puts the lights back). If Temponome crashed and left the output on
  BlackHole, the next launch puts it back.
- The owner uses **both** the MacBook speakers and other speakers (e.g. Bluetooth) at
  different times: a speaker picker, and a **speaker delay remembered per speaker**.
- Volume keys keep changing how loud the music is.

## Non-goals
- Microphone listening: sound in the room has already been heard, so pass-through needs
  BlackHole. With the microphone selected, the switch is unavailable (explained in a hint).
- Lip-sync for video. Videos will be ~D late; the owner turns the switch off for videos.
- Measuring a speaker's delay automatically (with the mic). Possible later.
- Paid tools (Loopback) or a macOS multi-output device (cannot add delay).

## Anti-goals
- **Leaving the owner with no sound.** Every exit path must restore the output; if the
  chosen speaker disappears mid-song (Bluetooth off), keep playing on the MacBook speakers
  and say so in the status line rather than going silent.
- Clicks, crackles or drift: the delayed sound must stay clean for hours.
- New install steps: the app must still need only BlackHole (packaging goal).

## Constraints
- CoreAudio device switching via `ctypes` (no new dependency). Probed on the owner's Mac:
  the device list, default output, transport type, reported output latency (MacBook Air
  Speakers ≈ 14 ms) and a settable volume on BlackHole 2ch all work.
  Reference for the same calls: switchaudio-osx (GitHub, MIT) uses
  `kAudioHardwarePropertyDefaultOutputDevice` / `DefaultSystemOutputDevice`.
- `sounddevice` (already used) opens the output stream. Settings are identified by device
  **UID** (stable), not index or name.
- Owner rules: plain-words UI and messages; no label touches a line; never commit settings.

## Approaches considered
- **A. Temponome switches the Mac's output itself (chosen).** It feels like one switch; it
  mirrors "Stop puts the lights back". Cost: CoreAudio code and careful restore paths.
- B. The owner switches the output to BlackHole in Sound settings by hand. Simpler, but
  forgetting a step means silence. Rejected.
- C. macOS multi-output device with a delay. macOS cannot delay one output. Dropped.

## Decided details
- **Delay D** = just enough to cover the slowest light: the largest light lead
  (live round trip + `calib`, as used now) plus detection time, minus the speaker's own
  delay; clamped to 100–600 ms. Recomputed when lights or calibration change, but **never
  changed while music is playing** (changing D mid-song is an audible jump); a new D applies
  on the next Play.
- **Speaker delay** (per speaker UID, ms): starts at what macOS reports for that speaker;
  a slider in Settings → Sound (0–400 ms) to fine-tune for wireless speakers. It is part
  of when the sound is heard: heard time = input time + D + speaker delay.
- **Which hits flash** (builder's call, owner may correct): "Follow a steady beat" keeps
  its meaning. On: flash on the tempo grid, but each grid beat moves to the real hit if one
  lies within ±15% of a beat of it (Temponome can now see the real hit before it is heard).
  Off: flash on every detected hit. Either way the time used is the hit's real time.
- **Speaker picker**: output devices except BlackHole; "Same as before" (the output that
  was active before Play, or the MacBook speakers if that was BlackHole) is the default.
- **Crash recovery**: before switching, save the previous output UID in settings
  (`restore_out`); clear it after restoring; on launch, if it is set and the output is still
  BlackHole, restore and clear.
- **Status line**: while on, e.g. "Listening · 3 lights · sound delayed 0.3 s".
- New settings: `passthru` (bool, false), `out_device` (UID or ""), `spk_delay`
  ({UID: ms}), `restore_out` (UID or "").

## Left to the builder
- Duplex vs separate streams, buffer sizes, sample-rate handling, and clock-drift
  correction between BlackHole and the speaker (requirement: clean audio for hours).
- How volume keys reach the speaker (BlackHole has a settable volume; verify whether
  BlackHole scales its signal; requirement: keys change loudness, beat detection still
  works at low volume, the speaker's volume is sensible after Stop).
- Exact wording of hints/status, within the owner's plain-words rule.
- Tests: delay accuracy of the buffer, hit-to-light scheduling math, switch/restore with a
  fake CoreAudio layer (including crash recovery and a speaker vanishing), and settings
  validation. Real-hardware check with the owner at the end.
