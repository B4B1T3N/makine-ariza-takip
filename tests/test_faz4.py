"""Faz 4: ek dosyalarının nesne depolamaya taşınması ve web'den yükleme.

Buradaki testler iki şeyi ayırır: depolama katmanının sözleşmesi (yerel disk
ve S3 uyumlu arka uç aynı şekilde davranmalı) ve web tarafındaki yükleme
akışı (yetki, boyut, uzantı).

S3 arka ucu sahte bir istemciyle sınanır: amaç boto3'ü değil, anahtarın
doğru üretildiğini ve hataların `StorageError`'a çevrildiğini doğrulamaktır.
"""
from __future__ import annotations

import io
import re

import pytest

from app import config
from app.services import fault_service, storage_service
from app.services.fault_service import FaultError


# --- Sahteler -------------------------------------------------------------
class SahteS3Istemcisi:
    """boto3 istemcisinin bu projede kullanılan dört çağrısını taklit eder."""

    def __init__(self) -> None:
        self.nesneler: dict[str, bytes] = {}

    def put_object(self, Bucket, Key, Body):  # noqa: N803 (boto3 imzası)
        self.nesneler[f"{Bucket}/{Key}"] = Body

    def get_object(self, Bucket, Key):  # noqa: N803
        veri = self.nesneler[f"{Bucket}/{Key}"]  # KeyError -> StorageError
        return {"Body": io.BytesIO(veri)}

    def delete_object(self, Bucket, Key):  # noqa: N803
        self.nesneler.pop(f"{Bucket}/{Key}", None)

    def head_object(self, Bucket, Key):  # noqa: N803
        if f"{Bucket}/{Key}" not in self.nesneler:
            raise KeyError(Key)
        return {}


class BellekDepo:
    """Yerel yolu olmayan bir depo — nesne depolamanın web'deki davranışı."""

    ad = "bellek"

    def __init__(self) -> None:
        self.nesneler: dict[str, bytes] = {}

    def yaz(self, anahtar, veri):
        self.nesneler[anahtar] = veri

    def oku(self, anahtar):
        if anahtar not in self.nesneler:
            raise storage_service.StorageError("Dosya nesne depolamada bulunamadı.")
        return self.nesneler[anahtar]

    def akis(self, anahtar):
        return io.BytesIO(self.oku(anahtar))

    def sil(self, anahtar):
        self.nesneler.pop(anahtar, None)

    def var_mi(self, anahtar):
        return anahtar in self.nesneler

    def yerel_yol(self, anahtar):
        return None


@pytest.fixture()
def s3_depo():
    istemci = SahteS3Istemcisi()
    depo = storage_service.S3Depo(
        {
            "bucket": "test-kova",
            "endpoint": None,
            "region": None,
            "access_key": None,
            "secret_key": None,
            "prefix": "ekler",
        },
        istemci=istemci,
    )
    return depo, istemci


@pytest.fixture()
def bellek_depo(monkeypatch):
    """Uygulamanın tamamını yerel yolu olmayan bir depoya bağlar."""
    depo = BellekDepo()
    monkeypatch.setattr(storage_service, "depo", lambda: depo)
    return depo


# --- Depolama katmanı -----------------------------------------------------
def test_yerel_depo_yazar_okur_siler(app_db, tmp_path, monkeypatch):
    monkeypatch.setenv("MAT_DATA_DIR", str(tmp_path))
    depo = storage_service.YerelDepo()

    depo.yaz("1_abc.png", b"veri")
    assert depo.var_mi("1_abc.png")
    assert depo.oku("1_abc.png") == b"veri"
    assert depo.yerel_yol("1_abc.png").is_file()

    depo.sil("1_abc.png")
    assert not depo.var_mi("1_abc.png")


def test_yerel_depo_olmayan_dosyada_hata_verir(app_db, tmp_path, monkeypatch):
    monkeypatch.setenv("MAT_DATA_DIR", str(tmp_path))
    with pytest.raises(storage_service.StorageError):
        storage_service.YerelDepo().oku("yok.png")


def test_s3_depo_onekli_anahtar_kullanir(s3_depo):
    depo, istemci = s3_depo

    depo.yaz("7_abc.pdf", b"pdf-veri")
    assert "test-kova/ekler/7_abc.pdf" in istemci.nesneler
    assert depo.oku("7_abc.pdf") == b"pdf-veri"
    assert depo.var_mi("7_abc.pdf")

    depo.sil("7_abc.pdf")
    assert not depo.var_mi("7_abc.pdf")


def test_s3_depo_okuma_hatasi_cevrilir(s3_depo):
    depo, _ = s3_depo
    with pytest.raises(storage_service.StorageError):
        depo.oku("olmayan.png")


def test_s3_depo_kova_tanimsizsa_kurulmaz():
    with pytest.raises(storage_service.StorageError, match="MAT_S3_BUCKET"):
        storage_service.S3Depo({"bucket": "", "prefix": ""})


def test_arka_uc_ortam_degiskeniyle_secilir(monkeypatch):
    storage_service.depoyu_sifirla()
    monkeypatch.setenv("MAT_STORAGE", "yerel")
    assert storage_service.arka_uc_adi() == config.STORAGE_LOCAL

    monkeypatch.setenv("MAT_STORAGE", "s3")
    monkeypatch.setenv("MAT_S3_BUCKET", "kova")
    assert storage_service.depo().ad == config.STORAGE_S3

    storage_service.depoyu_sifirla()


# --- Servis katmanı -------------------------------------------------------
@pytest.fixture()
def ariza_kaydi(users, machines):
    return fault_service.create_fault(
        machine_id=machines[0],
        title="Yağ sızıntısı",
        description="",
        priority=config.PRIORITY_HIGH,
        reporter_id=users["operator"].id,
    )


def test_yuklenen_baytlar_ek_olarak_kaydedilir(ariza_kaydi, users, bellek_depo):
    ek_id = fault_service.add_attachment_bytes(
        ariza_kaydi, users["operator"].id, "foto.png", b"sahte-goruntu"
    )

    ekler = fault_service.list_attachments(ariza_kaydi)
    assert len(ekler) == 1
    assert ekler[0]["file_name"] == "foto.png"
    assert fault_service.attachment_bytes(ek_id) == b"sahte-goruntu"

    # Geçmişe de düşmeli.
    kayitlar = [g for g in fault_service.get_logs(ariza_kaydi)
                if g["action"] == config.LOG_ATTACHMENT]
    assert kayitlar and kayitlar[0]["note"] == "foto.png"


def test_depodaki_anahtar_kullanicinin_adindan_uretilmez(
    ariza_kaydi, users, bellek_depo
):
    fault_service.add_attachment_bytes(
        ariza_kaydi, users["operator"].id, r"..\..\gizli.png", b"veri"
    )
    ek = fault_service.list_attachments(ariza_kaydi)[0]

    # Gösterilen ad temizlenir, depodaki anahtar sunucuda üretilir.
    assert ek["file_name"] == "gizli.png"
    assert re.fullmatch(rf"{ariza_kaydi}_[0-9a-f]{{8}}\.png", ek["stored_name"])
    assert ".." not in ek["stored_name"]


def test_izin_verilmeyen_uzanti_reddedilir(ariza_kaydi, users, bellek_depo):
    with pytest.raises(FaultError, match="kabul edilmiyor"):
        fault_service.add_attachment_bytes(
            ariza_kaydi, users["operator"].id, "betik.exe", b"MZ"
        )
    assert fault_service.list_attachments(ariza_kaydi) == []


def test_buyuk_dosya_reddedilir(ariza_kaydi, users, bellek_depo):
    buyuk = b"x" * (config.ATTACHMENT_MAX_BYTES + 1)
    with pytest.raises(FaultError, match="MB"):
        fault_service.add_attachment_bytes(
            ariza_kaydi, users["operator"].id, "video.mp4", buyuk
        )


def test_bos_dosya_reddedilir(ariza_kaydi, users, bellek_depo):
    with pytest.raises(FaultError, match="Boş dosya"):
        fault_service.add_attachment_bytes(
            ariza_kaydi, users["operator"].id, "bos.png", b""
        )


def test_ek_silinince_depodan_da_silinir(ariza_kaydi, users, bellek_depo):
    ek_id = fault_service.add_attachment_bytes(
        ariza_kaydi, users["operator"].id, "foto.png", b"veri"
    )
    anahtar = fault_service.get_attachment(ek_id)["stored_name"]
    assert bellek_depo.var_mi(anahtar)

    fault_service.delete_attachment(ek_id)
    assert not bellek_depo.var_mi(anahtar)
    assert fault_service.list_attachments(ariza_kaydi) == []


def test_nesne_depolamadaki_ek_gecici_dosyaya_inilir(
    ariza_kaydi, users, bellek_depo
):
    ek_id = fault_service.add_attachment_bytes(
        ariza_kaydi, users["operator"].id, "rapor.pdf", b"pdf-veri"
    )
    yol = fault_service.attachment_file(ek_id)

    assert yol.is_file()
    assert yol.name == "rapor.pdf"
    assert yol.read_bytes() == b"pdf-veri"


# --- Web akışı ------------------------------------------------------------
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


def _yukle(istemci, fault_id, ad, veri, token):
    return istemci.post(
        f"/arizalar/{fault_id}/ek",
        data={"csrf": token},
        files={"dosya": (ad, veri, "application/octet-stream")},
        follow_redirects=True,
    )


def test_web_uzerinden_dosya_yuklenir_ve_indirilir(
    istemci, ariza_kaydi, users, bellek_depo
):
    giris_yap(istemci, "op")
    token = _csrf(istemci.get(f"/arizalar/{ariza_kaydi}").text)

    yanit = _yukle(istemci, ariza_kaydi, "foto.png", b"sahte-goruntu", token)
    assert yanit.status_code == 200
    assert "1 dosya eklendi" in yanit.text

    ek = fault_service.list_attachments(ariza_kaydi)[0]
    indirme = istemci.get(f"/ekler/{ek['id']}")
    assert indirme.status_code == 200
    assert indirme.content == b"sahte-goruntu"
    assert "foto.png" in indirme.headers["content-disposition"]


def test_operator_baskasinin_kaydina_dosya_yukleyemez(
    istemci, ariza_kaydi, users, machines, bellek_depo
):
    baskasinin = fault_service.create_fault(
        machine_id=machines[0],
        title="Teknisyenin kaydı",
        description="",
        priority=config.PRIORITY_LOW,
        reporter_id=users["technician"].id,
    )

    giris_yap(istemci, "op")
    token = _csrf(istemci.get("/arizalar").text)
    yanit = istemci.post(
        f"/arizalar/{baskasinin}/ek",
        data={"csrf": token},
        files={"dosya": ("foto.png", b"veri", "image/png")},
        follow_redirects=False,
    )

    assert yanit.status_code == 403
    assert fault_service.list_attachments(baskasinin) == []


def test_operator_baskasinin_ekini_indiremez(
    istemci, users, machines, bellek_depo
):
    baskasinin = fault_service.create_fault(
        machine_id=machines[0],
        title="Teknisyenin kaydı",
        description="",
        priority=config.PRIORITY_LOW,
        reporter_id=users["technician"].id,
    )
    ek_id = fault_service.add_attachment_bytes(
        baskasinin, users["technician"].id, "gizli.pdf", b"veri"
    )

    giris_yap(istemci, "op")
    assert istemci.get(f"/ekler/{ek_id}").status_code == 403


def test_yuklemede_csrf_zorunlu(istemci, ariza_kaydi, users, bellek_depo):
    giris_yap(istemci, "op")
    yanit = istemci.post(
        f"/arizalar/{ariza_kaydi}/ek",
        data={"csrf": "sahte"},
        files={"dosya": ("foto.png", b"veri", "image/png")},
        follow_redirects=False,
    )
    assert yanit.status_code == 400
    assert fault_service.list_attachments(ariza_kaydi) == []


def test_web_yuklemesinde_uzanti_denetimi_calisir(
    istemci, ariza_kaydi, users, bellek_depo
):
    giris_yap(istemci, "op")
    token = _csrf(istemci.get(f"/arizalar/{ariza_kaydi}").text)

    yanit = _yukle(istemci, ariza_kaydi, "betik.exe", b"MZ", token)
    assert "kabul edilmiyor" in yanit.text
    assert fault_service.list_attachments(ariza_kaydi) == []


def test_operator_baskasinin_dosyasini_silemez_teknisyen_siler(
    istemci, ariza_kaydi, users, bellek_depo
):
    ek_id = fault_service.add_attachment_bytes(
        ariza_kaydi, users["technician"].id, "rapor.pdf", b"veri"
    )

    giris_yap(istemci, "op")
    token = _csrf(istemci.get(f"/arizalar/{ariza_kaydi}").text)
    yanit = istemci.post(
        f"/ekler/{ek_id}/sil", data={"csrf": token}, follow_redirects=False
    )
    assert yanit.status_code == 403
    assert len(fault_service.list_attachments(ariza_kaydi)) == 1

    giris_yap(istemci, "tk")
    token = _csrf(istemci.get(f"/arizalar/{ariza_kaydi}").text)
    istemci.post(f"/ekler/{ek_id}/sil", data={"csrf": token}, follow_redirects=True)
    assert fault_service.list_attachments(ariza_kaydi) == []


def test_kullanici_kendi_yukledigi_dosyayi_silebilir(
    istemci, ariza_kaydi, users, bellek_depo
):
    ek_id = fault_service.add_attachment_bytes(
        ariza_kaydi, users["operator"].id, "foto.png", b"veri"
    )

    giris_yap(istemci, "op")
    token = _csrf(istemci.get(f"/arizalar/{ariza_kaydi}").text)
    istemci.post(f"/ekler/{ek_id}/sil", data={"csrf": token}, follow_redirects=True)

    assert fault_service.list_attachments(ariza_kaydi) == []


# --- Taşıma aracı ---------------------------------------------------------
def test_tasima_araci_dosyalari_kopyalar_ve_dogrular(
    app_db, users, machines, tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("MAT_DATA_DIR", str(tmp_path))
    storage_service.depoyu_sifirla()

    fault_id = fault_service.create_fault(
        machine_id=machines[0], title="Ek taşıma", description="",
        priority=config.PRIORITY_LOW, reporter_id=users["operator"].id,
    )
    # Yerel arka uçla iki ek oluşturulur.
    fault_service.add_attachment_bytes(fault_id, users["operator"].id,
                                       "a.png", b"bir")
    ikinci = fault_service.add_attachment_bytes(fault_id, users["operator"].id,
                                                "b.pdf", b"iki")

    # İkinci kaydın yerel dosyası kaybolmuş olsun.
    eksik_anahtar = fault_service.get_attachment(ikinci)["stored_name"]
    (config.attachments_dir() / eksik_anahtar).unlink()

    from tools import migrate_attachments

    istemci = SahteS3Istemcisi()
    hedef = storage_service.S3Depo(
        {"bucket": "kova", "endpoint": None, "region": None,
         "access_key": None, "secret_key": None, "prefix": "ekler"},
        istemci=istemci,
    )
    monkeypatch.setattr(migrate_attachments, "_hedef_depo", lambda: hedef)
    monkeypatch.setattr("sys.argv", ["migrate_attachments.py"])

    assert migrate_attachments.main() == 0

    cikti = capsys.readouterr().out
    assert "Taşınan: 1" in cikti
    assert "Yerel dosyası yok: 1" in cikti
    assert len(istemci.nesneler) == 1

    storage_service.depoyu_sifirla()
