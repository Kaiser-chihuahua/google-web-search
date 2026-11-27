#!/usr/bin/env python3
"""
PyBrowser - a small standalone web browser in a single file.

It is its own app: it embeds the Chromium engine that ships with
PyQt6-WebEngine, so it doesn't open or depend on any other browser.

  - tabs, back / forward / reload, one bar for web addresses AND searches
  - start page with quick links (Krunker.io, YouTube, Google, Wikipedia)
  - made for web games and video: WebGL, fullscreen, mouse-lock, autoplay
  - downloads, zoom, find-in-page, pop-up blocking, saved cookies and settings

Setup (once):   pip install PyQt6 PyQt6-WebEngine
Run:            python pybrowser.py            (or: python pybrowser.py krunker.io)

Keys:  Ctrl+T new tab    Ctrl+W close tab    Ctrl+L address bar    Ctrl+F find
       Ctrl +/-/0 zoom   F11 fullscreen      F5 reload             Alt+Left/Right back/forward
(On a Mac, Ctrl means the Cmd key.)

Want a different search engine? Change SEARCH_URL below.
"""

import json
import os
import re
import sys
from urllib.parse import quote_plus

from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QSize, QStandardPaths, Qt, QTimer, QUrl
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWebEngineCore import (
    QWebEngineDownloadRequest,
    QWebEngineNewWindowRequest,
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineSettings,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QStyle,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

try:  # Qt 6.8+ replaced the old "feature permission" calls with this class
    from PyQt6.QtWebEngineCore import QWebEnginePermission
except ImportError:
    QWebEnginePermission = None

APP_NAME = "PyBrowser"

# Where searches go. {} is replaced with what you typed.
SEARCH_URL = "https://www.google.com/search?q={}"
# SEARCH_URL = "https://duckduckgo.com/?q={}"

# Typing one of these words in the address bar goes straight to the site.
SHORTCUTS = {
    "youtube": "https://www.youtube.com",
    "yt": "https://www.youtube.com",
    "krunker": "https://krunker.io",
    "google": "https://www.google.com",
    "wikipedia": "https://www.wikipedia.org",
}

_SCHEME = re.compile(r"^(https?|file|about|chrome|view-source):", re.I)
_LOCAL = re.compile(r"^(localhost|\d{1,3}(\.\d{1,3}){3})(:\d+)?([/?#]\S*)?$", re.I)
_DOMAIN = re.compile(r"^([\w-]+\.)+[a-z]{2,}(:\d+)?([/?#]\S*)?$", re.I)


def to_url_string(text):
    """Turn whatever was typed into a web address, or into a search."""
    text = text.strip()
    if text.lower() in SHORTCUTS:
        return SHORTCUTS[text.lower()]
    if _SCHEME.match(text):
        return text
    if _LOCAL.match(text):
        return "http://" + text
    if _DOMAIN.match(text):
        return "https://" + text
    return SEARCH_URL.format(quote_plus(text))


START_HTML = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>New Tab</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; display: flex; flex-direction: column;
         align-items: center; justify-content: center; gap: 28px;
         background: #15171c; color: #e8eaed;
         font: 16px/1.4 system-ui, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
  h1 { margin: 0; font-size: 30px; font-weight: 650; letter-spacing: .3px; }
  form { width: min(600px, 90vw); }
  input { width: 100%; padding: 14px 20px; font-size: 17px; color: inherit;
          background: #1f232b; border: 1px solid #343a45; border-radius: 999px; outline: none; }
  input:focus { border-color: #6ea0ff; box-shadow: 0 0 0 3px rgba(110,160,255,.18); }
  .tiles { display: flex; flex-wrap: wrap; gap: 16px; justify-content: center; max-width: 640px; }
  a { display: flex; flex-direction: column; align-items: center; gap: 10px; width: 118px;
      padding: 18px 8px; border: 1px solid transparent; border-radius: 16px; background: #1f232b;
      color: inherit; text-decoration: none; font-size: 14px; transition: .12s; }
  a:hover { background: #262b35; border-color: #6ea0ff; transform: translateY(-2px); }
  .ico { width: 46px; height: 46px; border-radius: 13px; display: grid; place-items: center;
         font-size: 22px; font-weight: 700; color: #fff; }
</style></head>
<body>
  <h1>Where to?</h1>
  <form id="f"><input id="q" placeholder="Search or type a web address" autofocus autocomplete="off"></form>
  <div class="tiles">
    <a href="https://krunker.io"><span class="ico" style="background:#e5484d">K</span>Krunker.io</a>
    <a href="https://www.youtube.com"><span class="ico" style="background:#d92d20">&#9654;</span>YouTube</a>
    <a href="https://www.google.com"><span class="ico" style="background:#3b7ddd">G</span>Google</a>
    <a href="https://www.wikipedia.org"><span class="ico" style="background:#4b5563">W</span>Wikipedia</a>
  </div>
<script>
  const SEARCH = "__SEARCH__", SHORT = __SHORTCUTS__;
  document.getElementById("f").addEventListener("submit", function (e) {
    e.preventDefault();
    const v = document.getElementById("q").value.trim();
    if (!v) return;
    let target;
    if (SHORT[v.toLowerCase()]) target = SHORT[v.toLowerCase()];
    else if (/^https?:\/\//i.test(v)) target = v;
    else if (/^([\w-]+\.)+[a-z]{2,}(:\d+)?([\/?#]\S*)?$/i.test(v)) target = "https://" + v;
    else target = SEARCH.replace("{}", encodeURIComponent(v));
    location.href = target;
  });
</script>
</body></html>
"""


def write_start_page():
    """Save the start page next to the browser's data and return its URL."""
    folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "start.html")
    html = START_HTML.replace("__SEARCH__", SEARCH_URL).replace("__SHORTCUTS__", json.dumps(SHORTCUTS))
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return QUrl.fromLocalFile(path)


class Tabs(QTabWidget):
    def __init__(self):
        super().__init__()
        self.tabBar().setElideMode(Qt.TextElideMode.ElideRight)

    def set_bar_visible(self, visible):
        self.tabBar().setVisible(visible)


class BrowserPage(QWebEnginePage):
    """A page that grants mouse-lock (shooters need it) and declines other permission prompts."""

    def __init__(self, profile, parent=None):
        super().__init__(profile, parent)
        if QWebEnginePermission is not None:  # Qt 6.8 and newer
            self.permissionRequested.connect(self._on_permission)
        else:  # older Qt 6
            self.featurePermissionRequested.connect(self._on_feature)

    def _on_permission(self, permission):
        if permission.permissionType() == QWebEnginePermission.PermissionType.MouseLock:
            permission.grant()
        else:
            permission.deny()

    def _on_feature(self, origin, feature):
        allow = feature == QWebEnginePage.Feature.MouseLock
        self.setFeaturePermission(
            origin,
            feature,
            QWebEnginePage.PermissionPolicy.PermissionGrantedByUser
            if allow
            else QWebEnginePage.PermissionPolicy.PermissionDeniedByUser,
        )


class BrowserView(QWebEngineView):
    def __init__(self, profile):
        super().__init__()
        self.setPage(BrowserPage(profile, self))
        self.is_loading = False
        self.progress = 100


class BrowserWindow(QMainWindow):
    def __init__(self, first_url=None):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 800)
        self.start_url = write_start_page()
        self.profile = QWebEngineProfile.defaultProfile()
        self._last_find = ""
        self._was_maximized = False
        self._fs_page = None  # the page that asked for fullscreen, if any
        self._setup_profile()
        self._build_ui()
        self.add_tab(QUrl(to_url_string(first_url)) if first_url else None)

    # ------------------------------------------------------------ setup
    def _setup_profile(self):
        p = self.profile
        p.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies)
        if hasattr(QWebEngineProfile, "PersistentPermissionsPolicy"):  # Qt 6.8+
            p.setPersistentPermissionsPolicy(QWebEngineProfile.PersistentPermissionsPolicy.AskEveryTime)
        attr = QWebEngineSettings.WebAttribute
        s = p.settings()
        s.setAttribute(attr.FullScreenSupportEnabled, True)  # fullscreen games / video
        s.setAttribute(attr.WebGLEnabled, True)
        s.setAttribute(attr.Accelerated2dCanvasEnabled, True)
        s.setAttribute(attr.PlaybackRequiresUserGesture, False)  # no extra click before audio/video
        s.setAttribute(attr.ScrollAnimatorEnabled, True)
        p.downloadRequested.connect(self.on_download)

    def _action(self, text, slot, *shortcuts, icon=None):
        action = QAction(text, self)
        if icon is not None:
            action.setIcon(icon)
        if shortcuts:
            action.setShortcuts([QKeySequence(s) for s in shortcuts])
        action.triggered.connect(slot)
        self.addAction(action)  # makes the shortcut work anywhere in the window
        return action

    def _build_ui(self):
        style = self.style()
        sp = QStyle.StandardPixmap
        self.reload_icon = style.standardIcon(sp.SP_BrowserReload)
        self.stop_icon = style.standardIcon(sp.SP_BrowserStop)

        # toolbar buttons
        self.back_act = self._action("Back", self.go_back, "Alt+Left", icon=style.standardIcon(sp.SP_ArrowBack))
        self.forward_act = self._action(
            "Forward", self.go_forward, "Alt+Right", icon=style.standardIcon(sp.SP_ArrowForward)
        )
        self.reload_act = self._action("Reload", self.reload_or_stop, icon=self.reload_icon)
        self.home_act = self._action("Home", self.go_home, "Alt+Home", icon=style.standardIcon(sp.SP_DirHomeIcon))

        # keyboard-only shortcuts
        self._action("Reload page", self.reload, "F5", "Ctrl+R")
        self._action("Address bar", self.focus_address, "Ctrl+L")
        self._action("Close tab", self.close_current_tab, "Ctrl+W")
        self._action("Next tab", lambda: self.cycle_tab(1), "Ctrl+Tab", "Ctrl+PgDown")
        self._action("Previous tab", lambda: self.cycle_tab(-1), "Ctrl+Shift+Tab", "Ctrl+PgUp")
        self._action("Find next", self.find_next, "F3")
        self.esc_act = self._action("Leave full screen", self.on_escape, "Esc")
        self.esc_act.setEnabled(False)  # only armed while a page is fullscreen; otherwise Esc goes to the page

        # menu items
        self.new_tab_act = self._action("New tab", self.new_tab, "Ctrl+T")
        self.find_act = self._action("Find in page...", self.find_in_page, "Ctrl+F")
        self.zoom_in_act = self._action("Zoom in", lambda: self.zoom(0.1), "Ctrl++", "Ctrl+=")
        self.zoom_out_act = self._action("Zoom out", lambda: self.zoom(-0.1), "Ctrl+-")
        self.zoom_reset_act = self._action("Reset zoom", self.zoom_reset, "Ctrl+0")
        self.fullscreen_act = self._action("Full screen", self.toggle_fullscreen, "F11")
        self.clear_act = self._action("Clear cookies and cache...", self.clear_data)

        self.address = QLineEdit()
        self.address.setPlaceholderText("Search or type a web address")
        self.address.setClearButtonEnabled(True)
        self.address.returnPressed.connect(self.navigate_from_address)

        self.toolbar = QToolBar("Navigation")
        self.toolbar.setMovable(False)
        self.toolbar.setIconSize(QSize(18, 18))
        self.addToolBar(self.toolbar)
        for act in (self.back_act, self.forward_act, self.reload_act, self.home_act):
            self.toolbar.addAction(act)
        self.toolbar.addWidget(self.address)

        menu = QMenu(self)
        for act in (
            self.new_tab_act,
            self.find_act,
            None,
            self.zoom_in_act,
            self.zoom_out_act,
            self.zoom_reset_act,
            None,
            self.fullscreen_act,
            None,
            self.clear_act,
        ):
            if act is None:
                menu.addSeparator()
            else:
                menu.addAction(act)
        menu_button = QToolButton()
        menu_button.setText("Menu")
        menu_button.setMenu(menu)
        menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.toolbar.addWidget(menu_button)

        self.tabs = Tabs()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.on_tab_changed)
        plus = QToolButton()
        plus.setText("+")
        plus.setToolTip("New tab")
        plus.setAutoRaise(True)
        plus.clicked.connect(self.new_tab)
        self.tabs.setCornerWidget(plus, Qt.Corner.TopRightCorner)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedHeight(3)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet(
            "QProgressBar{border:0;background:transparent}QProgressBar::chunk{background:#4c8bf5}"
        )

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.progress)
        layout.addWidget(self.tabs)
        self.setCentralWidget(central)
        self.statusBar()  # create the status bar (shows link hovers and download messages)

    # ------------------------------------------------------------ tabs
    def current_view(self):
        return self.tabs.currentWidget()

    def new_tab(self):
        self.add_tab()

    def add_tab(self, url=None, switch=True, blank=False):
        view = BrowserView(self.profile)
        page = view.page()
        view.titleChanged.connect(lambda title, v=view: self.on_title(v, title))
        view.iconChanged.connect(lambda icon, v=view: self.on_icon(v, icon))
        view.urlChanged.connect(lambda u, v=view: self.on_url(v, u))
        view.loadStarted.connect(lambda v=view: self.on_load_started(v))
        view.loadProgress.connect(lambda p, v=view: self.on_load_progress(v, p))
        view.loadFinished.connect(lambda ok, v=view: self.on_load_finished(v))
        page.linkHovered.connect(self.on_link_hovered)
        page.fullScreenRequested.connect(lambda request, p=page: self.on_fullscreen_request(p, request))
        page.newWindowRequested.connect(self.on_new_window)
        page.windowCloseRequested.connect(lambda v=view: self.close_view(v))

        index = self.tabs.addTab(view, "New Tab")
        if switch:
            self.tabs.setCurrentIndex(index)
        if not blank:
            view.load(url if url is not None else self.start_url)
        return view

    def close_tab(self, index):
        if index < 0:
            return
        if self.tabs.count() <= 1:
            self.close()
            return
        view = self.tabs.widget(index)
        if view.page() is self._fs_page:
            self._force_leave_fullscreen()
        self.tabs.removeTab(index)
        view.deleteLater()

    def close_current_tab(self):
        self.close_tab(self.tabs.currentIndex())

    def close_view(self, view):
        self.close_tab(self.tabs.indexOf(view))

    def cycle_tab(self, step):
        n = self.tabs.count()
        if n > 1:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + step) % n)

    def on_tab_changed(self, index):
        view = self.tabs.widget(index)
        if view is None:
            return
        if self._fs_page is not None and view.page() is not self._fs_page:
            self.leave_page_fullscreen()  # switching tabs ends page fullscreen, like Chrome
        self.set_address(view.url())
        self.setWindowTitle(f"{view.title() or 'New Tab'} - {APP_NAME}")
        self.show_load_state(view)
        view.setFocus()

    def on_new_window(self, request):
        """Links that open a new tab / window.pop-ups the page opens by itself are blocked."""
        if not request.isUserInitiated():
            self.statusBar().showMessage("Blocked a pop-up window", 4000)
            return
        background = request.destination() == QWebEngineNewWindowRequest.DestinationType.InNewBackgroundTab
        view = self.add_tab(blank=True, switch=not background)
        request.openIn(view.page())

    # ------------------------------------------------------------ page events
    def on_title(self, view, title):
        i = self.tabs.indexOf(view)
        if i < 0:
            return
        title = title or "New Tab"
        self.tabs.setTabText(i, title.replace("&", "&&")[:32])
        self.tabs.setTabToolTip(i, title)
        if view is self.current_view():
            self.setWindowTitle(f"{title} - {APP_NAME}")

    def on_icon(self, view, icon):
        i = self.tabs.indexOf(view)
        if i >= 0:
            self.tabs.setTabIcon(i, icon)

    def on_url(self, view, url):
        if view is self.current_view() and not self.address.hasFocus():
            self.set_address(url)

    def on_load_started(self, view):
        view.is_loading = True
        view.progress = 5
        if view is self.current_view():
            self.show_load_state(view)

    def on_load_progress(self, view, percent):
        view.progress = percent
        if view is self.current_view():
            self.show_load_state(view)

    def on_load_finished(self, view):
        view.is_loading = False
        view.progress = 100
        if view is self.current_view():
            self.show_load_state(view)

    def on_link_hovered(self, url):
        self.statusBar().showMessage(url)

    def show_load_state(self, view):
        self.progress.setValue(view.progress if view.is_loading else 0)
        self.reload_act.setIcon(self.stop_icon if view.is_loading else self.reload_icon)
        self.reload_act.setText("Stop" if view.is_loading else "Reload")

    def set_address(self, url):
        hidden = url == self.start_url or url.scheme() in ("", "about", "data")
        self.address.setText("" if hidden else url.toString())
        self.address.setCursorPosition(0)

    # ------------------------------------------------------------ navigation
    def navigate_from_address(self):
        text = self.address.text().strip()
        if not text:
            return
        view = self.current_view() or self.add_tab(blank=True)
        view.load(QUrl(to_url_string(text)))
        view.setFocus()

    def focus_address(self):
        self.address.setFocus()
        self.address.selectAll()

    def go_back(self):
        view = self.current_view()
        if view:
            view.back()

    def go_forward(self):
        view = self.current_view()
        if view:
            view.forward()

    def go_home(self):
        view = self.current_view()
        if view:
            view.load(self.start_url)

    def reload(self):
        view = self.current_view()
        if view:
            view.reload()

    def reload_or_stop(self):
        view = self.current_view()
        if view:
            view.stop() if view.is_loading else view.reload()

    # ------------------------------------------------------------ extras
    def zoom(self, delta):
        view = self.current_view()
        if view:
            view.setZoomFactor(max(0.25, min(5.0, view.zoomFactor() + delta)))

    def zoom_reset(self):
        view = self.current_view()
        if view:
            view.setZoomFactor(1.0)

    def find_in_page(self):
        view = self.current_view()
        if view is None:
            return
        text, ok = QInputDialog.getText(self, "Find in page", "Find:", text=self._last_find)
        if ok:
            self._last_find = text
            view.findText(text)

    def find_next(self):
        view = self.current_view()
        if view and self._last_find:
            view.findText(self._last_find)

    def clear_data(self):
        answer = QMessageBox.question(
            self,
            "Clear cookies and cache",
            "Delete cookies and cached files? You'll be signed out of websites.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.profile.cookieStore().deleteAllCookies()
            self.profile.clearHttpCache()
            self.statusBar().showMessage("Cookies and cache cleared", 4000)

    def on_download(self, item):
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        suggested = os.path.join(folder, item.downloadFileName())
        path, _ = QFileDialog.getSaveFileName(self, "Save download", suggested)
        if not path:
            item.cancel()
            return
        item.setDownloadDirectory(os.path.dirname(path))
        item.setDownloadFileName(os.path.basename(path))
        item.isFinishedChanged.connect(lambda: self._download_done(item, path))
        item.accept()
        self.statusBar().showMessage(f"Downloading {os.path.basename(path)}...", 4000)

    def _download_done(self, item, path):
        done = item.state() == QWebEngineDownloadRequest.DownloadState.DownloadCompleted
        self.statusBar().showMessage(f"Saved to {path}" if done else "Download did not finish", 6000)

    # ------------------------------------------------------------ fullscreen
    def on_fullscreen_request(self, page, request):
        """A page (YouTube, a game...) asked to go fullscreen or leave it."""
        request.accept()
        on = request.toggleOn()
        self._fs_page = page if on else None
        self.esc_act.setEnabled(on)  # Esc only means "leave fullscreen" while a page is fullscreen
        self.set_fullscreen(on)

    def on_escape(self):
        """Esc during page fullscreen: release the mouse first (like Chrome), otherwise leave fullscreen."""
        page = self._fs_page
        if page is None:
            return

        def decide(locked):
            try:
                if locked is True:
                    page.runJavaScript("document.exitPointerLock()")
                else:
                    self.leave_page_fullscreen()
            except RuntimeError:  # the page was closed in the meantime
                self._force_leave_fullscreen()

        page.runJavaScript("document.pointerLockElement !== null", decide)

    def leave_page_fullscreen(self):
        page = self._fs_page
        if page is None:
            return
        try:
            page.triggerAction(QWebEnginePage.WebAction.ExitFullScreen)
        except RuntimeError:  # the page is already gone
            self._force_leave_fullscreen()
            return
        QTimer.singleShot(300, self._force_leave_fullscreen)

    def _force_leave_fullscreen(self):
        """Backstop: if the page never confirms, still hand the window back to the user."""
        if self._fs_page is not None:
            self._fs_page = None
            self.esc_act.setEnabled(False)
            self.set_fullscreen(False)

    def toggle_fullscreen(self):
        self.set_fullscreen(not self.isFullScreen())

    def set_fullscreen(self, on):
        if on == self.isFullScreen():
            return
        self.toolbar.setVisible(not on)
        self.tabs.set_bar_visible(not on)
        self.statusBar().setVisible(not on)
        if on:
            self._was_maximized = self.isMaximized()
            self.showFullScreen()
        elif self._was_maximized:
            self.showMaximized()
        else:
            self.showNormal()


def main():
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    window = BrowserWindow(args[0] if args else None)
    window.show()
    code = app.exec()
    sip.delete(window)  # tear pages down before exit so cookies and settings are saved cleanly
    sys.exit(code)


if __name__ == "__main__":
    main()
