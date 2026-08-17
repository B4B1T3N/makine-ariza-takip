"""Bulut sürümüyle gelen davranışların testleri.

Bunlar Faz 1'de şemaya eklenen üç yeteneği kapsar:
  * client_uuid  -> çevrimdışı kuyruktan gelen kaydın iki kez yazılmaması
  * occurred_at  -> arızanın yazıldığı an ile sunucuya ulaştığı anın ayrılması
  * version      -> iki kişinin aynı kaydı aynı anda değiştirmesinin yakalanması
"""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app import config
from app.db import database as db
from app.services import fault_service, report_service
from app.services.fault_service import ConcurrentEditError
from app.utils.helpers import LOCAL_TZ, now_utc, today_local


# --- Çevrimdışı kuyruk: idempotency --------------------------------------
class TestCevrimdisiKuyruk:
    def test_ayni_uuid_ikinci_kez_kayit_acmaz(self, users, machines):
        """Bağlantı koptuğunda istemci aynı kaydı tekrar gönderir; kopyalanmamalı."""
        client_uuid = str(uuid.uuid4())

        first = fault_service.create_fault(
            machines[0], "Yağ kaçağı", "", config.PRIORITY_HIGH,
            users["operator"].id, client_uuid=client_uuid,
        )
        second = fault_service.create_fault(
            machines[0], "Yağ kaçağı", "", config.PRIORITY_HIGH,
            users["operator"].id, client_uuid=client_uuid,
        )

        assert first == second
        assert db.scalar("SELECT COUNT(*) FROM faults") == 1

    def test_farkli_uuid_ayri_kayit_acar(self, users, machines):
        for _ in range(2):
            fault_service.create_fault(
                machines[0], "Aynı başlık", "", config.PRIORITY_LOW,
                users["operator"].id, client_uuid=str(uuid.uuid4()),
            )
        assert db.scalar("SELECT COUNT(*) FROM faults") == 2

    def test_uuid_verilmezse_otomatik_uretilir(self, users, machines):
        fault_id = fault_service.create_fault(
            machines[0], "Arıza", "", config.PRIORITY_LOW, users["operator"].id
        )
        assert fault_service.get_fault(fault_id)["client_uuid"] is not None

    def test_uuid_ile_kayit_bulunabilir(self, users, machines):
        client_uuid = str(uuid.uuid4())
        fault_id = fault_service.create_fault(
            machines[0], "Arıza", "", config.PRIORITY_LOW,
            users["operator"].id, client_uuid=client_uuid,
        )
        found = fault_service.get_fault_by_client_uuid(client_uuid)
        assert found is not None and found["id"] == fault_id


# --- Cihaz saati vs sunucu saati -----------------------------------------
class TestOccurredAt:
    def test_gecmis_zamanli_kayit_korunur(self, users, machines):
        """Çevrimdışı yazılıp sonra senkronlanan kayıt kendi saatini korumalı."""
        yazilma_ani = now_utc() - timedelta(hours=3)

        fault_id = fault_service.create_fault(
            machines[0], "Çevrimdışı yazıldı", "", config.PRIORITY_HIGH,
            users["operator"].id, occurred_at=yazilma_ani,
        )
        row = fault_service.get_fault(fault_id)

        # occurred_at cihazın saatini, created_at sunucunun saatini taşır.
        assert abs((row["occurred_at"] - yazilma_ani).total_seconds()) < 2
        assert (row["created_at"] - row["occurred_at"]).total_seconds() > 3500

    def test_ileri_giden_cihaz_saati_kabul_edilmez(self, users, machines):
        """Cihaz saati yanlışsa gelecekten kayıt oluşmamalı."""
        gelecek = now_utc() + timedelta(days=2)

        fault_id = fault_service.create_fault(
            machines[0], "Saati ileri cihaz", "", config.PRIORITY_LOW,
            users["operator"].id, occurred_at=gelecek,
        )
        row = fault_service.get_fault(fault_id)
        assert row["occurred_at"] <= row["created_at"] + timedelta(seconds=2)

    def test_cozum_suresi_occurred_at_uzerinden_hesaplanir(self, users, machines):
        """Çevrimdışı gecikme çözüm süresini şişirmemeli."""
        yazilma_ani = now_utc() - timedelta(hours=5)
        fault_id = fault_service.create_fault(
            machines[0], "Arıza", "", config.PRIORITY_LOW,
            users["operator"].id, occurred_at=yazilma_ani,
        )
        fault_service.change_status(
            fault_id, users["technician"].id, config.STATUS_RESOLVED, "Çözüldü"
        )

        # occurred_at'ten bu yana ~5 saat geçti; created_at kullanılsaydı ~0 çıkardı.
        assert report_service.avg_resolution_hours() == pytest.approx(5, abs=0.2)

    def test_olusturma_logu_cihaz_saatini_tasir(self, users, machines):
        yazilma_ani = now_utc() - timedelta(hours=4)
        fault_id = fault_service.create_fault(
            machines[0], "Arıza", "", config.PRIORITY_LOW,
            users["operator"].id, occurred_at=yazilma_ani,
        )
        logs = fault_service.get_logs(fault_id)
        created_log = next(l for l in logs if l["action"] == config.LOG_CREATED)
        assert abs((created_log["created_at"] - yazilma_ani).total_seconds()) < 2


# --- İyimser kilitleme ----------------------------------------------------
class TestEszamanlıDuzenleme:
    def test_eski_surumle_degisiklik_reddedilir(self, users, machines):
        """İki teknisyen aynı kaydı açtı; ikincisi sessizce üzerine yazamamalı."""
        fault_id = fault_service.create_fault(
            machines[0], "Arıza", "", config.PRIORITY_LOW, users["operator"].id
        )
        gorulen_surum = fault_service.get_fault(fault_id)["version"]

        # Birinci teknisyen kaydı ilerletir.
        fault_service.change_status(
            fault_id, users["technician"].id, config.STATUS_IN_PROGRESS,
            "İnceliyorum", expected_version=gorulen_surum,
        )

        # İkincisi hâlâ eski sürümü elinde tutuyor.
        with pytest.raises(ConcurrentEditError):
            fault_service.change_status(
                fault_id, users["admin"].id, config.STATUS_WAITING,
                "Parça bekliyor", expected_version=gorulen_surum,
            )

    def test_guncel_surumle_degisiklik_gecer(self, users, machines):
        fault_id = fault_service.create_fault(
            machines[0], "Arıza", "", config.PRIORITY_LOW, users["operator"].id
        )
        surum = fault_service.get_fault(fault_id)["version"]

        fault_service.change_status(
            fault_id, users["technician"].id, config.STATUS_IN_PROGRESS,
            "", expected_version=surum,
        )
        yeni_surum = fault_service.get_fault(fault_id)["version"]
        assert yeni_surum > surum

        fault_service.change_status(
            fault_id, users["technician"].id, config.STATUS_WAITING,
            "", expected_version=yeni_surum,
        )
        assert fault_service.get_fault(fault_id)["status"] == config.STATUS_WAITING

    def test_surum_verilmezse_kontrol_yapilmaz(self, users, machines):
        """Masaüstü arayüz sürüm göndermez; çalışmaya devam etmeli."""
        fault_id = fault_service.create_fault(
            machines[0], "Arıza", "", config.PRIORITY_LOW, users["operator"].id
        )
        fault_service.change_status(
            fault_id, users["technician"].id, config.STATUS_IN_PROGRESS, ""
        )
        assert fault_service.get_fault(fault_id)["status"] == config.STATUS_IN_PROGRESS


# --- İşlem bütünlüğü ------------------------------------------------------
def test_gecersiz_gecis_yarim_kayit_birakmaz(users, machines):
    """Geçersiz geçiş denemesi yarım kayıt veya log bırakmamalı."""
    fault_id = fault_service.create_fault(
        machines[0], "Arıza", "", config.PRIORITY_LOW, users["operator"].id
    )
    log_sayisi = len(fault_service.get_logs(fault_id))

    with pytest.raises(Exception):
        fault_service.change_status(
            fault_id, users["technician"].id, config.STATUS_CLOSED, "Atlama denemesi"
        )

    assert len(fault_service.get_logs(fault_id)) == log_sayisi
    assert fault_service.get_fault(fault_id)["status"] == config.STATUS_OPEN


# --- Saat dilimi ----------------------------------------------------------
def test_gun_siniri_yerel_saate_gore(users, machines):
    """Rapor günü sunucunun UTC gününe değil tesisin gününe göre olmalı."""
    fault_service.create_fault(
        machines[0], "Bugünkü arıza", "", config.PRIORITY_LOW, users["operator"].id
    )
    assert report_service.summary()["opened_today"] == 1

    bugun = today_local().isoformat()
    assert len(fault_service.list_faults(date_from=bugun, date_to=bugun)) == 1


def test_zaman_damgalari_utc_saklanir(users, machines):
    fault_id = fault_service.create_fault(
        machines[0], "Arıza", "", config.PRIORITY_LOW, users["operator"].id
    )
    row = fault_service.get_fault(fault_id)

    # psycopg saat dilimi bilgili datetime döner.
    assert row["occurred_at"].tzinfo is not None
    # Yerel saate çevrilebilmeli.
    yerel = row["occurred_at"].astimezone(LOCAL_TZ)
    assert yerel.utcoffset() is not None
