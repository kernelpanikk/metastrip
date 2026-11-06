"""MetaStrip: native window with drag & drop; the page calls core via pywebview's js_api."""
import json
import os
import subprocess
import sys
from pathlib import Path

import webview
from webview.dom import DOMEventHandler

import core

# Apps launched from Finder get a bare PATH: make Homebrew's exiftool and qpdf findable.
os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "")
# Bundled data lives in sys._MEIPASS when frozen by PyInstaller.
HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))

# WKWebView's storage for file:// pages isn't reliably persisted, so settings live in a file.
SETTINGS = Path.home() / "Library/Application Support/MetaStrip/settings.json"


class Api:
    def inspect(self, path):
        return core.inspect(path)

    def strip(self, path, keys, overwrite, edits):
        return core.strip(path, keys, overwrite, edits)

    def info(self, path):
        p = Path(path)
        size = p.stat().st_size
        human = f"{size / 1024:.0f} KB" if size < 1024**2 else f"{size / 1024**2:.1f} MB"
        return {"type": p.suffix[1:].upper() or "File", "size": human, "folder": p.parent.name}

    def reveal(self, path):
        subprocess.run(["open", "-R", path], check=True)  # select the file in Finder

    def get_settings(self):
        try:
            return json.loads(SETTINGS.read_text())
        except (OSError, ValueError):
            return {}

    def save_settings(self, settings):
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(settings))

    def choose(self):
        picked = window.create_file_dialog(webview.FileDialog.OPEN)
        return picked[0] if picked else None


def on_drop(e):
    # Only the native side sees the real path of a dropped file.
    files = e["dataTransfer"]["files"]
    if files:
        window.evaluate_js(f"load({json.dumps(files[0]['pywebviewFullPath'])})")


def bind(w):
    w.dom.document.events.dragover += DOMEventHandler(lambda e: None, True, True)
    w.dom.document.events.drop += DOMEventHandler(on_drop, True, True)


window = webview.create_window(
    "MetaStrip", str(HERE / "index.html"), js_api=Api(), width=820, height=680, min_size=(520, 420)
)
webview.start(bind, window)
