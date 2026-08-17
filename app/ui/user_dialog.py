"""Kullanıcı ekleme / düzenleme formu (yönetici)."""
from __future__ import annotations

import sqlite3

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from app import config
from app.services import auth_service
from app.services.auth_service import AuthError
from app.ui import style

ROLE_HINTS = {
    config.ROLE_OPERATOR: "Arıza kaydı açar, yalnızca kendi kayıtlarını görür.",
    config.ROLE_TECHNICIAN: "Tüm kayıtları görür, durum günceller ve not ekler.",
    config.ROLE_MANAGER: "Tüm yetkiler: makine envanteri, kullanıcılar ve raporlar.",
}


class UserDialog(QDialog):
    """`user_row` verilirse düzenleme, verilmezse yeni kullanıcı modunda açılır."""

    def __init__(self, user_row: sqlite3.Row | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.user_row = user_row
        self.is_edit = user_row is not None

        self.setWindowTitle("Kullanıcıyı Düzenle" if self.is_edit else "Yeni Kullanıcı")
        self.setModal(True)
        self.setMinimumWidth(460)
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

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Giriş için kullanılacak ad")
        self.username_input.setMaxLength(40)
        form.addRow("Kullanıcı Adı *", self.username_input)

        self.fullname_input = QLineEdit()
        self.fullname_input.setPlaceholderText("Ad Soyad")
        self.fullname_input.setMaxLength(80)
        form.addRow("Ad Soyad *", self.fullname_input)

        self.role_combo = QComboBox()
        for value in config.ROLES:
            self.role_combo.addItem(config.ROLE_LABELS[value], value)
        self.role_combo.currentIndexChanged.connect(self._update_role_hint)
        form.addRow("Rol *", self.role_combo)

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        password_label = "Yeni Şifre" if self.is_edit else "Şifre *"
        self.password_input.setPlaceholderText(
            "Değiştirmek istemiyorsanız boş bırakın" if self.is_edit
            else "En az 4 karakter"
        )
        form.addRow(password_label, self.password_input)

        self.password_confirm = QLineEdit()
        self.password_confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_confirm.setPlaceholderText("Şifreyi tekrar girin")
        form.addRow("Şifre (Tekrar)", self.password_confirm)

        self.active_check = QCheckBox("Aktif (sisteme giriş yapabilir)")
        self.active_check.setChecked(True)
        if self.is_edit:
            form.addRow("Durum", self.active_check)

        layout.addLayout(form)

        self.role_hint = QLabel()
        self.role_hint.setWordWrap(True)
        self.role_hint.setStyleSheet(
            f"color: {style.TEXT_MUTED}; font-size: 9pt; "
            "background: #eef2f5; border-radius: 5px; padding: 8px;"
        )
        layout.addWidget(self.role_hint)
        self._update_role_hint()

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
        if not self.user_row:
            return
        self.username_input.setText(self.user_row["username"])
        self.username_input.setEnabled(False)  # Kullanıcı adı değiştirilemez.
        self.username_input.setToolTip("Kullanıcı adı sonradan değiştirilemez.")
        self.fullname_input.setText(self.user_row["full_name"])
        index = self.role_combo.findData(self.user_row["role"])
        if index >= 0:
            self.role_combo.setCurrentIndex(index)
        self.active_check.setChecked(bool(self.user_row["is_active"]))

    def _update_role_hint(self) -> None:
        self.role_hint.setText(ROLE_HINTS.get(self.role_combo.currentData(), ""))

    def _save(self) -> None:
        username = self.username_input.text().strip()
        full_name = self.fullname_input.text().strip()
        role = self.role_combo.currentData()
        password = self.password_input.text()
        confirm = self.password_confirm.text()

        if not full_name:
            QMessageBox.warning(self, "Eksik bilgi", "Ad soyad zorunludur.")
            self.fullname_input.setFocus()
            return
        if password and password != confirm:
            QMessageBox.warning(self, "Şifre uyuşmuyor", "Girilen iki şifre aynı değil.")
            self.password_confirm.setFocus()
            return
        if not self.is_edit and not password:
            QMessageBox.warning(self, "Eksik bilgi", "Yeni kullanıcı için şifre zorunludur.")
            self.password_input.setFocus()
            return

        try:
            if self.is_edit:
                auth_service.update_user(
                    self.user_row["id"], full_name, role,
                    self.active_check.isChecked(), password or None,
                )
            else:
                auth_service.create_user(username, password, full_name, role)
        except AuthError as exc:
            QMessageBox.warning(self, "Kayıt yapılamadı", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Hata", f"Beklenmeyen bir hata oluştu:\n{exc}")
            return

        self.accept()


class ChangePasswordDialog(QDialog):
    """Kullanıcının kendi şifresini değiştirmesi."""

    def __init__(self, user_id: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.user_id = user_id
        self.setWindowTitle("Şifre Değiştir")
        self.setModal(True)
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)

        self.old_input = QLineEdit()
        self.old_input.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Mevcut Şifre", self.old_input)

        self.new_input = QLineEdit()
        self.new_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_input.setPlaceholderText("En az 4 karakter")
        form.addRow("Yeni Şifre", self.new_input)

        self.confirm_input = QLineEdit()
        self.confirm_input.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Yeni Şifre (Tekrar)", self.confirm_input)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        save = buttons.button(QDialogButtonBox.StandardButton.Save)
        save.setText("Değiştir")
        save.setObjectName("Primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Vazgeç")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        if self.new_input.text() != self.confirm_input.text():
            QMessageBox.warning(self, "Şifre uyuşmuyor", "Girilen iki şifre aynı değil.")
            return
        try:
            auth_service.change_own_password(
                self.user_id, self.old_input.text(), self.new_input.text()
            )
        except AuthError as exc:
            QMessageBox.warning(self, "Değiştirilemedi", str(exc))
            return

        QMessageBox.information(self, "Başarılı", "Şifreniz güncellendi.")
        self.accept()
