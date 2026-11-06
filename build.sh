#!/bin/sh
# Builds dist/MetaStrip.app. Needs: brew install exiftool qpdf; .venv with pywebview + pyinstaller.
set -e
cd "$(dirname "$0")"
.venv/bin/pyinstaller --noconfirm --windowed --name MetaStrip --icon icon/MetaStrip.icns \
  --osx-bundle-identifier io.github.kernelpanikk.metastrip --add-data index.html:. app.py
