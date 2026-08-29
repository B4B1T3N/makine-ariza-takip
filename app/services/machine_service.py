"""Makine / ekipman envanteri işlemleri.

Makine kaydı bir arıza formundan fazlasıdır: tesisin ekipman listesindeki
künye (bina, bölüm, makina kodu, üretici, elektrik değerleri, ERP kodları)
burada durur. Alan adları veritabanı sütunlarıyla birebir aynıdır; arayüz
etiketleri `ALAN_ETIKETLERI` içindedir.
"""
from __future__ import annotations

import psycopg
from psycopg.types.json import Jsonb

from app import config
from app.db import database as db

TR_COLLATE = 'COLLATE "tr-TR-x-icu"'


class MachineError(Exception):
    """Makine işlemi hatası (kullanıcıya gösterilebilir mesaj)."""


# Künyedeki serbest metin alanları. create/update bunları olduğu gibi kabul
# eder; listeye yeni alan eklemek için tek yer burasıdır.
METIN_ALANLARI = (
    "building", "new_location", "machine_code", "asset_no", "model",
    "definition", "manufacturer", "physical_area", "sub_account", "unit_no",
    "bu_code", "bu_name", "awc_code", "awc_name",
    "voltage", "phase", "amperage", "fuse", "cable", "leakage_relay",
    "pressure_bar",
)
SAYI_ALANLARI = ("production_year", "power_kw")
TARIH_ALANLARI = ("manufacture_date",)

ENVANTER_ALANLARI = METIN_ALANLARI + SAYI_ALANLARI + TARIH_ALANLARI

ALAN_ETIKETLERI = {
    "name": "Tezgah / ekipman adı",
    "location": "Bölüm",
    "building": "Bina",
    "new_location": "Yeni fabrikadaki konum",
    "category": "Tip",
    "physical_area": "Fiziki bölüm",
    "machine_code": "Makina kodu",
    "asset_no": "Asset kodu",
    "model": "Model",
    "definition": "Tanım",
    "manufacturer": "Üretici firma",
    "serial_no": "Seri no",
    "unit_no": "Unit number",
    "commissioned_at": "Alım / devreye alma tarihi",
    "production_year": "Üretim yılı",
    "manufacture_date": "İmalat tarihi",
    "voltage": "Voltaj",
    "phase": "Faz sayısı",
    "amperage": "Amper",
    "power_kw": "Güç (kW)",
    "fuse": "Besleme sigortası",
    "cable": "Besleme kablosu",
    "leakage_relay": "Kaçak akım rölesi",
    "pressure_bar": "Basınç (bar)",
    "bu_code": "Business unit",
    "bu_name": "Business center",
    "awc_code": "Actual business center",
    "awc_name": "Actual work center",
    "sub_account": "Alt acc desc",
    "notes": "Not",
}

# Künye ekranındaki gruplar: hangi alan hangi başlık altında görünecek.
KUNYE_GRUPLARI = (
    ("Temel bilgiler", ("location", "building", "category", "new_location",
                        "physical_area")),
    ("Kimlik", ("machine_code", "asset_no", "model", "definition",
                "manufacturer", "serial_no", "unit_no")),
    ("Elektrik ve pnömatik", ("voltage", "phase", "amperage", "power_kw",
                              "fuse", "cable", "leakage_relay", "pressure_bar")),
    ("Tarihçe", ("commissioned_at", "production_year", "manufacture_date")),
    ("Organizasyon (ERP)", ("bu_code", "bu_name", "awc_code", "awc_name",
                            "sub_account")),
)

# Sol filtre panelindeki başlıklar: (sütun, etiket).
FILTRE_ALANLARI = (
    ("building", "Bina"),
    ("location", "Bölüm"),
    ("category", "Tip"),
    ("new_location", "Yeni konum"),
    ("manufacturer", "Üretici firma"),
)

# Sıralama seçenekleri: anahtar -> (etiket, sütun ifadeleri). Yön ayrı
# verilir; ifadelere DESC gömülmez ki ters sıralama tek yerden uygulansın.
SIRALAMALAR = {
    "bolum": ("Bölüm", (f"m.location {TR_COLLATE}", f"m.name {TR_COLLATE}")),
    "ad": ("Tezgah adı", (f"m.name {TR_COLLATE}",)),
    "bina": ("Bina", (f"m.building {TR_COLLATE}", f"m.name {TR_COLLATE}")),
    "tip": ("Tip", (f"m.category {TR_COLLATE}", f"m.name {TR_COLLATE}")),
    "guc": ("Güç (kW)", ("m.power_kw",)),
    "yil": ("Üretim yılı", ("m.production_year",)),
    "ariza": ("Açık arıza", ("open_faults", "total_faults")),
}
VARSAYILAN_SIRALAMA = "bolum"

# Boş değerlerin ekrandaki ve filtredeki karşılığı. Boş metin "filtre yok"
# anlamına geldiği için ayrı bir işaret gerekir: bu değer seçildiğinde
# alanı boş (NULL ya da boş metin) olan kayıtlar listelenir.
BOS_DEGER = "—"

# Yeni konum değerinin ne anlama geldiği: rozet rengi buna göre seçilir ve
# içe aktarma makineyi pasife alırken de aynı listeye bakar.
KONUM_HURDA = ("HURDA", "FAAL DEĞİL", "SATIL")
KONUM_TASINDI = ("TAŞINDI",)
KONUM_YENI = ("YENİ",)


def konum_durumu(deger: str | None) -> str:
    """Yeni konum etiketinin sınıfı: yeni | tasindi | hurda | atanmadi | diger."""
    if not deger or not deger.strip():
        return "atanmadi"
    # Türkçe'de "i" büyük harfte "İ" olur; bu dönüşüm upper()'dan önce
    # yapılmalıdır, sonra yapılırsa ortada "i" kalmadığı için etkisizdir.
    buyuk = deger.replace("i", "İ").upper()
    if any(k in buyuk for k in KONUM_HURDA):
        return "hurda"
    if any(buyuk.startswith(k) for k in KONUM_YENI):
        return "yeni"
    if any(k in buyuk for k in KONUM_TASINDI):
        return "tasindi"
    return "diger"


# --- Filtreleme -----------------------------------------------------------
_SECIM = """
    SELECT m.*,
           (SELECT COUNT(*) FROM faults f
             WHERE f.machine_id = m.id AND f.status = ANY(%s)) AS open_faults,
           (SELECT COUNT(*) FROM faults f WHERE f.machine_id = m.id) AS total_faults
      FROM machines m
"""


def _liste_kosulu(deger) -> list[str]:
    """Tek değer de liste de kabul edilir; boşlar elenir."""
    if deger is None:
        return []
    if isinstance(deger, str):
        deger = [deger]
    return [d for d in deger if d not in (None, "")]


def _filtre(
    search: str = "",
    include_inactive: bool = False,
    category=None,
    building=None,
    location=None,
    new_location=None,
    manufacturer=None,
    only_unassigned: bool = False,
    missing_power: bool = False,
    haric: str | None = None,
) -> tuple[str, list]:
    """Ortak WHERE koşulu.

    `haric`, o alanın kendi koşulunu dışarıda bırakır: filtre panelindeki
    sayılar hesaplanırken bir başlığın kendi seçimi sayıma katılmamalıdır,
    yoksa seçili olmayan değerler hep 0 görünürdü.
    """
    sql = " WHERE TRUE"
    params: list = []

    if not include_inactive:
        sql += " AND m.is_active"

    if search:
        sql += """ AND (m.name ILIKE %s OR m.serial_no ILIKE %s
                        OR m.location ILIKE %s OR m.machine_code ILIKE %s
                        OR m.asset_no ILIKE %s OR m.model ILIKE %s
                        OR m.manufacturer ILIKE %s OR m.definition ILIKE %s
                        OR m.building ILIKE %s)"""
        params += [f"%{search}%"] * 9

    for alan, deger in (
        ("category", category),
        ("building", building),
        ("location", location),
        ("new_location", new_location),
        ("manufacturer", manufacturer),
    ):
        secilenler = _liste_kosulu(deger)
        if not secilenler or alan == haric:
            continue

        # Boş değer ekranda tek bir "—" seçeneğidir; veritabanında ise hem
        # NULL hem boş metin olarak geçebilir (kaynak listede ikisi de var).
        dolu = [d for d in secilenler if d != BOS_DEGER]
        bos_secildi = BOS_DEGER in secilenler

        kosullar = []
        if dolu:
            kosullar.append(f"m.{alan} = ANY(%s)")
            params.append(dolu)
        if bos_secildi:
            kosullar.append(f"(m.{alan} IS NULL OR btrim(m.{alan}) = '')")
        sql += " AND (" + " OR ".join(kosullar) + ")"

    if only_unassigned:
        sql += " AND (m.new_location IS NULL OR btrim(m.new_location) = '')"
    if missing_power:
        sql += """ AND m.power_kw IS NULL AND (m.voltage IS NULL
                   OR btrim(m.voltage) = '')"""

    return sql, params


def list_machines(
    search: str = "",
    include_inactive: bool = False,
    category=None,
    building=None,
    location=None,
    new_location=None,
    manufacturer=None,
    only_unassigned: bool = False,
    missing_power: bool = False,
    sort: str = VARSAYILAN_SIRALAMA,
    descending: bool = False,
    limit: int | None = None,
) -> list[dict]:
    """Makineleri açık arıza sayısı ile birlikte listeler."""
    where, params = _filtre(
        search, include_inactive, category, building, location,
        new_location, manufacturer, only_unassigned, missing_power,
    )
    _etiket, ifadeler = SIRALAMALAR.get(sort, SIRALAMALAR[VARSAYILAN_SIRALAMA])
    yon = "DESC" if descending else "ASC"
    # Boş alanlar her iki yönde de sonda kalsın: künyesi eksik makineler
    # listenin başını kaplamamalı.
    siralama = ", ".join(f"{ifade} {yon} NULLS LAST" for ifade in ifadeler)

    sql = _SECIM + where + " ORDER BY m.is_active DESC, " + siralama
    if limit:
        sql += f" LIMIT {int(limit)}"
    return db.query(sql, tuple([list(config.ACTIVE_STATUSES)] + params))


def facet_counts(alan: str, **filtre) -> list[dict]:
    """Filtre panelindeki bir başlığın değerleri ve kayıt sayıları."""
    if alan not in dict(FILTRE_ALANLARI):
        raise MachineError("Bilinmeyen filtre alanı.")

    where, params = _filtre(haric=alan, **filtre)
    # ORDER BY içindeki COLLATE bir ifadedir; ifadeler çıktı takma adına
    # bakamaz, bu yüzden sütun ifadesi burada bir kez daha yazılır.
    deger = f"COALESCE(NULLIF(btrim(m.{alan}), ''), '{BOS_DEGER}')"
    return db.query(
        f"""SELECT {deger} AS deger, COUNT(*) AS adet
              FROM machines m {where}
             GROUP BY {deger}
             ORDER BY adet DESC, {deger} {TR_COLLATE}""",
        tuple(params),
    )


def inventory_summary(**filtre) -> dict:
    """Listenin üstündeki istatistik şeridi."""
    where, params = _filtre(**filtre)
    row = db.query_one(
        f"""SELECT COUNT(*)                                   AS kayit,
                   COALESCE(SUM(m.power_kw), 0)               AS guc,
                   COUNT(DISTINCT NULLIF(btrim(m.location), '')) AS bolum,
                   COUNT(DISTINCT NULLIF(btrim(m.building), '')) AS bina,
                   COUNT(*) FILTER (
                       WHERE m.new_location IS NULL
                          OR btrim(m.new_location) = '')      AS konumsuz,
                   COUNT(*) FILTER (WHERE NOT m.is_active)    AS pasif
              FROM machines m {where}""",
        tuple(params),
    )
    ozet = dict(row) if row else {}
    ozet["guc"] = float(ozet.get("guc") or 0)
    # Açık arızası olan makine sayısı ayrı sorgudur: filtre koşulu makineye,
    # sayım arızaya bakar.
    ozet["arizali"] = db.scalar(
        f"""SELECT COUNT(*) FROM machines m {where}
             AND EXISTS (SELECT 1 FROM faults f
                          WHERE f.machine_id = m.id AND f.status = ANY(%s))""",
        tuple(params + [list(config.ACTIVE_STATUSES)]),
    )
    return ozet


def get_machine(machine_id: int) -> dict | None:
    return db.query_one("SELECT * FROM machines WHERE id = %s", (machine_id,))


# Not: PostgreSQL'de SELECT DISTINCT ile birlikte COLLATE'li ORDER BY
# kullanılamaz ("ORDER BY expressions must appear in select list").
# Aynı sonucu veren GROUP BY bu kısıtlamaya tabi değildir.
def list_categories() -> list[str]:
    return _sutun_degerleri("category")


def list_locations() -> list[str]:
    return _sutun_degerleri("location")


def list_buildings() -> list[str]:
    return _sutun_degerleri("building")


def _sutun_degerleri(sutun: str) -> list[str]:
    rows = db.query(
        f"""SELECT {sutun} AS deger FROM machines
             WHERE {sutun} IS NOT NULL AND btrim({sutun}) <> ''
             GROUP BY {sutun}
             ORDER BY {sutun} {TR_COLLATE}"""
    )
    return [r["deger"] for r in rows]


# --- Kayıt ----------------------------------------------------------------
def _temizle(deger) -> str | None:
    if deger is None:
        return None
    metin = str(deger).strip()
    return metin or None


def _sayi(deger, ondalikli: bool = False):
    if deger in (None, ""):
        return None
    try:
        return float(deger) if ondalikli else int(deger)
    except (TypeError, ValueError):
        return None


def _envanter_degerleri(alanlar: dict) -> dict:
    """Künye alanlarını sütun adına göre normalleştirir."""
    temiz: dict = {}
    for alan in METIN_ALANLARI:
        temiz[alan] = _temizle(alanlar.get(alan))
    temiz["production_year"] = _sayi(alanlar.get("production_year"))
    temiz["power_kw"] = _sayi(alanlar.get("power_kw"), ondalikli=True)
    for alan in TARIH_ALANLARI:
        temiz[alan] = _temizle(alanlar.get(alan))
    return temiz


def create_machine(
    name: str,
    serial_no: str = "",
    location: str = "",
    category: str = "",
    commissioned_at: str | None = None,
    notes: str = "",
    is_active: bool = True,
    extra: dict | None = None,
    **envanter,
) -> int:
    name = (name or "").strip()
    if not name:
        raise MachineError("Makine adı boş olamaz.")

    alanlar = _envanter_degerleri(envanter)
    sutunlar = ["name", "serial_no", "location", "category", "commissioned_at",
                "notes", "is_active", "extra"] + list(alanlar)
    degerler = [
        name,
        _temizle(serial_no),
        (location or "").strip(),
        (category or "").strip(),
        commissioned_at or None,
        (notes or "").strip(),
        bool(is_active),
        Jsonb(extra) if extra else None,
    ] + [alanlar[a] for a in alanlar]

    yer_tutucu = ", ".join(["%s"] * len(sutunlar))
    try:
        return db.insert(
            f"INSERT INTO machines ({', '.join(sutunlar)}) VALUES ({yer_tutucu})",
            tuple(degerler),
        )
    except psycopg.errors.UniqueViolation as exc:
        raise MachineError(f"'{serial_no}' seri numarası zaten kayıtlı.") from exc


def update_machine(
    machine_id: int,
    name: str,
    serial_no: str = "",
    location: str = "",
    category: str = "",
    commissioned_at: str | None = None,
    notes: str = "",
    is_active: bool = True,
    extra: dict | None = None,
    **envanter,
) -> None:
    name = (name or "").strip()
    if not name:
        raise MachineError("Makine adı boş olamaz.")

    if not is_active and open_fault_count(machine_id) > 0:
        raise MachineError(
            "Bu makinede kapanmamış arıza kaydı var. Önce kayıtları kapatın."
        )

    alanlar = _envanter_degerleri(envanter)
    atamalar = ["name = %s", "serial_no = %s", "location = %s", "category = %s",
                "commissioned_at = %s", "notes = %s", "is_active = %s"]
    degerler = [
        name,
        _temizle(serial_no),
        (location or "").strip(),
        (category or "").strip(),
        commissioned_at or None,
        (notes or "").strip(),
        bool(is_active),
    ]
    if extra is not None:
        atamalar.append("extra = %s")
        degerler.append(Jsonb(extra) if extra else None)

    for alan, deger in alanlar.items():
        atamalar.append(f"{alan} = %s")
        degerler.append(deger)

    try:
        db.execute(
            f"UPDATE machines SET {', '.join(atamalar)} WHERE id = %s",
            tuple(degerler + [machine_id]),
        )
    except psycopg.errors.UniqueViolation as exc:
        raise MachineError(f"'{serial_no}' seri numarası zaten kayıtlı.") from exc


def set_active(machine_id: int, is_active: bool) -> None:
    if not is_active and open_fault_count(machine_id) > 0:
        raise MachineError(
            "Bu makinede kapanmamış arıza kaydı var. Önce kayıtları kapatın."
        )
    db.execute(
        "UPDATE machines SET is_active = %s WHERE id = %s", (bool(is_active), machine_id)
    )


def open_fault_count(machine_id: int) -> int:
    return db.scalar(
        """SELECT COUNT(*) FROM faults
            WHERE machine_id = %s AND status = ANY(%s)""",
        (machine_id, list(config.ACTIVE_STATUSES)),
    )


def machine_stats(machine_id: int) -> dict:
    """Makine detay ekranı için özet istatistikler."""
    total = db.scalar("SELECT COUNT(*) FROM faults WHERE machine_id = %s", (machine_id,))
    avg_hours = db.scalar(
        """SELECT AVG(EXTRACT(EPOCH FROM (resolved_at - occurred_at)) / 3600.0)
             FROM faults
            WHERE machine_id = %s AND resolved_at IS NOT NULL""",
        (machine_id,),
        default=None,
    )
    last = db.query_one(
        """SELECT occurred_at FROM faults
            WHERE machine_id = %s ORDER BY occurred_at DESC LIMIT 1""",
        (machine_id,),
    )
    return {
        "total_faults": total,
        "open_faults": open_fault_count(machine_id),
        "avg_resolution_hours": float(avg_hours) if avg_hours is not None else None,
        "last_fault_at": last["occurred_at"] if last else None,
    }
