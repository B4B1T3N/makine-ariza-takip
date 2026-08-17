"""Demo verisi üretir (kullanıcılar, makineler, arıza kayıtları).

Kullanım:
    python tools/seed_demo.py            # mevcut veritabanına ekler
    python tools/seed_demo.py --reset    # veritabanını sıfırlayıp yeniden kurar

Üretim ortamında çalıştırmayın.
"""
from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows konsolu varsayılan olarak cp1254 kullanır; Türkçe çıktı bozulmasın.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app import config  # noqa: E402
from app.db import database as db  # noqa: E402
from app.services import auth_service, fault_service, machine_service  # noqa: E402
from app.utils.helpers import SQL_FMT  # noqa: E402

USERS = [
    ("ahmet", "1234", "Ahmet Yılmaz", config.ROLE_OPERATOR),
    ("zeynep", "1234", "Zeynep Kaya", config.ROLE_OPERATOR),
    ("mehmet", "1234", "Mehmet Demir", config.ROLE_TECHNICIAN),
    ("elif", "1234", "Elif Şahin", config.ROLE_TECHNICIAN),
    ("mudur", "1234", "Hakan Öztürk", config.ROLE_MANAGER),
]

MACHINES = [
    ("CNC Torna Tezgahı 1", "CNC-2019-001", "Hat A", "Talaşlı İmalat", "2019-03-15"),
    ("CNC Torna Tezgahı 2", "CNC-2020-014", "Hat A", "Talaşlı İmalat", "2020-06-01"),
    ("Enjeksiyon Presi 200T", "ENJ-2018-007", "Hat B", "Plastik", "2018-11-20"),
    ("Enjeksiyon Presi 350T", "ENJ-2021-003", "Hat B", "Plastik", "2021-02-10"),
    ("Konveyör Bant Sistemi", "KNV-2017-022", "Hat C", "Taşıma", "2017-05-05"),
    ("Paketleme Makinesi", "PKT-2022-009", "Hat C", "Paketleme", "2022-01-18"),
    ("Kompresör Ünitesi", "KMP-2016-001", "Makine Dairesi", "Yardımcı Tesis", "2016-08-30"),
    ("Kaynak Robotu R2", "RBT-2021-011", "Hat D", "Robotik", "2021-09-12"),
    ("Hidrolik Pres 100T", "HID-2015-004", "Hat D", "Şekillendirme", "2015-04-22"),
    ("Etiketleme Ünitesi", "ETK-2023-002", "Hat C", "Paketleme", "2023-03-01"),
]

FAULT_TEMPLATES = [
    ("Yağ kaçağı tespit edildi", "Makine altında yağ birikintisi görüldü, sızıntı devam ediyor."),
    ("Anormal titreşim ve ses", "Çalışma sırasında normalin üzerinde titreşim ve metalik ses var."),
    ("Motor aşırı ısınıyor", "Motor gövdesi elle dokunulamayacak kadar ısınıyor, koruma devreye giriyor."),
    ("Panelde hata kodu E-042", "Operatör panelinde E-042 hatası veriyor, reset sonrası tekrarlıyor."),
    ("Konveyör bandı kayıyor", "Bant gergisi yetersiz, ürünler hat üzerinde kayıyor."),
    ("Hidrolik basınç düşük", "Sistem basıncı 120 bar yerine 80 bar seviyesinde kalıyor."),
    ("Sensör sinyal vermiyor", "Yaklaşım sensörü ürünü algılamıyor, hat duruyor."),
    ("Kalıp değişiminde sıkışma", "Kalıp bağlama sistemi tam kilitlenmiyor."),
    ("Basınçlı hava kaçağı", "Hat üzerinde belirgin hava kaçağı sesi var, kompresör sürekli çalışıyor."),
    ("Ekran donuyor", "HMI ekranı rastgele donuyor, güç kesip açınca düzeliyor."),
    ("Zincir gerginliği bozuk", "Tahrik zinciri gevşemiş, atlama yapıyor."),
    ("Soğutma suyu sirkülasyonu yok", "Pompa çalışıyor ancak devirdaim gerçekleşmiyor."),
]

RESOLUTION_NOTES = [
    "Arızalı conta değiştirildi, sızdırmazlık test edildi.",
    "Rulman değişimi yapıldı, titreşim ölçümü normale döndü.",
    "Motor fanı temizlendi, termik koruma ayarı güncellendi.",
    "Yazılım güncellemesi yapıldı, hata tekrarlamıyor.",
    "Bant gergisi ayarlandı, hizalama kontrol edildi.",
    "Hidrolik filtre değiştirildi ve sistem havası alındı.",
    "Sensör yenisiyle değiştirildi, mesafe kalibre edildi.",
]


def reset_database() -> None:
    db.close_connection()
    for suffix in ("", "-wal", "-shm"):
        Path(str(config.db_path()) + suffix).unlink(missing_ok=True)
    print("Veritabanı sıfırlandı.")


def seed() -> None:
    db.init_db()

    user_ids: dict[str, int] = {}
    for username, password, full_name, role in USERS:
        existing = db.query_one("SELECT id FROM users WHERE username = ?", (username,))
        if existing:
            user_ids[username] = existing["id"]
            continue
        user_ids[username] = auth_service.create_user(username, password, full_name, role)
    print(f"{len(user_ids)} kullanıcı hazır.")

    machine_ids: list[int] = []
    for name, serial, location, category, commissioned in MACHINES:
        existing = db.query_one("SELECT id FROM machines WHERE serial_no = ?", (serial,))
        if existing:
            machine_ids.append(existing["id"])
            continue
        machine_ids.append(
            machine_service.create_machine(name, serial, location, category, commissioned)
        )
    print(f"{len(machine_ids)} makine hazır.")

    if db.scalar("SELECT COUNT(*) FROM faults") > 0:
        print("Arıza kayıtları zaten mevcut, yeni kayıt üretilmedi.")
        return

    rng = random.Random(42)
    operators = [user_ids["ahmet"], user_ids["zeynep"]]
    technicians = [user_ids["mehmet"], user_ids["elif"]]
    now = datetime.now()

    created = 0
    for _ in range(140):
        days_ago = rng.randint(0, 179)
        created_at = now - timedelta(
            days=days_ago, hours=rng.randint(0, 23), minutes=rng.randint(0, 59)
        )
        title, description = rng.choice(FAULT_TEMPLATES)
        machine_id = rng.choices(
            machine_ids, weights=[9, 7, 12, 5, 14, 4, 8, 3, 6, 2]
        )[0]
        priority = rng.choices(
            list(config.PRIORITIES), weights=[25, 40, 25, 10]
        )[0]
        reporter = rng.choice(operators)

        fault_id = fault_service.create_fault(
            machine_id, title, description, priority, reporter
        )
        # Gerçekçi bir tarih dağılımı için zaman damgaları geriye alınır.
        stamp = created_at.strftime(SQL_FMT)
        db.execute(
            "UPDATE faults SET created_at = ?, updated_at = ? WHERE id = ?",
            (stamp, stamp, fault_id),
        )
        db.execute(
            "UPDATE fault_logs SET created_at = ? WHERE fault_id = ?", (stamp, fault_id)
        )

        # Kayıtların çoğu ilerletilir; bir kısmı açık bırakılır.
        roll = rng.random()
        if roll < 0.15:
            continue

        technician = rng.choice(technicians)
        fault_service.assign(fault_id, technician, technician)
        _shift_last_log(fault_id, created_at + timedelta(hours=rng.randint(1, 8)))
        fault_service.change_status(fault_id, technician, config.STATUS_IN_PROGRESS,
                                    "Yerinde inceleme yapıldı.")
        progress_at = created_at + timedelta(hours=rng.randint(2, 20))
        _shift_last_log(fault_id, progress_at)

        if roll < 0.30:
            continue

        if roll < 0.42:
            fault_service.change_status(fault_id, technician, config.STATUS_WAITING,
                                        "Yedek parça siparişi verildi.")
            _shift_last_log(fault_id, progress_at + timedelta(hours=rng.randint(1, 12)))
            continue

        resolve_hours = rng.choices(
            [rng.uniform(1, 6), rng.uniform(6, 30), rng.uniform(30, 120)],
            weights=[50, 35, 15],
        )[0]
        resolved_at = created_at + timedelta(hours=resolve_hours)
        if resolved_at > now:
            resolved_at = now - timedelta(hours=1)

        fault_service.change_status(
            fault_id, technician, config.STATUS_RESOLVED, rng.choice(RESOLUTION_NOTES)
        )
        db.execute(
            "UPDATE faults SET resolved_at = ?, updated_at = ? WHERE id = ?",
            (resolved_at.strftime(SQL_FMT), resolved_at.strftime(SQL_FMT), fault_id),
        )
        _shift_last_log(fault_id, resolved_at)

        if roll < 0.70:
            continue

        closed_at = resolved_at + timedelta(hours=rng.randint(1, 48))
        if closed_at > now:
            closed_at = now - timedelta(minutes=30)
        fault_service.change_status(
            fault_id, user_ids["mudur"], config.STATUS_CLOSED, "Kontrol edildi, kayıt kapatıldı."
        )
        db.execute(
            "UPDATE faults SET closed_at = ?, updated_at = ? WHERE id = ?",
            (closed_at.strftime(SQL_FMT), closed_at.strftime(SQL_FMT), fault_id),
        )
        _shift_last_log(fault_id, closed_at)
        created += 1

    total = db.scalar("SELECT COUNT(*) FROM faults")
    print(f"{total} arıza kaydı üretildi.")
    print("\nDemo giriş bilgileri (şifre: 1234):")
    for username, _, full_name, role in USERS:
        print(f"  {username:8s} - {full_name:16s} ({config.ROLE_LABELS[role]})")
    print("  admin    - Sistem Yöneticisi  (Yönetici, şifre: admin)")


def _shift_last_log(fault_id: int, when: datetime) -> None:
    """Demo verisinde log zaman damgasını gerçekçi tarihe çeker."""
    db.execute(
        """UPDATE fault_logs SET created_at = ?
            WHERE id = (SELECT MAX(id) FROM fault_logs WHERE fault_id = ?)""",
        (when.strftime(SQL_FMT), fault_id),
    )


if __name__ == "__main__":
    if "--reset" in sys.argv:
        reset_database()
    seed()
