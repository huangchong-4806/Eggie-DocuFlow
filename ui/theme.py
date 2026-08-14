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
    "dark": {
        "window_bg": "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #E1F3FF, stop:0.46 #8BC6EF, stop:1 #D7EEFC)",
        "panel": "rgba(255, 255, 255, 158)",
        "panel_alt": "rgba(255, 255, 255, 92)",
        "panel_hover": "rgba(255, 255, 255, 210)",
        "text": "#30465C",
        "title": "#10243A",
        "muted": "#5F7489",
        "placeholder": "#A3ACBA",
        "border": "rgba(255, 255, 255, 135)",
        "border_soft": "rgba(255, 255, 255, 78)",
        "table_header": "rgba(255, 255, 255, 160)",
        "table_row": "rgba(255, 255, 255, 196)",
        "table_row_alt": "rgba(255, 255, 255, 150)",
        "input": "rgba(255, 255, 255, 210)",
        "disabled_bg": "rgba(217, 229, 242, 168)",
        "disabled_text": "#8FA0B2",
        "danger_bg": "#FFF1F2",
        "danger_text": "#D92D20",
        "danger_border": "#FDA29B",
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
        font-family: "PingFang SC", "Microsoft YaHei";
    }}
    QWidget#appShell {{
        background: {colors["window_bg"]};
    }}
    QWidget#homePage,
    QWidget#excelPage,
    QWidget#splitPage,
    QWidget#cleanupPage,
    QWidget#invoicePage,
    QWidget#documentPage,
    QWidget#batchPage,
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
        font-size: 28px;
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
        border-radius: 8px;
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
        border-radius: 8px;
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
        border-radius: 8px;
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
    QPushButton {{
        background: {colors["panel"]};
        color: {colors["text"]};
        border: 1px solid {colors["border"]};
        border-radius: 8px;
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
        border-radius: 8px;
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
        color: {colors["primary"]};
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
        background: rgba(15, 67, 108, 232);
        border-right: 1px solid rgba(255, 255, 255, 86);
    }}
    QWidget#homeMain {{
        background: {colors["window_bg"]};
    }}
    QWidget[homePanel="true"],
    QWidget[homeCard="true"] {{
        background: rgba(255, 255, 255, 126);
        border: 1px solid rgba(255, 255, 255, 168);
        border-radius: 8px;
    }}
    QWidget[homeStatus="true"] {{
        background: rgba(255, 255, 255, 112);
        border: 1px solid rgba(255, 255, 255, 128);
        border-radius: 8px;
    }}
    QWidget[homeHero="true"] {{
        background: rgba(55, 143, 222, 98);
        border: 1px solid rgba(255, 255, 255, 150);
        border-radius: 8px;
    }}
    QWidget[homeCard="true"]:hover {{
        border: 1px solid {colors["primary"]};
    }}
    QLabel[homeRole="title"] {{
        color: {colors["title"]};
        font-size: 34px;
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
        border-radius: 8px;
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
        background: {colors["accent_soft"]};
        color: {colors["primary"]};
        border: none;
        border-radius: 8px;
        padding: 10px 14px;
        text-align: left;
        font-size: 15px;
        font-weight: 700;
    }}
    QPushButton[variant="homeOpen"] {{
        background: rgba(255, 255, 255, 210);
        color: {colors["title"]};
        border: 1px solid {colors["border"]};
        border-radius: 8px;
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
    QWidget#homeSidebar QLabel[homeRole="brand"] {{
        color: #FFFFFF;
    }}
    QWidget#homeSidebar QLabel[homeRole="muted"] {{
        color: rgba(255, 255, 255, 178);
    }}
    QWidget#homeSidebar QPushButton[variant="homeNav"] {{
        background: transparent;
        color: rgba(255, 255, 255, 206);
    }}
    QWidget#homeSidebar QPushButton[variant="homeNav"]:hover {{
        background: rgba(255, 255, 255, 34);
        color: #FFFFFF;
    }}
    QWidget#homeSidebar QPushButton[variant="homeNavActive"] {{
        background: rgba(255, 255, 255, 48);
        color: #FFFFFF;
        border: 1px solid rgba(255, 255, 255, 92);
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
