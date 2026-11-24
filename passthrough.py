"""Play the music to the speaker a moment late ("Play music through Temponome").

DelayLine: a stereo ring buffer that keeps the sound exactly `delay_s` late. BlackHole and
the speaker run on separate clocks that drift apart (a few seconds per day), so when the
buffered amount (averaged over ~2 s, because BlackHole delivers in bursts) wanders more than
5 ms from the target, one frame per pull is dropped or repeated until it is back within
1 ms; a single frame is inaudible. If it ever runs dry it goes quiet and refills to the
full delay before playing again.

Player: plays a DelayLine to a speaker. If the speaker disappears (Bluetooth switched
off), check() reopens on the fallback speaker and records that in fell_back.
"""
import threading

import numpy as np

BLOCK = 512


class DelayLine:
    def __init__(self, rate, delay_s, channels=2):
        self.rate, self.ch = rate, channels
        self.target = int(round(delay_s * rate))
        self.buf = np.zeros((max(self.target * 2, rate) + rate, channels), np.float32)
        self.read = 0             # read position (frames)
        self.written = 0          # write position (frames)
        self.fixing = 0           # +1 dropping frames, -1 repeating frames, 0 within range
        self.adjusted = 0         # frames dropped or repeated so far (drift correction)
        self.priming = True       # waiting for `target` of sound before playing (start, or after running dry)
        self.avg = 0.0            # smoothed amount waiting (frames)
        self.lock = threading.Lock()

    def buffered(self):
        return self.written - self.read

    def push(self, block):
        block = np.asarray(block, np.float32)
        if block.ndim == 1:
            block = block[:, None]
        if block.shape[1] != self.ch:
            block = np.repeat(block[:, :1], self.ch, axis=1)
        n, size = len(block), len(self.buf)
        with self.lock:
            idx = (self.written + np.arange(n)) % size
            self.buf[idx] = block
            self.written += n
            if self.buffered() > size - BLOCK:          # far too much: drop the oldest
                self.read = self.written - self.target

    def pull(self, n):
        with self.lock:
            if self.priming:
                if self.buffered() < self.target or self.buffered() == 0:
                    return np.zeros((n, self.ch), np.float32)
                # start so that every frame comes out exactly `target` after it went in
                # (frames before the first one are silence: the buffer was cleared)
                self.read = self.written - n - self.target
                self.priming, self.fixing = False, 0
                self.avg = float(self.target)
            elif self.buffered() < n:              # ran dry: clear and wait to fill up again
                self.buf[:] = 0
                self.read = self.written
                self.priming = True
                return np.zeros((n, self.ch), np.float32)
            # BlackHole hands over sound in bursts, so the amount waiting swings by tens of ms
            # from one moment to the next; only its ~2 s average shows real clock drift
            a = min(1.0, n / (2.0 * self.rate))
            self.avg += a * ((self.buffered() - n) - self.avg)
            extra = self.avg - self.target
            lim, ok = 0.005 * self.rate, max(1.0, 0.001 * self.rate)
            if self.fixing == 0 and abs(extra) > lim:
                self.fixing = 1 if extra > 0 else -1
            elif self.fixing and abs(extra) <= ok:
                self.fixing = 0
            idx = (self.read + np.arange(n)) % len(self.buf)
            out = self.buf[idx].copy()
            self.read += n
            take = n
            if self.fixing > 0 and self.buffered() > n:
                self.read += 1                         # drop one frame
                self.adjusted += 1
            elif self.fixing < 0 and take:
                self.read -= 1                         # repeat one frame
                self.adjusted += 1
            return out


def device_index(sd, name):
    for i, d in enumerate(sd.query_devices()):
        if d["name"] == name and d["max_output_channels"] > 0:
            return i
    return None


class Player:
    def __init__(self, sd, speaker_name, fallback_name, line, rate):
        self.sd, self.name, self.fallback = sd, speaker_name, fallback_name
        self.line, self.rate = line, rate
        self.stream = None
        self.closing = False
        self.lost = False
        self.fell_back = None

    def _callback(self, outdata, frames, t, status):
        outdata[:] = self.line.pull(frames)

    def _finished(self):
        if not self.closing:
            self.lost = True

    def _open(self, name):
        idx = device_index(self.sd, name)
        if idx is None:
            raise RuntimeError(f"The speaker “{name}” isn't available.")
        self.stream = self.sd.OutputStream(device=idx, channels=2, samplerate=self.rate,
                                           blocksize=BLOCK, callback=self._callback,
                                           finished_callback=self._finished)
        self.stream.start()

    def start(self):
        try:
            self._open(self.name)
        except Exception:
            if not self.fallback or self.fallback == self.name:
                raise
            self._open(self.fallback)
            self.fell_back = self.fallback

    def check(self):
        """Call regularly from the engine loop: reopen on the fallback if the speaker went away."""
        if self.closing or self.stream is None:
            return
        if self.lost or not getattr(self.stream, "active", True):
            self.lost = False
            try:
                self.stream.close()
            except Exception:
                pass
            target = self.fallback if self.fallback and self.fell_back is None else self.name
            try:
                self._open(target)
                if target != self.name:
                    self.fell_back = target
            except Exception:
                self.stream = None

    def close(self):
        self.closing = True
        if self.stream is not None:
            try:
                self.stream.close()
            except Exception:
                pass
