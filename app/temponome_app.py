#!/usr/bin/env python3
"""Temponome.app entry point: runs the Temponome engine and local server, and shows the
pages in native macOS windows (WebKit via pywebview) instead of a browser tab.

The main window is the deck; Settings opens in a second window (⌘, or the gear button).
Closing the main window hides it; Temponome keeps running behind the lamp in the menu bar.
Quit (menu bar, ⌘Q or the app menu) puts the lights back and quits."""
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
        if w.respondsToSelector_("setTitlebarSeparatorStyle:"):
            w.setTitlebarSeparatorStyle_(AppKit.NSTitlebarSeparatorStyleNone)
        # pywebview paints the title bar's container gray (windowBackgroundColor), which
        # would still show as a separate bar over the page: make it see-through too
        for v in w.contentView().superview().subviews():
            if "TitlebarContainer" in str(v.className()) and v.respondsToSelector_("setBackgroundColor:"):
                v.setBackgroundColor_(AppKit.NSColor.clearColor())
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
        eng.thread.join(temponome.RESTORE_TIMEOUT + 2.0)   # lets the lights get their earlier look back
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

    def show_guide(self):
        """Settings → Lights "Show the welcome guide": open it in the main window."""
        if self._main is not None:
            self._main.show()
            self._main.evaluate_js("window.showGuide && showGuide()")

    def open_in_browser(self, path="/settings#timing"):
        """Fallback when the camera isn't available inside the app window."""
        webbrowser.open(self._base + path)


def on_main_closed(server, shutdown=shutdown_all, exit=os._exit):
    """Closing the main window quits: stop the lights and the server, then always exit."""
    try:
        shutdown(server)
    finally:
        exit(0)


class Shell:
    """What the menu bar and the Mac's own Quit / Dock click do."""

    def __init__(self, server, api, main, quit=None):
        self.server, self.api, self.main = server, api, main
        self.quitting = False
        self._quit = quit or (lambda: on_main_closed(server))

    def on_closing(self):
        """Red close button: hide the window and keep playing (the menu bar lamp stays)."""
        if self.quitting:
            return True
        self.main.hide()
        return False

    def quit(self):
        if self.quitting:
            return
        self.quitting = True
        self._quit()

    def action(self, act):
        kind = act[0]
        if kind == "toggle":
            eng = temponome.ENGINE
            eng.stop() if eng.want_running else eng.start()
        elif kind == "preset":
            temponome.preset_action({"action": "apply", "name": act[1]})
        elif kind == "show":
            self.main.show()
        elif kind == "settings":
            self.main.show()
            self.api.open_settings()
        elif kind == "quit":
            self.quit()


def install_mac_hooks(shell):
    """On the main thread: the menu bar lamp, ⌘Q quits for real, a Dock click shows the window."""
    from PyObjCTools import AppHelper

    def install():
        try:
            from webview.platforms.cocoa import BrowserView
            import menubar

            class TemponomeAppDelegate(BrowserView.AppDelegate):
                def applicationShouldTerminate_(self, app):
                    threading.Thread(target=shell.quit, daemon=True).start()
                    return 0                    # NSTerminateCancel: shell.quit exits once the lights are back

                def applicationShouldHandleReopen_hasVisibleWindows_(self, app, visible):
                    shell.main.show()
                    return True

            BrowserView._shared_app_delegate = TemponomeAppDelegate.alloc().init()
            BrowserView.app.setDelegate_(BrowserView._shared_app_delegate)
            shell._menubar = menubar.make_menubar(temponome.state_dict, shell.action)
        except Exception as e:                  # never let the extras stop the app from working
            print("menu bar unavailable:", e, file=sys.stderr)

    AppHelper.callAfter(install)


def run():
    import webview
    temponome.recover_sound_output()
    temponome.start_autostart()
    server = start_server(8765)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    api = Api(base)
    main = webview.create_window("Temponome", base + "/", js_api=api,
                                 width=MAIN_SIZE[0], height=MAIN_SIZE[1], min_size=MAIN_MIN)
    api._main = main
    main.events.before_show += lambda: merge_title_bar(main, MAIN_SIZE)
    shell = Shell(server, api, main)
    main.events.closing += shell.on_closing
    # if the window really closes (it shouldn't), still quit cleanly; os._exit also closes
    # the Settings window and WebKit helpers; settings are saved atomically
    main.events.closed += lambda: on_main_closed(server)
    webview.start(lambda: install_mac_hooks(shell), private_mode=False)


if __name__ == "__main__":
    run()
