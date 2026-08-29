"""Envanter: genişletilmiş makine künyesi, filtreler ve ekipman içe aktarma.

Makine kaydı artık tesisin ekipman listesindeki künyeyi taşıyor (bina, bölüm,
makina kodu, üretici, elektrik değerleri, ERP kodları). Buradaki testler bu
alanların uçtan uca korunduğunu, filtre panelinin doğru saydığını ve içe
aktarmanın kaynak listeyi doğru eşlediğini sınar.
"""
from __future__ import annotations

import json
import re

import pytest

from app.services import machine_service as ms

from tools import import_equipment


# --- Ortak --------------------------------------------------------------
@pytest.fixture()
def envanter(app_db):
    """Farklı bina/bölüm/tip/konum değerlerine sahip küçük bir envanter."""
    ms.create_machine(
        "DİK İŞLEM - 4", serial_no="41351", location="KALIPHANE",
        category="CNC", commissioned_at="2007-05-22",
        building="Kalıphane", new_location="2. EL SATILCAK",
        machine_code="508078", model="SMM", manufacturer="HAAS AUTOMATION",
        power_kw=14, voltage="380 V", phase="3", amperage="35",
        production_year=2005, physical_area="KALIP",
    )
    ms.create_machine(
        "ETEK KESME MAKİNESİ", serial_no="290313", location="PRESHANE",
        category="PRES", building="Paslanmaz", new_location="YENİ",
        machine_code="508481", manufacturer="ELMA-SARRONI", power_kw=7,
        voltage="380 V", production_year=2013,
    )
    ms.create_machine(
        "SU DEPOSU", location="GENEL FABRİKA", building="FFS",
        category="SU DEPO",
    )
    return ms.list_machines()


# --- Künye alanları -------------------------------------------------------
def test_kunye_alanlari_kaydedilir_ve_okunur(app_db):
    makine_id = ms.create_machine(
        "CNC TORNA - 13",
        serial_no="261751",
        location="CNC",
        category="CNC",
        building="Yeni Bina",
        new_location="TAŞINDI",
        machine_code="509439",
        asset_no="201316030021+00",
        model="QTN-350-II",
        definition="CNC TEZGAH",
        manufacturer="YAKUP ZERE MAKINE",
        physical_area="CNC",
        unit_no="6000-191",
        production_year=2015,
        manufacture_date="2015-03-01",
        power_kw=0.37,
        voltage="Δ220Υ400V",
        phase="3",
        amperage="1.6",
        fuse="Makineden",
        cable="4 X 1,5 mm²",
        leakage_relay="30mA=4 X 100A",
        pressure_bar="6",
        bu_code="60002700",
        bu_name="Cnc (CNC Machining)",
        awc_code="60002710",
        awc_name="CNC Torna (CNC Turning)",
        sub_account="CNC HATTI",
        extra={"kaynak_id": 4, "vrd1": "0"},
    )

    makine = ms.get_machine(makine_id)
    assert makine["building"] == "Yeni Bina"
    assert makine["machine_code"] == "509439"
    assert makine["manufacturer"] == "YAKUP ZERE MAKINE"
    assert float(makine["power_kw"]) == 0.37
    assert makine["production_year"] == 2015
    assert makine["manufacture_date"].isoformat() == "2015-03-01"
    assert makine["awc_name"] == "CNC Torna (CNC Turning)"
    assert makine["extra"]["kaynak_id"] == 4


def test_kunye_guncellenir(app_db):
    makine_id = ms.create_machine("PRES", building="Paslanmaz", power_kw=5)
    ms.update_machine(makine_id, "PRES", building="Yeni Bina", power_kw=9.5,
                      manufacturer="ELMA")

    makine = ms.get_machine(makine_id)
    assert makine["building"] == "Yeni Bina"
    assert float(makine["power_kw"]) == 9.5
    assert makine["manufacturer"] == "ELMA"


def test_bos_birakilan_alan_temizlenir(app_db):
    makine_id = ms.create_machine("TORNA", manufacturer="ESKİ FİRMA")
    ms.update_machine(makine_id, "TORNA", manufacturer="")
    assert ms.get_machine(makine_id)["manufacturer"] is None


# --- Filtreler ------------------------------------------------------------
def test_bina_ve_tip_filtresi(envanter):
    assert len(ms.list_machines(building="Kalıphane")) == 1
    assert len(ms.list_machines(category=["CNC", "PRES"])) == 2
    assert len(ms.list_machines(building=["Kalıphane", "Paslanmaz"])) == 2


def test_bos_deger_filtresi_bos_alanlari_getirir(envanter):
    # "SU DEPOSU" kaydının yeni konumu yok.
    sonuc = ms.list_machines(new_location=ms.BOS_DEGER)
    assert [m["name"] for m in sonuc] == ["SU DEPOSU"]


def test_konumu_atanmamislar_suzgeci(envanter):
    assert len(ms.list_machines(only_unassigned=True)) == 1


def test_elektrik_verisi_eksikler_suzgeci(envanter):
    eksik = ms.list_machines(missing_power=True)
    assert [m["name"] for m in eksik] == ["SU DEPOSU"]


def test_arama_makina_kodu_ve_ureticiyi_de_tarar(envanter):
    assert len(ms.list_machines(search="508078")) == 1
    assert len(ms.list_machines(search="ELMA")) == 1
    assert len(ms.list_machines(search="Paslanmaz")) == 1


def test_guce_gore_siralama(envanter):
    adlar = [m["name"] for m in ms.list_machines(sort="guc", descending=True)]
    assert adlar[0] == "DİK İŞLEM - 4"  # 14 kW
    assert adlar[1] == "ETEK KESME MAKİNESİ"  # 7 kW


def test_facet_sayilari_diger_filtreleri_dikkate_alir(envanter):
    hepsi = {r["deger"]: r["adet"] for r in ms.facet_counts("building")}
    assert hepsi["Kalıphane"] == 1 and hepsi["Paslanmaz"] == 1

    # Tip=CNC seçiliyken bina sayıları daralır; ama binanın kendi seçimi
    # kendi sayımını daraltmaz (haric mantığı).
    daralmis = {r["deger"]: r["adet"] for r in ms.facet_counts("building", category="CNC")}
    assert daralmis == {"Kalıphane": 1}

    bina_secili = {r["deger"]: r["adet"]
                   for r in ms.facet_counts("building", building="Kalıphane")}
    assert bina_secili["Paslanmaz"] == 1


def test_facet_bos_degeri_tek_etikette_toplar(envanter):
    sayimlar = {r["deger"]: r["adet"] for r in ms.facet_counts("new_location")}
    assert sayimlar[ms.BOS_DEGER] == 1


def test_envanter_ozeti(envanter):
    ozet = ms.inventory_summary()
    assert ozet["kayit"] == 3
    assert ozet["guc"] == 21.0
    assert ozet["bolum"] == 3
    assert ozet["bina"] == 3
    assert ozet["konumsuz"] == 1


def test_konum_durumu_turkce_buyuk_harfe_dayanir():
    assert ms.konum_durumu("HURDA") == "hurda"
    assert ms.konum_durumu("Faal değil") == "hurda"
    assert ms.konum_durumu("2. el satılcak") == "hurda"
    assert ms.konum_durumu("YENİ (ENJEKSİYON)") == "yeni"
    assert ms.konum_durumu("TAŞINDI") == "tasindi"
    assert ms.konum_durumu("") == "atanmadi"
    assert ms.konum_durumu("transpalet") == "diger"


# --- İçe aktarma ----------------------------------------------------------
ORNEK_KAYITLAR = [
    {
        "id": 2, "bina": "Kalıphane", "bolum": "KALIPHANE", "ad": "DİK İŞLEM - 4",
        "yeniKonum": "2. EL SATILCAK", "kod": "508078", "model": "SMM",
        "tanim": "CNC DİK İŞLEME MAK.APARAT", "tip": "CNC", "fiziki": "KALIP",
        "uretici": "HAAS AUTOMATION", "seri": "41351", "kw": "14", "kwNum": 14.0,
        "voltaj": "380 V", "faz": "3", "amper": "35", "bar": "6",
        "alimTarihi": "2007-05-22", "uretimYili": "2005", "imalatYili": "2007-06-06",
        "vrd1": "1", "vrd2": "0", "not": "DK4", "bu": "60002700",
        "bc": "Kalıphane (Mold Workshop)", "altAcc": "CNC HATTI",
    },
    {
        "id": 3, "bina": "Kalıphane", "bolum": "KALIPHANE", "ad": "UNİVERSAL TORNA",
        "yeniKonum": "TAŞINDI", "tip": "TORNA", "kwNum": 0,
        "imalatYili": "03.07.2007",
    },
    {
        "id": 4, "bina": "FFS", "ad": "SU DEPOSU", "tip": "SU DEPO", "kwNum": 0,
        "seri": "41351", "uretimYili": "1899",
    },
]


def _ornek_dosya(tmp_path, kayitlar=None):
    yol = tmp_path / "ekipman.html"
    icerik = (
        "<div id='ek-app'></div>\n<script>\nconst DATA = "
        + json.dumps(kayitlar if kayitlar is not None else ORNEK_KAYITLAR,
                     ensure_ascii=False)
        + ";\nconst F = {};\n</script>\n"
    )
    yol.write_text(icerik, encoding="utf-8")
    return yol


def test_kaynak_dosya_okunur(tmp_path):
    kayitlar = import_equipment.kayitlari_oku(_ornek_dosya(tmp_path))
    assert len(kayitlar) == 3
    assert kayitlar[0]["ad"] == "DİK İŞLEM - 4"


def test_bozuk_dosya_anlasilir_hata_verir(tmp_path):
    yol = tmp_path / "bos.html"
    yol.write_text("<html>veri yok</html>", encoding="utf-8")
    with pytest.raises(import_equipment.AktarmaHatasi, match="DATA"):
        import_equipment.kayitlari_oku(yol)


def test_esleme_alanlari_dogru_cevirir():
    alanlar = import_equipment.esle(ORNEK_KAYITLAR[0])

    assert alanlar["name"] == "DİK İŞLEM - 4"
    assert alanlar["location"] == "KALIPHANE"       # bolum -> location
    assert alanlar["building"] == "Kalıphane"
    assert alanlar["category"] == "CNC"             # tip -> category
    assert alanlar["machine_code"] == "508078"
    assert alanlar["commissioned_at"] == "2007-05-22"
    assert alanlar["manufacture_date"] == "2007-06-06"
    assert alanlar["production_year"] == 2005
    assert alanlar["power_kw"] == 14.0
    assert alanlar["notes"] == "DK4"
    assert alanlar["extra"]["kaynak_id"] == 2
    assert alanlar["extra"]["vrd1"] == "1"


def test_hurdaya_ayrilan_ekipman_pasif_aktarilir():
    assert import_equipment.esle(ORNEK_KAYITLAR[0])["is_active"] is False
    assert import_equipment.esle(ORNEK_KAYITLAR[1])["is_active"] is True


def test_gun_ay_yil_tarihi_cevrilir():
    """Kaynak listede birkaç tarih gg.aa.yyyy yazılmış; ISO'ya çevrilmeli."""
    alanlar = import_equipment.esle(ORNEK_KAYITLAR[1])
    assert alanlar["manufacture_date"] == "2007-07-03"  # 3 Temmuz 2007


def test_anlamsiz_uretim_yili_alinmaz():
    assert import_equipment.esle(ORNEK_KAYITLAR[2])["production_year"] is None


def test_aktarma_kayitlari_ekler(app_db, tmp_path):
    sonuc = import_equipment.aktar(
        import_equipment.kayitlari_oku(_ornek_dosya(tmp_path))
    )
    assert sonuc["eklendi"] == 3
    assert not sonuc["hata"]

    makineler = {m["name"]: m for m in ms.list_machines(include_inactive=True)}
    assert len(makineler) == 3
    assert makineler["DİK İŞLEM - 4"]["is_active"] is False
    assert float(makineler["DİK İŞLEM - 4"]["power_kw"]) == 14.0


def test_ayni_dosya_ikinci_kez_kayit_cogaltmaz(app_db, tmp_path):
    dosya = _ornek_dosya(tmp_path)
    import_equipment.aktar(import_equipment.kayitlari_oku(dosya))
    sonuc = import_equipment.aktar(import_equipment.kayitlari_oku(dosya))

    assert sonuc["eklendi"] == 0
    assert sonuc["guncellendi"] == 3
    assert len(ms.list_machines(include_inactive=True)) == 3


def test_tekrarli_seri_numarasi_cakisma_olarak_raporlanir(app_db, tmp_path):
    sonuc = import_equipment.aktar(
        import_equipment.kayitlari_oku(_ornek_dosya(tmp_path))
    )
    # 41351 iki kayıtta geçiyor: ikincisi seri numarasız aktarılır.
    assert len(sonuc["seri_cakismasi"]) == 1
    assert "SU DEPOSU" in sonuc["seri_cakismasi"][0]

    depo = [m for m in ms.list_machines(include_inactive=True)
            if m["name"] == "SU DEPOSU"][0]
    assert depo["serial_no"] is None
    assert depo["extra"]["seri_cakisan"] == "41351"


def test_kuru_calistirma_veritabanina_dokunmaz(app_db, tmp_path):
    sonuc = import_equipment.aktar(
        import_equipment.kayitlari_oku(_ornek_dosya(tmp_path)), kuru=True
    )
    assert sonuc["eklendi"] == 3
    assert ms.list_machines(include_inactive=True) == []


# --- Web sayfası ----------------------------------------------------------
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


def test_envanter_sayfasi_istatistik_ve_filtre_paneli_gosterir(
    istemci, users, envanter
):
    giris_yap(istemci, "tk")
    sayfa = istemci.get("/makineler")

    assert sayfa.status_code == 200
    assert "Kurulu güç" in sayfa.text
    assert "21.0 kW" in sayfa.text
    # Filtre paneli başlıkları
    for etiket in ("Bina", "Bölüm", "Tip", "Yeni konum", "Üretici firma"):
        assert etiket in sayfa.text
    assert "HAAS AUTOMATION" in sayfa.text


def test_filtre_baglantisi_listeyi_daraltir(istemci, users, envanter):
    giris_yap(istemci, "tk")
    sayfa = istemci.get("/makineler?bina=Kal%C4%B1phane")

    assert sayfa.text.count('data-adres="/makineler/') == 1
    assert "DİK İŞLEM - 4" in sayfa.text
    assert "SU DEPOSU" not in sayfa.text
    # Aktif filtre çipi ve kaldırma bağlantısı
    assert "env-cip" in sayfa.text


def test_kart_gorunumu(istemci, users, envanter):
    giris_yap(istemci, "tk")
    sayfa = istemci.get("/makineler?gorunum=kart")
    # Sarmalayıcı "env-kartlar" da eşleşmesin diye sondaki boşlukla sayılır.
    assert sayfa.text.count('class="env-kart ') == 3


def test_siralama_baglantisi_calisir(istemci, users, envanter):
    giris_yap(istemci, "tk")
    sayfa = istemci.get("/makineler?sirala=guc&yon=ters")

    ilk = sayfa.text.index("DİK İŞLEM - 4")
    ikinci = sayfa.text.index("ETEK KESME MAKİNESİ")
    assert ilk < ikinci


def test_pasif_makine_varsayilan_listede_yok(istemci, users, envanter):
    giris_yap(istemci, "admin", "admin")
    hedef = [m for m in ms.list_machines() if m["name"] == "SU DEPOSU"][0]
    ms.set_active(hedef["id"], False)

    assert "SU DEPOSU" not in istemci.get("/makineler").text
    assert "SU DEPOSU" in istemci.get("/makineler?pasifler=1").text


def test_makine_detayinda_kunye_gruplari_gorunur(istemci, users, envanter):
    giris_yap(istemci, "tk")
    hedef = [m for m in ms.list_machines() if m["name"] == "DİK İŞLEM - 4"][0]
    sayfa = istemci.get(f"/makineler/{hedef['id']}")

    for baslik in ("Temel bilgiler", "Kimlik", "Elektrik ve pnömatik",
                   "Tarihçe", "Organizasyon (ERP)"):
        assert baslik in sayfa.text
    assert "HAAS AUTOMATION" in sayfa.text
    assert "14 kW" in sayfa.text


def test_yonetici_kunye_alanlariyla_makine_ekler(istemci, users):
    giris_yap(istemci, "admin", "admin")
    token = _csrf(istemci.get("/makineler/yeni").text)

    yanit = istemci.post(
        "/makineler/yeni",
        data={
            "name": "KAYNAK ROBOTU",
            "location": "KAYNAKHANE",
            "building": "Yeni Bina",
            "category": "KAYNAK",
            "machine_code": "600123",
            "manufacturer": "FRONIUS",
            "power_kw": "12.5",
            "voltage": "380 V",
            "production_year": "2021",
            "csrf": token,
        },
        follow_redirects=False,
    )
    assert yanit.status_code == 303

    makine = [m for m in ms.list_machines() if m["name"] == "KAYNAK ROBOTU"][0]
    assert makine["machine_code"] == "600123"
    assert float(makine["power_kw"]) == 12.5
    assert makine["production_year"] == 2021


def test_envanter_operatore_kapali_kalir(istemci, users, envanter):
    giris_yap(istemci, "op")
    assert istemci.get("/makineler").status_code == 403
    assert istemci.get("/makineler?bina=FFS").status_code == 403


def test_envanter_sayfasinda_satir_ici_betik_yok(istemci, users, envanter):
    """Faz 5'teki içerik güvenliği politikası envanter sayfasında da geçerli."""
    giris_yap(istemci, "tk")
    for yol in ("/makineler", "/makineler?gorunum=kart"):
        icerik = istemci.get(yol).text
        assert "onclick=" not in icerik
        assert "onsubmit=" not in icerik
