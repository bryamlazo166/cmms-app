"""Tests de utils/tz.py — helpers de zona horaria America/Lima."""
from datetime import datetime, timezone, timedelta

from utils.tz import (
    LIMA_TZ,
    now_lima,
    now_lima_naive,
    today_lima,
    now_lima_iso,
    today_lima_iso,
    to_lima,
)


def test_now_lima_is_tz_aware():
    n = now_lima()
    assert n.tzinfo is not None


def test_lima_offset_is_minus_5h():
    """Lima es UTC-5 fijo, sin DST."""
    n = now_lima()
    off = n.utcoffset()
    assert off.total_seconds() == -5 * 3600


def test_now_lima_naive_has_no_tz():
    n = now_lima_naive()
    assert n.tzinfo is None


def test_today_lima_returns_date():
    from datetime import date
    t = today_lima()
    assert isinstance(t, date)


def test_now_lima_iso_format():
    iso = now_lima_iso()
    # 'YYYY-MM-DDTHH:MM:SS'
    assert len(iso) == 19
    assert iso[4] == '-' and iso[7] == '-' and iso[10] == 'T' and iso[13] == ':'


def test_now_lima_iso_no_seconds():
    iso = now_lima_iso(with_seconds=False)
    # 'YYYY-MM-DDTHH:MM'
    assert len(iso) == 16


def test_today_lima_iso_format():
    iso = today_lima_iso()
    assert len(iso) == 10
    assert iso[4] == '-' and iso[7] == '-'


def test_to_lima_from_utc_naive():
    """Naive datetime se asume UTC y se convierte a Lima."""
    utc_naive = datetime(2026, 5, 13, 17, 30, 0)  # 17:30 UTC = 12:30 Lima
    lima = to_lima(utc_naive)
    assert lima.tzinfo is not None
    assert lima.hour == 12
    assert lima.minute == 30


def test_to_lima_from_utc_aware():
    """Aware UTC se convierte correctamente a Lima."""
    utc_aware = datetime(2026, 5, 13, 17, 30, 0, tzinfo=timezone.utc)
    lima = to_lima(utc_aware)
    assert lima.hour == 12
    assert lima.minute == 30


def test_to_lima_handles_none():
    assert to_lima(None) is None


def test_lima_does_not_observe_dst():
    """Lima NO observa horario de verano. Verifica que invierno/verano dan mismo offset."""
    # Enero (verano sur)
    summer = datetime(2026, 1, 15, 12, 0, 0, tzinfo=LIMA_TZ)
    # Julio (invierno sur)
    winter = datetime(2026, 7, 15, 12, 0, 0, tzinfo=LIMA_TZ)
    assert summer.utcoffset() == winter.utcoffset()
    assert summer.utcoffset() == timedelta(hours=-5)
