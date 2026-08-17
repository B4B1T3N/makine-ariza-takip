"""Giriş ekranı."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app import config
from app.db import database as db
from app.services import auth_service
from app.services.auth_service import AuthError, CurrentUser
from app.ui import style


class LoginDialog(QDialog):
    """Kullanıcı adı/şifre ile giriş. Başarılıysa `user` alanı dolar."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.user: CurrentUser | None = None

        self.setWindowTitle(f"{config.APP_NAME} - Giriş")
        self.setModal(True)
        self.setFixedSize(400, 430)
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 28, 28, 24)
        outer.setSpacing(0)

        title = QLabel(config.APP_NAME)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"font-size: 17pt; font-weight: bold; color: {style.PRIMARY};"
        )
        subtitle = QLabel("Arıza kayıt ve bakım takip sistemi")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(f"color: {style.TEXT_MUTED}; padding-bottom: 6px;")

        outer.addWidget(title)
        outer.addWidget(subtitle)
        outer.addSpacing(18)

        card = QFrame()
        card.setObjectName("Card")
        form = QVBoxLayout(card)
        form.setContentsMargins(20, 18, 20, 18)
        form.setSpacing(6)

        form.addWidget(QLabel("Kullanıcı Adı"))
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("kullanıcı adınız")
        form.addWidget(self.username_input)

        form.addSpacing(8)
        form.addWidget(QLabel("Şifre"))
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("••••••")
        form.addWidget(self.password_input)

        form.addSpacing(6)
        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #c0392b; font-size: 9pt;")
        self.error_label.setVisible(False)
        form.addWidget(self.error_label)

        form.addSpacing(6)
        self.login_button = QPushButton("Giriş Yap")
        self.login_button.setObjectName("Primary")
        self.login_button.setDefault(True)
        self.login_button.setMinimumHeight(38)
        self.login_button.clicked.connect(self._attempt_login)
        form.addWidget(self.login_button)

        outer.addWidget(card)
        outer.addSpacing(14)

        if db.default_admin_pending():
            hint = QLabel(
                "İlk kurulum: <b>admin</b> / <b>admin</b><br>"
                "Giriş yaptıktan sonra şifrenizi değiştirin."
            )
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hint.setStyleSheet(
                "background: #fdf3d8; border: 1px solid #f0d68a;"
                "border-radius: 6px; padding: 10px; color: #7d6608; font-size: 9pt;"
            )
            outer.addWidget(hint)

        outer.addStretch()

        version = QLabel(f"Sürüm {config.APP_VERSION}")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version.setStyleSheet(f"color: {style.TEXT_MUTED}; font-size: 8.5pt;")
        outer.addWidget(version)

        self.username_input.returnPressed.connect(self.password_input.setFocus)
        self.password_input.returnPressed.connect(self._attempt_login)
        self.username_input.setFocus()

    def _attempt_login(self) -> None:
        try:
            self.user = auth_service.login(
                self.username_input.text(), self.password_input.text()
            )
        except AuthError as exc:
            self.error_label.setText(str(exc))
            self.error_label.setVisible(True)
            self.password_input.clear()
            self.password_input.setFocus()
            return
        except Exception as exc:  # Beklenmeyen veritabanı hataları
            QMessageBox.critical(self, "Hata", f"Giriş sırasında hata oluştu:\n{exc}")
            return
        self.accept()
