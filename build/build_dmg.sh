#!/bin/bash
# Builds Temponome.app and the drag-to-install disk image dist/Temponome.dmg (Apple Silicon).
# Usage: build/build_dmg.sh
#        build/build_dmg.sh --sign "Developer ID Application: Name (TEAMID)" [--notary-profile PROFILE]
# Without --sign the app is ad-hoc signed (first open: right-click > Open).
# --notary-profile is a keychain profile made once with: xcrun notarytool store-credentials
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
SIGN_ID="-"
NOTARY=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --sign) SIGN_ID="${2:?give the signing identity}"; shift 2 ;;
    --notary-profile) NOTARY="${2:?give the notarytool keychain profile}"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 2 ;;
  esac
done
if [[ -n "$NOTARY" && "$SIGN_ID" == "-" ]]; then echo "Notarizing needs --sign."; exit 2; fi

PY="${PYTHON:-python3}"
VENV="$ROOT/build/.venv"
if [[ ! -x "$VENV/bin/python" ]]; then "$PY" -m venv "$VENV"; fi
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet numpy sounddevice tapo pywebview pyinstaller dmgbuild

# Build outside the project: ~/Documents may be synced by iCloud Drive, which keeps adding
# file metadata that codesign refuses ("resource fork, Finder information ... not allowed").
OUT="$HOME/Library/Caches/temponome-build"
mkdir -p "$OUT"
"$VENV/bin/pyinstaller" --noconfirm --clean --distpath "$OUT/dist" --workpath "$OUT/work" "$ROOT/build/temponome.spec"

APP="$OUT/dist/Temponome.app"
xattr -cr "$APP"       # strip any metadata copied from the source folder
if [[ "$SIGN_ID" == "-" ]]; then
  codesign --force --deep --sign - "$APP"
else
  # hardened runtime needs explicit permission for the microphone and camera
  codesign --force --deep --options runtime --timestamp \
           --entitlements "$ROOT/build/entitlements.plist" --sign "$SIGN_ID" "$APP"
fi
codesign --verify --deep --strict "$APP"

# Disk image: Temponome + an Applications shortcut + Read Me, on a background with an arrow.
DMGSRC="$OUT/dmg"
mkdir -p "$DMGSRC"
cp "$ROOT/build/dmg/Read Me.txt" "$DMGSRC/Read Me.txt"
qlmanage -t -s 1200 -o "$DMGSRC" "$ROOT/build/dmg/background.svg" >/dev/null 2>&1
sips -c 800 1200 "$DMGSRC/background.svg.png" --out "$DMGSRC/background.png" >/dev/null
sips -s dpiWidth 144 -s dpiHeight 144 "$DMGSRC/background.png" >/dev/null   # Retina: shows as 600x400
rm -f "$OUT/Temponome.dmg"
"$VENV/bin/dmgbuild" -s "$ROOT/build/dmg/settings.py" -D app="$APP" -D here="$DMGSRC" \
                     "Temponome" "$OUT/Temponome.dmg"
if [[ "$SIGN_ID" != "-" ]]; then
  codesign --force --timestamp --sign "$SIGN_ID" "$OUT/Temponome.dmg"
fi
if [[ -n "$NOTARY" ]]; then
  xcrun notarytool submit "$OUT/Temponome.dmg" --keychain-profile "$NOTARY" --wait
  xcrun stapler staple "$OUT/Temponome.dmg"
fi
hdiutil verify "$OUT/Temponome.dmg" >/dev/null
mkdir -p "$ROOT/dist"
cp "$OUT/Temponome.dmg" "$ROOT/dist/Temponome.dmg"   # a flat file: safe to keep in a synced folder
echo "App (for testing): $APP"
echo "Disk image: $ROOT/dist/Temponome.dmg"
