from collections.abc import Generator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.github_client import GitHubClient
from app.main import app
from app.verification_service import get_github_client

# Valores por defecto del PR falso. Los tests que necesiten desviarse mutan la
# instancia de FakeGitHub.
OWNER = "acme"
REPO = "demo"
PULL_NUMBER = 21
BASE_BRANCH = "main"
BASE_SHA = "b" * 40
HEAD_SHA = "h" * 40
DEVELOPER = "octodev"

REQUIRED_CHECK_NAMES = ("build", "regression-tests", "acceptance-tests")


def changed_file(
    filename: str,
    status: str = "modified",
    previous_filename: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "filename": filename,
        "status": status,
        "additions": 1,
        "deletions": 0,
        "changes": 1,
    }

    if previous_filename is not None:
        item["previous_filename"] = previous_filename

    return item


def check_run(
    name: str,
    status: str = "completed",
    conclusion: str | None = "success",
    head_sha: str = HEAD_SHA,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "head_sha": head_sha,
        "html_url": None,
    }


def passing_check_runs(head_sha: str = HEAD_SHA) -> list[dict[str, Any]]:
    return [check_run(name, head_sha=head_sha) for name in REQUIRED_CHECK_NAMES]


class FakeGitHub:
    """GitHub falso servido por httpx.MockTransport.

    Sustituye la red, no el GitHubClient: el codigo de cliente real (parseo de
    URL, mapeo de JSON, excepciones por codigo HTTP) sigue ejecutandose.
    """

    def __init__(self) -> None:
        self.state = "open"
        self.draft = False
        self.author: str | None = DEVELOPER
        self.base_ref = BASE_BRANCH
        self.base_sha = BASE_SHA
        self.head_ref = "feat/example"
        self.head_sha = HEAD_SHA

        self.files: list[dict[str, Any]] = [changed_file("app/main.py")]
        self.check_runs: list[dict[str, Any]] = passing_check_runs()

        # Para forzar respuestas de error sin tocar el resto del doble.
        self.pull_response: httpx.Response | None = None
        self.check_runs_response: httpx.Response | None = None

        self.requests: list[httpx.Request] = []

    def set_head_sha(self, head_sha: str) -> None:
        """Simula un push nuevo: cambia el commit y los checks que le cuelgan."""
        self.head_sha = head_sha
        self.check_runs = passing_check_runs(head_sha)

    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]

    def pull_request_payload(self) -> dict[str, Any]:
        return {
            "html_url": f"https://github.com/{OWNER}/{REPO}/pull/{PULL_NUMBER}",
            "state": self.state,
            "draft": self.draft,
            "user": None if self.author is None else {"login": self.author},
            "base": {"ref": self.base_ref, "sha": self.base_sha},
            "head": {
                "ref": self.head_ref,
                "sha": self.head_sha,
                "repo": {"full_name": f"{OWNER}/{REPO}"},
            },
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)

        path = request.url.path

        if path.endswith("/check-runs"):
            if self.check_runs_response is not None:
                return self.check_runs_response

            return httpx.Response(
                200,
                json={
                    "total_count": len(self.check_runs),
                    "check_runs": self.check_runs,
                },
            )

        if path.endswith("/files"):
            if request.url.params.get("page") == "2":
                return httpx.Response(200, json=[])

            return httpx.Response(200, json=self.files)

        if "/pulls/" in path:
            if self.pull_response is not None:
                return self.pull_response

            return httpx.Response(200, json=self.pull_request_payload())

        raise AssertionError(f"ruta inesperada: {path}")

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


@pytest.fixture
def github() -> FakeGitHub:
    return FakeGitHub()


@pytest.fixture
def engine() -> Generator[Engine, None, None]:
    """SQLite en memoria aislada por test.

    StaticPool mantiene una unica conexion para que la base sobreviva entre
    requests y sea visible tanto desde la app como desde el propio test.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(bind=engine)

    yield engine

    engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Sesiones para montar y leer estado directamente desde los tests."""
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


@pytest.fixture
def client(
    session_factory: sessionmaker[Session], github: FakeGitHub
) -> Generator[TestClient, None, None]:
    """Cliente con la base y GitHub sustituidos por dobles.

    El TestClient se instancia sin su context manager a proposito: asi no se
    ejecuta el lifespan y el engine real (mergepay.db) nunca se toca.
    """

    def override_get_db() -> Generator[Session, None, None]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    def override_get_github_client() -> Generator[GitHubClient, None, None]:
        github_client = GitHubClient(transport=github.transport)
        try:
            yield github_client
        finally:
            github_client.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_github_client] = override_get_github_client

    yield TestClient(app)

    app.dependency_overrides.clear()
