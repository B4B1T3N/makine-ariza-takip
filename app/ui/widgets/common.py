"""Ekranlar arasında paylaşılan küçük arayüz bileşenleri."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.ui import style


class StatCard(QFrame):
    """Dashboard üzerindeki özet sayı kartı."""

    def __init__(self, label: str, value: str = "0", color: str = style.ACCENT,
                 hint: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("StatCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(104)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(2)

        self.value_label = QLabel(value)
        self.value_label.setObjectName("StatValue")
        self.value_label.setStyleSheet(f"color: {color};")

        self.text_label = QLabel(label)
        self.text_label.setObjectName("StatLabel")
        self.text_label.setWordWrap(True)

        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("StatLabel")
        self.hint_label.setStyleSheet(f"color: {style.TEXT_MUTED}; font-size: 8.5pt;")
        self.hint_label.setVisible(bool(hint))

        layout.addWidget(self.value_label)
        layout.addWidget(self.text_label)
        layout.addWidget(self.hint_label)
        layout.addStretch()

    def set_value(self, value, hint: str = "") -> None:
        self.value_label.setText(str(value))
        if hint:
            self.hint_label.setText(hint)
            self.hint_label.setVisible(True)


class Card(QFrame):
    """Başlıklı beyaz içerik kutusu."""

    def __init__(self, title: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(14, 12, 14, 12)
        self._layout.setSpacing(8)
        if title:
            label = QLabel(title)
            label.setObjectName("SectionTitle")
            self._layout.addWidget(label)

    def body(self) -> QVBoxLayout:
        return self._layout

    def add(self, widget: QWidget, stretch: int = 0) -> None:
        self._layout.addWidget(widget, stretch)


def page_header(title: str, subtitle: str = "") -> QWidget:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)

    title_label = QLabel(title)
    title_label.setObjectName("PageTitle")
    layout.addWidget(title_label)

    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName("PageSubtitle")
        layout.addWidget(sub)
    return container


def field_row(label_text: str, widget: QWidget) -> QWidget:
    """Detay ekranlarında 'Etiket: değer' satırı."""
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    label = QLabel(label_text)
    label.setStyleSheet(f"color: {style.TEXT_MUTED};")
    label.setMinimumWidth(110)
    label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

    layout.addWidget(label)
    layout.addWidget(widget, 1)
    return row


def value_label(text: str, bold: bool = False) -> QLabel:
    label = QLabel(text or "-")
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if bold:
        font = label.font()
        font.setBold(True)
        label.setFont(font)
    return label


def badge_item(text: str, color: QColor) -> QTableWidgetItem:
    """Renkli arka planlı tablo hücresi (durum / öncelik rozeti)."""
    item = QTableWidgetItem(text)
    item.setBackground(style.tint(color, 45))
    item.setForeground(color.darker(135))
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    font = item.font()
    font.setBold(True)
    item.setFont(font)
    return item


def text_item(text: str, align_center: bool = False, sort_value=None) -> QTableWidgetItem:
    item = QTableWidgetItem(str(text) if text is not None else "-")
    if align_center:
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    if sort_value is not None:
        item.setData(Qt.ItemDataRole.UserRole + 1, sort_value)
    return item


class SortableItem(QTableWidgetItem):
    """Sayısal/tarihsel sıralamayı doğru yapan tablo hücresi."""

    def __init__(self, text: str, sort_key):
        super().__init__(text)
        self.sort_key = sort_key

    def __lt__(self, other):
        if isinstance(other, SortableItem):
            try:
                return self.sort_key < other.sort_key
            except TypeError:
                return str(self.sort_key) < str(other.sort_key)
        return super().__lt__(other)


def setup_table(table: QTableWidget, stretch_column: int | None = None) -> None:
    """Listeleme tablolarına ortak davranış uygular."""
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSortingEnabled(True)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(30)

    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setHighlightSections(False)
    if stretch_column is not None:
        header.setSectionResizeMode(stretch_column, QHeaderView.ResizeMode.Stretch)


def bold(widget: QLabel, size: int | None = None) -> QLabel:
    font: QFont = widget.font()
    font.setBold(True)
    if size:
        font.setPointSize(size)
    widget.setFont(font)
    return widget


def empty_state(message: str) -> QLabel:
    label = QLabel(message)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet(f"color: {style.TEXT_MUTED}; padding: 24px;")
    return label
