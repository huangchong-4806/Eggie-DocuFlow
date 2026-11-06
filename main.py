import multiprocessing
import os
import sys
from pathlib import Path

# The OS-elevated broker only verifies and hands off signed updates.
# Dispatch before importing Qt, PDF parsers, OCR clients or application settings.
if __name__ == "__main__" and sys.argv[1:2] == ["--eggie-install-update"]:
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        raise SystemExit(2)
    from eggie_update_windows import elevated_entry
    raise SystemExit(elevated_entry(sys.argv[2:]))

if __name__ == "__main__":
    from eggie_update_startup import startup_is_blocked
    if startup_is_blocked():
        raise SystemExit(0)


from PySide6.QtCore import QLocale, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app import (
    ExcelMergerWindow,
    application_icon_path,
    install_qt_translations,
    localized_app_name,
    preferred_system_locale,
    resource_path,
)
from excel_merge_tool import SUPPORTED_EXTENSIONS, discover_excel_files
from version import APP_VERSION


def load_startup_paths(window, paths):
    excel_paths = []
    loaded_pdf = False
    for path in paths:
        if os.path.isdir(path):
            excel_paths.extend(discover_excel_files(path))
        elif Path(path).suffix.lower() in SUPPORTED_EXTENSIONS:
            excel_paths.append(path)
        elif Path(path).suffix.lower() == ".pdf":
            loaded_pdf = window.set_document_source_file(path) or loaded_pdf

    # One review job must cover the whole launch request, in the given order.
    loaded_excel = bool(excel_paths) and window.add_paths(excel_paths)
    if loaded_pdf:
        window.show_document_tool()
    elif loaded_excel:
        window.show_excel_tool()


def main():
    multiprocessing.freeze_support()
    if sys.argv[1:] == ["--check-install"]:
        from core.install_check import check_install
        check_install()
        return
    if "--version" in sys.argv[1:]:
        print(APP_VERSION)
        return

    print(f"Eggie DocuFlow v{APP_VERSION}", flush=True)
    application = QApplication(sys.argv)
    application.preferred_locale = preferred_system_locale()
    app_name = localized_app_name(application.preferred_locale)
    application.setApplicationName(app_name)
    application.setApplicationDisplayName(app_name)
    application.setWindowIcon(QIcon(str(application_icon_path())))
    QLocale.setDefault(application.preferred_locale)
    install_qt_translations(application, application.preferred_locale)

    window = ExcelMergerWindow()
    window.show()
    if sys.platform == "darwin" and getattr(sys, "frozen", False):
        from eggie_update_mac import confirm_healthy_startup
        QTimer.singleShot(0, confirm_healthy_startup)

    QTimer.singleShot(0, lambda: load_startup_paths(window, sys.argv[1:]))
    sys.exit(application.exec())


if __name__ == "__main__":
    main()
