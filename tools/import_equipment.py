"""Ekipman listesini (tek dosyalık HTML uygulaması) envantere aktarır.

Kaynak, tesisin ekipman listesi uygulamasının HTML dosyasıdır; içindeki
`const DATA = [...]` satırı kayıtları taşır. Bu araç o kayıtları okur,
`machines` tablosunun sütunlarına eşler ve ekler/günceller.

Kimlik: her kaydın kaynak dosyadaki `id` değeri `extra.kaynak_id` içinde
saklanır. Tekrar çalıştırıldığında aynı kayıt ikinci kez eklenmez, üzerine
yazılır — makina kodu ve seri numarası bu listede benzersiz olmadığı için
kimlik olarak kullanılamaz.

Kullanım:
    :: Ne olacağını gör (hiçbir şey yazılmaz)
    python tools/import_equipment.py --dosya "C:\\...\\ekipman-listesi.html" --kuru-calistir

    :: Aktar
    python tools/import_equipment.py --dosya "C:\\...\\ekipman-listesi.html"

    :: Demo makineleri ve arıza kayıtlarını silip temiz bir envanterle başla
    python tools/import_equipment.py --dosya "..." --demo-temizle

`--demo-temizle` geri alınamaz: önce otomatik yedek alınır ve onay istenir.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app import config  # noqa: E402
from app.db import database as db  # noqa: E402
from app.services import backup_service, machine_service  # noqa: E402

# Kaynak alan -> veritabanı sütunu. Buradaki eşleme, ekranlardaki etiketlerle
# birlikte machine_service.ALAN_ETIKETLERI içinde belgelenmiştir.
ESLEME = {
    "ad": "name",
    "bolum": "location",
    "bina": "building",
    "tip": "category",
    "yeniKonum": "new_location",
    "fiziki": "physical_area",
    "kod": "machine_code",
    "asset": "asset_no",
    "model": "model",
    "tanim": "definition",
    "uretici": "manufacturer",
    "seri": "serial_no",
    "unit": "unit_no",
    "voltaj": "voltage",
    "faz": "phase",
    "amper": "amperage",
    "sigorta": "fuse",
    "kablo": "cable",
    "kacakAkim": "leakage_relay",
    "bar": "pressure_bar",
    "bu": "bu_code",
    "bc": "bu_name",
    "abc": "awc_code",
    "awc": "awc_name",
    "altAcc": "sub_account",
    "not": "notes",
}

# Sütuna çevrilmeyip `extra` içinde saklanan alanlar.
EXTRA_ALANLARI = ("vrd1", "vrd2", "vrd3", "vrd4", "vrd5")


class AktarmaHatasi(Exception):
    """Kaynak dosya okunamadı veya beklenen biçimde değil."""


# --- Kaynağı okuma --------------------------------------------------------
def kayitlari_oku(yol: str | Path) -> list[dict]:
    """HTML dosyasındaki `const DATA = [...]` dizisini çözer."""
    try:
        metin = Path(yol).read_text(encoding="utf-8")
    except OSError as exc:
        raise AktarmaHatasi(f"Dosya okunamadı: {exc}") from exc

    eslesme = re.search(r"const DATA\s*=\s*(\[.*?\]);?\s*$", metin, re.M)
    if not eslesme:
        raise AktarmaHatasi(
            "Dosyada `const DATA = [...]` satırı bulunamadı. "
            "Doğru HTML dosyasını verdiğinizden emin olun."
        )
    try:
        veri = json.loads(eslesme.group(1))
    except json.JSONDecodeError as exc:
        raise AktarmaHatasi(f"Kayıt listesi çözümlenemedi: {exc}") from exc

    if not isinstance(veri, list) or not veri:
        raise AktarmaHatasi("Kayıt listesi boş.")
    return veri


# --- Dönüştürme -----------------------------------------------------------
def _tarih(deger) -> str | None:
    """ISO ya da gg.aa.yyyy tarihini ISO'ya çevirir; yalnızca yıl varsa None."""
    if not deger:
        return None
    metin = str(deger).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", metin):
        return metin
    gun_ay_yil = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", metin)
    if gun_ay_yil:
        g, a, y = gun_ay_yil.groups()
        return f"{y}-{a}-{g}"
    return None


def _yil(deger) -> int | None:
    if not deger:
        return None
    eslesme = re.search(r"\d{4}", str(deger))
    if not eslesme:
        return None
    yil = int(eslesme.group())
    # Anlamsız yılları sessizce kabul etmek, raporları bozar.
    return yil if 1900 <= yil <= date.today().year + 1 else None


def _guc(kayit: dict) -> float | None:
    for anahtar in ("kwNum", "kw"):
        deger = kayit.get(anahtar)
        if deger in (None, ""):
            continue
        try:
            sayi = float(str(deger).replace(",", "."))
        except ValueError:
            continue
        if sayi > 0:
            return sayi
    return None


def esle(kayit: dict) -> dict:
    """Kaynak kaydı `machines` sütunlarına çevirir."""
    alanlar: dict = {}
    for kaynak, sutun in ESLEME.items():
        deger = kayit.get(kaynak)
        if deger not in (None, ""):
            alanlar[sutun] = str(deger).strip()

    alanlar["commissioned_at"] = _tarih(kayit.get("alimTarihi"))
    alanlar["manufacture_date"] = _tarih(kayit.get("imalatYili"))
    alanlar["production_year"] = _yil(kayit.get("uretimYili"))
    alanlar["power_kw"] = _guc(kayit)

    # Hurdaya ayrılmış / faal olmayan ekipman pasif başlar: yeni arıza
    # kaydında listelenmemeli, ama geçmişi korunmalı.
    alanlar["is_active"] = machine_service.konum_durumu(
        kayit.get("yeniKonum")
    ) != "hurda"

    extra = {"kaynak_id": kayit.get("id")}
    for alan in EXTRA_ALANLARI:
        if kayit.get(alan) not in (None, ""):
            extra[alan] = kayit[alan]
    # İmalat yılı yalnızca yıl olarak verilmişse tarih sütununa yazılamaz;
    # kaybolmasın diye burada durur.
    if kayit.get("imalatYili") and not alanlar["manufacture_date"]:
        extra["imalat_yili_ham"] = kayit["imalatYili"]
    alanlar["extra"] = extra

    return alanlar


# --- Yazma ----------------------------------------------------------------
def _mevcut_kayit(kaynak_id) -> dict | None:
    if kaynak_id is None:
        return None
    return db.query_one(
        "SELECT id, name FROM machines WHERE extra->>'kaynak_id' = %s",
        (str(kaynak_id),),
    )


def _seri_cakismasi(serial_no: str, machine_id: int | None) -> bool:
    """Bu seri numarası başka bir makinede kullanılıyor mu."""
    if not serial_no:
        return False
    sql = "SELECT id FROM machines WHERE serial_no = %s"
    params: list = [serial_no]
    if machine_id:
        sql += " AND id <> %s"
        params.append(machine_id)
    return db.query_one(sql, tuple(params)) is not None


def _demo_temizle(onaysiz: bool) -> bool:
    makine = db.scalar("SELECT COUNT(*) FROM machines")
    ariza = db.scalar("SELECT COUNT(*) FROM faults")
    if not makine and not ariza:
        print("Temizlenecek kayıt yok.")
        return True

    print(f"UYARI: {makine} makine ve {ariza} arıza kaydı silinecek.")
    print("       Arıza geçmişi, ekleri ve bildirimleri de silinir.")
    if not onaysiz:
        yanit = input("Devam etmek için 'evet' yazın: ").strip().lower()
        if yanit != "evet":
            print("Vazgeçildi.")
            return False

    print("Önce yedek alınıyor...")
    try:
        yedek = backup_service.auto_backup(force=True)
        print(f"  Yedek: {yedek}")
    except Exception as exc:  # yedek alınamıyorsa silme yapılmaz
        print(f"HATA: yedek alınamadı, silme iptal edildi: {exc}")
        return False

    with db.transaction():
        db.execute("DELETE FROM faults")
        db.execute("DELETE FROM machines")
    print("Demo veriler silindi.")
    return True


def aktar(kayitlar: list[dict], kuru: bool = False) -> dict:
    """Kayıtları ekler/günceller ve sayaçları döner."""
    sonuc = {"eklendi": 0, "guncellendi": 0, "seri_cakismasi": [], "hata": []}
    # Bu çalıştırmada kullanılan seri numaraları: kaynak dosyanın kendi
    # içindeki tekrarlar kuru çalıştırmada da görünsün diye tutulur
    # (veritabanına yazılmadığı için oradan yakalanamazlar).
    kullanilan_seri: set[str] = set()

    for kayit in kayitlar:
        alanlar = esle(kayit)
        ad = alanlar.get("name")
        if not ad:
            sonuc["hata"].append(f"#{kayit.get('id')}: adı olmayan kayıt atlandı")
            continue

        mevcut = _mevcut_kayit(kayit.get("id"))

        # Seri numarası benzersizdir; kaynak listede birkaç tekrar var ve
        # bunlar veri hatasıdır. Kayıt yine de aktarılır, seri numarası boş
        # bırakılıp ham değer `extra` içinde saklanır ve rapora düşer.
        seri = alanlar.get("serial_no")
        if seri and (
            seri.casefold() in kullanilan_seri
            or _seri_cakismasi(seri, mevcut["id"] if mevcut else None)
        ):
            sonuc["seri_cakismasi"].append(f"#{kayit.get('id')} {ad} → {seri}")
            alanlar["extra"]["seri_cakisan"] = seri
            alanlar.pop("serial_no")
        elif seri:
            kullanilan_seri.add(seri.casefold())

        if kuru:
            sonuc["guncellendi" if mevcut else "eklendi"] += 1
            continue

        try:
            if mevcut:
                machine_service.update_machine(mevcut["id"], **alanlar)
                sonuc["guncellendi"] += 1
            else:
                machine_service.create_machine(**alanlar)
                sonuc["eklendi"] += 1
        except machine_service.MachineError as exc:
            sonuc["hata"].append(f"#{kayit.get('id')} {ad}: {exc}")

    return sonuc


def main() -> int:
    ayristirici = argparse.ArgumentParser(
        description="Ekipman listesi HTML dosyasını envantere aktarır."
    )
    ayristirici.add_argument("--dosya", required=True, help="Kaynak HTML dosyası")
    ayristirici.add_argument("--kuru-calistir", action="store_true",
                             help="Hiçbir şey yazmaz, ne olacağını gösterir")
    ayristirici.add_argument("--demo-temizle", action="store_true",
                             help="Aktarmadan önce tüm makine ve arıza kayıtlarını siler")
    ayristirici.add_argument("--onaysiz", action="store_true",
                             help="--demo-temizle için soru sormaz (betikler için)")
    args = ayristirici.parse_args()

    try:
        kayitlar = kayitlari_oku(args.dosya)
    except AktarmaHatasi as exc:
        print(f"HATA: {exc}")
        return 1

    db.init_db()

    print(f"Kaynak dosya : {args.dosya}")
    print(f"Kayıt sayısı : {len(kayitlar)}")
    print(f"Veritabanı   : {config.database_url_safe()}")
    if args.kuru_calistir:
        print("KURU ÇALIŞTIRMA — hiçbir şey yazılmayacak")
    print("-" * 62)

    if args.demo_temizle and not args.kuru_calistir:
        if not _demo_temizle(args.onaysiz):
            return 1

    sonuc = aktar(kayitlar, kuru=args.kuru_calistir)

    print(f"Eklenen      : {sonuc['eklendi']}")
    print(f"Güncellenen  : {sonuc['guncellendi']}")

    if sonuc["seri_cakismasi"]:
        print(f"\nSeri numarası çakışması ({len(sonuc['seri_cakismasi'])}) — bu "
              "kayıtlar seri numarası boş aktarıldı, ham değer `extra` içinde:")
        for satir in sonuc["seri_cakismasi"]:
            print(f"  {satir}")

    if sonuc["hata"]:
        print(f"\nHata ({len(sonuc['hata'])}):")
        for satir in sonuc["hata"]:
            print(f"  {satir}")
        return 1

    if not args.kuru_calistir:
        toplam = db.scalar("SELECT COUNT(*) FROM machines")
        guc = db.scalar("SELECT COALESCE(SUM(power_kw), 0) FROM machines")
        print(f"\nEnvanterde {toplam} makine, toplam kurulu güç {float(guc):.1f} kW.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
