import os
import sys
from pathlib import Path

from PySide6.QtCore import QLocale, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app import (
    ExcelMergerWindow,
    install_qt_translations,
    localized_app_name,
    preferred_system_locale,
    resource_path,
)
from excel_merge_tool import SUPPORTED_EXTENSIONS
from version import APP_VERSION


def main():
    if "--version" in sys.argv[1:]:
        print(APP_VERSION)
        return

    print(f"Eggie DocuFlow v{APP_VERSION}", flush=True)
    application = QApplication(sys.argv)
    application.preferred_locale = preferred_system_locale()
    app_name = localized_app_name(application.preferred_locale)
    application.setApplicationName(app_name)
    application.setApplicationDisplayName(app_name)
    application.setWindowIcon(QIcon(str(resource_path("assets/app_icon.icns"))))
    QLocale.setDefault(application.preferred_locale)
    install_qt_translations(application, application.preferred_locale)

    window = ExcelMergerWindow()
    window.show()

    def load_startup_paths():
        loaded_paths = False
        loaded_pdf = False
        for input_path in sys.argv[1:]:
            if os.path.isdir(input_path):
                loaded_paths = bool(
                    window.load_folder(input_path, show_messages=False)
                ) or loaded_paths
            elif Path(input_path).suffix.lower() in SUPPORTED_EXTENSIONS:
                loaded_paths = bool(window.add_paths([input_path])) or loaded_paths
            elif Path(input_path).suffix.lower() == ".pdf":
                loaded_pdf = bool(window.set_document_source_file(input_path)) or loaded_pdf

        if loaded_pdf:
            window.show_document_tool()
        elif loaded_paths:
            window.show_excel_tool()

    QTimer.singleShot(0, load_startup_paths)
    sys.exit(application.exec())


if __name__ == "__main__":
    main()
