"""Tarih/saat ve metin biçimlendirme yardımcıları.

Saat dilimi kuralı (bulut sürümünde kritik):
  * Veritabanında her şey **UTC** saklanır (TIMESTAMPTZ).
  * Kullanıcıya her şey **yerel saatte** (Europe/Istanbul) gösterilir.
  * Rapor gün sınırları da yerel saate göre hesaplanır; aksi halde gece
    yarısı civarındaki kayıtlar yanlış güne düşer.

psycopg TIMESTAMPTZ sütunlarını saat dilimi bilgili `datetime` olarak döner,
bu yüzden SQLite sürümündeki metin ayrıştırma artık gerekmez. Yine de
fonksiyonlar metin girdisini de kabul eder (eski yedeklerden okuma vb.).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.config import APP_TIMEZONE, DATE_FMT, DATETIME_FMT

LOCAL_TZ = ZoneInfo(APP_TIMEZONE)

_TEXT_FORMATS = ("%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")


def now_utc() -> datetime:
    """Veritabanına yazılacak zaman damgası (UTC, saat dilimi bilgili)."""
    return datetime.now(timezone.utc)


def to_utc(value: datetime) -> datetime:
    """Saat dilimi bilgisi olmayan bir değeri yerel kabul edip UTC'ye çevirir."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=LOCAL_TZ)
    return value.astimezone(timezone.utc)


def to_local(value: datetime | str | None) -> datetime | None:
    """Herhangi bir zaman damgasını yerel saate çevirir."""
    parsed = _coerce(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        # Saat dilimi yoksa UTC varsayılır (veritabanı kuralı budur).
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(LOCAL_TZ)


def _coerce(value: datetime | str | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    for fmt in _TEXT_FORMATS:
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


# Eski adla çağıran kod için (masaüstü arayüz Faz 1'de değişmeden çalışsın).
parse_sql = to_local


def fmt_datetime(value: datetime | str | None) -> str:
    local = to_local(value)
    return local.strftime(DATETIME_FMT) if local else "-"


def fmt_date(value: datetime | str | date | None) -> str:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.strftime(DATE_FMT)
    local = to_local(value)
    return local.strftime(DATE_FMT) if local else "-"


def today_local() -> date:
    """Yerel saate göre bugünün tarihi (rapor gün sınırları için)."""
    return datetime.now(LOCAL_TZ).date()


def hours_between(start, end) -> float | None:
    """İki zaman damgası arasındaki saat farkı; biri yoksa None."""
    first, second = _coerce(start), _coerce(end)
    if first is None or second is None:
        return None
    if first.tzinfo is None:
        first = first.replace(tzinfo=timezone.utc)
    if second.tzinfo is None:
        second = second.replace(tzinfo=timezone.utc)
    return (second - first).total_seconds() / 3600


def humanize_duration(hours: float | None) -> str:
    """Saat cinsinden süreyi '2 gün 3 sa' gibi okunur metne çevirir."""
    if hours is None:
        return "-"
    if hours < 1:
        return f"{int(round(hours * 60))} dk"
    if hours < 24:
        return f"{hours:.1f} sa"
    days = int(hours // 24)
    rest = hours - days * 24
    if rest < 1:
        return f"{days} gün"
    return f"{days} gün {rest:.0f} sa"
