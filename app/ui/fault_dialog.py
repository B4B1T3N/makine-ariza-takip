"""Yeni arıza kaydı oluşturma / düzenleme formu."""
from __future__ import annotations

import sqlite3

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
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

from app import config
from app.services import auth_service, fault_service, machine_service
from app.services.auth_service import CurrentUser
from app.services.fault_service import FaultError
from app.ui import style


class FaultDialog(QDialog):
    """`fault` verilirse düzenleme, verilmezse yeni kayıt modunda açılır."""

    def __init__(
        self,
        user: CurrentUser,
        fault: sqlite3.Row | None = None,
        preselect_machine_id: int | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.user = user
        self.fault = fault
        self.fault_id: int | None = fault["id"] if fault else None
        self.is_edit = fault is not None

        self.setWindowTitle(
            f"Arıza Kaydını Düzenle (#{self.fault_id})" if self.is_edit
            else "Yeni Arıza Kaydı"
        )
        self.setModal(True)
        self.setMinimumWidth(520)
        self._build()
        self._load(preselect_machine_id)

    # --- Arayüz -----------------------------------------------------------
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        header = QLabel(
            "Arıza kaydını güncelleyin" if self.is_edit
            else "Arızalı makineyi ve sorunu tanımlayın"
        )
        header.setObjectName("PageSubtitle")
        layout.addWidget(header)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        self.machine_combo = QComboBox()
        form.addRow("Makine *", self.machine_combo)

        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("Örn: Motor aşırı ısınıyor")
        self.title_input.setMaxLength(160)
        form.addRow("Arıza Başlığı *", self.title_input)

        self.priority_combo = QComboBox()
        for value in config.PRIORITIES:
            self.priority_combo.addItem(config.PRIORITY_LABELS[value], value)
        self.priority_combo.setCurrentIndex(1)  # Varsayılan: Orta
        form.addRow("Öncelik *", self.priority_combo)

        self.assignee_combo = QComboBox()
        self.assignee_combo.addItem("— Atanmamış —", None)
        for row in auth_service.list_technicians():
            label = f"{row['full_name']} ({config.ROLE_LABELS[row['role']]})"
            self.assignee_combo.addItem(label, row["id"])
        self.assignee_row_visible = self.user.can_assign and not self.is_edit
        if self.assignee_row_visible:
            form.addRow("Teknisyen", self.assignee_combo)

        self.description_input = QPlainTextEdit()
        self.description_input.setPlaceholderText(
            "Arızanın nasıl ortaya çıktığını, belirtilerini ve varsa hata kodunu yazın."
        )
        self.description_input.setMinimumHeight(120)
        form.addRow("Açıklama", self.description_input)

        layout.addLayout(form)

        note = QLabel(
            "Kaydı açan kişi ve tarih otomatik olarak eklenir. "
            "Fotoğraf/dosya ekini kayıt oluştuktan sonra detay ekranından yükleyebilirsiniz."
            if not self.is_edit else
            "Durum değişikliği ve notlar detay ekranından yapılır."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {style.TEXT_MUTED}; font-size: 9pt;")
        layout.addWidget(note)

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

    def _load(self, preselect_machine_id: int | None) -> None:
        machines = machine_service.list_machines(include_inactive=False)
        for row in machines:
            label = row["name"]
            if row["location"]:
                label += f" — {row['location']}"
            if row["serial_no"]:
                label += f" ({row['serial_no']})"
            self.machine_combo.addItem(label, row["id"])

        if not machines:
            self.machine_combo.addItem("Kayıtlı aktif makine yok", None)
            self.machine_combo.setEnabled(False)

        if self.fault:
            self._select_by_data(self.machine_combo, self.fault["machine_id"])
            self.title_input.setText(self.fault["title"])
            self.description_input.setPlainText(self.fault["description"] or "")
            self._select_by_data(self.priority_combo, self.fault["priority"])
        elif preselect_machine_id:
            self._select_by_data(self.machine_combo, preselect_machine_id)

    @staticmethod
    def _select_by_data(combo: QComboBox, value) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    # --- Kaydetme ---------------------------------------------------------
    def _save(self) -> None:
        machine_id = self.machine_combo.currentData()
        title = self.title_input.text().strip()
        description = self.description_input.toPlainText().strip()
        priority = self.priority_combo.currentData()

        if machine_id is None:
            QMessageBox.warning(self, "Eksik bilgi", "Lütfen bir makine seçin.")
            self.machine_combo.setFocus()
            return
        if not title:
            QMessageBox.warning(self, "Eksik bilgi", "Arıza başlığı zorunludur.")
            self.title_input.setFocus()
            return

        try:
            if self.is_edit:
                fault_service.update_fault(
                    self.fault_id, self.user.id, machine_id, title, description, priority
                )
            else:
                assignee_id = (
                    self.assignee_combo.currentData() if self.assignee_row_visible else None
                )
                self.fault_id = fault_service.create_fault(
                    machine_id, title, description, priority, self.user.id, assignee_id
                )
        except FaultError as exc:
            QMessageBox.warning(self, "Kayıt yapılamadı", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Hata", f"Beklenmeyen bir hata oluştu:\n{exc}")
            return

        self.accept()
