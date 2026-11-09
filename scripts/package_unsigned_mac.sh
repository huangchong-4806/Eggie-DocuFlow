#!/bin/bash
# Unsigned Mac CI artifact. Does not ad-hoc sign, Developer-ID sign, or notarize.
# Local release builds stay in scripts/build_macos.sh.
set -euo pipefail

if [[ "${EGGIE_CI_UNSIGNED:-}" != "1" ]]; then
  echo "Refusing to build. Set EGGIE_CI_UNSIGNED=1. This script does not sign the app." >&2
  exit 2
fi

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
cd "$PROJECT_ROOT"
APP_VERSION="$("$PYTHON" -c 'from version import APP_VERSION; print(APP_VERSION)')"
ZIP_NAME="EggieDocuFlow_V${APP_VERSION}_mac_arm64_ci-unsigned.zip"
RELEASE_DIR="$PROJECT_ROOT/ci-package"
rm -rf "$RELEASE_DIR"
mkdir -p "$RELEASE_DIR"
STAGE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/eggie-ci-mac.XXXXXX")"
trap 'rm -rf "$STAGE_DIR"' EXIT

"$PYTHON" -m PyInstaller \
  --noconfirm \
  --clean \
  --distpath "$STAGE_DIR/dist" \
  --workpath "$STAGE_DIR/build" \
  "$PROJECT_ROOT/packaging/EggieDocuFlow.spec"

APP_PATH="$STAGE_DIR/dist/Eggie DocuFlow.app"
if [[ ! -d "$APP_PATH" ]]; then
  echo "Build failed: $APP_PATH was not created." >&2
  exit 1
fi

"$APP_PATH/Contents/MacOS/Eggie DocuFlow" --version

COPYFILE_DISABLE=1 /usr/bin/ditto -c -k --norsrc --keepParent "$APP_PATH" "$RELEASE_DIR/$ZIP_NAME"
/usr/bin/unzip -tq "$RELEASE_DIR/$ZIP_NAME" >/dev/null
"$PYTHON" "$PROJECT_ROOT/scripts/write_sha256sums.py" "$RELEASE_DIR/$ZIP_NAME" "$RELEASE_DIR/SHA256SUMS.txt"
echo "CI unsigned zip: $RELEASE_DIR/$ZIP_NAME"
