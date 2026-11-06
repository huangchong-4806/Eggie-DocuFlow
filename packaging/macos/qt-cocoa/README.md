# Mac Qt Cocoa accessibility backport

Qt 6.10.3's Cocoa plugin is rebuilt with upstream fix
`8148c48deb8e4345bacb797cb75c011df6f797fa` (QTBUG-149612). This changes native
accessibility element teardown, so that the table and accessibility cache retain
ownership of their interfaces. PySide6, Shiboken6 and the other Qt libraries are
unchanged. This is a local backport, not an official Qt binary release.

The original Qt copyright and LGPLv3 rights remain. The full LGPLv3/GPLv3 texts
are bundled under `licenses/`. Qt source, its third-party notices and these
changes must remain available with the matching release source materials.

Pinned inputs (SHA-256 is checked in `packaging/mac_cocoa.py`):

- [Qt Base 6.10.3 source](https://download.qt.io/archive/qt/6.10/6.10.3/submodules/qtbase-everywhere-src-6.10.3.tar.xz), saved as `qtbase-source.tar.xz`.
- [Qt Base 6.10.3 macOS SDK](https://download.qt.io/online/qtsdkrepository/mac_x64/desktop/qt6_6103/qt6_6103/qt.qt6.6103.clang_64/6.10.3-0-202603310405qtbase-MacOS-MacOS_15-Clang-MacOS-MacOS_15-X86_64-ARM64.7z), saved as `qtbase-sdk.7z`.
- [Upstream patch](https://github.com/qt/qtbase/commit/8148c48deb8e4345bacb797cb75c011df6f797fa), preserved as `QTBUG-149612.patch`.

On an Apple Silicon Mac with Xcode command-line tools, CMake and Ninja available:

```sh
python scripts/build_mac_cocoa.py --inputs /path/to/downloads --output /path/to/new-component
EGGIE_QT_COCOA_REPAIR_DIR=/path/to/new-component PYTHON=/path/to/python bash scripts/build_macos.sh
```

`--cmake` and `--ninja` accept paths to independently unpacked tools. The build
uses a temporary SDK/source tree and does not install or replace any libraries
in the development environment. Existing output directories are never replaced.

`cocoa-repair.json` records inputs, recipe, compiler and the rebuilt plugin's
digest **before** PyInstaller relocation, stripping and application signing.
The final release manifest checks the packaged application bytes separately.
PyInstaller removes build-machine SDK paths and points the plugin at the Qt
libraries inside the application. Verify its real process mapping and signature
after packaging. Re-evaluate this backport when upgrading Qt; the build guard
rejects a different PySide6 version instead of silently using an incompatible
plugin.
