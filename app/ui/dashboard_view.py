"""Ana ekran: özet göstergeler, dağılım grafikleri ve öncelikli kayıtlar."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app import config
from app.services import fault_service, report_service
from app.services.auth_service import CurrentUser
from app.ui import style
from app.ui.widgets import common
from app.ui.widgets.charts import ChartCanvas, ordinal_colors
from app.utils.helpers import fmt_datetime, humanize_duration

RECENT_COLUMNS = ["No", "Makine", "Arıza", "Öncelik", "Durum", "Atanan", "Açılış"]


class DashboardView(QWidget):
    """Rol bazlı özet ekran."""

    open_fault_requested = pyqtSignal(int)
    new_fault_requested = pyqtSignal()

    def __init__(self, user: CurrentUser, parent: QWidget | None = None):
        super().__init__(parent)
        self.user = user
        self._build()
        self.refresh()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        scroll.setWidget(container)
        outer.addWidget(scroll)

        root = QVBoxLayout(container)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        header_row = QHBoxLayout()
        header_row.addWidget(common.page_header(
            f"Hoş geldiniz, {self.user.full_name}",
            f"{self.user.role_label} · Üretim hattı arıza durumu özeti",
        ))
        header_row.addStretch()

        new_button = QPushButton("+ Yeni Arıza Kaydı")
        new_button.setObjectName("Primary")
        new_button.setMinimumHeight(36)
        new_button.clicked.connect(self.new_fault_requested.emit)
        header_row.addWidget(new_button)
        root.addLayout(header_row)

        # --- Özet kartları ---
        cards = QGridLayout()
        cards.setSpacing(10)
        self.open_card = common.StatCard(
            "Açık arıza kaydı", "0", config.STATUS_COLORS[config.STATUS_OPEN]
        )
        self.urgent_card = common.StatCard(
            "Acil öncelikli açık kayıt", "0", config.PRIORITY_COLORS[config.PRIORITY_URGENT]
        )
        self.today_open_card = common.StatCard("Bugün açılan", "0", style.ACCENT)
        self.today_closed_card = common.StatCard("Bugün çözülen/kapanan", "0", "#0ca30c")
        self.unassigned_card = common.StatCard("Atanmamış kayıt", "0", "#eb6834")
        self.avg_card = common.StatCard("Ortalama çözüm süresi", "-", style.PRIMARY)

        for index, card in enumerate([
            self.open_card, self.urgent_card, self.today_open_card,
            self.today_closed_card, self.unassigned_card, self.avg_card,
        ]):
            cards.addWidget(card, index // 3, index % 3)
        root.addLayout(cards)

        # --- Grafikler ---
        charts_row = QHBoxLayout()
        charts_row.setSpacing(12)

        priority_card = common.Card("Açık Kayıtların Öncelik Dağılımı")
        self.priority_chart = ChartCanvas(height=2.6)
        priority_card.add(self.priority_chart)
        charts_row.addWidget(priority_card, 1)

        status_card = common.Card("Tüm Kayıtların Durum Dağılımı")
        self.status_chart = ChartCanvas(height=2.6)
        status_card.add(self.status_chart)
        charts_row.addWidget(status_card, 1)
        root.addLayout(charts_row)

        # --- Öncelikli kayıtlar tablosu ---
        table_card = common.Card()
        table_header = QHBoxLayout()
        self.table_title = QLabel("Öncelikli Açık Kayıtlar")
        self.table_title.setObjectName("SectionTitle")
        table_header.addWidget(self.table_title)
        table_header.addStretch()

        self.table_hint = QLabel("Detay için satıra çift tıklayın")
        self.table_hint.setStyleSheet(f"color: {style.TEXT_MUTED}; font-size: 9pt;")
        table_header.addWidget(self.table_hint)
        table_card.body().addLayout(table_header)

        self.recent_table = QTableWidget(0, len(RECENT_COLUMNS))
        self.recent_table.setHorizontalHeaderLabels(RECENT_COLUMNS)
        common.setup_table(self.recent_table, stretch_column=2)
        self.recent_table.setSortingEnabled(False)
        self.recent_table.setMinimumHeight(260)
        self.recent_table.doubleClicked.connect(self._open_selected)
        table_card.add(self.recent_table)
        root.addWidget(table_card)

        root.addStretch()

    # --- Veri -------------------------------------------------------------
    def refresh(self) -> None:
        stats = report_service.summary()
        self.open_card.set_value(stats["open_total"])
        self.urgent_card.set_value(stats["urgent_open"])
        self.today_open_card.set_value(stats["opened_today"])
        self.today_closed_card.set_value(stats["closed_today"])
        self.unassigned_card.set_value(stats["unassigned"])
        self.avg_card.set_value(humanize_duration(stats["avg_resolution_hours"]))

        # Öncelik dağılımı: sıralı veri olduğu için açıktan koyuya rampa.
        priorities = report_service.priority_distribution(only_active=True)
        ordered = [config.PRIORITY_LOW, config.PRIORITY_MEDIUM,
                   config.PRIORITY_HIGH, config.PRIORITY_URGENT]
        self.priority_chart.draw_vbar(
            [config.PRIORITY_LABELS[p] for p in ordered],
            [priorities[p] for p in ordered],
            colors=ordinal_colors(4),
            ylabel="Açık kayıt",
        )

        statuses = report_service.status_distribution()
        self.status_chart.draw_hbar(
            [config.STATUS_LABELS[s] for s in config.STATUSES],
            [statuses[s] for s in config.STATUSES],
            colors=ordinal_colors(5),
            xlabel="Kayıt sayısı",
        )

        self._fill_recent()

    def _fill_recent(self) -> None:
        if self.user.is_operator:
            self.table_title.setText("Açtığım Son Kayıtlar")
            rows = fault_service.list_faults(reporter_id=self.user.id)[:15]
        elif self.user.is_technician:
            self.table_title.setText("Bana Atanan Açık Kayıtlar")
            rows = fault_service.list_faults(
                assignee_id=self.user.id, only_active=True
            )[:15]
            if not rows:
                self.table_title.setText("Öncelikli Açık Kayıtlar")
                rows = fault_service.list_faults(only_active=True)[:15]
        else:
            self.table_title.setText("Öncelikli Açık Kayıtlar")
            rows = fault_service.list_faults(only_active=True)[:15]

        self.recent_table.setRowCount(len(rows))
        for index, fault in enumerate(rows):
            id_item = common.text_item(str(fault["id"]), align_center=True)
            id_item.setData(Qt.ItemDataRole.UserRole, fault["id"])
            self.recent_table.setItem(index, 0, id_item)

            self.recent_table.setItem(index, 1, common.text_item(fault["machine_name"]))
            self.recent_table.setItem(index, 2, common.text_item(fault["title"]))
            self.recent_table.setItem(
                index, 3,
                common.badge_item(
                    config.PRIORITY_LABELS[fault["priority"]],
                    style.priority_color(fault["priority"]),
                ),
            )
            self.recent_table.setItem(
                index, 4,
                common.badge_item(
                    config.STATUS_LABELS[fault["status"]],
                    style.status_color(fault["status"]),
                ),
            )
            self.recent_table.setItem(
                index, 5, common.text_item(fault["assignee_name"] or "—")
            )
            self.recent_table.setItem(
                index, 6, common.text_item(fmt_datetime(fault["created_at"]))
            )

        if not rows:
            self.recent_table.setRowCount(1)
            empty = common.text_item("Görüntülenecek açık kayıt yok.", align_center=True)
            empty.setForeground(QColor(style.TEXT_MUTED))
            self.recent_table.setItem(0, 2, empty)

    def _open_selected(self) -> None:
        row = self.recent_table.currentRow()
        if row < 0:
            return
        item = self.recent_table.item(row, 0)
        if item is None:
            return
        fault_id = item.data(Qt.ItemDataRole.UserRole)
        if fault_id:
            self.open_fault_requested.emit(fault_id)
