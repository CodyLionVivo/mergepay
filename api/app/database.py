"""Motor de base de datos: SQLite en local, PostgreSQL en produccion.

La URL llega por configuracion. Railway entrega la suya en el formato
`postgresql://`, que SQLAlchemy resolveria al driver psycopg2; aqui se
normaliza al que instalamos, psycopg 3.
"""

from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

PSYCOPG_PREFIX = "postgresql+psycopg://"

# Esquemas de PostgreSQL que hay que reescribir. `postgres://` es la forma
# antigua que todavia usan algunos proveedores.
POSTGRES_PREFIXES = ("postgresql://", "postgres://")


def normalize_database_url(url: str) -> str:
    """Fija el driver de PostgreSQL. SQLite y cualquier otra URL no cambian."""
    if url.startswith(PSYCOPG_PREFIX):
        return url

    for prefix in POSTGRES_PREFIXES:
        if url.startswith(prefix):
            return PSYCOPG_PREFIX + url[len(prefix) :]

    return url


def connect_args_for(url: str) -> dict[str, object]:
    """`check_same_thread` es exclusivo de SQLite: PostgreSQL lo rechazaria."""
    return {"check_same_thread": False} if url.startswith("sqlite") else {}


def create_database_engine(url: str) -> Engine:
    """Engine perezoso: no abre ninguna conexion hasta la primera consulta.

    `pool_pre_ping` descarta conexiones muertas, lo que en un backend alojado
    evita el primer error tras un reinicio de la base de datos.
    """
    normalized = normalize_database_url(url)

    return create_engine(
        normalized,
        connect_args=connect_args_for(normalized),
        pool_pre_ping=True,
    )


class Base(DeclarativeBase):
    pass


engine = create_database_engine(settings.database_url)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    """Dependencia de FastAPI: una sesion por request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
