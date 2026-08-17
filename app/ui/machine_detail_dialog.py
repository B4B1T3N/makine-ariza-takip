"""Makine detay ekranı: künye bilgileri, özet ve geçmiş arıza kayıtları."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app import config
from app.services import fault_service, machine_service
from app.services.auth_service import CurrentUser
from app.ui import style
from app.ui.widgets import common
from app.utils.helpers import fmt_date, fmt_datetime, humanize_duration, parse_sql

HISTORY_COLUMNS = ["No", "Arıza", "Öncelik", "Durum", "Bildiren", "Açılış", "Süre"]


class MachineDetailDialog(QDialog):
    """Bir makinenin künyesi ve tüm arıza geçmişi."""

    def __init__(self, user: CurrentUser, machine_id: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.user = user
        self.machine_id = machine_id
        self.changed = False

        self.setWindowTitle("Makine Detayı")
        self.setModal(True)
        self.resize(900, 660)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)

        self.title_label = QLabel()
        self.title_label.setObjectName("PageTitle")
        self.subtitle_label = QLabel()
        self.subtitle_label.setObjectName("PageSubtitle")
        root.addWidget(self.title_label)
        root.addWidget(self.subtitle_label)

        # Özet kartları
        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)
        self.total_card = common.StatCard("Toplam arıza kaydı", "0", style.PRIMARY)
        self.open_card = common.StatCard("Açık kayıt", "0", config.STATUS_COLORS[config.STATUS_OPEN])
        self.avg_card = common.StatCard("Ortalama çözüm süresi", "-", "#0ca30c")
        self.last_card = common.StatCard("Son arıza", "-", style.ACCENT)
        for card in (self.total_card, self.open_card, self.avg_card, self.last_card):
            stats_row.addWidget(card)
        root.addLayout(stats_row)

        # Künye
        info_card = common.Card("Makine Künyesi")
        self.info_body = QVBoxLayout()
        self.info_body.setSpacing(5)
        info_card.body().addLayout(self.info_body)
        root.addWidget(info_card)

        # Geçmiş
        history_label = QLabel("Arıza Geçmişi")
        history_label.setObjectName("SectionTitle")
        root.addWidget(history_label)

        self.history_table = QTableWidget(0, len(HISTORY_COLUMNS))
        self.history_table.setHorizontalHeaderLabels(HISTORY_COLUMNS)
        common.setup_table(self.history_table, stretch_column=1)
        self.history_table.doubleClicked.connect(self._open_fault)
        root.addWidget(self.history_table, 1)

        footer = QHBoxLayout()
        self.history_count = QLabel()
        self.history_count.setStyleSheet(f"color: {style.TEXT_MUTED};")
        footer.addWidget(self.history_count)
        footer.addStretch()

        self.new_fault_button = QPushButton("+ Bu Makineye Arıza Kaydı Aç")
        self.new_fault_button.setObjectName("Primary")
        self.new_fault_button.clicked.connect(self._create_fault)
        footer.addWidget(self.new_fault_button)

        open_button = QPushButton("Seçili Kaydı Aç")
        open_button.clicked.connect(self._open_fault)
        footer.addWidget(open_button)

        close_button = QPushButton("Kapat")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        root.addLayout(footer)

    # --- Veri -------------------------------------------------------------
    def refresh(self) -> None:
        machine = machine_service.get_machine(self.machine_id)
        if machine is None:
            QMessageBox.warning(self, "Bulunamadı", "Makine kaydı bulunamadı.")
            self.reject()
            return

        status_text = "" if machine["is_active"] else "  ·  PASİF"
        self.title_label.setText(machine["name"] + status_text)
        self.subtitle_label.setText(
            " · ".join(
                part for part in (
                    machine["serial_no"], machine["location"], machine["category"]
                ) if part
            ) or "Ek künye bilgisi girilmemiş"
        )

        stats = machine_service.machine_stats(self.machine_id)
        self.total_card.set_value(stats["total_faults"])
        self.open_card.set_value(stats["open_faults"])
        self.avg_card.set_value(humanize_duration(stats["avg_resolution_hours"]))
        self.last_card.set_value(
            fmt_date(stats["last_fault_at"]) if stats["last_fault_at"] else "-"
        )

        self._fill_info(machine)
        self._fill_history()

        self.new_fault_button.setEnabled(bool(machine["is_active"]))
        if not machine["is_active"]:
            self.new_fault_button.setToolTip(
                "Pasif makineler için yeni arıza kaydı açılamaz."
            )

    def _fill_info(self, machine) -> None:
        while self.info_body.count():
            item = self.info_body.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        rows = [
            ("Makine Adı", machine["name"]),
            ("Seri No", machine["serial_no"] or "-"),
            ("Konum / Hat", machine["location"] or "-"),
            ("Kategori", machine["category"] or "-"),
            ("Devreye Alma", fmt_date(machine["commissioned_at"])),
            ("Kayıt Tarihi", fmt_datetime(machine["created_at"])),
            ("Durum", "Aktif" if machine["is_active"] else "Pasif"),
        ]
        if machine["notes"]:
            rows.append(("Notlar", machine["notes"]))

        for label, value in rows:
            self.info_body.addWidget(common.field_row(label, common.value_label(value)))

    def _fill_history(self) -> None:
        faults = fault_service.list_machine_faults(self.machine_id)
        self.history_table.setSortingEnabled(False)
        self.history_table.setRowCount(len(faults))

        for index, fault in enumerate(faults):
            created = parse_sql(fault["created_at"])
            end = parse_sql(fault["resolved_at"]) or parse_sql(fault["closed_at"])
            duration = (end - created).total_seconds() / 3600 if created and end else None

            id_item = common.SortableItem(str(fault["id"]), fault["id"])
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            id_item.setData(Qt.ItemDataRole.UserRole, fault["id"])
            self.history_table.setItem(index, 0, id_item)

            self.history_table.setItem(index, 1, common.text_item(fault["title"]))
            self.history_table.setItem(
                index, 2,
                common.badge_item(
                    config.PRIORITY_LABELS[fault["priority"]],
                    style.priority_color(fault["priority"]),
                ),
            )
            self.history_table.setItem(
                index, 3,
                common.badge_item(
                    config.STATUS_LABELS[fault["status"]],
                    style.status_color(fault["status"]),
                ),
            )
            self.history_table.setItem(index, 4, common.text_item(fault["reporter_name"]))
            self.history_table.setItem(
                index, 5,
                common.SortableItem(fmt_datetime(fault["created_at"]), fault["created_at"]),
            )
            self.history_table.setItem(
                index, 6,
                common.SortableItem(
                    humanize_duration(duration),
                    duration if duration is not None else -1,
                ),
            )

        self.history_table.setSortingEnabled(True)
        self.history_count.setText(f"{len(faults)} arıza kaydı")

    # --- Etkileşim --------------------------------------------------------
    def _open_fault(self) -> None:
        row = self.history_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Seçim yok", "Lütfen bir arıza kaydı seçin.")
            return

        from app.ui.fault_detail_dialog import FaultDetailDialog

        fault_id = self.history_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        dialog = FaultDetailDialog(self.user, fault_id, parent=self)
        dialog.exec()
        if dialog.changed:
            self.changed = True
            self.refresh()

    def _create_fault(self) -> None:
        from app.ui.fault_dialog import FaultDialog

        dialog = FaultDialog(
            self.user, preselect_machine_id=self.machine_id, parent=self
        )
        if dialog.exec():
            self.changed = True
            self.refresh()
