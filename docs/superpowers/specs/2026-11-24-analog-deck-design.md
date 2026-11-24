# Analog deck redesign (direction C: studio VU meter)

## Why
The owner wanted a fresh look inspired by Audio-Technica, picked the "studio VU meter"
direction, and asked for analog detail without overdoing it. The per-light lamps also
answer a real question: is each light on the beat, and is any light not answering?

## Goals
- Main window looks like a small analog device: dark panel (silver in light mode), a few
  screws, a cream VU meter whose needle rests at the tempo and kicks on each beat, one lamp
  per light (its live color and brightness), a chunky Stop/Play key, a flip toggle for
  Together/Chase, Brightness as 10 amber step cells, Pulse as a fader with ticks, a
  "temponome" nameplate with a power light, and the status strip with Settings.
- **No label touches or crosses a line** (owner rule).
- **Title bar is part of the panel**: transparent, full-size content; the window buttons
  sit on the panel; a top strip drags the window.
- Settings → Colors: a **tempo strip** (80→160 BPM, marker at the current tempo) above
  **one segmented wheel** (24 hues × 6 rings, vivid outside → pastel inside, no gaps) with
  two markers (calm, energetic). The wheel's center is a **white** option. A **Preview on
  lights** button sends the selected color to the lamps briefly.
- Engine: blend calm → energetic **around the wheel** (hue path, saturation linear), so the
  middle stays vivid instead of going white. White (saturation 0) takes the other color's hue.

## Non-goals / anti-goals
- No gradients, glare or skeuomorphic textures; motion stops with Reduce Motion.
- Settings layout stays as it is apart from the Colors tab and matching colors.
- No new dependencies.

## Approaches considered
- Pro deck (LP120), studio headphones (M50x), VU meter: owner picked the VU meter.
- Color picker: gel swatches, tempo strip, hue dials, moods: owner picked the tempo strip,
  then asked for a segmented wheel like the owner's reference images; one wheel with two markers
  (A) over two wheels (B); gaps between pieces removed.

## Decided details
- Wheel colors: HSL(h, 90→65%, 50→86%) per ring; sent to lamps as hue + HSV saturation
  (outer 95% … inner 19%), all within what Tapo (hue/sat) and Govee (RGB) accept.
- `/api/state` gains `lamps`: `[{name, b, hex, ok}]` for the connected lights.
- `POST /api/preview {"color": "#rrggbb"}` shows that color on all lights at max
  brightness for about 1.5 s; needs Play (connected), like calibration.

## Left to the builder
Exact light-mode panel colors, needle ballistics, sizes inside the 600×400 page.
