"""Uygulama geneli görsel stil ve renk yardımcıları."""
from __future__ import annotations

from PyQt6.QtGui import QColor, QPalette

from app import config

PRIMARY = "#2c3e50"
PRIMARY_LIGHT = "#34495e"
ACCENT = "#2980b9"
BG = "#f4f6f8"
CARD = "#ffffff"
BORDER = "#dfe4ea"
TEXT = "#2f3640"
TEXT_MUTED = "#7f8c8d"

ALT_ROW = "#f7f9fa"


def light_palette() -> QPalette:
    """Açık renk paleti.

    Windows koyu tema açıkken Fusion stili sistem paletini koyu alır ve
    ekranlar okunmaz hale gelir. Uygulama tek bir açık temada çalıştığı için
    palet burada sabitlenir.
    """
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(CARD))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(ALT_ROW))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(CARD))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#d6eaf8"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(PRIMARY))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(TEXT_MUTED))

    disabled = QPalette.ColorGroup.Disabled
    palette.setColor(disabled, QPalette.ColorRole.Text, QColor("#b2bec3"))
    palette.setColor(disabled, QPalette.ColorRole.ButtonText, QColor("#b2bec3"))
    palette.setColor(disabled, QPalette.ColorRole.WindowText, QColor("#b2bec3"))
    return palette


STYLESHEET = f"""
QWidget {{
    font-family: "Segoe UI", "Noto Sans", sans-serif;
    font-size: 10pt;
    color: {TEXT};
}}
QMainWindow, QDialog, QStackedWidget, QScrollArea > QWidget > QWidget {{
    background: {BG};
}}

/* --- Sol menü --- */
#Sidebar {{ background: {PRIMARY}; }}
#SidebarTitle {{
    color: #ffffff; font-size: 13pt; font-weight: bold;
    padding: 18px 16px 4px 16px;
}}
#SidebarSubtitle {{
    color: #a9b7c6; font-size: 9pt; padding: 0 16px 14px 16px;
}}
#NavList {{
    background: {PRIMARY}; border: none; outline: none;
    color: #dfe6e9; font-size: 10.5pt;
}}
#NavList::item {{ padding: 12px 16px; border: none; }}
#NavList::item:selected {{ background: {ACCENT}; color: #ffffff; }}
#NavList::item:hover:!selected {{ background: {PRIMARY_LIGHT}; }}
#SidebarFooter {{ color: #8fa2b3; font-size: 8.5pt; padding: 10px 16px; }}

/* --- Başlıklar --- */
#PageTitle {{ font-size: 16pt; font-weight: bold; color: {PRIMARY}; }}
#PageSubtitle {{ color: {TEXT_MUTED}; font-size: 9.5pt; }}
#SectionTitle {{ font-size: 11pt; font-weight: bold; color: {PRIMARY}; }}

/* --- Kartlar --- */
#Card, #StatCard {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
#StatValue {{ font-size: 22pt; font-weight: bold; }}
#StatLabel {{ color: {TEXT_MUTED}; font-size: 9.5pt; }}

/* --- Tablolar --- */
QTableWidget, QTableView, QTreeWidget, QListWidget {{
    background: {CARD};
    alternate-background-color: {ALT_ROW};
    border: 1px solid {BORDER};
    border-radius: 6px;
    gridline-color: #eef1f4;
    selection-background-color: #d6eaf8;
    selection-color: {TEXT};
}}
#NavList {{ alternate-background-color: {PRIMARY}; }}
QHeaderView::section {{
    background: #eef2f5;
    color: {PRIMARY};
    padding: 8px 6px;
    border: none;
    border-right: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
    font-weight: bold;
}}
QTableWidget::item, QTableView::item {{ padding: 4px 6px; }}

/* --- Girdi alanları --- */
QLineEdit, QComboBox, QDateEdit, QTextEdit, QPlainTextEdit, QSpinBox {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 6px 8px;
    min-height: 18px;
}}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus,
QTextEdit:focus, QPlainTextEdit:focus {{ border: 1px solid {ACCENT}; }}
QLineEdit:disabled, QComboBox:disabled, QTextEdit:disabled {{
    background: #f0f2f5; color: {TEXT_MUTED};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}

/* --- Butonlar --- */
QPushButton {{
    background: {CARD};
    border: 1px solid #c8d0d8;
    border-radius: 5px;
    padding: 7px 16px;
    min-height: 18px;
}}
QPushButton:hover {{ background: #eaf2f8; border-color: {ACCENT}; }}
QPushButton:pressed {{ background: #d6eaf8; }}
QPushButton:disabled {{ background: #f0f2f5; color: #b2bec3; border-color: #dcdde1; }}
QPushButton#Primary {{
    background: {ACCENT}; color: #ffffff; border: none; font-weight: bold;
}}
QPushButton#Primary:hover {{ background: #2471a3; }}
QPushButton#Primary:disabled {{ background: #a9c9de; color: #f0f0f0; }}
QPushButton#Danger {{ background: #c0392b; color: #ffffff; border: none; }}
QPushButton#Danger:hover {{ background: #a93226; }}
QPushButton#Success {{ background: #27ae60; color: #ffffff; border: none; font-weight: bold; }}
QPushButton#Success:hover {{ background: #1e8449; }}
QPushButton#Link {{
    background: transparent; border: none; color: {ACCENT};
    text-decoration: underline; padding: 4px;
}}

/* --- Diğer --- */
QGroupBox {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 14px;
    padding: 12px 10px 10px 10px;
    font-weight: bold;
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 12px; padding: 0 6px; color: {PRIMARY};
}}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 6px; background: {CARD}; }}
QTabBar::tab {{
    background: #e8edf1; padding: 8px 18px; margin-right: 2px;
    border-top-left-radius: 6px; border-top-right-radius: 6px;
    color: {TEXT_MUTED};
}}
QTabBar::tab:selected {{ background: {CARD}; color: {PRIMARY}; font-weight: bold; }}
QStatusBar {{ background: {CARD}; border-top: 1px solid {BORDER}; color: {TEXT_MUTED}; }}
QScrollArea {{ border: none; background: {BG}; }}

QCheckBox {{ spacing: 7px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px;
    border: 1px solid #b8c2cc; border-radius: 3px; background: {CARD};
}}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{
    background: {ACCENT}; border-color: {ACCENT};
    image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxNiAxNiI+PHBhdGggZmlsbD0ibm9uZSIgc3Ryb2tlPSIjZmZmIiBzdHJva2Utd2lkdGg9IjIuNCIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBkPSJNMy41IDguNCA2LjQgMTEuMyAxMi41IDQuNiIvPjwvc3ZnPg==);
}}
QCheckBox::indicator:disabled {{ background: #eceff1; border-color: #d6dbe0; }}

QMenu {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 6px; padding: 4px; }}
QMenu::item {{ padding: 7px 22px 7px 16px; border-radius: 4px; }}
QMenu::item:selected {{ background: #eaf2f8; color: {PRIMARY}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}
QToolTip {{
    background: {PRIMARY}; color: #ffffff;
    border: none; padding: 6px; border-radius: 4px;
}}
"""


def status_color(status: str) -> QColor:
    return QColor(config.STATUS_COLORS.get(status, "#95a5a6"))


def priority_color(priority: str) -> QColor:
    return QColor(config.PRIORITY_COLORS.get(priority, "#95a5a6"))


def tint(color: QColor, alpha: int = 38) -> QColor:
    """Tablo hücresi arka planı için soluk ton."""
    c = QColor(color)
    c.setAlpha(alpha)
    return c


# --- Grafik renkleri ------------------------------------------------------
# Aşağıdaki setler erişilebilirlik doğrulayıcısından geçirilmiştir; değiştirirken
# renk körlüğü ayrımı ve zemin kontrastının yeniden kontrol edilmesi gerekir.

# Tek serili grafikler (örn. en çok arızalanan makineler).
CHART_SINGLE = "#2a78d6"

# İki serili çizgi grafiği (açılan / kapanan) - tüm çiftlerde ΔE >= 24.
CHART_SERIES = ["#2a78d6", "#eb6834"]

# Sıralı (ordinal) mavi rampa: açıktan koyuya. Öncelik ve durum dağılımları
# doğal olarak sıralı olduğu için kategorik palet yerine bu rampa kullanılır.
CHART_ORDINAL_4 = ["#86b6ef", "#3987e5", "#256abf", "#104281"]
CHART_ORDINAL_5 = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"]

# Grafik gövdesi ink renkleri.
CHART_SURFACE = "#ffffff"
CHART_GRID = "#e1e0d9"
CHART_AXIS = "#c3c2b7"
CHART_INK = "#2f3640"
CHART_INK_MUTED = "#898781"
