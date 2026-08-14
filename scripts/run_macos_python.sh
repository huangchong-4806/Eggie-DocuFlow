#!/bin/bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-$PROJECT_ROOT/.venv/bin/python}"
cd "$PROJECT_ROOT"
PLUGIN_SOURCE="$("$PYTHON" -c 'from pathlib import Path; import PySide6; print(Path(PySide6.__file__).parent / "Qt" / "plugins")')"
PLUGIN_DIR="$(mktemp -d "${TMPDIR:-/tmp}/eggie-qt-platforms.XXXXXX")"

cleanup() {
  rm -rf "$PLUGIN_DIR"
}
trap cleanup EXIT

cp -R "$PLUGIN_SOURCE/." "$PLUGIN_DIR/"
find "$PLUGIN_DIR" -type f -name '*.dylib' -exec chmod 755 {} +
while IFS= read -r -d '' plugin; do
  /usr/bin/codesign --force --sign - "$plugin" >/dev/null 2>&1
done < <(find "$PLUGIN_DIR" -type f -name '*.dylib' -print0)

QT_PLUGIN_PATH="$PLUGIN_DIR" \
QT_QPA_PLATFORM_PLUGIN_PATH="$PLUGIN_DIR/platforms" \
"$PYTHON" "$@"
