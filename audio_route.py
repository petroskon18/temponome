"""Switch the Mac's sound output (for "Play music through Temponome").

Uses CoreAudio through ctypes, so nothing extra has to be installed. The same calls are
used by switchaudio-osx (github.com/deweller/switchaudio-osx). Devices are identified by
their UID, which stays the same across restarts (indexes and IDs don't).
"""
import ctypes
import ctypes.util
import struct

NO_BLACKHOLE_MSG = ("Playing music through Temponome needs BlackHole 2ch. Install it, or turn "
                    "this off in Settings > Sound.")


def _fourcc(s):
    return struct.unpack(">I", s.encode())[0]


class _Addr(ctypes.Structure):
    _fields_ = [("sel", ctypes.c_uint32), ("scope", ctypes.c_uint32), ("elem", ctypes.c_uint32)]


class CoreAudioBackend:
    """The real Mac. Tests replace BACKEND with a fake that has the same five methods."""
    SYSTEM = 1
    GLOBAL, OUTPUT = _fourcc("glob"), _fourcc("outp")

    def __init__(self):
        self._ca = None

    def _lib(self):
        if self._ca is None:
            ca = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreAudio"))
            cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
            P = ctypes.POINTER
            ca.AudioObjectGetPropertyDataSize.argtypes = [ctypes.c_uint32, P(_Addr), ctypes.c_uint32,
                                                          ctypes.c_void_p, P(ctypes.c_uint32)]
            ca.AudioObjectGetPropertyData.argtypes = [ctypes.c_uint32, P(_Addr), ctypes.c_uint32,
                                                      ctypes.c_void_p, P(ctypes.c_uint32), ctypes.c_void_p]
            ca.AudioObjectSetPropertyData.argtypes = [ctypes.c_uint32, P(_Addr), ctypes.c_uint32,
                                                      ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
            ca.AudioObjectHasProperty.argtypes = [ctypes.c_uint32, P(_Addr)]
            ca.AudioObjectHasProperty.restype = ctypes.c_ubyte
            cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
            cf.CFRelease.argtypes = [ctypes.c_void_p]
            self._ca, self._cf = ca, cf
        return self._ca

    def _get(self, obj, sel, scope=None, ctype=ctypes.c_uint32, many=False, elem=0):
        ca = self._lib()
        a = _Addr(_fourcc(sel), self.GLOBAL if scope is None else scope, elem)
        size = ctypes.c_uint32(0)
        if ca.AudioObjectGetPropertyDataSize(obj, ctypes.byref(a), 0, None, ctypes.byref(size)):
            return None
        n = max(1, size.value // ctypes.sizeof(ctype))
        buf = (ctype * n)()
        if ca.AudioObjectGetPropertyData(obj, ctypes.byref(a), 0, None, ctypes.byref(size), buf):
            return None
        return list(buf[: size.value // ctypes.sizeof(ctype)]) if many else buf[0]

    def _set(self, obj, sel, value, scope=None, elem=0):
        ca = self._lib()
        a = _Addr(_fourcc(sel), self.GLOBAL if scope is None else scope, elem)
        err = ca.AudioObjectSetPropertyData(obj, ctypes.byref(a), 0, None, ctypes.sizeof(value),
                                            ctypes.byref(value))
        if err:
            raise OSError(f"CoreAudio refused the change (error {err})")

    def _str(self, obj, sel):
        ref = self._get(obj, sel, ctype=ctypes.c_void_p)
        if not ref:
            return ""
        out = ctypes.create_string_buffer(512)
        self._cf.CFStringGetCString(ref, out, 512, 0x08000100)   # UTF-8
        self._cf.CFRelease(ref)
        return out.value.decode("utf-8", "replace")

    def devices(self):
        out = []
        for d in self._get(self.SYSTEM, "dev#", many=True) or []:
            streams = self._get(d, "stm#", self.OUTPUT, many=True)
            if not streams:
                continue                                    # input-only device
            rate = self._get(d, "nsrt", ctype=ctypes.c_double) or 0.0
            frames = ((self._get(d, "ltnc", self.OUTPUT) or 0) + (self._get(d, "saft", self.OUTPUT) or 0)
                      + (self._get(streams[0], "ltnc") or 0))
            tr = self._get(d, "tran") or 0
            out.append({"id": d, "uid": self._str(d, "uid "), "name": self._str(d, "lnam"),
                        "transport": struct.pack(">I", tr).decode("ascii", "replace"),
                        "latency_ms": round(frames / rate * 1000.0, 1) if rate else 0.0})
        return out

    def default(self):
        return self._get(self.SYSTEM, "dOut")

    def set_default(self, dev_id):
        v = ctypes.c_uint32(dev_id)
        self._set(self.SYSTEM, "dOut", v)
        try:
            self._set(self.SYSTEM, "sOut", v)               # alert sounds too
        except OSError:
            pass

    def volume(self, dev_id):
        for el in (0, 1):
            v = self._get(dev_id, "volm", self.OUTPUT, ctype=ctypes.c_float, elem=el)
            if v is not None:
                return float(v)
        return None

    def set_volume(self, dev_id, v):
        v = ctypes.c_float(max(0.0, min(1.0, float(v))))
        for el in (0, 1, 2):
            try:
                self._set(dev_id, "volm", v, self.OUTPUT, el)
                if el == 0:
                    return
            except OSError:
                continue

    def _convert(self, dev_id, sel, value):
        """CoreAudio's own scalar <-> decibel converters ('v2db', 'db2v'): the value goes in
        and comes back out in the same buffer."""
        ca = self._lib()
        buf = ctypes.c_float(float(value))
        size = ctypes.c_uint32(ctypes.sizeof(buf))
        for el in (0, 1):
            a = _Addr(_fourcc(sel), self.OUTPUT, el)
            if ca.AudioObjectHasProperty(dev_id, ctypes.byref(a)):
                if not ca.AudioObjectGetPropertyData(dev_id, ctypes.byref(a), 0, None,
                                                     ctypes.byref(size), ctypes.byref(buf)):
                    return float(buf.value)
        # no converter (BlackHole): its level runs evenly in decibels across its range
        # (measured: half volume = -32 dB of a -64..0 dB range)
        class _Range(ctypes.Structure):
            _fields_ = [("lo", ctypes.c_double), ("hi", ctypes.c_double)]
        r = self._get(dev_id, "vdb#", self.OUTPUT, ctype=_Range)
        if r is None or r.hi <= r.lo:
            return None
        if sel == "v2db":
            return r.lo + (r.hi - r.lo) * max(0.0, min(1.0, value))
        return max(0.0, min(1.0, (value - r.lo) / (r.hi - r.lo)))

    def volume_db(self, dev_id):
        v = self.volume(dev_id)
        return None if v is None else self._convert(dev_id, "v2db", v)

    def set_volume_db(self, dev_id, db):
        # only the level -> decibel reading is used: the Mac's two converters are not exact
        # opposites (measured: -4.0 dB -> 0.878 -> -7.7 dB on the MacBook speakers)
        if self._convert(dev_id, "v2db", 1.0) is not None:
            self.set_volume(dev_id, level_for_db(lambda v: self._convert(dev_id, "v2db", v), db))


def level_for_db(to_db, db):
    """The 0..1 volume level at which to_db(level) gives `db` (to_db rises with the level)."""
    if db >= to_db(1.0):
        return 1.0
    if db <= to_db(0.0):
        return 0.0
    lo, hi = 0.0, 1.0
    for _ in range(30):
        mid = (lo + hi) / 2
        if to_db(mid) < db:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


BACKEND = CoreAudioBackend()


def list_outputs():
    return [{"uid": d["uid"], "name": d["name"], "builtin": d["transport"] == "bltn",
             "latency_ms": d["latency_ms"], "blackhole": d["name"].startswith("BlackHole"),
             "id": d["id"]} for d in BACKEND.devices()]


def _by_uid(uid):
    return next((o for o in list_outputs() if o["uid"] == uid), None) if uid else None


def default_output():
    cur = BACKEND.default()
    return next((o["uid"] for o in list_outputs() if o["id"] == cur), "")


def blackhole():
    return next((o for o in list_outputs() if o["blackhole"]), None)


def pick_speaker(chosen_uid, previous_uid):
    """Where the delayed music should play: the chosen speaker, else the one used before
    Play, else the built-in speakers, else anything that isn't BlackHole."""
    outs = [o for o in list_outputs() if not o["blackhole"]]
    for uid in (chosen_uid, previous_uid):
        o = next((o for o in outs if uid and o["uid"] == uid), None)
        if o:
            return o
    return next((o for o in outs if o["builtin"]), outs[0] if outs else None)


def switch_to_blackhole(save):
    """Remember the current output (save(uid) writes it to settings, so a crash can be
    undone at the next launch), then send the Mac's sound to BlackHole."""
    bh = blackhole()
    if bh is None:
        raise RuntimeError(NO_BLACKHOLE_MSG)
    prev = default_output()
    if prev != bh["uid"]:
        save(prev)
    BACKEND.set_default(bh["id"])
    return prev


def restore_output(prev_uid, save):
    """Put the Mac's sound back where it was (or on the built-in speakers if that device
    is gone), then clear the saved note."""
    target = _by_uid(prev_uid) or pick_speaker("", "")
    if target is not None:
        BACKEND.set_default(target["id"])
    save("")


def recover(cfg, save):
    """At launch: if Temponome was stopped without putting the sound back (a crash), and the
    Mac still plays to BlackHole, put it back. Returns True if it changed the output."""
    prev = cfg.get("restore_out") or ""
    if not prev:
        return False
    bh = blackhole()
    if bh is not None and default_output() == bh["uid"]:
        spk = _by_uid(prev)
        if cfg.get("restore_vol") and spk is not None:
            give_back_volume({"bh": bh["id"], "spk": spk["id"]})   # don't leave the speaker at full
        restore_output(prev, save)
        return True
    save("")
    return False


def take_over_volume(speaker_uid):
    """BlackHole scales the sound by its own volume (measured: half volume = about 1/40), so
    while music plays through Temponome the volume keys (which now change BlackHole) set the
    loudness: BlackHole gets the speaker's level in decibels and the speaker goes to full.
    Returns what give_back_volume needs."""
    bh, spk = blackhole(), _by_uid(speaker_uid)
    if bh is None or spk is None:
        return None
    db = BACKEND.volume_db(spk["id"])
    if db is None:
        return None                       # the speaker has no volume control of its own
    BACKEND.set_volume_db(bh["id"], db)
    BACKEND.set_volume(spk["id"], 1.0)
    return {"bh": bh["id"], "spk": spk["id"]}


def give_back_volume(state):
    """The speaker keeps the last loudness the owner chose; BlackHole goes back to full."""
    if not state:
        return
    db = BACKEND.volume_db(state["bh"])
    if db is not None:
        BACKEND.set_volume_db(state["spk"], db)
    BACKEND.set_volume(state["bh"], 1.0)
