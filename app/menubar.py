"""The small lamp in the Mac's menu bar: Play/Stop, presets, open the window, quit.

`menu_model` decides what the menu shows (plain Python, tested); `MenuBar` draws it with
AppKit (PyObjC, which pywebview already uses). Every click runs its action on a separate
thread, because opening windows or stopping the lights must not block the menu.
"""
import threading


def menu_model(state):
    """The menu as a list of entries: {"title", "action", "enabled", "checked", "sub"};
    None is a separator. `action` is a tuple handed to the click handler."""
    running = state.get("running")
    if running:
        bpm = round(state.get("bpm") or 0)
        head = "Playing" + (f" · {bpm} BPM" if bpm else "")
    else:
        head = "Stopped"
    presets = [p["name"] for p in (state.get("cfg") or {}).get("presets") or []]
    current = state.get("preset") or ""
    sub = [{"title": n, "action": ("preset", n), "enabled": True, "checked": n == current}
           for n in presets] or [{"title": "No presets yet", "action": None, "enabled": False}]
    return [
        {"title": head, "action": None, "enabled": False},
        {"title": "Stop" if running else "Play", "action": ("toggle",), "enabled": True},
        None,
        {"title": "Presets", "action": None, "enabled": True, "sub": sub},
        None,
        {"title": "Open Temponome", "action": ("show",), "enabled": True},
        {"title": "Settings…", "action": ("settings",), "enabled": True},
        None,
        {"title": "Quit Temponome", "action": ("quit",), "enabled": True},
    ]


def lamp_image():
    """An 18 pt template image of the logo's lamp (macOS tints it for light/dark menu bars)."""
    from AppKit import NSBezierPath, NSColor, NSImage, NSMakePoint
    img = NSImage.alloc().initWithSize_((18, 18))
    img.lockFocus()
    NSColor.blackColor().set()
    shade = NSBezierPath.bezierPath()                 # wide at the bottom, like the logo
    for i, (x, y) in enumerate(((2.5, 6.5), (15.5, 6.5), (12, 16), (6, 16))):
        (shade.moveToPoint_ if i == 0 else shade.lineToPoint_)(NSMakePoint(x, y))
    shade.closePath()
    shade.fill()
    NSBezierPath.fillRect_(((8, 1.5), (2, 4)))      # the stand
    img.unlockFocus()
    img.setTemplate_(True)
    return img


def make_menubar(get_state, on_action):
    """Create the status item (call on the main thread). Returns an object to keep alive."""
    import objc
    from AppKit import NSMenu, NSMenuItem, NSStatusBar, NSVariableStatusItemLength
    from Foundation import NSObject

    class _Delegate(NSObject):
        def menuNeedsUpdate_(self, menu):
            try:
                entries = menu_model(get_state())
            except Exception:
                entries = menu_model({})
            self.actions = []
            menu.removeAllItems()
            self._fill(menu, entries)

        @objc.python_method
        def _fill(self, menu, entries):
            for e in entries:
                if e is None:
                    menu.addItem_(NSMenuItem.separatorItem())
                    continue
                item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    e["title"], "clicked:" if e.get("action") else None, "")
                item.setEnabled_(bool(e.get("enabled")))
                if e.get("checked"):
                    item.setState_(1)
                if e.get("action"):
                    item.setTarget_(self)
                    item.setTag_(len(self.actions))
                    self.actions.append(e["action"])
                if e.get("sub"):
                    sub = NSMenu.alloc().init()
                    sub.setAutoenablesItems_(False)
                    self._fill(sub, e["sub"])
                    item.setSubmenu_(sub)
                menu.addItem_(item)

        def clicked_(self, sender):
            act = self.actions[sender.tag()]
            threading.Thread(target=on_action, args=(act,), daemon=True).start()

    item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
    try:
        item.button().setImage_(lamp_image())
        item.button().setToolTip_("Temponome")
    except Exception:
        item.button().setTitle_("Temponome")
    delegate = _Delegate.alloc().init()
    delegate.actions = []
    menu = NSMenu.alloc().init()
    menu.setAutoenablesItems_(False)
    menu.setDelegate_(delegate)
    item.setMenu_(menu)
    return item, menu, delegate


def remove_menubar(handle):
    """Take the lamp out of the menu bar (call on the main thread)."""
    from AppKit import NSStatusBar
    item = handle[0]
    NSStatusBar.systemStatusBar().removeStatusItem_(item)
