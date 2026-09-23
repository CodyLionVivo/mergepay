"""Configuracion del motor de base de datos, sin tocar ninguna red.

SQLite en local y PostgreSQL en produccion salen de la misma URL: lo unico
que cambia es el driver y los argumentos de conexion.
"""

import pytest
from sqlalchemy import text

from app.database import (
    Base,
    connect_args_for,
    create_database_engine,
    normalize_database_url,
)

SQLITE_URL = "sqlite:///./mergepay.db"
POSTGRES_URL = "postgresql://mergepay:secret@db.railway.internal:5432/railway"
PSYCOPG_URL = "postgresql+psycopg://mergepay:secret@db.railway.internal:5432/railway"


# ─────────────────────────────────────────
# 1 a 5. Normalizacion de la URL.
# ─────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        SQLITE_URL,
        "sqlite://",
        "sqlite:////absolute/path/mergepay.db",
        "sqlite+pysqlite:///./mergepay.db",
    ],
)
def test_sqlite_urls_are_left_alone(url: str) -> None:
    assert normalize_database_url(url) == url


def test_postgresql_url_gets_the_psycopg_driver() -> None:
    assert normalize_database_url(POSTGRES_URL) == PSYCOPG_URL


def test_legacy_postgres_url_gets_the_psycopg_driver() -> None:
    legacy = "postgres://mergepay:secret@db.railway.internal:5432/railway"

    assert normalize_database_url(legacy) == PSYCOPG_URL


def test_psycopg_url_is_left_alone() -> None:
    assert normalize_database_url(PSYCOPG_URL) == PSYCOPG_URL


def test_normalization_keeps_everything_after_the_scheme() -> None:
    url = "postgresql://user:p%40ss@host:5432/db?sslmode=require"

    normalized = normalize_database_url(url)

    assert normalized.startswith("postgresql+psycopg://")
    assert normalized.endswith("user:p%40ss@host:5432/db?sslmode=require")


# ─────────────────────────────────────────
# 2 y 6. Argumentos de conexion.
# ─────────────────────────────────────────


@pytest.mark.parametrize("url", [SQLITE_URL, "sqlite://"])
def test_sqlite_gets_check_same_thread(url: str) -> None:
    assert connect_args_for(url) == {"check_same_thread": False}


@pytest.mark.parametrize("url", [POSTGRES_URL, PSYCOPG_URL])
def test_postgres_gets_no_connect_args(url: str) -> None:
    # check_same_thread es de SQLite: psycopg lo rechazaria al conectar.
    assert connect_args_for(url) == {}


# ─────────────────────────────────────────
# 7. El engine de PostgreSQL se construye sin conectar.
# ─────────────────────────────────────────


def test_postgres_engine_is_built_without_connecting() -> None:
    engine = create_database_engine(POSTGRES_URL)

    assert engine.url.drivername == "postgresql+psycopg"
    assert engine.url.host == "db.railway.internal"
    assert engine.url.database == "railway"
    assert engine.pool._pre_ping is True

    # El dialecto es el de psycopg 3, y no se abrio ninguna conexion.
    assert engine.dialect.driver == "psycopg"

    engine.dispose()


def test_postgres_engine_hides_the_password_in_its_repr() -> None:
    engine = create_database_engine(POSTGRES_URL)

    assert "secret" not in repr(engine)
    assert "secret" not in str(engine.url)

    engine.dispose()


# ─────────────────────────────────────────
# 8. SQLite sigue funcionando de verdad.
# ─────────────────────────────────────────


def test_sqlite_engine_creates_the_schema_and_queries() -> None:
    engine = create_database_engine("sqlite://")

    assert engine.url.drivername == "sqlite"

    Base.metadata.create_all(bind=engine)

    with engine.connect() as connection:
        tables = connection.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'table'")
        ).scalars()

        names = set(tables)

    assert {"bounties", "submissions", "verifications"} <= names
    assert {"auth_challenges", "auth_sessions"} <= names

    engine.dispose()
