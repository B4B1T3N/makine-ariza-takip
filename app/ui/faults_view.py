"""Arıza kayıtları listesi, filtreler ve dışa aktarma."""
from __future__ import annotations

from datetime import date

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
from app.ui.fault_detail_dialog import FaultDetailDialog
from app.ui.fault_dialog import FaultDialog
from app.ui.widgets import common
from app.utils import export
from app.utils.helpers import fmt_datetime, humanize_duration, parse_sql

COLUMNS = [
    "No", "Makine", "Arıza", "Öncelik", "Durum",
    "Bildiren", "Atanan", "Açılış", "Süre",
]


class FaultsView(QWidget):
    """Filtrelenebilir arıza listesi."""

    def __init__(self, user: CurrentUser, parent: QWidget | None = None):
        super().__init__(parent)
        self.user = user
        self._rows: list = []
        self._build()
        self.refresh()

    # --- Arayüz -----------------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        header_row = QHBoxLayout()
        subtitle = (
            "Açtığınız arıza kayıtları ve durumları"
            if self.user.is_operator else
            "Tüm arıza kayıtları — filtreleyerek arayabilirsiniz"
        )
        header_row.addWidget(common.page_header("Arıza Kayıtları", subtitle))
        header_row.addStretch()

        self.new_button = QPushButton("+ Yeni Arıza Kaydı")
        self.new_button.setObjectName("Primary")
        self.new_button.setMinimumHeight(36)
        self.new_button.clicked.connect(self.create_fault)
        header_row.addWidget(self.new_button)
        root.addLayout(header_row)

        root.addWidget(self._build_filters())

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        common.setup_table(self.table, stretch_column=2)
        self.table.doubleClicked.connect(self._open_selected)
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.count_label = QLabel()
        self.count_label.setStyleSheet(f"color: {style.TEXT_MUTED};")
        footer.addWidget(self.count_label)
        footer.addStretch()

        self.detail_button = QPushButton("Detayı Aç")
        self.detail_button.clicked.connect(self._open_selected)
        self.export_button = QPushButton("Excel/CSV'ye Aktar")
        self.export_button.clicked.connect(self._export)
        footer.addWidget(self.detail_button)
        footer.addWidget(self.export_button)
        root.addLayout(footer)

    def _build_filters(self) -> QWidget:
        card = common.Card()
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        def label(text: str) -> QLabel:
            widget = QLabel(text)
            widget.setStyleSheet(f"color: {style.TEXT_MUTED}; font-size: 9pt;")
            return widget

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Kayıt no, başlık, açıklama veya makine…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.returnPressed.connect(self.refresh)
        self.search_input.textChanged.connect(self._on_search_changed)
        grid.addWidget(label("Ara"), 0, 0)
        grid.addWidget(self.search_input, 1, 0)

        self.machine_filter = QComboBox()
        self.machine_filter.currentIndexChanged.connect(self.refresh)
        grid.addWidget(label("Makine"), 0, 1)
        grid.addWidget(self.machine_filter, 1, 1)

        self.status_filter = QComboBox()
        self.status_filter.addItem("Tümü", None)
        self.status_filter.addItem("Sadece açık kayıtlar", "__active__")
        for value in config.STATUSES:
            self.status_filter.addItem(config.STATUS_LABELS[value], value)
        self.status_filter.setCurrentIndex(1)
        self.status_filter.currentIndexChanged.connect(self.refresh)
        grid.addWidget(label("Durum"), 0, 2)
        grid.addWidget(self.status_filter, 1, 2)

        self.priority_filter = QComboBox()
        self.priority_filter.addItem("Tümü", None)
        for value in config.PRIORITIES:
            self.priority_filter.addItem(config.PRIORITY_LABELS[value], value)
        self.priority_filter.currentIndexChanged.connect(self.refresh)
        grid.addWidget(label("Öncelik"), 0, 3)
        grid.addWidget(self.priority_filter, 1, 3)

        self.date_check = QCheckBox("Tarih aralığı")
        self.date_check.stateChanged.connect(self._toggle_dates)
        grid.addWidget(self.date_check, 0, 4, 1, 2)

        self.date_from = QDateEdit(QDate.currentDate().addMonths(-1))
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("dd.MM.yyyy")
        self.date_from.setEnabled(False)
        self.date_from.dateChanged.connect(self._on_date_changed)
        grid.addWidget(self.date_from, 1, 4)

        self.date_to = QDateEdit(QDate.currentDate())
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("dd.MM.yyyy")
        self.date_to.setEnabled(False)
        self.date_to.dateChanged.connect(self._on_date_changed)
        grid.addWidget(self.date_to, 1, 5)

        self.mine_check = QCheckBox(
            "Bana atananlar" if self.user.is_technician else "Benim kayıtlarım"
        )
        self.mine_check.stateChanged.connect(self.refresh)
        self.mine_check.setVisible(not self.user.is_operator)
        grid.addWidget(self.mine_check, 1, 6)

        reset_button = QPushButton("Filtreleri Temizle")
        reset_button.clicked.connect(self._reset_filters)
        grid.addWidget(reset_button, 1, 7)

        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        card.body().addLayout(grid)
        return card

    # --- Veri -------------------------------------------------------------
    def reload_machines(self) -> None:
        """Makine listesi değiştiğinde filtre açılır kutusunu tazeler."""
        current = self.machine_filter.currentData()
        self.machine_filter.blockSignals(True)
        self.machine_filter.clear()
        self.machine_filter.addItem("Tümü", None)
        for row in machine_service.list_machines(include_inactive=True):
            self.machine_filter.addItem(row["name"], row["id"])
        index = self.machine_filter.findData(current)
        self.machine_filter.setCurrentIndex(max(index, 0))
        self.machine_filter.blockSignals(False)

    def refresh(self) -> None:
        if self.machine_filter.count() == 0:
            self.reload_machines()

        status_value = self.status_filter.currentData()
        statuses = None
        only_active = False
        if status_value == "__active__":
            only_active = True
        elif status_value:
            statuses = [status_value]

        priority = self.priority_filter.currentData()
        date_from = date_to = None
        if self.date_check.isChecked():
            date_from = self.date_from.date().toString("yyyy-MM-dd")
            date_to = self.date_to.date().toString("yyyy-MM-dd")

        reporter_id = assignee_id = None
        if self.user.is_operator:
            reporter_id = self.user.id  # Operatör yalnızca kendi kayıtlarını görür.
        elif self.mine_check.isChecked():
            if self.user.is_technician:
                assignee_id = self.user.id
            else:
                reporter_id = self.user.id

        self._rows = fault_service.list_faults(
            search=self.search_input.text().strip(),
            machine_id=self.machine_filter.currentData(),
            statuses=statuses,
            priorities=[priority] if priority else None,
            date_from=date_from,
            date_to=date_to,
            reporter_id=reporter_id,
            assignee_id=assignee_id,
            only_active=only_active,
        )
        self._fill_table()

    def _fill_table(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self._rows))

        for row_index, fault in enumerate(self._rows):
            created = parse_sql(fault["created_at"])
            end = parse_sql(fault["resolved_at"]) or parse_sql(fault["closed_at"])
            duration = (end - created).total_seconds() / 3600 if created and end else None

            id_item = common.SortableItem(str(fault["id"]), fault["id"])
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            id_item.setData(Qt.ItemDataRole.UserRole, fault["id"])
            self.table.setItem(row_index, 0, id_item)

            self.table.setItem(row_index, 1, common.text_item(fault["machine_name"]))
            self.table.setItem(row_index, 2, common.text_item(fault["title"]))
            self.table.setItem(
                row_index, 3,
                common.badge_item(
                    config.PRIORITY_LABELS[fault["priority"]],
                    style.priority_color(fault["priority"]),
                ),
            )
            self.table.setItem(
                row_index, 4,
                common.badge_item(
                    config.STATUS_LABELS[fault["status"]],
                    style.status_color(fault["status"]),
                ),
            )
            self.table.setItem(row_index, 5, common.text_item(fault["reporter_name"]))
            self.table.setItem(
                row_index, 6, common.text_item(fault["assignee_name"] or "—")
            )
            self.table.setItem(
                row_index, 7,
                common.SortableItem(fmt_datetime(fault["created_at"]),
                                    created or date.min),
            )
            self.table.setItem(
                row_index, 8,
                common.SortableItem(humanize_duration(duration),
                                    duration if duration is not None else -1),
            )

        self.table.setSortingEnabled(True)
        self.count_label.setText(f"{len(self._rows)} kayıt listeleniyor")
        self.detail_button.setEnabled(bool(self._rows))
        self.export_button.setEnabled(bool(self._rows))

    # --- Etkileşim --------------------------------------------------------
    def _on_search_changed(self, text: str) -> None:
        # Arama kutusu temizlendiğinde listeyi hemen geri getir.
        if not text:
            self.refresh()

    def _on_date_changed(self) -> None:
        if self.date_check.isChecked():
            self.refresh()

    def _toggle_dates(self) -> None:
        enabled = self.date_check.isChecked()
        self.date_from.setEnabled(enabled)
        self.date_to.setEnabled(enabled)
        self.refresh()

    def _reset_filters(self) -> None:
        for widget in (self.status_filter, self.priority_filter, self.machine_filter):
            widget.blockSignals(True)
        self.search_input.clear()
        self.machine_filter.setCurrentIndex(0)
        self.status_filter.setCurrentIndex(1)
        self.priority_filter.setCurrentIndex(0)
        self.mine_check.setChecked(False)
        self.date_check.setChecked(False)
        for widget in (self.status_filter, self.priority_filter, self.machine_filter):
            widget.blockSignals(False)
        self.refresh()

    def selected_fault_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _open_selected(self) -> None:
        fault_id = self.selected_fault_id()
        if fault_id is None:
            QMessageBox.information(
                self, "Seçim yok", "Lütfen listeden bir arıza kaydı seçin."
            )
            return
        self.open_fault(fault_id)

    def open_fault(self, fault_id: int) -> None:
        dialog = FaultDetailDialog(self.user, fault_id, parent=self)
        dialog.exec()
        if dialog.changed:
            self.refresh()

    def create_fault(self, preselect_machine_id: int | None = None) -> bool:
        if not machine_service.list_machines(include_inactive=False):
            QMessageBox.information(
                self, "Makine kaydı yok",
                "Önce makine envanterine en az bir makine eklenmelidir.\n"
                "Bu işlem için yönetici yetkisi gerekir.",
            )
            return False

        dialog = FaultDialog(
            self.user, preselect_machine_id=preselect_machine_id, parent=self
        )
        if dialog.exec():
            self.refresh()
            if dialog.fault_id:
                QMessageBox.information(
                    self, "Kayıt oluşturuldu",
                    f"Arıza kaydı #{dialog.fault_id} numarasıyla oluşturuldu.\n"
                    "Bakım ekibi bilgilendirildi.",
                )
            return True
        return False

    # --- Dışa aktarma -----------------------------------------------------
    def _export(self) -> None:
        if not self._rows:
            QMessageBox.information(self, "Veri yok", "Aktarılacak kayıt bulunmuyor.")
            return

        default_name = f"ariza_kayitlari_{date.today().isoformat()}.xlsx"
        path, _ = QFileDialog.getSaveFileName(
            self, "Arıza kayıtlarını kaydet", default_name, export.EXPORT_FILTER
        )
        if not path:
            return

        headers = [
            "Kayıt No", "Makine", "Seri No", "Konum", "Arıza Başlığı", "Açıklama",
            "Öncelik", "Durum", "Bildiren", "Atanan",
            "Açılış Tarihi", "Çözüm Tarihi", "Kapanış Tarihi", "Çözüm Süresi (saat)",
        ]
        rows = []
        for fault in self._rows:
            created = parse_sql(fault["created_at"])
            end = parse_sql(fault["resolved_at"]) or parse_sql(fault["closed_at"])
            duration = round((end - created).total_seconds() / 3600, 1) if created and end else None
            rows.append([
                fault["id"],
                fault["machine_name"],
                fault["machine_serial"] or "",
                fault["machine_location"] or "",
                fault["title"],
                fault["description"] or "",
                config.PRIORITY_LABELS[fault["priority"]],
                config.STATUS_LABELS[fault["status"]],
                fault["reporter_name"],
                fault["assignee_name"] or "",
                fmt_datetime(fault["created_at"]),
                fmt_datetime(fault["resolved_at"]),
                fmt_datetime(fault["closed_at"]),
                duration,
            ])

        try:
            saved = export.export_auto(path, headers, rows, "Ariza Kayitlari")
        except export.ExportError as exc:
            QMessageBox.warning(self, "Dışa aktarılamadı", str(exc))
            return

        QMessageBox.information(
            self, "Dışa aktarıldı",
            f"{len(rows)} kayıt aktarıldı:\n{saved}",
        )
