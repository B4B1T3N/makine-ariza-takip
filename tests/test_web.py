"""Web arayüzü (Faz 2) uçtan uca testleri.

Buradaki testler HTTP katmanını sınar: oturum, yetki, CSRF, sayfalama,
iyimser kilitleme ve çevrimdışı kuyruğun idempotency sözü. İş kurallarının
kendisi servis testlerinde zaten kapsanıyor.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app import config


# --- Ortak yardımcılar ----------------------------------------------------
def _csrf(html: str) -> str:
    eslesme = re.search(r'name="csrf-token" content="([^"]+)"', html)
    assert eslesme, "Sayfada CSRF etiketi yok"
    return eslesme.group(1)


def _token(istemci, yol: str = "/giris") -> str:
    return _csrf(istemci.get(yol).text)


def giris_yap(istemci, kullanici_adi: str, sifre: str = "1234"):
    yanit = istemci.post(
        "/giris",
        data={
            "kullanici_adi": kullanici_adi,
            "sifre": sifre,
            "csrf": _token(istemci),
        },
        follow_redirects=False,
    )
    return yanit


@pytest.fixture()
def istemci(app_db):
    from fastapi.testclient import TestClient

    from app.web.main import create_app

    return TestClient(create_app())


@pytest.fixture()
def ariza(users, machines):
    """Operatörün açtığı tek bir arıza kaydı."""
    from app.services import fault_service

    return fault_service.create_fault(
        machine_id=machines[0],
        title="Yağ sızıntısı",
        description="Pres altında yağ birikiyor.",
        priority=config.PRIORITY_HIGH,
        reporter_id=users["operator"].id,
    )


# --- Oturum ---------------------------------------------------------------
def test_oturumsuz_istek_giris_sayfasina_yonlendirir(istemci):
    yanit = istemci.get("/arizalar", follow_redirects=False)
    assert yanit.status_code == 303
    assert yanit.headers["location"].startswith("/giris")


def test_hatali_sifre_reddedilir(istemci, users):
    yanit = istemci.post(
        "/giris",
        data={"kullanici_adi": "op", "sifre": "yanlis", "csrf": _token(istemci)},
        follow_redirects=False,
    )
    assert yanit.status_code == 401
    assert "hatalı" in yanit.text.lower()


def test_giris_ve_cikis(istemci, users):
    assert giris_yap(istemci, "op").status_code == 303
    assert istemci.get("/arizalar").status_code == 200

    yanit = istemci.post(
        "/cikis", data={"csrf": _token(istemci, "/arizalar")}, follow_redirects=False
    )
    assert yanit.status_code == 303
    assert istemci.get("/arizalar", follow_redirects=False).status_code == 303


def test_giris_sonrasi_hedefe_donulur(istemci, users, ariza):
    yanit = istemci.get(f"/arizalar/{ariza}", follow_redirects=False)
    assert "devam=" in yanit.headers["location"]

    yanit = istemci.post(
        "/giris",
        data={
            "kullanici_adi": "op",
            "sifre": "1234",
            "devam": f"/arizalar/{ariza}",
            "csrf": _token(istemci),
        },
        follow_redirects=False,
    )
    assert yanit.headers["location"] == f"/arizalar/{ariza}"


def test_baska_siteye_yonlendirme_engellenir(istemci, users):
    """`devam` parametresi dış adrese işaret ederse yok sayılmalı."""
    yanit = istemci.post(
        "/giris",
        data={
            "kullanici_adi": "op",
            "sifre": "1234",
            "devam": "//kotu-site.example",
            "csrf": _token(istemci),
        },
        follow_redirects=False,
    )
    assert yanit.headers["location"] == "/arizalar"


def test_pasife_alinan_kullanicinin_oturumu_duser(istemci, users):
    from app.services import auth_service

    giris_yap(istemci, "op")
    assert istemci.get("/arizalar").status_code == 200

    auth_service.update_user(
        users["operator"].id, "Operatör Kişi", config.ROLE_OPERATOR, is_active=False
    )
    assert istemci.get("/arizalar", follow_redirects=False).status_code == 303


def test_csrf_olmadan_gonderim_reddedilir(istemci, users, machines):
    giris_yap(istemci, "op")
    yanit = istemci.post(
        "/arizalar/yeni",
        data={"makine_id": machines[0], "baslik": "Test", "csrf": "sahte"},
    )
    assert yanit.status_code == 400
    assert "doğrulanamadı" in yanit.text


# --- Liste ve görünürlük --------------------------------------------------
def test_operator_yalnizca_kendi_kaydini_gorur(istemci, users, machines, ariza):
    from app.services import fault_service

    baskasinin = fault_service.create_fault(
        machine_id=machines[1],
        title="Teknisyenin kaydı",
        description="",
        priority=config.PRIORITY_LOW,
        reporter_id=users["technician"].id,
    )

    giris_yap(istemci, "op")
    liste = istemci.get("/arizalar").text
    assert "Yağ sızıntısı" in liste
    assert "Teknisyenin kaydı" not in liste

    # Adres çubuğundan doğrudan erişim de kapalı olmalı.
    assert istemci.get(f"/arizalar/{baskasinin}").status_code == 403


def test_teknisyen_tum_kayitlari_gorur(istemci, users, machines, ariza):
    giris_yap(istemci, "tk")
    assert "Yağ sızıntısı" in istemci.get("/arizalar").text


def test_filtreler_ve_sayfalama(istemci, users, machines):
    from app.services import fault_service

    for i in range(30):
        fault_service.create_fault(
            machine_id=machines[0],
            title=f"Kayıt {i}",
            description="",
            priority=config.PRIORITY_LOW,
            reporter_id=users["technician"].id,
        )

    giris_yap(istemci, "tk")

    ilk = istemci.get("/arizalar").text
    assert "30 kayıt bulundu" in ilk
    assert ilk.count('<tr onclick') == 25

    ikinci = istemci.get("/arizalar?sayfa=2").text
    assert ikinci.count('<tr onclick') == 5

    # Var olmayan sayfa son sayfaya sabitlenir, boş liste dönmez.
    assert istemci.get("/arizalar?sayfa=99").text.count('<tr onclick') == 5

    # Geçersiz filtre değeri sorguya taşınmamalı.
    assert istemci.get("/arizalar?durum=olmayan-durum").status_code == 200


def test_makine_filtresi(istemci, users, machines, ariza):
    giris_yap(istemci, "tk")
    assert "Yağ sızıntısı" in istemci.get(f"/arizalar?makine={machines[0]}").text
    assert "Yağ sızıntısı" not in istemci.get(f"/arizalar?makine={machines[1]}").text


def test_sayim_ve_liste_ayni_filtreyi_kullanir(users, machines, ariza):
    """count_faults ile list_faults aynı sonucu saymalı."""
    from app.services import fault_service

    filtre = dict(search="sızıntı", machine_id=machines[0])
    assert fault_service.count_faults(**filtre) == len(fault_service.list_faults(**filtre))


# --- Kayıt açma -----------------------------------------------------------
def test_form_ile_kayit_acilir(istemci, users, machines):
    giris_yap(istemci, "op")
    yanit = istemci.post(
        "/arizalar/yeni",
        data={
            "makine_id": machines[0],
            "baslik": "Titreşim var",
            "aciklama": "Rulman sesi geliyor.",
            "oncelik": config.PRIORITY_URGENT,
            "csrf": _token(istemci, "/arizalar/yeni"),
        },
        follow_redirects=False,
    )
    assert yanit.status_code == 303
    assert istemci.get(yanit.headers["location"]).status_code == 200


def test_bos_baslik_formu_hatayla_geri_verir(istemci, users, machines):
    giris_yap(istemci, "op")
    yanit = istemci.post(
        "/arizalar/yeni",
        data={
            "makine_id": machines[0],
            "baslik": "   ",
            "csrf": _token(istemci, "/arizalar/yeni"),
        },
    )
    assert yanit.status_code == 400
    assert "başlığı boş olamaz" in yanit.text


# --- Detay üzerindeki işlemler --------------------------------------------
def test_teknisyen_durum_degistirir(istemci, users, ariza):
    giris_yap(istemci, "tk")
    yanit = istemci.post(
        f"/arizalar/{ariza}/durum",
        data={
            "yeni_durum": config.STATUS_IN_PROGRESS,
            "aciklama": "Bakıldı.",
            "csrf": _token(istemci, f"/arizalar/{ariza}"),
        },
        follow_redirects=False,
    )
    assert yanit.status_code == 303

    from app.services import fault_service
    assert fault_service.get_fault(ariza)["status"] == config.STATUS_IN_PROGRESS


def test_operator_durum_degistiremez(istemci, users, ariza):
    giris_yap(istemci, "op")
    yanit = istemci.post(
        f"/arizalar/{ariza}/durum",
        data={
            "yeni_durum": config.STATUS_IN_PROGRESS,
            "csrf": _token(istemci, f"/arizalar/{ariza}"),
        },
    )
    assert yanit.status_code == 403

    from app.services import fault_service
    assert fault_service.get_fault(ariza)["status"] == config.STATUS_OPEN


def test_gecersiz_durum_gecisi_kayitla_oynamaz(istemci, users, ariza):
    giris_yap(istemci, "tk")
    istemci.post(
        f"/arizalar/{ariza}/durum",
        data={
            "yeni_durum": config.STATUS_CLOSED,  # Açık → Kapatıldı doğrudan yapılamaz
            "aciklama": "Kapat",
            "csrf": _token(istemci, f"/arizalar/{ariza}"),
        },
    )
    from app.services import fault_service
    assert fault_service.get_fault(ariza)["status"] == config.STATUS_OPEN


def test_not_eklenir(istemci, users, ariza):
    giris_yap(istemci, "op")
    istemci.post(
        f"/arizalar/{ariza}/not",
        data={"notu": "Sızıntı arttı.", "csrf": _token(istemci, f"/arizalar/{ariza}")},
    )
    assert "Sızıntı arttı." in istemci.get(f"/arizalar/{ariza}").text


def test_operator_atama_yapamaz(istemci, users, ariza):
    giris_yap(istemci, "op")
    yanit = istemci.post(
        f"/arizalar/{ariza}/atama",
        data={
            "teknisyen_id": users["technician"].id,
            "csrf": _token(istemci, f"/arizalar/{ariza}"),
        },
    )
    assert yanit.status_code == 403


def test_teknisyen_atama_yapar(istemci, users, ariza):
    giris_yap(istemci, "tk")
    istemci.post(
        f"/arizalar/{ariza}/atama",
        data={
            "teknisyen_id": users["technician"].id,
            "csrf": _token(istemci, f"/arizalar/{ariza}"),
        },
    )
    from app.services import fault_service
    assert fault_service.get_fault(ariza)["assignee_id"] == users["technician"].id


def test_eszamanli_duzenleme_engellenir(istemci, users, ariza):
    """İki teknisyen aynı kaydı açtıysa ikincisinin yazması reddedilmeli."""
    from app.services import fault_service

    giris_yap(istemci, "tk")
    eski_surum = fault_service.get_fault(ariza)["version"]

    # Başka biri araya girip kaydı değiştirir.
    fault_service.change_status(
        ariza, users["admin"].id, config.STATUS_IN_PROGRESS, "Ben aldım."
    )

    yanit = istemci.post(
        f"/arizalar/{ariza}/durum",
        data={
            "yeni_durum": config.STATUS_WAITING,
            "aciklama": "Parça bekliyor.",
            "surum": eski_surum,  # Sayfa açıldığındaki sürüm
            "csrf": _token(istemci, "/arizalar"),
        },
        follow_redirects=True,
    )
    assert "başka biri tarafından değiştirildi" in yanit.text
    assert fault_service.get_fault(ariza)["status"] == config.STATUS_IN_PROGRESS


def test_operator_islenen_kaydi_duzenleyemez(istemci, users, ariza):
    from app.services import fault_service

    fault_service.change_status(
        ariza, users["technician"].id, config.STATUS_IN_PROGRESS, "Alındı."
    )

    giris_yap(istemci, "op")
    yanit = istemci.post(
        f"/arizalar/{ariza}/duzenle",
        data={
            "baslik": "Değişti",
            "oncelik": config.PRIORITY_LOW,
            "csrf": _token(istemci, f"/arizalar/{ariza}"),
        },
    )
    assert yanit.status_code == 403
    assert fault_service.get_fault(ariza)["title"] == "Yağ sızıntısı"


# --- Çevrimdışı kuyruk ----------------------------------------------------
def _api_gonder(istemci, govde: dict, token: str):
    return istemci.post("/api/arizalar", json=govde, headers={"X-CSRF-Token": token})


def test_api_oturumsuz_401_doner_yonlendirmez(istemci, machines):
    """Kuyruk, yönlendirmeyi başarı sanıp kaydı silmemeli."""
    yanit = istemci.post("/api/arizalar", json={}, follow_redirects=False)
    assert yanit.status_code == 401
    assert yanit.headers["content-type"].startswith("application/json")


def test_api_csrf_basligi_zorunlu(istemci, users, machines):
    giris_yap(istemci, "op")
    yanit = istemci.post(
        "/api/arizalar",
        json={
            "client_uuid": str(uuid.uuid4()),
            "makine_id": machines[0],
            "baslik": "Başlıksız istek",
        },
    )
    assert yanit.status_code == 400


def test_kuyruk_kaydi_olusturur(istemci, users, machines):
    giris_yap(istemci, "op")
    token = _token(istemci, "/arizalar")

    yanit = _api_gonder(istemci, {
        "client_uuid": str(uuid.uuid4()),
        "makine_id": machines[0],
        "baslik": "Çevrimdışı girilen arıza",
        "aciklama": "Bağlantı yokken yazıldı.",
        "oncelik": config.PRIORITY_HIGH,
    }, token)

    assert yanit.status_code == 201
    govde = yanit.json()
    assert govde["yeni"] is True
    assert istemci.get(govde["adres"]).status_code == 200


def test_ayni_uuid_ikinci_kez_kayit_acmaz(istemci, users, machines):
    """Yanıt kaybolup kuyruk tekrar denerse mükerrer kayıt olmamalı."""
    from app.services import fault_service

    giris_yap(istemci, "op")
    token = _token(istemci, "/arizalar")
    govde = {
        "client_uuid": str(uuid.uuid4()),
        "makine_id": machines[0],
        "baslik": "Tek kez kaydedilmeli",
    }

    ilk = _api_gonder(istemci, govde, token)
    ikinci = _api_gonder(istemci, govde, token)

    assert ilk.status_code == 201 and ilk.json()["yeni"] is True
    assert ikinci.status_code == 200 and ikinci.json()["yeni"] is False
    assert ilk.json()["id"] == ikinci.json()["id"]
    assert fault_service.count_faults(search="Tek kez kaydedilmeli") == 1


def test_kuyrukta_bekleyen_kaydin_zamani_korunur(istemci, users, machines):
    """Arıza zamanı gönderim anı değil, cihazda yazıldığı an olmalı."""
    from app.services import fault_service

    giris_yap(istemci, "op")
    yazilma = datetime.now(timezone.utc) - timedelta(hours=3)

    yanit = _api_gonder(istemci, {
        "client_uuid": str(uuid.uuid4()),
        "makine_id": machines[0],
        "baslik": "Üç saat önce yazıldı",
        "olusma_zamani": yazilma.isoformat(),
    }, _token(istemci, "/arizalar"))

    kayit = fault_service.get_fault(yanit.json()["id"])
    assert abs((kayit["occurred_at"] - yazilma).total_seconds()) < 5
    # Sunucuya ulaşma anı ayrı tutulur; denetim izi bozulmaz.
    assert kayit["created_at"] > kayit["occurred_at"]


def test_gecersiz_kayit_400_doner(istemci, users, machines):
    """Kuyruk 4xx alınca kaydı atmalı; sonsuza dek denememeli."""
    giris_yap(istemci, "op")
    yanit = _api_gonder(istemci, {
        "client_uuid": str(uuid.uuid4()),
        "makine_id": 999999,  # Olmayan makine
        "baslik": "Hatalı kayıt",
    }, _token(istemci, "/arizalar"))
    assert yanit.status_code == 400
    assert "hata" in yanit.json()


def test_makine_listesi_api(istemci, users, machines):
    giris_yap(istemci, "op")
    veri = istemci.get("/api/makineler").json()
    assert len(veri) == len(machines)
    assert {"id", "ad", "konum", "seri_no"} <= set(veri[0])


# --- Çevrimdışı sayfa ve statik dosyalar ----------------------------------
def test_cevrimdisi_sayfasi_oturumsuz_acilir(istemci):
    """Service worker bunu kurulumda önbelleğe alır; oturum istememeli."""
    assert istemci.get("/cevrimdisi").status_code == 200


def test_service_worker_kokten_sunulur(istemci):
    """Kapsamı tüm siteyi kapsasın diye /static altından değil kökten."""
    yanit = istemci.get("/sw.js")
    assert yanit.status_code == 200
    assert "javascript" in yanit.headers["content-type"]


def test_saglik_ucu(istemci):
    assert istemci.get("/saglik").json()["durum"] == "calisiyor"
