"""Makine / ekipman envanteri listesi."""
from __future__ import annotations

from datetime import date

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app.services import machine_service
from app.services.auth_service import CurrentUser
from app.services.machine_service import MachineError
from app.ui import style
from app.ui.machine_detail_dialog import MachineDetailDialog
from app.ui.machine_dialog import MachineDialog
from app.ui.widgets import common
from app.utils import export
from app.utils.helpers import fmt_date

COLUMNS = [
    "Makine Adı", "Seri No", "Konum / Hat", "Kategori",
    "Devreye Alma", "Açık Arıza", "Toplam Arıza", "Durum",
]


class MachinesView(QWidget):
    """Makine envanteri; yönetici ekleme/düzenleme/pasife alma yapabilir."""

    def __init__(self, user: CurrentUser, parent: QWidget | None = None):
        super().__init__(parent)
        self.user = user
        self._rows: list = []
        self.changed = False
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        header_row = QHBoxLayout()
        header_row.addWidget(common.page_header(
            "Makine Envanteri",
            "Üretim hattındaki makineler ve arıza yoğunlukları",
        ))
        header_row.addStretch()

        self.new_button = QPushButton("+ Yeni Makine")
        self.new_button.setObjectName("Primary")
        self.new_button.setMinimumHeight(36)
        self.new_button.clicked.connect(self._create)
        self.new_button.setVisible(self.user.can_manage_machines)
        header_row.addWidget(self.new_button)
        root.addLayout(header_row)

        # Filtre çubuğu
        filter_card = common.Card()
        filter_row = QHBoxLayout()
        filter_row.setSpacing(10)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Makine adı, seri no veya konum ara…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self.refresh)
        filter_row.addWidget(self.search_input, 3)

        self.category_filter = QComboBox()
        self.category_filter.currentIndexChanged.connect(self.refresh)
        filter_row.addWidget(self.category_filter, 1)

        self.inactive_check = QCheckBox("Pasifleri de göster")
        self.inactive_check.stateChanged.connect(self.refresh)
        filter_row.addWidget(self.inactive_check)
        filter_card.body().addLayout(filter_row)
        root.addWidget(filter_card)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        common.setup_table(self.table, stretch_column=0)
        self.table.doubleClicked.connect(self._open_detail)
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.count_label = QLabel()
        self.count_label.setStyleSheet(f"color: {style.TEXT_MUTED};")
        footer.addWidget(self.count_label)
        footer.addStretch()

        self.detail_button = QPushButton("Detay / Arıza Geçmişi")
        self.detail_button.clicked.connect(self._open_detail)
        footer.addWidget(self.detail_button)

        self.edit_button = QPushButton("Düzenle")
        self.edit_button.clicked.connect(self._edit)
        self.edit_button.setVisible(self.user.can_manage_machines)
        footer.addWidget(self.edit_button)

        self.toggle_button = QPushButton("Pasife Al / Aktifleştir")
        self.toggle_button.clicked.connect(self._toggle_active)
        self.toggle_button.setVisible(self.user.can_manage_machines)
        footer.addWidget(self.toggle_button)

        export_button = QPushButton("Excel/CSV'ye Aktar")
        export_button.clicked.connect(self._export)
        footer.addWidget(export_button)
        root.addLayout(footer)

    # --- Veri -------------------------------------------------------------
    def refresh(self) -> None:
        self._reload_categories()
        self._rows = machine_service.list_machines(
            search=self.search_input.text().strip(),
            include_inactive=self.inactive_check.isChecked(),
            category=self.category_filter.currentData(),
        )

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self._rows))

        for index, machine in enumerate(self._rows):
            name_item = common.text_item(machine["name"])
            name_item.setData(Qt.ItemDataRole.UserRole, machine["id"])
            if not machine["is_active"]:
                name_item.setForeground(QColor(style.TEXT_MUTED))
            self.table.setItem(index, 0, name_item)

            self.table.setItem(index, 1, common.text_item(machine["serial_no"] or "-"))
            self.table.setItem(index, 2, common.text_item(machine["location"] or "-"))
            self.table.setItem(index, 3, common.text_item(machine["category"] or "-"))
            self.table.setItem(
                index, 4,
                common.SortableItem(
                    fmt_date(machine["commissioned_at"]),
                    machine["commissioned_at"] or "",
                ),
            )

            open_count = machine["open_faults"]
            open_item = common.SortableItem(str(open_count), open_count)
            open_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if open_count:
                open_item.setForeground(style.status_color("acik"))
                font = open_item.font()
                font.setBold(True)
                open_item.setFont(font)
            self.table.setItem(index, 5, open_item)

            total_item = common.SortableItem(
                str(machine["total_faults"]), machine["total_faults"]
            )
            total_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(index, 6, total_item)

            self.table.setItem(
                index, 7,
                common.badge_item(
                    "Aktif" if machine["is_active"] else "Pasif",
                    QColor("#0ca30c" if machine["is_active"] else "#6b6a66"),
                ),
            )

        self.table.setSortingEnabled(True)
        self.count_label.setText(f"{len(self._rows)} makine listeleniyor")

    def _reload_categories(self) -> None:
        current = self.category_filter.currentData()
        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem("Tüm kategoriler", None)
        for category in machine_service.list_categories():
            self.category_filter.addItem(category, category)
        index = self.category_filter.findData(current)
        self.category_filter.setCurrentIndex(max(index, 0))
        self.category_filter.blockSignals(False)

    def selected_machine_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selected_row(self):
        machine_id = self.selected_machine_id()
        if machine_id is None:
            QMessageBox.information(self, "Seçim yok", "Lütfen listeden bir makine seçin.")
            return None
        return machine_service.get_machine(machine_id)

    # --- İşlemler ---------------------------------------------------------
    def _create(self) -> None:
        dialog = MachineDialog(parent=self)
        if dialog.exec():
            self.changed = True
            self.refresh()

    def _edit(self) -> None:
        machine = self._selected_row()
        if machine is None:
            return
        dialog = MachineDialog(machine=machine, parent=self)
        if dialog.exec():
            self.changed = True
            self.refresh()

    def _toggle_active(self) -> None:
        machine = self._selected_row()
        if machine is None:
            return

        new_state = not machine["is_active"]
        action = "aktifleştirilecek" if new_state else "pasife alınacak"
        confirm = QMessageBox.question(
            self, "Onay",
            f"'{machine['name']}' {action}.\n"
            + ("" if new_state else
               "Pasif makineler için yeni arıza kaydı açılamaz, geçmiş kayıtlar korunur.\n")
            + "Devam edilsin mi?",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        try:
            machine_service.set_active(machine["id"], new_state)
        except MachineError as exc:
            QMessageBox.warning(self, "İşlem yapılamadı", str(exc))
            return

        self.changed = True
        self.refresh()

    def _open_detail(self) -> None:
        machine_id = self.selected_machine_id()
        if machine_id is None:
            QMessageBox.information(self, "Seçim yok", "Lütfen listeden bir makine seçin.")
            return

        dialog = MachineDetailDialog(self.user, machine_id, parent=self)
        dialog.exec()
        if dialog.changed:
            self.changed = True
            self.refresh()

    def _export(self) -> None:
        if not self._rows:
            QMessageBox.information(self, "Veri yok", "Aktarılacak makine bulunmuyor.")
            return

        default_name = f"makine_envanteri_{date.today().isoformat()}.xlsx"
        path, _ = QFileDialog.getSaveFileName(
            self, "Makine envanterini kaydet", default_name, export.EXPORT_FILTER
        )
        if not path:
            return

        headers = [
            "Makine Adı", "Seri No", "Konum / Hat", "Kategori",
            "Devreye Alma", "Açık Arıza", "Toplam Arıza", "Durum", "Notlar",
        ]
        rows = [
            [
                m["name"], m["serial_no"] or "", m["location"] or "", m["category"] or "",
                fmt_date(m["commissioned_at"]), m["open_faults"], m["total_faults"],
                "Aktif" if m["is_active"] else "Pasif", m["notes"] or "",
            ]
            for m in self._rows
        ]

        try:
            saved = export.export_auto(path, headers, rows, "Makine Envanteri")
        except export.ExportError as exc:
            QMessageBox.warning(self, "Dışa aktarılamadı", str(exc))
            return

        QMessageBox.information(
            self, "Dışa aktarıldı", f"{len(rows)} makine aktarıldı:\n{saved}"
        )
