from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """Cliente contra una SQLite en memoria, aislada por test.

    El engine real de la app nunca se usa: `get_db` queda sobreescrito y el
    TestClient se instancia sin su context manager, de modo que el lifespan
    (y por tanto el create_all sobre mergepay.db) no llega a ejecutarse.
    StaticPool mantiene una unica conexion para que la base en memoria
    sobreviva entre requests.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(bind=engine)

    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_get_db() -> Generator[Session, None, None]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    yield TestClient(app)

    app.dependency_overrides.clear()
    engine.dispose()
