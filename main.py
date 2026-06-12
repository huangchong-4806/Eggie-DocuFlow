import os
import sys
from pathlib import Path

from PySide6.QtCore import QLocale, QTimer
from PySide6.QtWidgets import QApplication

from app import (
    ExcelMergerWindow,
    install_qt_translations,
    preferred_system_locale,
)
from excel_merge_tool import SUPPORTED_EXTENSIONS


def main():
    application = QApplication(sys.argv)
    application.setApplicationName("Excel合并工具V1.0.0")
    application.preferred_locale = preferred_system_locale()
    QLocale.setDefault(application.preferred_locale)
    install_qt_translations(application, application.preferred_locale)

    window = ExcelMergerWindow()
    window.show()

    def load_startup_paths():
        for input_path in sys.argv[1:]:
            if os.path.isdir(input_path):
                window.load_folder(input_path, show_messages=False)
            elif Path(input_path).suffix.lower() in SUPPORTED_EXTENSIONS:
                window.add_paths([input_path])

    QTimer.singleShot(0, load_startup_paths)
    sys.exit(application.exec())


if __name__ == "__main__":
    main()
