"""Uygulama giriş noktası."""
from __future__ import annotations

import sys
import traceback

from PyQt6.QtWidgets import QApplication, QMessageBox

from app import config
from app.db import database as db
from app.ui import style
from app.ui.login_dialog import LoginDialog
from app.ui.main_window import MainWindow


def _install_exception_hook() -> None:
    """Beklenmeyen hatalarda uygulamanın sessizce kapanmasını engeller."""

    def hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return

        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        print(detail, file=sys.stderr)

        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Beklenmeyen hata")
        box.setText(
            "Uygulamada beklenmeyen bir hata oluştu.\n"
            "İşleminiz tamamlanmamış olabilir."
        )
        box.setInformativeText(str(exc_value))
        box.setDetailedText(detail)
        box.exec()

    sys.excepthook = hook


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setApplicationVersion(config.APP_VERSION)
    app.setOrganizationName(config.ORG_NAME)
    app.setStyle("Fusion")
    # Sistem koyu teması açık olsa da uygulama tek bir açık temada çalışır.
    app.setPalette(style.light_palette())
    app.setStyleSheet(style.STYLESHEET)

    _install_exception_hook()

    try:
        db.init_db()
    except Exception as exc:
        QMessageBox.critical(
            None, "Veritabanı hatası",
            f"Veritabanına bağlanılamadı:\n{exc}\n\n"
            f"Adres: {config.database_url_safe()}\n\n"
            "PostgreSQL sunucusunun çalıştığını ve .env dosyasındaki "
            "DATABASE_URL değerinin doğru olduğunu kontrol edin.",
        )
        return 1

    login = LoginDialog()
    if not login.exec() or login.user is None:
        return 0

    window = MainWindow(login.user)
    window.show()

    exit_code = app.exec()
    db.close_connection()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
