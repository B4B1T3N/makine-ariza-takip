"""Uygulama geneli sabitler ve dosya yolları."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Makine Arıza Takip"
APP_VERSION = "1.0.0"
ORG_NAME = "MakineArizaTakip"


def _base_dir() -> Path:
    """PyInstaller ile paketlendiğinde exe klasörü, aksi halde proje kökü."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _base_dir()


def data_dir() -> Path:
    """Ek dosyaların ve yerel yedeklerin tutulduğu klasör.

    Öncelik sırası:
      1. MAT_DATA_DIR ortam değişkeni (sunucu kurulumunda bu kullanılır)
      2. Exe/proje klasöründe `portable.txt` varsa yanındaki `data` klasörü
      3. Windows: Belgeler\\MakineArizaTakip, diğer: ~/.local/share/MakineArizaTakip

    Neden %APPDATA% değil: Microsoft Store sürümü Python, AppData'ya yapılan
    yazmaları paketin sanal klasörüne yönlendirir. Python bu yolu "var"
    görür ama pg_dump gibi harici programlar göremez ve yedekleme sessizce
    kırılır. Belgeler klasörü bu yönlendirmeye tabi değildir.
    """
    env = os.environ.get("MAT_DATA_DIR")
    if env:
        path = Path(env)
    elif (BASE_DIR / "portable.txt").exists():
        path = BASE_DIR / "data"
    elif os.name == "nt":
        path = Path.home() / "Documents" / ORG_NAME
    else:
        path = Path.home() / ".local" / "share" / ORG_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


# --- Veritabanı -----------------------------------------------------------
# Yerel geliştirme varsayılanı. Üretimde DATABASE_URL ortam değişkeni
# (veya proje kökündeki .env dosyası) ile ezilir.
DEFAULT_DATABASE_URL = (
    "postgresql://postgres:MatDev2026!local@localhost:5432/ariza_takip"
)

DB_POOL_MAX = int(os.environ.get("MAT_DB_POOL_MAX", "8"))


def _load_dotenv() -> None:
    """Proje kökündeki .env dosyasını ortama yükler (varsa).

    Küçük bir okuyucu; python-dotenv bağımlılığı eklemeye değmiyor.
    Zaten tanımlı ortam değişkenleri ezilmez.
    """
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv()


def database_url() -> str:
    return os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL


def database_url_safe() -> str:
    """Şifresi gizlenmiş bağlantı adresi — ekranda/loglarda göstermek için."""
    url = database_url()
    if "://" not in url or "@" not in url:
        return url
    scheme, _, rest = url.partition("://")
    credentials, _, host = rest.rpartition("@")
    user = credentials.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"


def attachments_dir() -> Path:
    path = data_dir() / "ekler"
    path.mkdir(parents=True, exist_ok=True)
    return path


def backups_dir() -> Path:
    path = data_dir() / "yedekler"
    path.mkdir(parents=True, exist_ok=True)
    return path


# --- Ek dosyaları ve nesne depolama (Faz 4) -------------------------------
STORAGE_LOCAL = "yerel"
STORAGE_S3 = "s3"


def storage_backend() -> str:
    """Ek dosyalarının nerede tutulacağı: `yerel` veya `s3`.

    Varsayılan yereldir; tek sunucuda çalışan bir kurulum hiçbir şey
    tanımlamadan çalışmaya devam eder. `s3`, S3 uyumlu her servisi kapsar
    (AWS S3, MinIO, Cloudflare R2, DigitalOcean Spaces) — fark yalnızca
    `MAT_S3_ENDPOINT` değeridir.
    """
    secim = os.environ.get("MAT_STORAGE", STORAGE_LOCAL).strip().lower()
    return STORAGE_S3 if secim in ("s3", "blob", "nesne") else STORAGE_LOCAL


def s3_settings() -> dict:
    """S3 arka ucunun ayarları. Kimlik bilgileri ortam değişkenlerinden gelir."""
    return {
        "bucket": os.environ.get("MAT_S3_BUCKET", ""),
        # Boş bırakılırsa AWS'nin kendi adresi kullanılır. MinIO/R2/Spaces
        # için buraya servisin adresi yazılır.
        "endpoint": os.environ.get("MAT_S3_ENDPOINT", "") or None,
        "region": os.environ.get("MAT_S3_REGION", "") or None,
        "access_key": os.environ.get("MAT_S3_ACCESS_KEY", "") or None,
        "secret_key": os.environ.get("MAT_S3_SECRET_KEY", "") or None,
        # Kovanın içinde ekleri tek klasörde toplar; aynı kova başka bir iş
        # için de kullanılıyorsa karışmaz.
        "prefix": os.environ.get("MAT_S3_PREFIX", "ekler").strip("/"),
    }


# Ek dosyası üst sınırı. Atölyede telefonla çekilen fotoğraf birkaç MB'tır;
# 20 MB video olmayan her makul eki kapsar ve sunucuyu doldurmaz.
ATTACHMENT_MAX_BYTES = 20 * 1024 * 1024

# İzin verilen uzantılar. Beyaz liste tutulur: sunucuya çalıştırılabilir
# dosya yüklenmesinin önü baştan kapansın.
ATTACHMENT_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".bmp",
    ".pdf", ".txt", ".csv", ".log",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".mp4", ".mov",
)


# --- Roller ---------------------------------------------------------------
ROLE_OPERATOR = "operator"
ROLE_TECHNICIAN = "teknisyen"
ROLE_MANAGER = "yonetici"

ROLES = (ROLE_OPERATOR, ROLE_TECHNICIAN, ROLE_MANAGER)

ROLE_LABELS = {
    ROLE_OPERATOR: "Operatör",
    ROLE_TECHNICIAN: "Teknisyen",
    ROLE_MANAGER: "Yönetici",
}

# --- Arıza durumları ------------------------------------------------------
STATUS_OPEN = "acik"
STATUS_IN_PROGRESS = "inceleniyor"
STATUS_WAITING = "beklemede"
STATUS_RESOLVED = "cozuldu"
STATUS_CLOSED = "kapatildi"

STATUSES = (
    STATUS_OPEN,
    STATUS_IN_PROGRESS,
    STATUS_WAITING,
    STATUS_RESOLVED,
    STATUS_CLOSED,
)

STATUS_LABELS = {
    STATUS_OPEN: "Açık",
    STATUS_IN_PROGRESS: "İnceleniyor",
    STATUS_WAITING: "Parça/Bekleme",
    STATUS_RESOLVED: "Çözüldü",
    STATUS_CLOSED: "Kapatıldı",
}

# Durum akışı: hangi durumdan hangilerine geçilebilir.
STATUS_TRANSITIONS = {
    STATUS_OPEN: (STATUS_IN_PROGRESS, STATUS_WAITING, STATUS_RESOLVED),
    STATUS_IN_PROGRESS: (STATUS_WAITING, STATUS_RESOLVED, STATUS_OPEN),
    STATUS_WAITING: (STATUS_IN_PROGRESS, STATUS_RESOLVED, STATUS_OPEN),
    STATUS_RESOLVED: (STATUS_CLOSED, STATUS_IN_PROGRESS),
    STATUS_CLOSED: (),
}

# Henüz kapanmamış sayılan durumlar (dashboard "açık arıza" sayımı).
ACTIVE_STATUSES = (STATUS_OPEN, STATUS_IN_PROGRESS, STATUS_WAITING)

# Rozet renkleri: her zaman metin etiketiyle birlikte gösterilir, renk tek
# başına anlam taşımaz.
STATUS_COLORS = {
    STATUS_OPEN: "#d03b3b",
    STATUS_IN_PROGRESS: "#c98500",
    STATUS_WAITING: "#4a3aa7",
    STATUS_RESOLVED: "#0ca30c",
    STATUS_CLOSED: "#6b6a66",
}

# --- Öncelikler -----------------------------------------------------------
PRIORITY_LOW = "dusuk"
PRIORITY_MEDIUM = "orta"
PRIORITY_HIGH = "yuksek"
PRIORITY_URGENT = "acil"

PRIORITIES = (PRIORITY_LOW, PRIORITY_MEDIUM, PRIORITY_HIGH, PRIORITY_URGENT)

PRIORITY_LABELS = {
    PRIORITY_LOW: "Düşük",
    PRIORITY_MEDIUM: "Orta",
    PRIORITY_HIGH: "Yüksek",
    PRIORITY_URGENT: "Acil",
}

PRIORITY_ORDER = {
    PRIORITY_URGENT: 0,
    PRIORITY_HIGH: 1,
    PRIORITY_MEDIUM: 2,
    PRIORITY_LOW: 3,
}

PRIORITY_COLORS = {
    PRIORITY_LOW: "#2a78d6",
    PRIORITY_MEDIUM: "#c98500",
    PRIORITY_HIGH: "#eb6834",
    PRIORITY_URGENT: "#d03b3b",
}

# --- Log/geçmiş kayıt tipleri --------------------------------------------
LOG_CREATED = "olusturuldu"
LOG_STATUS = "durum"
LOG_NOTE = "not"
LOG_ASSIGN = "atama"
LOG_ATTACHMENT = "ek"
LOG_EDIT = "duzenleme"

LOG_LABELS = {
    LOG_CREATED: "Kayıt oluşturuldu",
    LOG_STATUS: "Durum değişikliği",
    LOG_NOTE: "Not eklendi",
    LOG_ASSIGN: "Atama",
    LOG_ATTACHMENT: "Dosya eklendi",
    LOG_EDIT: "Kayıt düzenlendi",
}

DATETIME_FMT = "%d.%m.%Y %H:%M"
DATE_FMT = "%d.%m.%Y"

# Veritabanı UTC saklar; kullanıcıya ve raporlara bu saat diliminde gösterilir.
# Rapor gün sınırları da bu dilime göre hesaplanır.
APP_TIMEZONE = os.environ.get("MAT_TIMEZONE", "Europe/Istanbul")


# --- Yayın ayarları (Faz 5) -----------------------------------------------
def _bayrak(ad: str, varsayilan: bool = False) -> bool:
    deger = os.environ.get(ad)
    if deger is None:
        return varsayilan
    return deger.strip().lower() in ("1", "true", "evet", "acik", "on", "yes")


def https_only() -> bool:
    """Uygulama HTTPS arkasında mı çalışıyor.

    Açıkken oturum çerezi yalnızca güvenli bağlantıda gönderilir ve HSTS
    başlığı eklenir. Düz HTTP ile çalışan yerel geliştirmede kapalıdır —
    açık olsaydı çerez hiç gönderilmez, giriş yapılamazdı.
    """
    return _bayrak("MAT_HTTPS", False)


def trust_proxy() -> bool:
    """`X-Forwarded-For` / `X-Forwarded-Proto` başlıklarına güvenilsin mi.

    Yalnızca uygulamanın önünde kendi ters vekiliniz (nginx, Caddy, bulut
    yük dengeleyici) varken açılmalıdır. Aksi halde istemci bu başlıkları
    kendisi uydurup hız sınırını başka bir adresin üzerine yıkabilir.
    """
    return _bayrak("MAT_TRUST_PROXY", False)


# Giriş hız sınırı: aynı kullanıcı adına art arda kaç başarısız deneme
# yapılabileceği ve sayacın kaç dakikada sıfırlandığı.
LOGIN_MAX_ATTEMPTS = int(os.environ.get("MAT_LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_WINDOW_MINUTES = int(os.environ.get("MAT_LOGIN_WINDOW_MINUTES", "15"))
# Aynı ağ adresinden gelen toplam başarısız deneme sınırı: saldırgan
# kullanıcı adı deneyerek sınırın etrafından dolaşmasın.
LOGIN_MAX_PER_ADDRESS = int(os.environ.get("MAT_LOGIN_MAX_PER_ADDRESS", "20"))

# Yedek bu yaşı geçtiyse yöneticiye uyarı gösterilir. Haftalık periyoda bir
# günlük pay eklenmiştir; zamanlanmış görev bir gün gecikse de bağırmasın.
BACKUP_WARN_DAYS = int(os.environ.get("MAT_BACKUP_WARN_DAYS", "8"))
