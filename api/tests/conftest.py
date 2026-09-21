from collections.abc import Generator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from stellar_sdk.exceptions import ConnectionError as RpcConnectionError

from app import assignment_service, funding_service, verification_service
from app.database import Base, get_db
from app.github_client import GitHubClient
from app.main import app
from app.stellar_client import (
    OnChainBounty,
    StellarConfigurationError,
    StellarTransactionError,
)
from app.verification_service import get_github_client

TRANSACTION_HASH = "7c" * 32

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

BRANCH_HEAD_SHA = "d" * 40


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

        # HEAD de la rama base, que es lo que resuelve el funding.
        self.branch_head_sha = BRANCH_HEAD_SHA

        # Para forzar respuestas de error sin tocar el resto del doble.
        self.pull_response: httpx.Response | None = None
        self.check_runs_response: httpx.Response | None = None
        self.branch_response: httpx.Response | None = None

        # Fallo de red: cualquier peticion lanza esto en vez de responder.
        self.transport_error: httpx.RequestError | None = None

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

        if self.transport_error is not None:
            raise self.transport_error

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

        # /repos/{owner}/{repo}/commits/{branch}. Las check-runs tambien
        # cuelgan de /commits/, pero ya se atendieron arriba.
        if "/commits/" in path:
            if self.branch_response is not None:
                return self.branch_response

            return httpx.Response(
                200,
                json={
                    "sha": self.branch_head_sha,
                    "commit": {"message": "campo que no debe aparecer"},
                },
            )

        raise AssertionError(f"ruta inesperada: {path}")

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


class FakeStellar:
    """Sustituye `get_stellar_client` y el cliente que devuelve.

    Hace de las dos cosas a la vez: `get_client` ocupa el lugar del helper del
    servicio y devuelve este mismo objeto como cliente, asi que un unico fake
    permite contar construcciones y llamadas por separado.
    """

    def __init__(self) -> None:
        self.builds = 0
        self.calls: list[tuple[int, str]] = []

        self.transaction_hash = TRANSACTION_HASH

        self.configuration_error: StellarConfigurationError | None = None
        self.transaction_error: StellarTransactionError | None = None

        # Lecturas del funding: que transacciones y bounties se consultaron, y
        # que devolver o lanzar en cada caso.
        self.checked_transactions: list[str] = []
        self.read_bounties: list[int] = []

        self.on_chain: OnChainBounty | None = None
        self.transaction_status_error: StellarTransactionError | None = None
        self.read_error: StellarTransactionError | None = None

    def get_client(self) -> "FakeStellar":
        self.builds += 1

        if self.configuration_error is not None:
            raise self.configuration_error

        return self

    def release_bounty(self, bounty_id: int, evidence_hash: str) -> str:
        self.calls.append((bounty_id, evidence_hash))

        if self.transaction_error is not None:
            raise self.transaction_error

        return self.transaction_hash

    def assert_transaction_success(self, transaction_hash: str) -> None:
        self.checked_transactions.append(transaction_hash)

        if self.transaction_status_error is not None:
            raise self.transaction_status_error

    def get_bounty(self, bounty_id: int) -> OnChainBounty:
        self.read_bounties.append(bounty_id)

        if self.read_error is not None:
            raise self.read_error

        if self.on_chain is None:
            raise StellarTransactionError("get_bounty simulation failed")

        return self.on_chain


# URL de RPC con aspecto de proveedor de pago: nunca debe aparecer en errores.
SENSITIVE_RPC_URL = "https://rpc.example.invalid/?apiKey=PAID-PROVIDER-KEY"


class DownSorobanServer:
    """RPC inalcanzable: toda llamada falla como lo haria el SDK real.

    Sustituye a SorobanServer por debajo de un StellarClient real, para probar
    la conversion de transporte de punta a punta.
    """

    def __init__(self, server_url: str) -> None:
        self.server_url = server_url

    def _down(self, *args: Any, **kwargs: Any) -> Any:
        raise RpcConnectionError(
            f"HTTPSConnectionPool: Max retries exceeded with url: {SENSITIVE_RPC_URL}"
        )

    load_account = _down
    simulate_transaction = _down
    get_transaction = _down
    prepare_transaction = _down
    send_transaction = _down
    poll_transaction = _down


@pytest.fixture
def github() -> FakeGitHub:
    return FakeGitHub()


@pytest.fixture
def stellar(monkeypatch: pytest.MonkeyPatch) -> FakeStellar:
    """Instalado en todos los tests: nadie puede alcanzar Stellar de verdad."""
    fake = FakeStellar()

    monkeypatch.setattr(verification_service, "get_stellar_client", fake.get_client)
    monkeypatch.setattr(funding_service, "get_stellar_client", fake.get_client)
    monkeypatch.setattr(assignment_service, "get_stellar_client", fake.get_client)

    return fake


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
    session_factory: sessionmaker[Session],
    github: FakeGitHub,
    stellar: FakeStellar,
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
