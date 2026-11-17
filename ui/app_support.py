import re
import subprocess
import sys
from pathlib import Path
from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator


APP_NAME_ZH = "Eggie文档处理系统"

APP_NAME_EN = "Eggie DocuFlow"

DOCUMENT_TYPE_LABELS = {
    "INVOICE": "发票",
    "CONTRACT": "合同",
    "TABLE": "表格",
    "UNKNOWN": "未知文档",
}

PDF_IMAGE_WARNING_COUNT = 100

PDF_IMAGE_MAX_COUNT = 300

RENAME_WARNING_COUNT = 5000

RENAME_MAX_COUNT = 20000


def is_chinese_locale(locale):
    return locale.language() == QLocale.Chinese


def localized_app_name(locale):
    return APP_NAME_ZH if is_chinese_locale(locale) else APP_NAME_EN


def resource_path(relative_path):
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base_path / relative_path


def application_icon_path():
    icon_name = "app_icon.ico" if sys.platform == "win32" else "app_icon.icns"
    return resource_path(f"assets/{icon_name}")


def preferred_system_locale():
    locale_name = QLocale.system().name()

    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["/usr/bin/defaults", "read", "-g", "AppleLanguages"],
                capture_output=True,
                check=False,
                text=True,
                timeout=2,
            )
            match = re.search(r'"([^"]+)"', result.stdout)
            if match:
                locale_name = match.group(1)
        except (OSError, subprocess.SubprocessError):
            pass

    return QLocale(locale_name)


def install_qt_translations(application, locale):
    translations_path = QLibraryInfo.path(QLibraryInfo.TranslationsPath)
    translator = QTranslator(application)

    if translator.load(locale, "qtbase", "_", translations_path):
        application.installTranslator(translator)
        application.qtbase_translator = translator


def default_output_filename(locale):
    if locale.language() != QLocale.Chinese:
        return "Merged result.xlsx"

    if locale.script() == QLocale.TraditionalHanScript:
        return "合併結果.xlsx"
    return "合并结果.xlsx"


def format_elapsed_seconds(seconds):
    if seconds < 60:
        return f"{seconds:.2f} 秒"

    minutes = int(seconds // 60)
    remaining_seconds = seconds - minutes * 60
    return f"{minutes} 分 {remaining_seconds:.2f} 秒"
