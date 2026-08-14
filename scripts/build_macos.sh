#!/bin/bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
DIST_APP_NAME="Eggie DocuFlow.app"
APP_VERSION="$("$PYTHON" -c 'from version import APP_VERSION; print(APP_VERSION)')"
APP_NAME="EggieDocuFlow_V${APP_VERSION}_mac.app"
ZIP_NAME="EggieDocuFlow_V${APP_VERSION}_mac.zip"
DIST_DIR="$PROJECT_ROOT/dist"
BUILD_DIR="$PROJECT_ROOT/build"
RELEASE_DIR="$PROJECT_ROOT/release"

rm -rf "$DIST_DIR" "$BUILD_DIR"
find "$PROJECT_ROOT" \
  -path "$PROJECT_ROOT/.git" -prune -o \
  -path "$PROJECT_ROOT/.venv" -prune -o \
  -path "$RELEASE_DIR" -prune -o \
  -name "__pycache__" -type d -exec rm -rf {} +
find "$PROJECT_ROOT" \
  -path "$PROJECT_ROOT/.git" -prune -o \
  -path "$PROJECT_ROOT/.venv" -prune -o \
  -path "$RELEASE_DIR" -prune -o \
  -name ".DS_Store" -type f -delete
mkdir -p "$RELEASE_DIR"
rm -rf "$RELEASE_DIR/$APP_NAME"
rm -f "$RELEASE_DIR/$ZIP_NAME"

"$PYTHON" -m PyInstaller \
  --noconfirm \
  --clean \
  --distpath "$DIST_DIR" \
  --workpath "$BUILD_DIR" \
  "$PROJECT_ROOT/packaging/EggieDocuFlow.spec"

APP_PATH="$DIST_DIR/$DIST_APP_NAME"
if [[ ! -d "$APP_PATH" ]]; then
  echo "Build failed: $APP_PATH was not created." >&2
  exit 1
fi

SIGN_DIR="$(mktemp -d /tmp/eggie-sign.XXXXXX)"
trap 'rm -rf "$SIGN_DIR"' EXIT
SIGNED_APP_PATH="$SIGN_DIR/$APP_NAME"
/usr/bin/ditto --norsrc "$APP_PATH" "$SIGNED_APP_PATH"
/usr/bin/xattr -cr "$SIGNED_APP_PATH"
/usr/bin/codesign --force --deep --sign - "$SIGNED_APP_PATH"
/usr/bin/codesign --verify --deep --strict "$SIGNED_APP_PATH"

(
  cd "$SIGN_DIR"
  COPYFILE_DISABLE=1 /usr/bin/zip -9 -y -q -r "$RELEASE_DIR/$ZIP_NAME" "$APP_NAME" \
    -x "*.DS_Store" "*/__MACOSX/*"
)

APP_BYTES="$(/usr/bin/du -sk "$SIGNED_APP_PATH" | awk '{print $1 * 1024}')"
ZIP_BYTES="$(/usr/bin/stat -f '%z' "$RELEASE_DIR/$ZIP_NAME")"

echo "App size: $((APP_BYTES / 1024 / 1024)) MB"
echo "Zip size: $((ZIP_BYTES / 1024 / 1024)) MB"

echo "Release ZIP is in $RELEASE_DIR"
