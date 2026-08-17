"""Arıza detay ekranı: durum akışı, notlar, geçmiş ve ekler."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QColor, QDesktopServices
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app import config
from app.services import auth_service, fault_service
from app.services.auth_service import CurrentUser
from app.services.fault_service import FaultError
from app.ui import style
from app.ui.widgets import common
from app.utils.helpers import fmt_datetime, humanize_duration, parse_sql

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}


class FaultDetailDialog(QDialog):
    """Tek bir arıza kaydının tüm bilgilerini gösterir ve işlem yapılmasını sağlar."""

    def __init__(self, user: CurrentUser, fault_id: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.user = user
        self.fault_id = fault_id
        self.changed = False

        self.setWindowTitle(f"Arıza Kaydı #{fault_id}")
        self.setModal(True)
        self.resize(880, 700)
        self._build()
        self.refresh()

    # --- Arayüz -----------------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)

        # Başlık bloğu
        self.header_card = QFrame()
        self.header_card.setObjectName("Card")
        header_layout = QVBoxLayout(self.header_card)
        header_layout.setContentsMargins(16, 14, 16, 14)
        header_layout.setSpacing(8)

        self.title_label = QLabel()
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet(
            f"font-size: 14pt; font-weight: bold; color: {style.PRIMARY};"
        )
        header_layout.addWidget(self.title_label)

        badge_row = QHBoxLayout()
        badge_row.setSpacing(8)
        self.status_badge = _Badge()
        self.priority_badge = _Badge()
        self.machine_label = QLabel()
        self.machine_label.setStyleSheet(f"color: {style.TEXT_MUTED};")
        badge_row.addWidget(self.status_badge)
        badge_row.addWidget(self.priority_badge)
        badge_row.addWidget(self.machine_label)
        badge_row.addStretch()
        header_layout.addLayout(badge_row)
        root.addWidget(self.header_card)

        # Bilgi + işlem sütunları
        columns = QHBoxLayout()
        columns.setSpacing(12)

        info_card = common.Card("Kayıt Bilgileri")
        info_card.setMinimumWidth(300)
        info_card.setMaximumWidth(340)
        self.info_body = QVBoxLayout()
        self.info_body.setSpacing(6)
        info_card.body().addLayout(self.info_body)
        info_card.body().addStretch()
        columns.addWidget(info_card)

        action_card = common.Card("İşlemler")
        self._build_actions(action_card)
        columns.addWidget(action_card, 1)
        root.addLayout(columns)

        # Sekmeler
        self.tabs = QTabWidget()

        self.log_list = QListWidget()
        self.log_list.setStyleSheet("QListWidget::item { padding: 8px 6px; }")
        self.log_list.setWordWrap(True)
        self.tabs.addTab(self.log_list, "Geçmiş")

        attach_page = QWidget()
        attach_layout = QVBoxLayout(attach_page)
        attach_layout.setContentsMargins(10, 10, 10, 10)
        attach_layout.setSpacing(8)

        attach_buttons = QHBoxLayout()
        self.add_file_button = QPushButton("Dosya/Fotoğraf Ekle")
        self.add_file_button.clicked.connect(self._add_attachment)
        self.open_file_button = QPushButton("Seçileni Aç")
        self.open_file_button.clicked.connect(self._open_attachment)
        self.delete_file_button = QPushButton("Seçileni Sil")
        self.delete_file_button.clicked.connect(self._delete_attachment)
        attach_buttons.addWidget(self.add_file_button)
        attach_buttons.addWidget(self.open_file_button)
        attach_buttons.addWidget(self.delete_file_button)
        attach_buttons.addStretch()
        attach_layout.addLayout(attach_buttons)

        self.attachment_list = QListWidget()
        self.attachment_list.itemDoubleClicked.connect(lambda _: self._open_attachment())
        attach_layout.addWidget(self.attachment_list)
        self.tabs.addTab(attach_page, "Ekler")

        root.addWidget(self.tabs, 1)

        footer = QHBoxLayout()
        footer.addStretch()
        close_button = QPushButton("Kapat")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        root.addLayout(footer)

    def _build_actions(self, card: common.Card) -> None:
        body = card.body()

        # Durum geçiş butonları
        self.status_hint = QLabel()
        self.status_hint.setStyleSheet(f"color: {style.TEXT_MUTED}; font-size: 9pt;")
        self.status_hint.setWordWrap(True)
        body.addWidget(self.status_hint)

        self.transition_row = QHBoxLayout()
        self.transition_row.setSpacing(6)
        transition_holder = QWidget()
        transition_holder.setLayout(self.transition_row)
        body.addWidget(transition_holder)

        # Atama
        assign_row = QHBoxLayout()
        assign_row.setSpacing(6)
        assign_label = QLabel("Atanan:")
        assign_label.setStyleSheet(f"color: {style.TEXT_MUTED};")
        self.assignee_combo = QComboBox()
        self.assignee_combo.addItem("— Atanmamış —", None)
        for row in auth_service.list_technicians():
            self.assignee_combo.addItem(row["full_name"], row["id"])
        self.assign_button = QPushButton("Ata")
        self.assign_button.clicked.connect(self._change_assignee)
        assign_row.addWidget(assign_label)
        assign_row.addWidget(self.assignee_combo, 1)
        assign_row.addWidget(self.assign_button)

        self.assign_widget = QWidget()
        self.assign_widget.setLayout(assign_row)
        self.assign_widget.setVisible(self.user.can_assign)
        body.addWidget(self.assign_widget)

        # Not ekleme
        note_label = QLabel("Not ekle")
        note_label.setStyleSheet(f"color: {style.TEXT_MUTED}; font-size: 9pt;")
        body.addWidget(note_label)

        self.note_input = QPlainTextEdit()
        self.note_input.setPlaceholderText(
            "Yapılan işlem, gözlem veya bilgilendirme notu yazın…"
        )
        self.note_input.setMaximumHeight(80)
        body.addWidget(self.note_input)

        note_row = QHBoxLayout()
        note_row.addStretch()
        self.edit_button = QPushButton("Kaydı Düzenle")
        self.edit_button.clicked.connect(self._edit_fault)
        self.note_button = QPushButton("Notu Kaydet")
        self.note_button.setObjectName("Primary")
        self.note_button.clicked.connect(self._add_note)
        note_row.addWidget(self.edit_button)
        note_row.addWidget(self.note_button)
        body.addLayout(note_row)

    # --- Veri yükleme -----------------------------------------------------
    def refresh(self) -> None:
        fault = fault_service.get_fault(self.fault_id)
        if fault is None:
            QMessageBox.warning(self, "Kayıt bulunamadı", "Arıza kaydı silinmiş olabilir.")
            self.reject()
            return
        self.fault = fault

        self.title_label.setText(f"#{fault['id']} — {fault['title']}")
        self.status_badge.set(
            config.STATUS_LABELS[fault["status"]], config.STATUS_COLORS[fault["status"]]
        )
        self.priority_badge.set(
            config.PRIORITY_LABELS[fault["priority"]],
            config.PRIORITY_COLORS[fault["priority"]],
        )
        self.machine_label.setText(
            f"{fault['machine_name']}"
            + (f" · {fault['machine_location']}" if fault["machine_location"] else "")
        )

        self._fill_info(fault)
        self._fill_transitions(fault)
        self._fill_logs()
        self._fill_attachments()

        index = self.assignee_combo.findData(fault["assignee_id"])
        self.assignee_combo.setCurrentIndex(index if index >= 0 else 0)

        can_edit = self.user.is_manager or fault["reporter_id"] == self.user.id
        is_closed = fault["status"] == config.STATUS_CLOSED
        self.edit_button.setEnabled(can_edit and not is_closed)
        self.note_button.setEnabled(not is_closed)
        self.note_input.setEnabled(not is_closed)
        self.add_file_button.setEnabled(not is_closed)
        self.assign_widget.setEnabled(self.user.can_assign and not is_closed)

    def _fill_info(self, fault) -> None:
        while self.info_body.count():
            item = self.info_body.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        duration = None
        created = parse_sql(fault["created_at"])
        end = parse_sql(fault["resolved_at"]) or parse_sql(fault["closed_at"])
        if created and end:
            duration = (end - created).total_seconds() / 3600

        rows = [
            ("Makine", fault["machine_name"]),
            ("Seri No", fault["machine_serial"] or "-"),
            ("Konum / Hat", fault["machine_location"] or "-"),
            ("Bildiren", fault["reporter_name"]),
            ("Atanan", fault["assignee_name"] or "Atanmamış"),
            ("Açılış", fmt_datetime(fault["created_at"])),
            ("Son Güncelleme", fmt_datetime(fault["updated_at"])),
            ("Çözüm", fmt_datetime(fault["resolved_at"])),
            ("Kapanış", fmt_datetime(fault["closed_at"])),
            ("Çözüm Süresi", humanize_duration(duration)),
        ]
        for label, value in rows:
            self.info_body.addWidget(common.field_row(label, common.value_label(value)))

        if fault["description"]:
            separator = QFrame()
            separator.setFrameShape(QFrame.Shape.HLine)
            separator.setStyleSheet(f"color: {style.BORDER};")
            self.info_body.addWidget(separator)

            desc_title = QLabel("Açıklama")
            desc_title.setStyleSheet(f"color: {style.TEXT_MUTED};")
            self.info_body.addWidget(desc_title)
            self.info_body.addWidget(common.value_label(fault["description"]))

    def _fill_transitions(self, fault) -> None:
        while self.transition_row.count():
            item = self.transition_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self.user.can_change_status:
            self.status_hint.setText(
                "Durum güncelleme yetkiniz yok. Bakım ekibi kaydı işleme alacaktır."
            )
            return

        targets = fault_service.available_transitions(fault["status"])
        if not targets:
            self.status_hint.setText("Bu kayıt kapatılmıştır, durum değiştirilemez.")
            return

        self.status_hint.setText(
            f"Mevcut durum: {config.STATUS_LABELS[fault['status']]} — "
            "yeni durumu seçin:"
        )
        for target in targets:
            button = QPushButton(config.STATUS_LABELS[target])
            if target == config.STATUS_RESOLVED:
                button.setObjectName("Success")
            elif target == config.STATUS_CLOSED:
                button.setObjectName("Primary")
            button.clicked.connect(lambda _, t=target: self._change_status(t))
            self.transition_row.addWidget(button)
        self.transition_row.addStretch()

    def _fill_logs(self) -> None:
        self.log_list.clear()
        logs = fault_service.get_logs(self.fault_id)
        if not logs:
            self.log_list.addItem("Henüz kayıt geçmişi yok.")
            return

        for log in logs:
            action = config.LOG_LABELS.get(log["action"], log["action"])
            detail = ""
            if log["action"] == config.LOG_STATUS:
                detail = (
                    f"{config.STATUS_LABELS.get(log['old_value'], log['old_value'])} → "
                    f"{config.STATUS_LABELS.get(log['new_value'], log['new_value'])}"
                )
            elif log["action"] == config.LOG_ASSIGN and log["note"]:
                detail = log["note"]
            elif log["new_value"] and log["action"] == config.LOG_ATTACHMENT:
                detail = log["new_value"]

            text = f"[{fmt_datetime(log['created_at'])}]  {log['user_name'] or 'Sistem'}  •  {action}"
            if detail:
                text += f"\n    {detail}"
            if log["note"] and log["action"] in (config.LOG_NOTE, config.LOG_STATUS, config.LOG_EDIT):
                text += f"\n    “{log['note']}”"

            item = QListWidgetItem(text)
            if log["action"] == config.LOG_STATUS:
                item.setForeground(style.status_color(log["new_value"] or ""))
            self.log_list.addItem(item)
        self.log_list.scrollToBottom()

    def _fill_attachments(self) -> None:
        self.attachment_list.clear()
        rows = fault_service.list_attachments(self.fault_id)
        if not rows:
            placeholder = QListWidgetItem("Bu kayda eklenmiş dosya yok.")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.attachment_list.addItem(placeholder)
            self.open_file_button.setEnabled(False)
            self.delete_file_button.setEnabled(False)
            return

        self.open_file_button.setEnabled(True)
        self.delete_file_button.setEnabled(True)
        for row in rows:
            suffix = Path(row["file_name"]).suffix.lower()
            icon = "🖼" if suffix in IMAGE_SUFFIXES else "📄"
            item = QListWidgetItem(
                f"{icon}  {row['file_name']}\n"
                f"      {row['uploader_name'] or 'Bilinmiyor'} · {fmt_datetime(row['created_at'])}"
            )
            item.setData(Qt.ItemDataRole.UserRole, dict(row))
            self.attachment_list.addItem(item)

    # --- İşlemler ---------------------------------------------------------
    def _change_status(self, new_status: str) -> None:
        requires_note = new_status in (config.STATUS_RESOLVED, config.STATUS_CLOSED)
        prompt = (
            "Yapılan işlemi kısaca açıklayın (zorunlu):" if requires_note
            else "İsterseniz bir açıklama ekleyin:"
        )
        note, ok = QInputDialog.getMultiLineText(
            self,
            f"Durum: {config.STATUS_LABELS[new_status]}",
            prompt,
            self.note_input.toPlainText().strip(),
        )
        if not ok:
            return

        try:
            fault_service.change_status(self.fault_id, self.user.id, new_status, note)
        except FaultError as exc:
            QMessageBox.warning(self, "İşlem yapılamadı", str(exc))
            return

        self.note_input.clear()
        self.changed = True
        self.refresh()

    def _change_assignee(self) -> None:
        try:
            fault_service.assign(
                self.fault_id, self.user.id, self.assignee_combo.currentData()
            )
        except FaultError as exc:
            QMessageBox.warning(self, "Atama yapılamadı", str(exc))
            return
        self.changed = True
        self.refresh()

    def _add_note(self) -> None:
        note = self.note_input.toPlainText().strip()
        if not note:
            QMessageBox.information(self, "Boş not", "Lütfen bir not yazın.")
            return
        try:
            fault_service.add_note(self.fault_id, self.user.id, note)
        except FaultError as exc:
            QMessageBox.warning(self, "Not eklenemedi", str(exc))
            return
        self.note_input.clear()
        self.changed = True
        self.refresh()

    def _edit_fault(self) -> None:
        from app.ui.fault_dialog import FaultDialog

        dialog = FaultDialog(self.user, fault=self.fault, parent=self)
        if dialog.exec():
            self.changed = True
            self.refresh()

    def _add_attachment(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Eklenecek dosyaları seçin",
            "",
            "Tüm Dosyalar (*.*);;Görseller (*.png *.jpg *.jpeg *.bmp *.gif);;PDF (*.pdf)",
        )
        if not paths:
            return

        errors = []
        for path in paths:
            try:
                fault_service.add_attachment(self.fault_id, self.user.id, path)
            except (FaultError, OSError) as exc:
                errors.append(f"{Path(path).name}: {exc}")

        if errors:
            QMessageBox.warning(self, "Bazı dosyalar eklenemedi", "\n".join(errors))
        self.changed = True
        self.refresh()
        self.tabs.setCurrentIndex(1)

    def _selected_attachment(self) -> dict | None:
        item = self.attachment_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _open_attachment(self) -> None:
        data = self._selected_attachment()
        if not data:
            QMessageBox.information(self, "Seçim yok", "Lütfen bir dosya seçin.")
            return

        path = fault_service.attachment_path(data["stored_name"])
        if not path.exists():
            QMessageBox.warning(
                self, "Dosya bulunamadı",
                "Ek dosyası diskte bulunamadı. Yedekten geri yüklenmiş olabilir."
            )
            return
        _open_in_system(path)

    def _delete_attachment(self) -> None:
        data = self._selected_attachment()
        if not data:
            QMessageBox.information(self, "Seçim yok", "Lütfen bir dosya seçin.")
            return
        if not (self.user.is_manager or data["uploaded_by"] == self.user.id):
            QMessageBox.warning(
                self, "Yetki yok", "Yalnızca ekleyen kişi veya yönetici silebilir."
            )
            return

        confirm = QMessageBox.question(
            self, "Ek silinsin mi?",
            f"'{data['file_name']}' kalıcı olarak silinecek. Onaylıyor musunuz?",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        fault_service.delete_attachment(data["id"])
        self.changed = True
        self._fill_attachments()


class _Badge(QLabel):
    """Renkli durum/öncelik etiketi (metin her zaman görünür)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set(self, text: str, color: str) -> None:
        self.setText(f"  {text}  ")
        # Qt stylesheet'te 8 haneli hex #AARRGGBB olarak yorumlanır; şeffaflık
        # için rgba() kullanmak gerekir.
        rgb = QColor(color)
        fill = f"rgba({rgb.red()}, {rgb.green()}, {rgb.blue()}, 0.13)"
        edge = f"rgba({rgb.red()}, {rgb.green()}, {rgb.blue()}, 0.40)"
        self.setStyleSheet(
            f"background: {fill}; color: {rgb.darker(115).name()};"
            f"border: 1px solid {edge};"
            "border-radius: 10px; padding: 3px 10px; font-weight: bold; font-size: 9pt;"
        )


def _open_in_system(path: Path) -> None:
    """Dosyayı işletim sisteminin varsayılan uygulamasıyla açar."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
    except OSError:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
