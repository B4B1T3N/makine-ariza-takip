"""Faz 3 web ekranları: envanter, kullanıcılar, bildirimler, panel, raporlar.

Buradaki testler HTTP katmanını sınar: hangi rolün hangi sayfayı görebildiği,
formların iş kurallarına bağlanışı ve rapor dışa aktarımının doğru dosyayı
döndürmesi. İş kurallarının kendisi servis testlerinde kapsanıyor.
"""
from __future__ import annotations

import re

import pytest

from app import config


# --- Ortak yardımcılar ----------------------------------------------------
def _csrf(html: str) -> str:
    eslesme = re.search(r'name="csrf-token" content="([^"]+)"', html)
    assert eslesme, "Sayfada CSRF etiketi yok"
    return eslesme.group(1)


def giris_yap(istemci, kullanici_adi: str, sifre: str = "1234"):
    token = _csrf(istemci.get("/giris").text)
    return istemci.post(
        "/giris",
        data={"kullanici_adi": kullanici_adi, "sifre": sifre, "csrf": token},
        follow_redirects=False,
    )


@pytest.fixture()
def istemci(app_db):
    from fastapi.testclient import TestClient

    from app.web.main import create_app

    return TestClient(create_app())


@pytest.fixture()
def ariza(users, machines):
    from app.services import fault_service

    return fault_service.create_fault(
        machine_id=machines[0],
        title="Yağ sızıntısı",
        description="Pres altında yağ birikiyor.",
        priority=config.PRIORITY_HIGH,
        reporter_id=users["operator"].id,
    )


# --- Makine envanteri -----------------------------------------------------
def test_envanter_operatore_kapali(istemci, users, machines):
    giris_yap(istemci, "op")
    yanit = istemci.get("/makineler")
    assert yanit.status_code == 403
    # Menüde de hiç görünmemeli.
    assert "/makineler" not in istemci.get("/arizalar").text


def test_teknisyen_envanteri_gorur_ama_degistiremez(istemci, users, machines):
    giris_yap(istemci, "tk")

    liste = istemci.get("/makineler")
    assert liste.status_code == 200
    assert "Pres 1" in liste.text
    assert "/makineler/yeni" not in liste.text

    assert istemci.get("/makineler/yeni").status_code == 403
    assert istemci.get(f"/makineler/{machines[0]}/duzenle").status_code == 403


def test_yonetici_makine_ekler(istemci, users):
    giris_yap(istemci, "admin", "admin")
    token = _csrf(istemci.get("/makineler/yeni").text)

    # Form alanları sütun adlarıyla aynıdır (envanter genişlemesiyle birlikte
    # 30 alan için ikinci bir eşleme tablosu tutmamak için).
    yanit = istemci.post(
        "/makineler/yeni",
        data={
            "name": "Kaynak Robotu",
            "serial_no": "SN-99",
            "location": "Hat C",
            "category": "Robot",
            "commissioned_at": "2024-05-01",
            "notes": "Haftalık yağlama",
            "csrf": token,
        },
        follow_redirects=False,
    )
    assert yanit.status_code == 303

    detay = istemci.get(yanit.headers["location"])
    assert "Kaynak Robotu" in detay.text
    assert "SN-99" in detay.text


def test_ayni_seri_no_ikinci_kez_kabul_edilmez(istemci, users, machines):
    giris_yap(istemci, "admin", "admin")
    token = _csrf(istemci.get("/makineler/yeni").text)

    yanit = istemci.post(
        "/makineler/yeni",
        data={"name": "Kopya", "serial_no": "SN-1", "csrf": token},
    )
    assert yanit.status_code == 400
    assert "zaten kayıtlı" in yanit.text


def test_acik_arizasi_olan_makine_pasife_alinamaz(istemci, users, machines, ariza):
    giris_yap(istemci, "admin", "admin")
    token = _csrf(istemci.get(f"/makineler/{machines[0]}").text)

    yanit = istemci.post(
        f"/makineler/{machines[0]}/aktiflik",
        data={"aktif": "0", "csrf": token},
        follow_redirects=True,
    )
    assert "kapanmamış arıza" in yanit.text

    from app.services import machine_service

    assert machine_service.get_machine(machines[0])["is_active"] is True


def test_makine_pasife_alinir_ve_yeni_arizada_listelenmez(istemci, users, machines):
    giris_yap(istemci, "admin", "admin")
    token = _csrf(istemci.get(f"/makineler/{machines[1]}").text)

    istemci.post(
        f"/makineler/{machines[1]}/aktiflik",
        data={"aktif": "0", "csrf": token},
        follow_redirects=True,
    )

    from app.services import machine_service

    assert machine_service.get_machine(machines[1])["is_active"] is False
    assert "Torna 1" not in istemci.get("/arizalar/yeni").text


def test_makine_detayinda_ariza_gecmisi_gorunur(istemci, users, machines, ariza):
    giris_yap(istemci, "tk")
    detay = istemci.get(f"/makineler/{machines[0]}")
    assert "Yağ sızıntısı" in detay.text
    assert f"/arizalar/{ariza}" in detay.text


# --- Kullanıcı yönetimi ---------------------------------------------------
def test_kullanici_yonetimi_teknisyene_kapali(istemci, users):
    giris_yap(istemci, "tk")
    assert istemci.get("/kullanicilar").status_code == 403
    assert istemci.get("/kullanicilar/yeni").status_code == 403


def test_yonetici_kullanici_olusturur_ve_giris_yapabilir(istemci, users):
    giris_yap(istemci, "admin", "admin")
    token = _csrf(istemci.get("/kullanicilar/yeni").text)

    yanit = istemci.post(
        "/kullanicilar/yeni",
        data={
            "kullanici_adi": "yeni_op",
            "ad_soyad": "Yeni Operatör",
            "rol": config.ROLE_OPERATOR,
            "sifre": "sifre1",
            "csrf": token,
        },
        follow_redirects=False,
    )
    assert yanit.status_code == 303

    from app.services import auth_service

    assert auth_service.login("yeni_op", "sifre1").full_name == "Yeni Operatör"


def test_ayni_kullanici_adi_ikinci_kez_kabul_edilmez(istemci, users):
    giris_yap(istemci, "admin", "admin")
    token = _csrf(istemci.get("/kullanicilar/yeni").text)

    yanit = istemci.post(
        "/kullanicilar/yeni",
        data={
            "kullanici_adi": "op",
            "ad_soyad": "Kopya Kişi",
            "rol": config.ROLE_OPERATOR,
            "sifre": "1234",
            "csrf": token,
        },
    )
    assert yanit.status_code == 400
    assert "zaten kayıtlı" in yanit.text


def test_pasife_alinan_kullanicinin_oturumu_ilk_istekte_duser(istemci, users):
    from fastapi.testclient import TestClient

    from app.web.main import create_app

    operator = TestClient(create_app())
    giris_yap(operator, "op")
    assert operator.get("/arizalar").status_code == 200

    giris_yap(istemci, "admin", "admin")
    op_id = users["operator"].id
    token = _csrf(istemci.get(f"/kullanicilar/{op_id}/duzenle").text)
    istemci.post(
        f"/kullanicilar/{op_id}/duzenle",
        data={
            "ad_soyad": "Operatör Kişi",
            "rol": config.ROLE_OPERATOR,
            "aktif": "",
            "csrf": token,
        },
        follow_redirects=False,
    )

    yanit = operator.get("/arizalar", follow_redirects=False)
    assert yanit.status_code == 303
    assert yanit.headers["location"].startswith("/giris")


def test_yonetici_kendi_hesabini_pasife_alamaz(istemci, users):
    giris_yap(istemci, "admin", "admin")
    ben = users["admin"].id
    token = _csrf(istemci.get(f"/kullanicilar/{ben}/duzenle").text)

    yanit = istemci.post(
        f"/kullanicilar/{ben}/duzenle",
        data={"ad_soyad": "Sistem Yöneticisi", "rol": config.ROLE_MANAGER,
              "aktif": "", "csrf": token},
    )
    assert yanit.status_code == 400
    assert "Kendi hesabınızı" in yanit.text

    from app.services import auth_service

    assert auth_service.get_user(ben)["is_active"] is True


def test_son_yonetici_rolunu_dusuremez(istemci, users):
    giris_yap(istemci, "admin", "admin")
    ben = users["admin"].id
    token = _csrf(istemci.get(f"/kullanicilar/{ben}/duzenle").text)

    yanit = istemci.post(
        f"/kullanicilar/{ben}/duzenle",
        data={"ad_soyad": "Sistem Yöneticisi", "rol": config.ROLE_TECHNICIAN,
              "aktif": "1", "csrf": token},
    )
    assert yanit.status_code == 400
    assert "en az bir aktif yönetici" in yanit.text


def test_yonetici_sifre_sifirlar(istemci, users):
    giris_yap(istemci, "admin", "admin")
    op_id = users["operator"].id
    token = _csrf(istemci.get(f"/kullanicilar/{op_id}/duzenle").text)

    yanit = istemci.post(
        f"/kullanicilar/{op_id}/duzenle",
        data={
            "ad_soyad": "Operatör Kişi",
            "rol": config.ROLE_OPERATOR,
            "aktif": "1",
            "yeni_sifre": "yeni123",
            "csrf": token,
        },
        follow_redirects=False,
    )
    assert yanit.status_code == 303

    from app.services import auth_service

    assert auth_service.login("op", "yeni123").username == "op"


# --- Kendi şifresini değiştirme -------------------------------------------
def test_kullanici_kendi_sifresini_degistirir(istemci, users):
    giris_yap(istemci, "op")
    token = _csrf(istemci.get("/hesap/sifre").text)

    yanit = istemci.post(
        "/hesap/sifre",
        data={
            "mevcut_sifre": "1234",
            "yeni_sifre": "yeni456",
            "yeni_sifre_tekrar": "yeni456",
            "csrf": token,
        },
        follow_redirects=False,
    )
    assert yanit.status_code == 303

    from app.services import auth_service

    assert auth_service.login("op", "yeni456").username == "op"


def test_mevcut_sifre_yanlissa_degismez(istemci, users):
    giris_yap(istemci, "op")
    token = _csrf(istemci.get("/hesap/sifre").text)

    yanit = istemci.post(
        "/hesap/sifre",
        data={
            "mevcut_sifre": "yanlis",
            "yeni_sifre": "yeni456",
            "yeni_sifre_tekrar": "yeni456",
            "csrf": token,
        },
    )
    assert yanit.status_code == 400
    assert "Mevcut şifre hatalı" in yanit.text

    from app.services import auth_service

    assert auth_service.login("op", "1234").username == "op"


def test_yeni_sifre_tekrari_tutmazsa_degismez(istemci, users):
    giris_yap(istemci, "op")
    token = _csrf(istemci.get("/hesap/sifre").text)

    yanit = istemci.post(
        "/hesap/sifre",
        data={
            "mevcut_sifre": "1234",
            "yeni_sifre": "yeni456",
            "yeni_sifre_tekrar": "baska",
            "csrf": token,
        },
    )
    assert yanit.status_code == 400

    from app.services import auth_service

    assert auth_service.login("op", "1234").username == "op"


# --- Bildirimler ----------------------------------------------------------
def test_yeni_ariza_teknisyene_bildirim_dusurur(istemci, users, machines, ariza):
    giris_yap(istemci, "tk")

    sayfa = istemci.get("/bildirimler")
    assert sayfa.status_code == 200
    assert "Yağ sızıntısı" in sayfa.text
    # Üst menüdeki okunmamış rozeti her sayfada görünür.
    assert 'class="rozet sayac"' in istemci.get("/arizalar").text


def test_bildirimden_kayda_gecilir_ve_okundu_isaretlenir(istemci, users, ariza):
    from app.services import notification_service

    giris_yap(istemci, "tk")
    tk_id = users["technician"].id
    bildirim = notification_service.list_for_user(tk_id)[0]

    token = _csrf(istemci.get("/bildirimler").text)
    yanit = istemci.post(
        f"/bildirimler/{bildirim['id']}/okundu",
        data={"hedef": str(ariza), "csrf": token},
        follow_redirects=False,
    )
    assert yanit.status_code == 303
    assert yanit.headers["location"] == f"/arizalar/{ariza}"
    assert notification_service.unread_count(tk_id) == 0


def test_baskasinin_bildirimi_okundu_yapilamaz(istemci, users, ariza):
    from app.services import notification_service

    tk_id = users["technician"].id
    bildirim = notification_service.list_for_user(tk_id)[0]

    # Operatör, teknisyene düşen bildirimin numarasını deniyor.
    giris_yap(istemci, "op")
    token = _csrf(istemci.get("/bildirimler").text)
    istemci.post(
        f"/bildirimler/{bildirim['id']}/okundu",
        data={"csrf": token},
        follow_redirects=False,
    )

    assert notification_service.unread_count(tk_id) == 1


def test_hedef_serbest_adres_kabul_etmez(istemci, users, ariza):
    from app.services import notification_service

    giris_yap(istemci, "tk")
    bildirim = notification_service.list_for_user(users["technician"].id)[0]
    token = _csrf(istemci.get("/bildirimler").text)

    yanit = istemci.post(
        f"/bildirimler/{bildirim['id']}/okundu",
        data={"hedef": "https://baska-site.example", "csrf": token},
        follow_redirects=False,
    )
    assert yanit.headers["location"] == "/bildirimler"


def test_tumu_okundu_ve_temizle(istemci, users, ariza):
    from app.services import notification_service

    giris_yap(istemci, "tk")
    tk_id = users["technician"].id
    token = _csrf(istemci.get("/bildirimler").text)

    istemci.post("/bildirimler/tumu-okundu", data={"csrf": token},
                 follow_redirects=True)
    assert notification_service.unread_count(tk_id) == 0

    istemci.post("/bildirimler/temizle", data={"csrf": token}, follow_redirects=True)
    assert notification_service.list_for_user(tk_id) == []


# --- Panel ----------------------------------------------------------------
def test_kok_adres_panele_yonlendirir(istemci, users):
    giris_yap(istemci, "tk")
    yanit = istemci.get("/", follow_redirects=False)
    assert yanit.status_code == 303
    assert yanit.headers["location"] == "/panel"


def test_yonetici_panelinde_tesis_ozeti_var(istemci, users, machines, ariza):
    giris_yap(istemci, "admin", "admin")
    panel = istemci.get("/panel")

    assert panel.status_code == 200
    assert "Açık arıza kaydı" in panel.text
    assert "Durum dağılımı" in panel.text
    assert "En çok arızalanan makineler" in panel.text
    assert "Yağ sızıntısı" in panel.text


def test_operator_panelinde_baskasinin_kaydi_gorunmez(istemci, users, machines):
    from app.services import fault_service

    fault_service.create_fault(
        machine_id=machines[0],
        title="Teknisyenin kaydı",
        description="",
        priority=config.PRIORITY_LOW,
        reporter_id=users["technician"].id,
    )

    giris_yap(istemci, "op")
    panel = istemci.get("/panel")

    assert panel.status_code == 200
    assert "Teknisyenin kaydı" not in panel.text
    # Tesis geneli özet operatöre gösterilmez.
    assert "Durum dağılımı" not in panel.text
    assert "Atanmamış kayıt" not in panel.text


def test_raporlar_operatore_kapali(istemci, users):
    giris_yap(istemci, "op")
    assert istemci.get("/raporlar").status_code == 403
    assert (
        istemci.get("/raporlar/disa-aktar?rapor=makine").status_code == 403
    )


def test_rapor_sayfasi_tablolari_gosterir(istemci, users, machines, ariza):
    giris_yap(istemci, "tk")
    sayfa = istemci.get("/raporlar")

    assert sayfa.status_code == 200
    assert "En çok arızalanan makineler" in sayfa.text
    assert "Makine bazında çözüm süreleri" in sayfa.text
    assert "Personel iş yükü" in sayfa.text
    assert "Pres 1" in sayfa.text


def test_bozuk_tarih_sayfayi_dusurmez(istemci, users):
    giris_yap(istemci, "tk")
    yanit = istemci.get("/raporlar?donem=ozel&baslangic=abc&bitis=2026-13-45")
    assert yanit.status_code == 200


def test_ters_tarih_araligi_duzeltilir(istemci, users):
    giris_yap(istemci, "tk")
    yanit = istemci.get(
        "/raporlar?donem=ozel&baslangic=2026-08-20&bitis=2026-08-01"
    )
    assert yanit.status_code == 200
    # Başlangıç küçük olan tarihe çekilir.
    assert 'value="2026-08-01"' in yanit.text


def test_rapor_excel_olarak_indirilir(istemci, users, machines, ariza):
    giris_yap(istemci, "tk")
    yanit = istemci.get("/raporlar/disa-aktar?rapor=makine&bicim=xlsx")

    assert yanit.status_code == 200
    assert "spreadsheet" in yanit.headers["content-type"]
    assert yanit.content[:2] == b"PK"  # xlsx bir zip arşividir


def test_rapor_csv_olarak_indirilir(istemci, users, machines, ariza):
    giris_yap(istemci, "tk")
    yanit = istemci.get("/raporlar/disa-aktar?rapor=personel&bicim=csv")

    assert yanit.status_code == 200
    metin = yanit.content.decode("utf-8-sig")
    assert metin.startswith("Personel;Rol;")
    assert "Teknisyen Kişi" in metin


def test_bilinmeyen_rapor_turu_404(istemci, users):
    giris_yap(istemci, "tk")
    assert istemci.get("/raporlar/disa-aktar?rapor=olmayan").status_code == 404


def test_teknisyen_panelinde_kendi_atamalari_one_cikar(istemci, users, machines, ariza):
    from app.services import fault_service

    fault_service.assign(ariza, users["admin"].id, users["technician"].id)

    giris_yap(istemci, "tk")
    panel = istemci.get("/panel")
    assert "Bana atanan açık kayıtlar" in panel.text
    assert "Yağ sızıntısı" in panel.text
