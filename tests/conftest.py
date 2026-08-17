"""Test ortamı.

Testler ayrı bir PostgreSQL veritabanına bağlanır ve her testten önce tüm
tabloları siler. Bağlantı adresi `TEST_DATABASE_URL` ile verilir; üretim
veritabanının yanlışlıkla silinmemesi için adında "test" geçmesi zorunludur.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _test_database_url() -> str:
    from app import config  # .env yüklensin diye içeride import edilir

    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        # Varsayılan: üretim adresinin yanına "_test" eklenmiş veritabanı.
        base = config.database_url()
        url = base.rsplit("/", 1)[0] + "/ariza_takip_test"

    if "test" not in url.rsplit("/", 1)[-1].lower():
        raise RuntimeError(
            "TEST_DATABASE_URL bir test veritabanını göstermeli "
            f"(adında 'test' geçmeli). Şu an: {url.rsplit('/', 1)[-1]}"
        )
    return url


@pytest.fixture(scope="session", autouse=True)
def _point_at_test_database():
    """Tüm oturum boyunca uygulamayı test veritabanına yönlendirir."""
    url = _test_database_url()
    os.environ["DATABASE_URL"] = url

    from app import config
    config.DEFAULT_DATABASE_URL = url

    yield

    from app.db import database
    database.close_pool()


@pytest.fixture()
def app_db(_point_at_test_database):
    """Her test için boş, yeni kurulmuş bir şema."""
    from app.db import database

    database.close_pool()
    database.drop_all()
    database.init_db()
    yield database
    database.close_pool()


@pytest.fixture()
def users(app_db):
    """admin / operatör / teknisyen üçlüsü."""
    from app import config
    from app.services import auth_service

    auth_service.create_user("op", "1234", "Operatör Kişi", config.ROLE_OPERATOR)
    auth_service.create_user("tk", "1234", "Teknisyen Kişi", config.ROLE_TECHNICIAN)
    return {
        "admin": auth_service.login("admin", "admin"),
        "operator": auth_service.login("op", "1234"),
        "technician": auth_service.login("tk", "1234"),
    }


@pytest.fixture()
def machines(app_db):
    from app.services import machine_service

    return [
        machine_service.create_machine("Pres 1", "SN-1", "Hat A", "Pres", "2020-01-01"),
        machine_service.create_machine("Torna 1", "SN-2", "Hat B", "Torna"),
    ]
