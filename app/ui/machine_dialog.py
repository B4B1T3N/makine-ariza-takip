"""Makine ekleme / düzenleme formu (yönetici)."""
from __future__ import annotations

import sqlite3

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.services import machine_service
from app.services.machine_service import MachineError
from app.ui import style


class MachineDialog(QDialog):
    """`machine` verilirse düzenleme, verilmezse yeni kayıt modunda açılır."""

    def __init__(self, machine: sqlite3.Row | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.machine = machine
        self.is_edit = machine is not None
        self.machine_id: int | None = machine["id"] if machine else None

        self.setWindowTitle("Makineyi Düzenle" if self.is_edit else "Yeni Makine")
        self.setModal(True)
        self.setMinimumWidth(480)
        self._build()
        self._load()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Örn: CNC Torna Tezgahı 1")
        self.name_input.setMaxLength(120)
        form.addRow("Makine Adı *", self.name_input)

        self.serial_input = QLineEdit()
        self.serial_input.setPlaceholderText("Örn: CNC-2019-001 (benzersiz)")
        form.addRow("Seri No", self.serial_input)

        self.location_combo = QComboBox()
        self.location_combo.setEditable(True)
        self.location_combo.setPlaceholderText("Örn: Hat A")
        form.addRow("Konum / Hat", self.location_combo)

        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        self.category_combo.setPlaceholderText("Örn: Talaşlı İmalat")
        form.addRow("Kategori", self.category_combo)

        self.commissioned_check = QCheckBox("Devreye alma tarihi biliniyor")
        self.commissioned_check.stateChanged.connect(
            lambda: self.commissioned_input.setEnabled(self.commissioned_check.isChecked())
        )
        form.addRow("", self.commissioned_check)

        self.commissioned_input = QDateEdit(QDate.currentDate())
        self.commissioned_input.setCalendarPopup(True)
        self.commissioned_input.setDisplayFormat("dd.MM.yyyy")
        self.commissioned_input.setMaximumDate(QDate.currentDate())
        self.commissioned_input.setEnabled(False)
        form.addRow("Devreye Alma", self.commissioned_input)

        self.notes_input = QPlainTextEdit()
        self.notes_input.setPlaceholderText("Teknik özellikler, bakım periyodu vb.")
        self.notes_input.setMaximumHeight(90)
        form.addRow("Notlar", self.notes_input)

        self.active_check = QCheckBox("Aktif (arıza kaydı açılabilir)")
        self.active_check.setChecked(True)
        if self.is_edit:
            form.addRow("Durum", self.active_check)

        layout.addLayout(form)

        self.hint_label = QLabel(
            "Pasife alınan makineler listede gizlenir ve yeni arıza kaydı açılamaz; "
            "geçmiş kayıtları korunur."
        )
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet(f"color: {style.TEXT_MUTED}; font-size: 9pt;")
        layout.addWidget(self.hint_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        save = buttons.button(QDialogButtonBox.StandardButton.Save)
        save.setText("Kaydet")
        save.setObjectName("Primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Vazgeç")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load(self) -> None:
        self.location_combo.addItems([""] + machine_service.list_locations())
        self.category_combo.addItems([""] + machine_service.list_categories())

        if not self.machine:
            self.location_combo.setCurrentText("")
            self.category_combo.setCurrentText("")
            return

        self.name_input.setText(self.machine["name"])
        self.serial_input.setText(self.machine["serial_no"] or "")
        self.location_combo.setCurrentText(self.machine["location"] or "")
        self.category_combo.setCurrentText(self.machine["category"] or "")
        self.notes_input.setPlainText(self.machine["notes"] or "")
        self.active_check.setChecked(bool(self.machine["is_active"]))

        if self.machine["commissioned_at"]:
            parsed = QDate.fromString(self.machine["commissioned_at"], "yyyy-MM-dd")
            if parsed.isValid():
                self.commissioned_check.setChecked(True)
                self.commissioned_input.setDate(parsed)

    def _save(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Eksik bilgi", "Makine adı zorunludur.")
            self.name_input.setFocus()
            return

        commissioned = (
            self.commissioned_input.date().toString("yyyy-MM-dd")
            if self.commissioned_check.isChecked() else None
        )
        values = dict(
            name=name,
            serial_no=self.serial_input.text().strip(),
            location=self.location_combo.currentText().strip(),
            category=self.category_combo.currentText().strip(),
            commissioned_at=commissioned,
            notes=self.notes_input.toPlainText().strip(),
        )

        try:
            if self.is_edit:
                machine_service.update_machine(
                    self.machine_id, is_active=self.active_check.isChecked(), **values
                )
            else:
                self.machine_id = machine_service.create_machine(**values)
        except MachineError as exc:
            QMessageBox.warning(self, "Kayıt yapılamadı", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Hata", f"Beklenmeyen bir hata oluştu:\n{exc}")
            return

        self.accept()
