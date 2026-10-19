ACCENT_PALETTES = {
    "cyan": {
        "label": "苹果蓝",
        "accent": "#007AFF",
        "accent_hover": "#006FE8",
        "accent_pressed": "#005FCC",
        "accent_soft_dark": "#DCEEFF",
        "accent_border_dark": "#9CCBFF",
        "primary": "#007AFF",
        "primary_hover": "#006FE8",
        "primary_pressed": "#005FCC",
    },
    "green": {
        "label": "薄荷绿",
        "accent": "#34C759",
        "accent_hover": "#28B84B",
        "accent_pressed": "#209E3F",
        "accent_soft_dark": "#E4F8EA",
        "accent_border_dark": "#A9E5B8",
        "primary": "#34C759",
        "primary_hover": "#28B84B",
        "primary_pressed": "#209E3F",
    },
    "blue": {
        "label": "海湾蓝",
        "accent": "#0A84FF",
        "accent_hover": "#0071E3",
        "accent_pressed": "#0060C9",
        "accent_soft_dark": "#E4F1FF",
        "accent_border_dark": "#A8D2FF",
        "primary": "#0A84FF",
        "primary_hover": "#0071E3",
        "primary_pressed": "#0060C9",
    },
    "purple": {
        "label": "鸢尾紫",
        "accent": "#AF52DE",
        "accent_hover": "#9B43C8",
        "accent_pressed": "#8436AD",
        "accent_soft_dark": "#F4E8FB",
        "accent_border_dark": "#D8A7EF",
        "primary": "#AF52DE",
        "primary_hover": "#9B43C8",
        "primary_pressed": "#8436AD",
    },
}

ACCENT_SOFT_COLORS = {
    "cyan": "#E8F3FF",
    "green": "#ECF9F0",
    "blue": "#EAF4FF",
    "purple": "#F6EAFE",
}

THEME_BASES = {
    "dark": {  # legacy key retained for callers
        "window_bg": "#F6F5F1", "panel": "#FFFEFA", "panel_alt": "#EEEDE7",
        "panel_hover": "#F0F0E9", "text": "#343C37", "title": "#252D29",
        "muted": "#747D75", "placeholder": "#9A9F98", "border": "#DCDDD5",
        "border_soft": "#E9E9E2", "table_header": "#F0F0EA", "table_row": "#FFFEFA",
        "table_row_alt": "#F8F8F3", "input": "#FFFFFF", "disabled_bg": "#EEEFE8",
        "disabled_text": "#9A9F98", "danger_bg": "#FFFEFA", "danger_text": "#AC4D43",
        "danger_border": "#E8DAD4", "shadow": "transparent",
    }
}
ACCENT_PALETTES["green"].update(label="森林绿", accent="#335C4F", accent_hover="#294E42",
    accent_pressed="#214135", primary="#335C4F", primary_hover="#294E42", primary_pressed="#214135")
ACCENT_SOFT_COLORS["green"] = "#E5ECE5"


def build_theme_colors(accent_name):
    colors = THEME_BASES["dark"].copy()
    accent = ACCENT_PALETTES.get(accent_name, ACCENT_PALETTES["green"])
    colors.update(accent)
    colors["accent_soft"] = ACCENT_SOFT_COLORS.get(accent_name, "#E5ECE5")
    colors["accent_border"] = accent["accent"]
    return colors


def build_theme_stylesheet(c):
    return f"""
    QWidget {{ font-family: "PingFang SC", "Microsoft YaHei"; font-size: 13px; color: {c['text']}; }}
    QMainWindow, QDialog, QWidget#appShell, QWidget#homePage,
    QWidget#excelPage, QWidget#splitPage, QWidget#cleanupPage,
    QWidget#invoicePage, QWidget#documentPage, QWidget#batchPage,
    QWidget#pdfPage, QWidget#renamePage, QWidget#categorySplitPage {{
        background: {c['window_bg']}; color: {c['text']};
        font-family: "PingFang SC", "Microsoft YaHei"; font-size: 13px;
    }}
    QLabel {{ color: {c['text']}; background: transparent; }}
    QLabel[role="title"], QLabel[homeRole="title"] {{ color: {c['title']}; font-size: 24px; font-weight: 600; }}
    QLabel[role="subtitle"], QLabel[role="hint"], QLabel[homeRole="muted"] {{ color: {c['muted']}; font-size: 12px; }}
    QLabel[role="status"] {{ color: {c['primary']}; font-size: 12px; }}
    QLabel[homeRole="brand"] {{ font-size: 15px; font-weight: 600; }}
    QLabel[homeRole="cardTitle"], QLabel[splitHeading="true"] {{ color: {c['title']}; font-size: 16px; font-weight: 600; }}
    QLabel[homeRole="section"] {{ color: {c['muted']}; font-size: 12px; }}
    QWidget#homeSidebar {{ background: #EAEAE3; border-right: 1px solid {c['border']}; }}
    QWidget[homePanel="true"], QFrame[splitCard="true"] {{ background: {c['panel']}; border: 1px solid {c['border_soft']}; border-radius: 6px; }}
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QGroupBox {{ background: {c['panel']}; border: 1px solid {c['border_soft']}; border-radius: 6px;
        margin-top: 20px; padding-top: 8px; color: {c['text']}; }}
    QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 0px; padding: 0px; font-weight: 600; color: {c['title']}; }}
    QTreeWidget, QTableWidget, QListWidget {{ background: {c['table_row']}; alternate-background-color: {c['table_row_alt']};
        color: {c['text']}; border: 1px solid {c['border_soft']}; border-radius: 5px; font-size: 13px;
        selection-background-color: {c['accent_soft']}; selection-color: {c['title']}; }}
    QTreeWidget::item {{ height: 34px; border-bottom: 1px solid {c['border_soft']}; }}
    QListWidget::item {{ padding: 6px; }}
    QTreeWidget::item:selected, QListWidget::item:selected {{ background: {c['accent_soft']}; color: {c['title']}; }}
    QHeaderView::section {{ background: {c['table_header']}; color: {c['muted']}; border: none;
        border-bottom: 1px solid {c['border']}; padding: 9px 8px; font-size: 12px; font-weight: 500; }}
    QLineEdit, QComboBox, QSpinBox {{ background: {c['input']}; color: {c['text']}; border: 1px solid {c['border']};
        border-radius: 5px; padding: 6px 10px; min-height: 22px; selection-background-color: {c['accent_soft']}; selection-color: {c['title']}; }}
    QLineEdit:read-only {{ color: {c['muted']}; background: {c['panel']}; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {c['accent']}; }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: {c['disabled_text']}; background: {c['disabled_bg']}; }}
    QComboBox {{ padding-right: 28px; }}
    QComboBox::drop-down {{ width: 26px; border: none; }}
    QComboBox QAbstractItemView {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; selection-background-color: {c['accent_soft']}; selection-color: {c['title']}; }}
    QSpinBox {{ padding-right: 26px; }}
    QSpinBox::up-button, QSpinBox::down-button {{ subcontrol-origin: border; width: 24px; border-left: 1px solid {c['border_soft']}; }}
    QSpinBox::up-button {{ subcontrol-position: top right; }}
    QSpinBox::down-button {{ subcontrol-position: bottom right; }}
    QSpinBox::up-arrow, QSpinBox::down-arrow {{ image: none; width: 0; height: 0; }}
    QCheckBox {{ color: {c['text']}; spacing: 7px; }}
    QPushButton {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']};
        border-radius: 5px; padding: 6px 12px; font-size: 13px; font-weight: 500; }}
    QPushButton:hover {{ background: {c['panel_hover']}; border-color: {c['accent']}; }}
    QPushButton:pressed, QPushButton:checked {{ background: {c['accent_soft']}; color: {c['primary']}; }}
    QPushButton[variant="primary"] {{ background: {c['primary']}; color: white; border-color: {c['primary']}; padding: 7px 20px; font-weight: 600; }}
    QPushButton[variant="primary"]:hover {{ background: {c['primary_hover']}; }}
    QPushButton[variant="mode"] {{ background: {c['accent_soft']}; color: {c['primary']};
        padding: 7px 20px; font-weight: 600; border: 1px solid {c['border']}; }}
    QPushButton[variant="mode"]:checked {{ background: {c['primary']}; color: white; border-color: {c['primary']}; }}
    QPushButton[variant="mode"]:checked:hover {{ background: {c['primary_hover']}; }}
    QPushButton[variant="accent"] {{ background: {c['accent_soft']}; color: {c['primary']}; border-color: {c['border']}; }}
    QPushButton[variant="danger"] {{ color: {c['danger_text']}; background: {c['panel']}; border-color: {c['danger_border']}; }}
    QPushButton:disabled, QPushButton[variant="primary"]:disabled, QPushButton[variant="accent"]:disabled,
    QPushButton[variant="danger"]:disabled {{ color: {c['disabled_text']}; background: {c['disabled_bg']}; border-color: {c['border_soft']}; }}
    QPushButton[variant="homeNav"], QPushButton[variant="homeNavActive"], QPushButton[variant="disclosure"] {{
        background: transparent; text-align: left; border: none; padding: 8px 12px; font-size: 13px; }}
    QPushButton[variant="homeNav"]:hover, QPushButton[variant="disclosure"]:hover {{ background: {c['panel_hover']}; }}
    QPushButton[variant="homeNavActive"] {{ background: {c['accent_soft']}; color: {c['primary']}; border-left: 3px solid {c['primary']}; font-weight: 600; }}
    QPushButton[variant="toolEntry"] {{ background: transparent; border: 1px solid transparent; border-bottom-color: {c['border_soft']}; border-radius: 0; padding: 0; text-align: left; }}
    QPushButton[variant="toolEntry"]:focus {{ border-color: {c['primary']}; }}
    QPushButton[variant="toolEntry"]:hover {{ background: {c['accent_soft']}; }}
    QTabWidget::pane {{ background: transparent; border: none; border-top: 1px solid {c['border']}; }}
    QTabWidget::tab-bar {{ alignment: left; }}
    QTabBar::tab {{ background: transparent; color: {c['muted']}; border: none; border-bottom: 2px solid transparent; padding: 10px 16px; }}
    QTabBar::tab:selected {{ color: {c['primary']}; border-bottom-color: {c['primary']}; font-weight: 600; }}
    QTabBar::tab:hover {{ background: {c['panel_hover']}; }}
    QLabel[splitStep="true"] {{ padding: 8px 12px; color: {c['muted']}; font-size: 12px; border-bottom: 1px solid {c['border_soft']}; }}
    QLabel[splitStep="true"][active="true"] {{ color: {c['primary']}; border-bottom: 2px solid {c['primary']}; font-weight: 600; }}
    QLabel[splitMetric="true"] {{ color: {c['primary']}; padding: 4px 0; font-size: 14px; font-weight: 600; }}
    QWidget[pdfCard="true"] {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 5px; }}
    QWidget[pdfCard="true"][checked="true"] {{ background: {c['accent_soft']}; border-color: {c['primary']}; }}
    QWidget[pdfCard="true"][dragging="true"] {{ border: 2px solid {c['primary']}; }}
    QWidget#pdfThumbnailBox {{ background: white; border: 1px solid {c['border_soft']}; }}
    QLabel[pdfCardTitle="true"] {{ color: {c['title']}; font-size: 13px; font-weight: 600; }}
    QLabel[pdfCardName="true"] {{ color: {c['muted']}; font-size: 12px; }}
    QWidget#pdfWorkspace QToolBar {{ background: {c['panel']}; border: none; spacing: 2px; padding: 2px; }}
    QWidget#pdfWorkspace QToolButton {{ color: {c['text']}; background: transparent; border: none; border-radius: 4px; padding: 6px; font-size: 12px; }}
    QWidget#pdfWorkspace QToolButton:hover, QWidget#pdfWorkspace QToolButton:checked {{ background: {c['accent_soft']}; color: {c['primary']}; }}
    QWidget#pdfWorkspace QToolButton:disabled {{ color: {c['disabled_text']}; }}
    QProgressDialog, QMessageBox {{ background: {c['panel']}; color: {c['text']}; }}
    """


__all__ = ["ACCENT_PALETTES", "build_theme_colors", "build_theme_stylesheet"]
