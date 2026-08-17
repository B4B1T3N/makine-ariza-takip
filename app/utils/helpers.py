"""Tarih/metin biçimlendirme yardımcıları."""
from __future__ import annotations

from datetime import datetime

from app.config import DATE_FMT, DATETIME_FMT

SQL_FMT = "%Y-%m-%d %H:%M:%S"
SQL_DATE_FMT = "%Y-%m-%d"


def now_sql() -> str:
    """Veritabanına yazılacak yerel zaman damgası."""
    return datetime.now().strftime(SQL_FMT)


def parse_sql(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in (SQL_FMT, SQL_DATE_FMT):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def fmt_datetime(value: str | None) -> str:
    dt = parse_sql(value)
    return dt.strftime(DATETIME_FMT) if dt else "-"


def fmt_date(value: str | None) -> str:
    dt = parse_sql(value)
    return dt.strftime(DATE_FMT) if dt else "-"


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
