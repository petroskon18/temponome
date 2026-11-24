# Temponome

Makes your Tapo and Govee lights pulse and change color with your music, on a Mac.

## Install
1. Download **Temponome.dmg** from the [latest release](https://github.com/petroskon18/temponome/releases/latest) (Apple silicon Macs), open it and drag **Temponome** onto the **Applications** folder (choose Replace if asked).
2. The first time: open Applications, **right-click Temponome → Open**, then Open again. (macOS asks this because the app isn't signed with an Apple developer account.)
3. For your Mac's own sound, install **BlackHole 2ch** (free) from https://existential.audio/blackhole/. You can use the Mac's microphone instead.

## Use
- Press **Play**. The record shows the tempo and glows in your lights' color on each beat.
- **Brightness** and **Pulse** are on the main window. Everything else is in **Settings** (⌘, or the gear): find your lights, colors, sound input, and timing calibration with the camera.
- Your lights, colors and timing from the old version carry over automatically. Settings live in `~/Library/Application Support/Temponome/`.

## Older way to run it
Double-click `Start Tapo Music.command` (needs Python). Don't run it at the same time as the app.

## For developers
- Tests: `python3 -m unittest tests.test_temponome` and `python3 tests/simulate.py` (needs numpy, scipy).
- Build the disk image: `build/build_dmg.sh` → `dist/Temponome.dmg`.
- Project notes for Claude Code are in `CLAUDE.md`.

## License

Temponome is free software under the GNU General Public License v3.0. See [LICENSE](LICENSE).
