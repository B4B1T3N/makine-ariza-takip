"""Test ortamı: her test izole bir geçici veritabanı kullanır."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture()
def app_db(tmp_path, monkeypatch):
    """Geçici veri klasörü ile kurulmuş boş bir veritabanı döner."""
    monkeypatch.setenv("MAT_DATA_DIR", str(tmp_path))

    from app.db import database

    database.close_connection()
    database.init_db()
    yield database
    database.close_connection()


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
