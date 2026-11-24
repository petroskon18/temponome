#!/usr/bin/env python3
"""Temponome.app entry point: runs the Temponome engine and local server, and shows the
pages in native macOS windows (WebKit via pywebview) instead of a browser tab.

The main window is the deck; Settings opens in a second window (⌘, or the gear button).
Closing the main window stops the lights' engine and quits."""
import os
import socket
import sys
import threading
import webbrowser

if not getattr(sys, "frozen", False):   # running from the source folder
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import temponome  # noqa: E402

# pywebview sizes are the whole window. The title bar is see-through and drawn over the
# page (merge_title_bar), so each page starts with a TITLE_BAR-high strip (`.titlebar` in
# deck.css, 30 px + rounding) under the window buttons, then the space it needs
# (main 600x400, Settings 680x640, measured)
TITLE_BAR = 32
MAIN_SIZE = (600, 400 + TITLE_BAR)
MAIN_MIN = (440, 330 + TITLE_BAR)
SETTINGS_SIZE = (680, 640 + TITLE_BAR)
SETTINGS_MIN = (480, 420 + TITLE_BAR)


MENU_BAR = 25          # keep windows below the macOS menu bar
GAP = 12               # space between the main window and Settings


def settings_position(main, screen, size=SETTINGS_SIZE, gap=GAP):
    """Where to open Settings so it doesn't cover the main window.

    main = (x, y, width, height) of the main window, screen = (width, height), both in
    points from the top-left. Returns (settings_x, settings_y, new_main_x or None):
    Settings goes to the right of the main window, else to its left; if neither side has
    room but both windows fit side by side, the main window slides over to make room;
    on a very small screen Settings overlaps as little as it can."""
    mx, my, mw, mh = main
    sw, sh = screen
    w, h = size
    new_mx = None
    if mx + mw + gap + w <= sw:                 # room on the right
        x = mx + mw + gap
    elif mx - gap - w >= 0:                     # room on the left
        x = mx - gap - w
    elif mw + gap + w <= sw:                    # room for both: slide the main window left
        new_mx = max(0, (sw - (mw + gap + w)) // 2)
        x = new_mx + mw + gap
    else:                                       # small screen: cover as little as possible
        x = sw - w if sw - (mx + mw) >= mx else 0
        x = max(0, x)
    y = max(MENU_BAR, min(my, sh - h))
    return int(x), int(y), new_mx


def merge_title_bar(window, size):
    """Make the macOS title bar part of the page: see-through, no title text, the page
    drawn underneath it. The red/yellow/green buttons stay and sit on the panel; the
    page's `.pywebview-drag-region` strip moves the window. Does nothing off macOS."""
    try:
        import AppKit
        from PyObjCTools import AppHelper
    except ImportError:
        return

    def apply():
        w = getattr(window, "native", None)
        if w is None:
            return
        w.setStyleMask_(w.styleMask() | AppKit.NSWindowStyleMaskFullSizeContentView)
        w.setTitlebarAppearsTransparent_(True)
        w.setTitleVisibility_(AppKit.NSWindowTitleHidden)
        # the window loses the title bar's height when its content moves under it: put the
        # full size back, keeping the top-left corner where it was
        f = w.frame()
        top = f.origin.y + f.size.height
        w.setFrame_display_(AppKit.NSMakeRect(f.origin.x, top - size[1], size[0], size[1]), True)

    AppHelper.callAfter(apply)


def free_port(preferred=8765):
    """`preferred` if nothing is listening there (e.g. the old launcher), else any free port."""
    for port in (preferred, 0):
        s = socket.socket()
        # same rule as the web server (allow_reuse_address): just-closed connections don't
        # block the port, but another program listening on it does
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return s.getsockname()[1]
        except OSError:
            continue
        finally:
            s.close()
    raise OSError("no free local port")


def start_server(preferred=8765):
    """Bind the web server directly (no check-then-bind gap): 8765 if it's free,
    otherwise any free port."""
    try:
        return temponome.make_server(preferred)
    except OSError:
        return temponome.make_server(0)


def shutdown_all(server):
    """Stop the engine (lights stop pulsing), close the web server and the Govee socket."""
    eng = temponome.ENGINE
    eng.stop()
    if eng.thread:
        eng.thread.join(3.0)
    eng.running = False
    server.shutdown()
    server.server_close()
    temponome.GOVEE.close()


class Api:
    """Functions the pages can call through window.pywebview.api. Only public methods are
    meant for the page; state is kept in underscore attributes, which pywebview doesn't expose."""

    def __init__(self, base_url):
        self._base = base_url
        self._settings = None
        self._main = None          # the main window, so Settings can open beside it

    def open_settings(self, tab="lights"):
        tab = tab if tab in ("lights", "colors", "sound", "timing") else "lights"
        if self._settings is not None:
            try:
                self._settings.evaluate_js(f"showTab({tab!r})")
                self._settings.show()
                self._settings.restore()
                return
            except Exception:           # it was closing: make a new one
                self._settings = None
        self._create_settings(tab)

    def _create_settings(self, tab):
        import webview
        x = y = None
        try:
            m, scr = self._main, webview.screens[0]
            x, y, new_mx = settings_position((m.x, m.y, m.width, m.height), (scr.width, scr.height))
            if new_mx is not None:
                m.move(new_mx, m.y)
        except Exception:                # unknown position: let macOS place it
            x = y = None
        self._settings = webview.create_window(
            "Temponome Settings", f"{self._base}/settings#{tab}", js_api=self,
            width=SETTINGS_SIZE[0], height=SETTINGS_SIZE[1], min_size=SETTINGS_MIN, x=x, y=y)
        self._settings.events.before_show += lambda: merge_title_bar(self._settings, SETTINGS_SIZE)
        self._settings.events.closed += self._settings_closed

    def _settings_closed(self):
        self._settings = None

    def open_in_browser(self, path="/settings#timing"):
        """Fallback when the camera isn't available inside the app window."""
        webbrowser.open(self._base + path)


def on_main_closed(server, shutdown=shutdown_all, exit=os._exit):
    """Closing the main window quits: stop the lights and the server, then always exit."""
    try:
        shutdown(server)
    finally:
        exit(0)


def run():
    import webview
    server = start_server(8765)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    api = Api(base)
    main = webview.create_window("Temponome", base + "/", js_api=api,
                                 width=MAIN_SIZE[0], height=MAIN_SIZE[1], min_size=MAIN_MIN)
    api._main = main
    main.events.before_show += lambda: merge_title_bar(main, MAIN_SIZE)

    # os._exit also closes the Settings window and WebKit helpers; settings are saved atomically
    main.events.closed += lambda: on_main_closed(server)
    webview.start(private_mode=False)


if __name__ == "__main__":
    run()
