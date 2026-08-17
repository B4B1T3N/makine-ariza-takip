"""Kullanıcı ve rol yönetimi ekranı (yönetici)."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app import config
from app.services import auth_service
from app.services.auth_service import AuthError, CurrentUser
from app.ui import style
from app.ui.user_dialog import UserDialog
from app.ui.widgets import common
from app.utils.helpers import fmt_datetime

COLUMNS = ["Kullanıcı Adı", "Ad Soyad", "Rol", "Durum", "Kayıt Tarihi"]

ROLE_COLORS = {
    config.ROLE_OPERATOR: "#2a78d6",
    config.ROLE_TECHNICIAN: "#eb6834",
    config.ROLE_MANAGER: "#4a3aa7",
}


class UsersView(QWidget):
    def __init__(self, user: CurrentUser, parent: QWidget | None = None):
        super().__init__(parent)
        self.user = user
        self._rows: list = []
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        header_row = QHBoxLayout()
        header_row.addWidget(common.page_header(
            "Kullanıcılar",
            "Sisteme giriş yapabilecek kişiler ve yetkileri",
        ))
        header_row.addStretch()

        new_button = QPushButton("+ Yeni Kullanıcı")
        new_button.setObjectName("Primary")
        new_button.setMinimumHeight(36)
        new_button.clicked.connect(self._create)
        header_row.addWidget(new_button)
        root.addLayout(header_row)

        filter_row = QHBoxLayout()
        self.inactive_check = QCheckBox("Pasif kullanıcıları da göster")
        self.inactive_check.setChecked(True)
        self.inactive_check.stateChanged.connect(self.refresh)
        filter_row.addWidget(self.inactive_check)
        filter_row.addStretch()
        root.addLayout(filter_row)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        common.setup_table(self.table, stretch_column=1)
        self.table.doubleClicked.connect(self._edit)
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.count_label = QLabel()
        self.count_label.setStyleSheet(f"color: {style.TEXT_MUTED};")
        footer.addWidget(self.count_label)
        footer.addStretch()

        edit_button = QPushButton("Düzenle")
        edit_button.clicked.connect(self._edit)
        footer.addWidget(edit_button)

        toggle_button = QPushButton("Pasife Al / Aktifleştir")
        toggle_button.clicked.connect(self._toggle_active)
        footer.addWidget(toggle_button)
        root.addLayout(footer)

        hint = QLabel(
            "Not: Kullanıcı adları sonradan değiştirilemez ve kullanıcı kaydı silinmez; "
            "ayrılan personel pasife alınır. Böylece geçmiş arıza kayıtlarındaki "
            "'kim yaptı' bilgisi korunur."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {style.TEXT_MUTED}; font-size: 9pt;")
        root.addWidget(hint)

    # --- Veri -------------------------------------------------------------
    def refresh(self) -> None:
        self._rows = auth_service.list_users(
            include_inactive=self.inactive_check.isChecked()
        )
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self._rows))

        for index, row in enumerate(self._rows):
            username_item = common.text_item(row["username"])
            username_item.setData(Qt.ItemDataRole.UserRole, row["id"])
            if not row["is_active"]:
                username_item.setForeground(QColor(style.TEXT_MUTED))
            self.table.setItem(index, 0, username_item)

            name = row["full_name"]
            if row["id"] == self.user.id:
                name += "  (siz)"
            self.table.setItem(index, 1, common.text_item(name))

            self.table.setItem(
                index, 2,
                common.badge_item(
                    config.ROLE_LABELS[row["role"]],
                    QColor(ROLE_COLORS.get(row["role"], "#6b6a66")),
                ),
            )
            self.table.setItem(
                index, 3,
                common.badge_item(
                    "Aktif" if row["is_active"] else "Pasif",
                    QColor("#0ca30c" if row["is_active"] else "#6b6a66"),
                ),
            )
            self.table.setItem(
                index, 4,
                common.SortableItem(fmt_datetime(row["created_at"]), row["created_at"]),
            )

        self.table.setSortingEnabled(True)
        active = sum(1 for r in self._rows if r["is_active"])
        self.count_label.setText(
            f"{len(self._rows)} kullanıcı · {active} aktif"
        )

    def _selected_user(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Seçim yok", "Lütfen bir kullanıcı seçin.")
            return None
        user_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        return auth_service.get_user(user_id)

    # --- İşlemler ---------------------------------------------------------
    def _create(self) -> None:
        dialog = UserDialog(parent=self)
        if dialog.exec():
            self.refresh()

    def _edit(self) -> None:
        user_row = self._selected_user()
        if user_row is None:
            return
        dialog = UserDialog(user_row=user_row, parent=self)
        if dialog.exec():
            self.refresh()

    def _toggle_active(self) -> None:
        user_row = self._selected_user()
        if user_row is None:
            return
        if user_row["id"] == self.user.id:
            QMessageBox.warning(
                self, "İşlem yapılamaz", "Kendi hesabınızı pasife alamazsınız."
            )
            return

        new_state = not user_row["is_active"]
        action = "aktifleştirilecek" if new_state else "pasife alınacak"
        confirm = QMessageBox.question(
            self, "Onay",
            f"'{user_row['full_name']}' {action}. Devam edilsin mi?",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        try:
            auth_service.update_user(
                user_row["id"], user_row["full_name"], user_row["role"], new_state
            )
        except AuthError as exc:
            QMessageBox.warning(self, "İşlem yapılamadı", str(exc))
            return

        self.refresh()
