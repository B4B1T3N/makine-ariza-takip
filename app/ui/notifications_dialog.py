"""Uygulama içi bildirim listesi."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services import notification_service
from app.services.auth_service import CurrentUser
from app.ui import style
from app.utils.helpers import fmt_datetime


class NotificationsDialog(QDialog):
    """Kullanıcının bildirimleri; çift tıklayınca ilgili arıza kaydı açılır."""

    open_fault_requested = pyqtSignal(int)

    def __init__(self, user: CurrentUser, parent: QWidget | None = None):
        super().__init__(parent)
        self.user = user

        self.setWindowTitle("Bildirimler")
        self.setModal(True)
        self.resize(560, 560)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        title = QLabel("Bildirimler")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        self.subtitle = QLabel()
        self.subtitle.setObjectName("PageSubtitle")
        root.addWidget(self.subtitle)

        self.list_widget = QListWidget()
        self.list_widget.setWordWrap(True)
        self.list_widget.setStyleSheet("QListWidget::item { padding: 10px 8px; }")
        self.list_widget.itemDoubleClicked.connect(self._open_item)
        root.addWidget(self.list_widget, 1)

        buttons = QHBoxLayout()
        open_button = QPushButton("Kaydı Aç")
        open_button.setObjectName("Primary")
        open_button.clicked.connect(lambda: self._open_item(self.list_widget.currentItem()))
        buttons.addWidget(open_button)

        read_button = QPushButton("Tümünü Okundu İşaretle")
        read_button.clicked.connect(self._mark_all_read)
        buttons.addWidget(read_button)

        clear_button = QPushButton("Tümünü Sil")
        clear_button.clicked.connect(self._clear_all)
        buttons.addWidget(clear_button)

        buttons.addStretch()
        close_button = QPushButton("Kapat")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(close_button)
        root.addLayout(buttons)

        note = QLabel(
            "Bildirimler yalnızca uygulama içinde gösterilir. "
            "E-posta/SMS gönderimi bu sürümde kapsam dışıdır."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {style.TEXT_MUTED}; font-size: 8.5pt;")
        root.addWidget(note)

    def refresh(self) -> None:
        self.list_widget.clear()
        rows = notification_service.list_for_user(self.user.id)
        unread = sum(1 for row in rows if not row["is_read"])
        self.subtitle.setText(
            f"{len(rows)} bildirim · {unread} okunmamış" if rows else "Bildiriminiz yok"
        )

        if not rows:
            placeholder = QListWidgetItem("Henüz bildiriminiz yok.")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list_widget.addItem(placeholder)
            return

        for row in rows:
            marker = "●" if not row["is_read"] else "○"
            text = (
                f"{marker}  {row['title']}\n"
                f"      {row['message']}\n"
                f"      {fmt_datetime(row['created_at'])}"
            )
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, dict(row))
            if not row["is_read"]:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self.list_widget.addItem(item)

    def _open_item(self, item: QListWidgetItem | None) -> None:
        if item is None:
            QMessageBox.information(self, "Seçim yok", "Lütfen bir bildirim seçin.")
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return

        notification_service.mark_read(data["id"], self.user.id)
        if data["fault_id"]:
            self.open_fault_requested.emit(data["fault_id"])
            self.accept()
        else:
            self.refresh()

    def _mark_all_read(self) -> None:
        notification_service.mark_all_read(self.user.id)
        self.refresh()

    def _clear_all(self) -> None:
        confirm = QMessageBox.question(
            self, "Onay", "Tüm bildirimleriniz silinecek. Devam edilsin mi?"
        )
        if confirm == QMessageBox.StandardButton.Yes:
            notification_service.delete_all(self.user.id)
            self.refresh()
