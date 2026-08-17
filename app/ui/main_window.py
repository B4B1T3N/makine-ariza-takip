"""Ana pencere: sol menü, sayfa yönlendirme ve rol bazlı görünürlük."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from app import config
from app.db import database as db
from app.services import backup_service, notification_service
from app.services.auth_service import CurrentUser
from app.services.backup_service import BackupError
from app.ui.dashboard_view import DashboardView
from app.ui.faults_view import FaultsView
from app.ui.machines_view import MachinesView
from app.ui.notifications_dialog import NotificationsDialog
from app.ui.reports_view import ReportsView
from app.ui.user_dialog import ChangePasswordDialog
from app.ui.users_view import UsersView

NOTIFICATION_POLL_MS = 30_000


class MainWindow(QMainWindow):
    """Uygulamanın ana çerçevesi."""

    def __init__(self, user: CurrentUser):
        super().__init__()
        self.user = user
        self.restart_required = False

        self.setWindowTitle(f"{config.APP_NAME} — {user.full_name} ({user.role_label})")
        self.resize(1320, 860)
        self.setMinimumSize(1080, 700)

        self._build()
        self._check_default_password()

        self.notification_timer = QTimer(self)
        self.notification_timer.timeout.connect(self._update_notification_badge)
        self.notification_timer.start(NOTIFICATION_POLL_MS)

    # --- Arayüz -----------------------------------------------------------
    def _build(self) -> None:
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self._build_pages()

        self.setStatusBar(QStatusBar())
        self._set_status(f"{config.APP_NAME} {config.APP_VERSION} · "
                         f"Veritabanı: {config.database_url_safe()}")

        self.nav_list.setCurrentRow(0)
        self._update_notification_badge()

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(226)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title = QLabel("Makine Arıza\nTakip")
        title.setObjectName("SidebarTitle")
        layout.addWidget(title)

        subtitle = QLabel(f"{self.user.full_name}\n{self.user.role_label}")
        subtitle.setObjectName("SidebarSubtitle")
        layout.addWidget(subtitle)

        self.nav_list = QListWidget()
        self.nav_list.setObjectName("NavList")
        self.nav_list.currentRowChanged.connect(self._on_nav_changed)
        layout.addWidget(self.nav_list, 1)

        # Alt aksiyonlar
        actions = QWidget()
        actions_layout = QVBoxLayout(actions)
        actions_layout.setContentsMargins(10, 6, 10, 6)
        actions_layout.setSpacing(6)

        self.notification_button = QPushButton("Bildirimler")
        self.notification_button.clicked.connect(self.open_notifications)
        actions_layout.addWidget(self.notification_button)

        self.menu_button = QPushButton("Ayarlar")
        self.menu_button.clicked.connect(self._show_settings_menu)
        actions_layout.addWidget(self.menu_button)

        logout_button = QPushButton("Çıkış Yap")
        logout_button.clicked.connect(self.close)
        actions_layout.addWidget(logout_button)

        layout.addWidget(actions)

        footer = QLabel(f"Sürüm {config.APP_VERSION}")
        footer.setObjectName("SidebarFooter")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(footer)
        return sidebar

    def _build_pages(self) -> None:
        """Rol yetkisine göre sayfaları ekler."""
        self.pages: dict[str, QWidget] = {}
        self.page_order: list[str] = []

        self.dashboard = DashboardView(self.user)
        self.dashboard.open_fault_requested.connect(self.open_fault)
        self.dashboard.new_fault_requested.connect(self._new_fault_from_dashboard)
        self._add_page("dashboard", "  Ana Sayfa", self.dashboard)

        self.faults = FaultsView(self.user)
        self._add_page("faults", "  Arıza Kayıtları", self.faults)

        self.machines = MachinesView(self.user)
        self._add_page("machines", "  Makine Envanteri", self.machines)

        if self.user.can_view_reports:
            self.reports = ReportsView(self.user)
            self._add_page("reports", "  Raporlar", self.reports)

        if self.user.can_manage_users:
            self.users = UsersView(self.user)
            self._add_page("users", "  Kullanıcılar", self.users)

    def _add_page(self, key: str, label: str, widget: QWidget) -> None:
        self.pages[key] = widget
        self.page_order.append(key)
        self.stack.addWidget(widget)
        self.nav_list.addItem(QListWidgetItem(label))

    # --- Gezinme ----------------------------------------------------------
    def _on_nav_changed(self, row: int) -> None:
        if row < 0 or row >= len(self.page_order):
            return
        self.stack.setCurrentIndex(row)
        self._refresh_current_page()

    def _refresh_current_page(self) -> None:
        key = self.page_order[self.stack.currentIndex()]
        widget = self.pages[key]

        # Makine listesi değiştiyse arıza filtreleri tazelensin.
        if key == "faults" and getattr(self.machines, "changed", False):
            self.faults.reload_machines()
            self.machines.changed = False

        if hasattr(widget, "refresh"):
            widget.refresh()
        self._update_notification_badge()

    def go_to(self, key: str) -> None:
        if key in self.page_order:
            self.nav_list.setCurrentRow(self.page_order.index(key))

    def open_fault(self, fault_id: int) -> None:
        self.go_to("faults")
        self.faults.open_fault(fault_id)
        self._update_notification_badge()

    def _new_fault_from_dashboard(self) -> None:
        if self.faults.create_fault():
            self.dashboard.refresh()
        self._update_notification_badge()

    # --- Bildirimler ------------------------------------------------------
    def _update_notification_badge(self) -> None:
        try:
            count = notification_service.unread_count(self.user.id)
        except Exception:
            return  # Bildirim sayacı ana akışı bozmamalı.

        if count:
            self.notification_button.setText(f"Bildirimler ({count})")
            self.notification_button.setStyleSheet(
                "background: #d03b3b; color: white; border: none; font-weight: bold;"
            )
        else:
            self.notification_button.setText("Bildirimler")
            self.notification_button.setStyleSheet("")

    def open_notifications(self) -> None:
        dialog = NotificationsDialog(self.user, parent=self)
        dialog.open_fault_requested.connect(self.open_fault)
        dialog.exec()
        self._update_notification_badge()

    # --- Ayarlar menüsü ---------------------------------------------------
    def _show_settings_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction("Şifremi Değiştir", self._change_password)
        menu.addSeparator()
        menu.addAction("Yedek Al (veritabanı)", self._backup_database)
        menu.addAction("Tam Yedek Al (veritabanı + ekler)", self._backup_full)
        if self.user.is_manager:
            menu.addAction("Yedekten Geri Yükle…", self._restore_backup)
        menu.addSeparator()
        menu.addAction("Veri Klasörünü Göster", self._show_data_dir)
        menu.addAction("Hakkında", self._show_about)

        menu.exec(self.menu_button.mapToGlobal(self.menu_button.rect().topRight()))

    def _change_password(self) -> None:
        dialog = ChangePasswordDialog(self.user.id, parent=self)
        dialog.exec()

    def _backup_database(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Veritabanı yedeğini kaydet",
            str(config.backups_dir() / backup_service.default_backup_name()),
            "PostgreSQL Yedeği (*.dump)",
        )
        if not path:
            return
        try:
            saved = backup_service.backup_database(path)
        except BackupError as exc:
            QMessageBox.warning(self, "Yedek alınamadı", str(exc))
            return

        size_mb = saved.stat().st_size / (1024 * 1024)
        QMessageBox.information(
            self, "Yedek alındı",
            f"Veritabanı yedeği oluşturuldu:\n{saved}\n\nBoyut: {size_mb:.1f} MB",
        )
        self._set_status(f"Yedek alındı: {saved}")

    def _backup_full(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Tam yedeği kaydet",
            str(config.backups_dir() / backup_service.default_backup_name(as_zip=True)),
            "ZIP Arşivi (*.zip)",
        )
        if not path:
            return
        try:
            saved = backup_service.backup_full(path)
        except BackupError as exc:
            QMessageBox.warning(self, "Yedek alınamadı", str(exc))
            return

        size_mb = saved.stat().st_size / (1024 * 1024)
        QMessageBox.information(
            self, "Tam yedek alındı",
            f"Veritabanı ve ek dosyaları arşivlendi:\n{saved}\n\nBoyut: {size_mb:.1f} MB",
        )
        self._set_status(f"Tam yedek alındı: {saved}")

    def _restore_backup(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Geri yüklenecek yedeği seçin",
            str(config.backups_dir()), "PostgreSQL Yedeği (*.dump)",
        )
        if not path:
            return

        confirm = QMessageBox.warning(
            self, "Geri yükleme onayı",
            "Mevcut veritabanının yerine seçilen yedek konulacak.\n\n"
            "• Şu anki veriler otomatik olarak yedekler klasörüne kopyalanır.\n"
            "• İşlem sonrası uygulama kapanacak, yeniden açmanız gerekir.\n\n"
            "Devam etmek istiyor musunuz?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        try:
            backup_service.restore_database(path)
        except BackupError as exc:
            QMessageBox.warning(self, "Geri yüklenemedi", str(exc))
            return

        QMessageBox.information(
            self, "Geri yüklendi",
            "Yedek geri yüklendi. Uygulama şimdi kapanacak, tekrar açın.",
        )
        self.restart_required = True
        self.close()

    def _show_data_dir(self) -> None:
        import os
        import sys

        path = config.data_dir()
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                from PyQt6.QtCore import QUrl
                from PyQt6.QtGui import QDesktopServices
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        except OSError:
            QMessageBox.information(self, "Veri klasörü", str(path))

    def _show_about(self) -> None:
        QMessageBox.about(
            self, f"{config.APP_NAME} Hakkında",
            f"<h3>{config.APP_NAME}</h3>"
            f"<p>Sürüm {config.APP_VERSION}</p>"
            "<p>Üretim tesisleri için çevrimdışı çalışan arıza kayıt ve "
            "bakım takip sistemi.</p>"
            f"<p><b>Veri klasörü:</b><br>{config.data_dir()}</p>"
            f"<p><b>Veritabanı:</b><br>{config.database_url_safe()}</p>",
        )

    def _check_default_password(self) -> None:
        """Varsayılan admin şifresi değiştirilmediyse uyarır."""
        if self.user.username.lower() == "admin" and db.default_admin_pending():
            QMessageBox.warning(
                self, "Güvenlik uyarısı",
                "Varsayılan yönetici şifresi hâlâ kullanımda.\n\n"
                "Ayarlar → Şifremi Değiştir menüsünden şifrenizi güncelleyin.",
            )

    def _set_status(self, message: str) -> None:
        self.statusBar().showMessage(message)

    # --- Kapanış ----------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802 (Qt isimlendirmesi)
        if self.restart_required:
            event.accept()
            return

        confirm = QMessageBox.question(
            self, "Çıkış",
            "Uygulamadan çıkmak istediğinize emin misiniz?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            event.accept()
        else:
            event.ignore()
