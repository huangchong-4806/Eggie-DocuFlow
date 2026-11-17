from pathlib import Path
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from ui.presentation import ToolEntry, tool_icon
from api_layer import PROVIDER_LABELS
from api_layer.config import select_provider, selected_provider
from ocr_settings_dialog import SoftwareSettingsDialog
from ui.update_check import UpdateCheckButton
from ui.theme import ACCENT_PALETTES, build_theme_colors, build_theme_stylesheet
from version import APP_VERSION, BUILD_NUMBER, BUILD_TYPE
from ui.app_support import (
    resource_path,
)


class WindowShellMixin:
    """Existing window methods; initialization remains in the window."""

    def create_sidebar(self):
        sidebar = QWidget()
        sidebar.setObjectName("homeSidebar")
        sidebar.setAttribute(Qt.WA_StyledBackground, True)
        sidebar.setFixedWidth(200)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 20, 12, 16)
        layout.setSpacing(8)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        self.home_logo_pixmap = QPixmap(str(resource_path("assets/app_icon.png")))
        self.home_logo_label = QLabel()
        self.home_logo_label.setFixedSize(32, 32)
        self.home_logo_label.setAlignment(Qt.AlignCenter)
        if not self.home_logo_pixmap.isNull():
            self.home_logo_label.setPixmap(
                self.home_logo_pixmap.scaled(
                    QSize(32, 32),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )
        else:
            self.home_logo_label.setText("Eggie")
        brand.addWidget(self.home_logo_label)

        brand_text = QVBoxLayout()
        brand_text.setSpacing(2)
        name = QLabel("Eggie")
        name.setProperty("homeRole", "brand")
        subtitle = QLabel("文档处理系统")
        subtitle.setProperty("homeRole", "muted")
        brand_text.addWidget(name)
        brand_text.addWidget(subtitle)
        brand.addLayout(brand_text, 1)
        layout.addLayout(brand)
        layout.addSpacing(16)

        self.nav_buttons = {}

        def add_nav(key, text, handler):
            button = QPushButton(text)
            button.setMinimumHeight(38)
            button.setIcon(tool_icon(key))
            button.setIconSize(QSize(18, 18))
            button.setProperty("variant", "homeNav")
            button.clicked.connect(handler)
            layout.addWidget(button)
            self.nav_buttons[key] = button

        add_nav("home", "工作台", self.show_home)
        add_nav("excel", "Excel 合并", self.show_excel_tool)
        add_nav("split", "Excel 拆分", self.show_split_tool)
        add_nav("cleanup", "Excel 数据清理", self.show_cleanup_tool)
        add_nav("invoice", "发票解析", self.show_invoice_tool)
        add_nav("document", "文档处理", self.show_document_tool)
        add_nav("batch", "批量处理", self.show_batch_tool)
        add_nav("rename", "批量改名", self.show_rename_tool)
        add_nav("pdf", "PDF 工具箱", self.show_pdf_tool)
        layout.addStretch(1)

        version_suffix = {"development": "开发版", "release_candidate": "发布候选版"}.get(BUILD_TYPE, "")
        version = QLabel(f"版本 {APP_VERSION}（{BUILD_NUMBER}）")
        version.setProperty("homeRole", "muted")
        layout.addWidget(version)
        if version_suffix:
            release_type = QLabel(version_suffix)
            release_type.setProperty("homeRole", "muted")
            layout.addWidget(release_type)
        self.update_check_button = UpdateCheckButton(self)
        layout.addWidget(self.update_check_button)
        settings_button = QPushButton("设置")
        settings_button.setMinimumHeight(38)
        settings_button.setIcon(tool_icon("settings"))
        settings_button.setProperty("variant", "homeNav")
        settings_button.clicked.connect(self.show_settings)
        layout.addWidget(settings_button)
        return sidebar

    def create_home_page(self):
        page = QWidget(); page.setObjectName("homePage")
        root = QVBoxLayout(page); self.home_layout = root
        root.setContentsMargins(28, 24, 28, 24); root.setSpacing(12)
        self.home_title_label = QLabel("工作台"); self.home_title_label.setProperty("role", "title")
        self.home_subtitle_label = QLabel("选择工具，开始处理文件"); self.home_subtitle_label.setProperty("role", "subtitle")
        root.addWidget(self.home_title_label); root.addWidget(self.home_subtitle_label); root.addSpacing(12)
        panel = QWidget(); panel.setProperty("homePanel", "true")
        panel.setAttribute(Qt.WA_StyledBackground, True)
        self.home_grid = QGridLayout(panel); self.home_grid.setContentsMargins(16, 8, 16, 8)
        self.home_grid.setHorizontalSpacing(24); self.home_grid.setVerticalSpacing(0)
        self.home_tool_buttons = []; self.home_tool_cards = []
        specs = [
            ("excel", "Excel 合并", "按顺序合并多个表格", self.show_excel_tool),
            ("split", "Excel 拆分", "按固定行数或指定列分类拆分", self.show_split_tool),
            ("cleanup", "数据清理", "先预览变化，再清理并另存", self.show_cleanup_tool),
            ("invoice", "发票解析", "提取发票信息，每份另存为 Excel", self.show_invoice_tool),
            ("document", "文档处理", "识别 PDF 并生成对应结果", self.show_document_tool),
            ("batch", "批量处理", "逐个处理文件夹中的 PDF", self.show_batch_tool),
            ("rename", "批量改名", "先核对新名称，再执行改名", self.show_rename_tool),
            ("pdf", "PDF 工具箱", "整理页面、脱敏、水印与转换", self.show_pdf_tool),
        ]
        for index, spec in enumerate(specs):
            entry = ToolEntry(*spec)
            self.home_grid.addWidget(entry, index // 2, index % 2)
            self.home_tool_buttons.append(entry); self.home_tool_cards.append(entry)
        root.addWidget(panel); root.addStretch(1)
        return page

    def update_home_responsive_layout(self):
        if not hasattr(self, "home_logo_label"):
            return

        height = max(self.home_page.height(), self.height())
        logo_size = 32
        if not self.home_logo_pixmap.isNull():
            self.home_logo_label.setPixmap(
                self.home_logo_pixmap.scaled(
                    QSize(logo_size, logo_size),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )
        self.home_logo_label.setFixedSize(logo_size, logo_size)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_home_responsive_layout()

    def set_active_navigation(self, active_key):
        for key, button in self.nav_buttons.items():
            button.setProperty(
                "variant",
                "homeNavActive" if key == active_key else "homeNav",
            )
            button.style().unpolish(button)
            button.style().polish(button)

    def show_home(self):
        self.stack.setCurrentWidget(self.home_page)
        self.set_active_navigation("home")
        self.setWindowTitle(self.app_name)

    def show_excel_tool(self):
        self.stack.setCurrentWidget(self.excel_page)
        self.set_active_navigation("excel")
        self.setWindowTitle(f"{self.app_name} - Excel 合并工具")

    def show_split_tool(self):
        self.stack.setCurrentWidget(self.split_page)
        self.set_active_navigation("split")
        self.setWindowTitle(f"{self.app_name} - Excel 拆分工具")

    def show_cleanup_tool(self):
        self.stack.setCurrentWidget(self.cleanup_page)
        self.set_active_navigation("cleanup")
        self.setWindowTitle(f"{self.app_name} - Excel 数据清理")

    def show_invoice_tool(self):
        self.stack.setCurrentWidget(self.invoice_page)
        self.set_active_navigation("invoice")
        self.setWindowTitle(f"{self.app_name} - PDF发票解析工具")

    def show_document_tool(self):
        self.stack.setCurrentWidget(self.document_page)
        self.set_active_navigation("document")
        self.setWindowTitle(f"{self.app_name} - 文档智能处理")

    def show_batch_tool(self):
        self.stack.setCurrentWidget(self.batch_page)
        self.set_active_navigation("batch")
        self.setWindowTitle(f"{self.app_name} - 批量处理中心")

    def show_rename_tool(self):
        self.stack.setCurrentWidget(self.rename_page)
        self.set_active_navigation("rename")
        self.setWindowTitle(f"{self.app_name} - 批量改名工具")

    def show_pdf_tool(self):
        self.stack.setCurrentWidget(self.pdf_page)
        self.set_active_navigation("pdf")
        self.setWindowTitle(f"{self.app_name} - PDF 工具箱")

    def show_settings(self, initial_provider=None):
        if initial_provider not in PROVIDER_LABELS:
            initial_provider = selected_provider()
        accent_options = [
            (key, palette["label"])
            for key, palette in ACCENT_PALETTES.items()
        ]
        dialog = SoftwareSettingsDialog(
            initial_provider,
            accent_options,
            self.accent_name,
            self,
        )
        dialog.setStyleSheet(self.styleSheet())
        dialog.accent_changed.connect(self.save_accent_setting)
        if dialog.exec() == QDialog.Accepted:
            try:
                select_provider(dialog.selected_provider)
            except OSError as error:
                QMessageBox.warning(self, "无法保存选择", str(error))
        provider = selected_provider()
        index = self.document_ocr_provider_combo.findData(provider)
        if index >= 0:
            self.document_ocr_provider_combo.setCurrentIndex(index)
        batch_index = self.batch_ocr_provider_combo.findData(provider)
        if batch_index >= 0:
            self.batch_ocr_provider_combo.setCurrentIndex(batch_index)
        smart_index = self.rename_smart_provider_combo.findData(provider)
        if smart_index >= 0:
            self.rename_smart_provider_combo.setCurrentIndex(smart_index)
        searchable_index = self.pdf_searchable_provider_combo.findData(provider)
        if searchable_index >= 0:
            self.pdf_searchable_provider_combo.setCurrentIndex(searchable_index)
        self.refresh_document_ocr_status()

    def save_accent_setting(self, accent_name):
        if accent_name not in ACCENT_PALETTES:
            return
        self.accent_name = accent_name
        self.settings.setValue("appearance/warm-accent", self.accent_name)
        self.settings.sync()
        self.apply_theme()

    def dialog_folder(self, key, fallback=""):
        downloads = str(Path.home() / "Downloads")
        for candidate in (self.settings.value(f"dialogs/{key}", ""), fallback, downloads):
            if not candidate:
                continue
            path = Path(str(candidate)).expanduser()
            if path.exists() and path.is_file():
                path = path.parent
            elif not path.exists() and path.parent.exists():
                path = path.parent
            if path.exists() and path.is_dir():
                return str(path)
        return downloads

    def remember_dialog_folder(self, key, selected_path):
        if not selected_path:
            return
        path = Path(str(selected_path)).expanduser()
        if path.exists() and path.is_file():
            path = path.parent
        elif not path.exists() and path.parent.exists():
            path = path.parent
        if path.exists() and path.is_dir():
            self.settings.setValue(f"dialogs/{key}", str(path.resolve()))
            self.settings.sync()

    def apply_theme(self):
        colors = build_theme_colors(self.accent_name)
        self.setStyleSheet(build_theme_stylesheet(colors))
