ACCENT_PALETTES = {
    "cyan": {
        "label": "科技蓝",
        "accent": "#3B9DFF",
        "accent_hover": "#2389F0",
        "accent_pressed": "#1675D1",
        "accent_soft_dark": "#0E2B36",
        "accent_border_dark": "#164E63",
        "primary": "#3198F5",
        "primary_hover": "#2389F0",
        "primary_pressed": "#1675D1",
    },
    "green": {
        "label": "翡翠绿",
        "accent": "#34D399",
        "accent_hover": "#10B981",
        "accent_pressed": "#059669",
        "accent_soft_dark": "#0F2F26",
        "accent_border_dark": "#166534",
        "primary": "#10B981",
        "primary_hover": "#059669",
        "primary_pressed": "#047857",
    },
    "blue": {
        "label": "深蓝",
        "accent": "#60A5FA",
        "accent_hover": "#3B82F6",
        "accent_pressed": "#2563EB",
        "accent_soft_dark": "#172B4E",
        "accent_border_dark": "#1D4ED8",
        "primary": "#3B82F6",
        "primary_hover": "#2563EB",
        "primary_pressed": "#1D4ED8",
    },
    "purple": {
        "label": "紫色",
        "accent": "#A78BFA",
        "accent_hover": "#8B5CF6",
        "accent_pressed": "#7C3AED",
        "accent_soft_dark": "#2E2453",
        "accent_border_dark": "#6D28D9",
        "primary": "#8B5CF6",
        "primary_hover": "#7C3AED",
        "primary_pressed": "#6D28D9",
    },
}

ACCENT_SOFT_COLORS = {
    "cyan": "#E8F3FF",
    "green": "#EEF7F1",
    "blue": "#EFF6FF",
    "purple": "#F3E8FF",
}

THEME_BASES = {
    "dark": {
        "window_bg": "#FFFFFF",
        "panel": "#FFFFFF",
        "panel_alt": "#F5F5F6",
        "panel_hover": "#ECEFF2",
        "text": "#50555C",
        "title": "#202327",
        "muted": "#8A8F96",
        "placeholder": "#A1A6AD",
        "border": "#DFE2E6",
        "border_soft": "#EAECF0",
        "table_header": "#F3F4F6",
        "table_row": "#FFFFFF",
        "table_row_alt": "#FAFBFC",
        "input": "#FFFFFF",
        "disabled_bg": "#EEF2F5",
        "disabled_text": "#A0AAB6",
        "danger_bg": "#FFF1F2",
        "danger_text": "#BE123C",
        "danger_border": "#FDA4AF",
        "shadow": "rgba(15, 23, 42, 24)",
    },
}


def build_theme_colors(accent_name):
    base = THEME_BASES["dark"].copy()
    accent = ACCENT_PALETTES.get(accent_name, ACCENT_PALETTES["cyan"])
    base.update(
        {
            "accent": accent["accent"],
            "accent_hover": accent["accent_hover"],
            "accent_pressed": accent["accent_pressed"],
            "accent_soft": ACCENT_SOFT_COLORS.get(accent_name, "#E8F4F4"),
            "accent_border": accent["primary"],
            "primary": accent["primary"],
            "primary_hover": accent["primary_hover"],
            "primary_pressed": accent["primary_pressed"],
        }
    )
    return base


def build_theme_stylesheet(colors):
    return f"""
    QMainWindow {{
        background: {colors["window_bg"]};
        color: {colors["text"]};
    }}
    QWidget#appShell {{
        background: {colors["window_bg"]};
    }}
    QWidget#homePage,
    QWidget#excelPage,
    QWidget#splitPage,
    QWidget#invoicePage,
    QWidget#documentPage,
    QWidget#pdfPage,
    QWidget#renamePage {{
        background: {colors["window_bg"]};
        color: {colors["text"]};
    }}
    QLabel {{
        color: {colors["text"]};
    }}
    QLabel[role="title"] {{
        color: {colors["title"]};
        font-size: 26px;
        font-weight: 700;
    }}
    QLabel[role="subtitle"],
    QLabel[role="hint"] {{
        color: {colors["muted"]};
        font-size: 13px;
    }}
    QLabel[role="status"] {{
        color: {colors["accent"]};
        font-size: 12px;
    }}
    QScrollArea {{
        background: transparent;
        border: none;
    }}
    QScrollArea > QWidget > QWidget {{
        background: transparent;
    }}
    QGroupBox {{
        background: {colors["panel"]};
        border: 1px solid {colors["border"]};
        border-radius: 12px;
        margin-top: 12px;
        padding-top: 12px;
        color: {colors["text"]};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 8px;
        color: {colors["title"]};
        font-weight: 600;
        background: {colors["panel"]};
    }}
    QTreeWidget {{
        background: {colors["table_row"]};
        alternate-background-color: {colors["table_row_alt"]};
        color: {colors["text"]};
        border: 1px solid {colors["border"]};
        border-radius: 10px;
        font-size: 13px;
        selection-background-color: {colors["accent"]};
        selection-color: #FFFFFF;
    }}
    QTreeWidget::item {{
        height: 34px;
        border-bottom: 1px solid {colors["border_soft"]};
    }}
    QTreeWidget::item:selected {{
        background: {colors["accent"]};
        color: #FFFFFF;
    }}
    QTreeWidget::indicator {{
        width: 18px;
        height: 18px;
        border-radius: 5px;
        border: 1px solid {colors["border"]};
        background: {colors["input"]};
    }}
    QTreeWidget::indicator:checked {{
        background: {colors["accent"]};
        border: 1px solid {colors["accent"]};
    }}
    QTreeWidget::indicator:unchecked:selected {{
        background: {colors["input"]};
        border: 1px solid #FFFFFF;
    }}
    QTreeWidget::indicator:checked:selected {{
        background: #FFFFFF;
        border: 1px solid #FFFFFF;
    }}
    QWidget[pdfCard="true"] {{
        background: {colors["table_row"]};
        border: 1px solid {colors["border_soft"]};
        border-radius: 8px;
    }}
    QWidget[pdfCard="true"][checked="true"] {{
        background: {colors["accent_soft"]};
        border: 1px solid {colors["accent"]};
    }}
    QWidget[pdfCard="true"][dragging="true"] {{
        border: 2px solid {colors["accent"]};
    }}
    QWidget#pdfThumbnailBox {{
        background: #FFFFFF;
        border: 1px solid {colors["border_soft"]};
        border-radius: 6px;
    }}
    QLabel[pdfCardTitle="true"] {{
        color: {colors["title"]};
        font-size: 13px;
        font-weight: 600;
    }}
    QLabel[pdfCardName="true"] {{
        color: {colors["text"]};
        font-size: 12px;
    }}
    QTabWidget::pane {{
        border: 1px solid {colors["border"]};
        border-radius: 10px;
        background: {colors["panel"]};
    }}
    QTabBar::tab {{
        background: {colors["panel_alt"]};
        color: {colors["text"]};
        padding: 8px 14px;
        border: 1px solid {colors["border"]};
        border-bottom: none;
    }}
    QTabBar::tab:selected {{
        background: {colors["accent_soft"]};
        color: {colors["title"]};
    }}
    QHeaderView::section {{
        background: {colors["table_header"]};
        color: {colors["text"]};
        border: none;
        border-right: 1px solid {colors["border"]};
        border-bottom: 1px solid {colors["border"]};
        padding: 8px;
        font-weight: 600;
    }}
    QLineEdit,
    QComboBox,
    QSpinBox {{
        background: {colors["input"]};
        color: {colors["text"]};
        border: 1px solid {colors["border"]};
        border-radius: 8px;
        padding: 6px 10px;
        min-height: 24px;
    }}
    QSpinBox {{
        padding-right: 34px;
    }}
    QSpinBox::up-button,
    QSpinBox::down-button {{
        subcontrol-origin: border;
        width: 30px;
        background: {colors["panel_alt"]};
        border-left: 1px solid {colors["border"]};
    }}
    QSpinBox::up-button {{
        subcontrol-position: top right;
        border-bottom: 1px solid {colors["border"]};
        border-top-right-radius: 8px;
    }}
    QSpinBox::down-button {{
        subcontrol-position: bottom right;
        border-bottom-right-radius: 8px;
    }}
    QSpinBox::up-button:hover,
    QSpinBox::down-button:hover {{
        background: {colors["accent_soft"]};
    }}
    QSpinBox::up-arrow,
    QSpinBox::down-arrow {{
        image: none;
        width: 0;
        height: 0;
    }}
    QLineEdit:focus,
    QComboBox:focus,
    QSpinBox:focus {{
        border: 1px solid {colors["accent"]};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 30px;
    }}
    QComboBox QAbstractItemView {{
        background: {colors["panel"]};
        color: {colors["text"]};
        border: 1px solid {colors["border"]};
        selection-background-color: {colors["accent"]};
        selection-color: white;
    }}
    QLineEdit:read-only {{
        color: {colors["muted"]};
    }}
    QCheckBox {{
        color: {colors["text"]};
        spacing: 8px;
    }}
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border-radius: 5px;
        border: 1px solid {colors["border"]};
        background: {colors["input"]};
    }}
    QCheckBox::indicator:checked {{
        background: {colors["accent"]};
        border: 1px solid {colors["accent"]};
    }}
    QPushButton {{
        background: {colors["panel"]};
        color: {colors["text"]};
        border: 1px solid {colors["border"]};
        border-radius: 9px;
        padding: 7px 14px;
        font-weight: 500;
    }}
    QPushButton:hover {{
        background: {colors["panel_hover"]};
        border-color: {colors["accent_border"]};
    }}
    QPushButton:pressed {{
        background: {colors["accent_soft"]};
    }}
    QPushButton:disabled {{
        background: {colors["disabled_bg"]};
        color: {colors["disabled_text"]};
        border: 1px solid {colors["border_soft"]};
    }}
    QPushButton[compactToolbar="true"] {{
        padding: 7px 9px;
    }}
    QPushButton[variant="primary"] {{
        background: {colors["primary"]};
        color: #FFFFFF;
        border: 1px solid {colors["primary"]};
        border-radius: 12px;
        font-weight: 700;
        padding: 9px 30px;
    }}
    QPushButton[variant="primary"]:hover {{
        background: {colors["primary_hover"]};
        border-color: {colors["primary_hover"]};
    }}
    QPushButton[variant="primary"]:pressed {{
        background: {colors["primary_pressed"]};
        border-color: {colors["primary_pressed"]};
    }}
    QPushButton[variant="accent"] {{
        background: {colors["accent_soft"]};
        color: {colors["accent"]};
        border: 1px solid {colors["accent_border"]};
        font-weight: 600;
    }}
    QPushButton[variant="danger"] {{
        background: {colors["danger_bg"]};
        color: {colors["danger_text"]};
        border: 1px solid {colors["danger_border"]};
    }}
    QPushButton[variant="ghost"] {{
        background: transparent;
        color: {colors["text"]};
        border: 1px solid {colors["border"]};
    }}
    QPushButton[variant="toolCardPrimary"] {{
        background: {colors["primary"]};
        color: #FFFFFF;
        border: 1px solid {colors["primary"]};
        border-radius: 14px;
        font-weight: 700;
    }}
    QPushButton[variant="toolCardPrimary"]:hover {{
        background: {colors["primary_hover"]};
        border-color: {colors["primary_hover"]};
    }}
    QPushButton[variant="toolCardEmpty"] {{
        background: {colors["panel_alt"]};
        color: {colors["muted"]};
        border: 1px dashed {colors["border"]};
        border-radius: 14px;
    }}
    QPushButton[variant="primary"]:disabled,
    QPushButton[variant="accent"]:disabled,
    QPushButton[variant="danger"]:disabled,
    QPushButton[variant="ghost"]:disabled {{
        background: {colors["disabled_bg"]};
        color: {colors["disabled_text"]};
        border: 1px solid {colors["border_soft"]};
    }}
    QPushButton[variant="toolCardEmpty"]:disabled {{
        background: {colors["panel_alt"]};
        color: {colors["muted"]};
        border: 1px dashed {colors["border"]};
    }}
    QWidget#homePage {{
        background: {colors["window_bg"]};
        color: {colors["title"]};
    }}
    QWidget#homeSidebar {{
        background: {colors["panel_alt"]};
        border-right: 1px solid {colors["border"]};
    }}
    QWidget#homeMain {{
        background: {colors["window_bg"]};
    }}
    QWidget[homePanel="true"],
    QWidget[homeCard="true"] {{
        background: {colors["panel_alt"]};
        border: 1px solid {colors["border"]};
        border-radius: 12px;
    }}
    QWidget[homeStatus="true"] {{
        background: {colors["accent_soft"]};
        border-left: 4px solid {colors["primary"]};
    }}
    QWidget[homeHero="true"] {{
        background: {colors["accent_soft"]};
        border-left: 4px solid {colors["primary"]};
    }}
    QWidget[homeCard="true"]:hover {{
        border: 1px solid {colors["primary"]};
    }}
    QLabel[homeRole="title"] {{
        color: {colors["title"]};
        font-size: 32px;
        font-weight: 700;
    }}
    QLabel[homeRole="section"] {{
        color: {colors["title"]};
        font-size: 22px;
        font-weight: 700;
    }}
    QLabel[homeRole="cardTitle"] {{
        color: {colors["title"]};
        font-size: 18px;
        font-weight: 700;
    }}
    QLabel[homeRole="brand"] {{
        color: {colors["title"]};
        font-size: 15px;
        font-weight: 700;
    }}
    QLabel[homeRole="body"] {{
        color: {colors["text"]};
        font-size: 14px;
    }}
    QLabel[homeRole="muted"] {{
        color: {colors["muted"]};
        font-size: 13px;
    }}
    QPushButton[variant="homeNav"] {{
        background: transparent;
        color: {colors["text"]};
        border: none;
        border-radius: 10px;
        padding: 10px 14px;
        text-align: left;
        font-size: 15px;
        font-weight: 500;
    }}
    QPushButton[variant="homeNav"]:hover {{
        background: {colors["panel_hover"]};
        color: {colors["primary"]};
    }}
    QPushButton[variant="homeNavActive"] {{
        background: {colors["primary"]};
        color: #FFFFFF;
        border: none;
        border-radius: 10px;
        padding: 10px 14px;
        text-align: left;
        font-size: 15px;
        font-weight: 700;
    }}
    QPushButton[variant="homeOpen"] {{
        background: {colors["panel_alt"]};
        color: {colors["title"]};
        border: 1px solid {colors["border"]};
        border-radius: 9px;
        padding: 7px 16px;
        font-weight: 600;
    }}
    QPushButton[variant="homeOpen"]:hover {{
        background: {colors["accent_soft"]};
        border-color: {colors["primary"]};
        color: {colors["primary"]};
    }}
    QPushButton[variant="homePrimary"] {{
        background: {colors["primary"]};
        color: #FFFFFF;
        border: 1px solid {colors["primary"]};
        border-radius: 9px;
        padding: 8px 18px;
        font-weight: 700;
    }}
    QPushButton[variant="homeGhost"] {{
        background: {colors["panel"]};
        color: {colors["title"]};
        border: 1px solid {colors["border"]};
        border-radius: 9px;
        padding: 8px 18px;
        font-weight: 600;
    }}
    QProgressDialog {{
        background: {colors["panel"]};
        color: {colors["text"]};
    }}
    QMessageBox {{
        background: {colors["panel"]};
        color: {colors["text"]};
    }}
    """


__all__ = [
    "ACCENT_PALETTES",
    "build_theme_colors",
    "build_theme_stylesheet",
]
