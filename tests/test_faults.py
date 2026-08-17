"""Arıza kaydı, durum akışı, geçmiş ve filtreleme testleri."""
from __future__ import annotations

import pytest

from app import config
from app.services import fault_service
from app.services.fault_service import FaultError


@pytest.fixture()
def fault(users, machines):
    return fault_service.create_fault(
        machines[0], "Yağ kaçağı", "Detaylı açıklama",
        config.PRIORITY_HIGH, users["operator"].id,
    )


def test_kayit_acik_durumda_baslar(fault):
    row = fault_service.get_fault(fault)
    assert row["status"] == config.STATUS_OPEN
    assert row["resolved_at"] is None
    assert row["created_at"] and row["updated_at"]


def test_zorunlu_alanlar(users, machines):
    with pytest.raises(FaultError, match="başlığı boş"):
        fault_service.create_fault(
            machines[0], "  ", "", config.PRIORITY_LOW, users["operator"].id
        )
    with pytest.raises(FaultError, match="Makine seçiniz"):
        fault_service.create_fault(
            None, "Başlık", "", config.PRIORITY_LOW, users["operator"].id
        )
    with pytest.raises(FaultError, match="bulunamadı"):
        fault_service.create_fault(
            9999, "Başlık", "", config.PRIORITY_LOW, users["operator"].id
        )


def test_tam_durum_akisi(fault, users):
    technician, manager = users["technician"].id, users["admin"].id

    fault_service.change_status(fault, technician, config.STATUS_IN_PROGRESS, "Bakıldı")
    fault_service.change_status(fault, technician, config.STATUS_WAITING, "Parça bekleniyor")
    fault_service.change_status(fault, technician, config.STATUS_RESOLVED, "Conta değişti")

    row = fault_service.get_fault(fault)
    assert row["status"] == config.STATUS_RESOLVED
    assert row["resolved_at"] is not None

    fault_service.change_status(fault, manager, config.STATUS_CLOSED, "Kontrol edildi")
    row = fault_service.get_fault(fault)
    assert row["status"] == config.STATUS_CLOSED
    assert row["closed_at"] is not None


def test_gecersiz_durum_gecisi_reddedilir(fault, users):
    with pytest.raises(FaultError, match="geçilemez"):
        fault_service.change_status(
            fault, users["technician"].id, config.STATUS_CLOSED, "Not"
        )


def test_ayni_duruma_gecis_reddedilir(fault, users):
    with pytest.raises(FaultError, match="zaten bu durumda"):
        fault_service.change_status(
            fault, users["technician"].id, config.STATUS_OPEN, ""
        )


def test_cozum_icin_aciklama_zorunlu(fault, users):
    with pytest.raises(FaultError, match="açıklama girilmesi zorunlu"):
        fault_service.change_status(
            fault, users["technician"].id, config.STATUS_RESOLVED, "   "
        )


def test_kapali_kayit_degistirilemez(fault, users):
    technician = users["technician"].id
    fault_service.change_status(fault, technician, config.STATUS_RESOLVED, "Çözüldü")
    fault_service.change_status(fault, technician, config.STATUS_CLOSED, "Kapatıldı")

    assert fault_service.available_transitions(config.STATUS_CLOSED) == ()
    with pytest.raises(FaultError):
        fault_service.change_status(fault, technician, config.STATUS_OPEN, "Tekrar")


def test_yeniden_acilinca_cozum_tarihi_sifirlanir(fault, users):
    technician = users["technician"].id
    fault_service.change_status(fault, technician, config.STATUS_RESOLVED, "Çözüldü")
    assert fault_service.get_fault(fault)["resolved_at"] is not None

    fault_service.change_status(fault, technician, config.STATUS_IN_PROGRESS, "Tekrarladı")
    assert fault_service.get_fault(fault)["resolved_at"] is None


def test_gecmis_kaydi_tutulur(fault, users):
    technician = users["technician"].id
    fault_service.assign(fault, technician, technician)
    fault_service.change_status(fault, technician, config.STATUS_IN_PROGRESS, "Bakılıyor")
    fault_service.add_note(fault, technician, "Ara bilgilendirme")

    logs = fault_service.get_logs(fault)
    actions = [log["action"] for log in logs]

    assert config.LOG_CREATED in actions
    assert config.LOG_ASSIGN in actions
    assert config.LOG_STATUS in actions
    assert config.LOG_NOTE in actions
    # Her kayıtta kim / ne zaman bilgisi bulunmalı.
    assert all(log["created_at"] for log in logs)
    assert all(log["user_name"] for log in logs)

    status_log = next(log for log in logs if log["action"] == config.LOG_STATUS)
    assert status_log["old_value"] == config.STATUS_OPEN
    assert status_log["new_value"] == config.STATUS_IN_PROGRESS
    assert status_log["note"] == "Bakılıyor"


def test_bos_not_reddedilir(fault, users):
    with pytest.raises(FaultError, match="Not boş"):
        fault_service.add_note(fault, users["technician"].id, "   ")


def test_atama_degisikligi_loglanir(fault, users):
    technician = users["technician"].id
    fault_service.assign(fault, users["admin"].id, technician)
    assert fault_service.get_fault(fault)["assignee_id"] == technician

    fault_service.assign(fault, users["admin"].id, None)
    assert fault_service.get_fault(fault)["assignee_id"] is None

    assign_logs = [
        log for log in fault_service.get_logs(fault)
        if log["action"] == config.LOG_ASSIGN
    ]
    assert len(assign_logs) == 2


def test_oncelik_degisikligi_loglanir(fault, users, machines):
    fault_service.update_fault(
        fault, users["admin"].id, machines[0], "Yağ kaçağı", "Detaylı açıklama",
        config.PRIORITY_URGENT,
    )
    assert fault_service.get_fault(fault)["priority"] == config.PRIORITY_URGENT
    edit_logs = [
        log for log in fault_service.get_logs(fault)
        if log["action"] == config.LOG_EDIT
    ]
    assert edit_logs and "Öncelik" in edit_logs[0]["note"]


class TestFiltreleme:
    @pytest.fixture(autouse=True)
    def veri(self, users, machines):
        self.users, self.machines = users, machines
        self.f1 = fault_service.create_fault(
            machines[0], "Titreşim var", "", config.PRIORITY_URGENT, users["operator"].id
        )
        self.f2 = fault_service.create_fault(
            machines[1], "Ekran donuyor", "", config.PRIORITY_LOW, users["admin"].id
        )
        fault_service.assign(self.f2, users["admin"].id, users["technician"].id)
        fault_service.change_status(
            self.f2, users["technician"].id, config.STATUS_RESOLVED, "Bitti"
        )

    def test_tumu(self):
        assert len(fault_service.list_faults()) == 2

    def test_sadece_acik(self):
        rows = fault_service.list_faults(only_active=True)
        assert [r["id"] for r in rows] == [self.f1]

    def test_makineye_gore(self):
        assert len(fault_service.list_faults(machine_id=self.machines[1])) == 1

    def test_oncelige_gore(self):
        rows = fault_service.list_faults(priorities=[config.PRIORITY_URGENT])
        assert [r["id"] for r in rows] == [self.f1]

    def test_duruma_gore(self):
        rows = fault_service.list_faults(statuses=[config.STATUS_RESOLVED])
        assert [r["id"] for r in rows] == [self.f2]

    def test_metin_aramasi(self):
        assert len(fault_service.list_faults(search="donuyor")) == 1
        assert len(fault_service.list_faults(search="bulunmayan")) == 0

    def test_kayit_no_ile_arama(self):
        # Arama kayıt no, başlık, açıklama ve makine adında birlikte çalışır;
        # aranan kaydın sonuçta bulunması yeterlidir.
        rows = fault_service.list_faults(search=str(self.f1))
        assert self.f1 in [row["id"] for row in rows]

    def test_bildirene_gore(self):
        rows = fault_service.list_faults(reporter_id=self.users["operator"].id)
        assert [r["id"] for r in rows] == [self.f1]

    def test_atanana_gore(self):
        rows = fault_service.list_faults(assignee_id=self.users["technician"].id)
        assert [r["id"] for r in rows] == [self.f2]

    def test_tarih_araligi(self):
        assert len(fault_service.list_faults(date_from="2000-01-01", date_to="2000-12-31")) == 0
        assert len(fault_service.list_faults(date_from="2000-01-01", date_to="2100-01-01")) == 2

    def test_acil_kayit_once_siralanir(self):
        rows = fault_service.list_faults()
        assert rows[0]["id"] == self.f1  # Acil ve açık olan üstte


def test_ek_dosya_ekleme_ve_silme(fault, users, tmp_path):
    sample = tmp_path / "foto.png"
    sample.write_bytes(b"sahte-goruntu")

    fault_service.add_attachment(fault, users["operator"].id, str(sample))
    attachments = fault_service.list_attachments(fault)
    assert len(attachments) == 1
    assert fault_service.attachment_path(attachments[0]["stored_name"]).exists()
    assert attachments[0]["file_name"] == "foto.png"

    fault_service.delete_attachment(attachments[0]["id"])
    assert fault_service.list_attachments(fault) == []


def test_olmayan_dosya_eklenemez(fault, users, tmp_path):
    with pytest.raises(FaultError, match="bulunamadı"):
        fault_service.add_attachment(fault, users["operator"].id, str(tmp_path / "yok.png"))
