"""CORS: que origenes puede usar el navegador, y con que cabeceras.

CORS no autentica nada. Solo decide que paginas pueden llamar a la API desde
un navegador; la sesion sigue viajando en Authorization y las reglas de acceso
no cambian.
"""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, settings
from app.main import app

ALLOWED_ORIGIN = "http://localhost:5173"
OTHER_ALLOWED_ORIGIN = "http://127.0.0.1:5173"
UNKNOWN_ORIGIN = "https://mergepay.example.evil"

ALLOW_ORIGIN_HEADER = "access-control-allow-origin"


def preflight(client: TestClient, origin: str, method: str = "POST", headers: str = "authorization"):
    return client.options(
        "/bounties",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": headers,
        },
    )


# ─────────────────────────────────────────
# 9 a 14. Comportamiento del middleware.
# ─────────────────────────────────────────


@pytest.mark.parametrize("origin", [ALLOWED_ORIGIN, OTHER_ALLOWED_ORIGIN])
def test_allowed_origin_gets_the_cors_header(client: TestClient, origin: str) -> None:
    response = client.get("/health", headers={"Origin": origin})

    assert response.status_code == 200
    assert response.headers[ALLOW_ORIGIN_HEADER] == origin
    # Sin cookies: la sesion va en Authorization.
    assert "access-control-allow-credentials" not in response.headers


def test_preflight_allows_the_authorization_header(client: TestClient) -> None:
    response = preflight(client, ALLOWED_ORIGIN)

    assert response.status_code == 200

    allowed = response.headers["access-control-allow-headers"].lower()

    assert "authorization" in allowed


def test_preflight_allows_the_content_type_header(client: TestClient) -> None:
    response = preflight(client, ALLOWED_ORIGIN, headers="content-type")

    assert response.status_code == 200
    assert "content-type" in response.headers["access-control-allow-headers"].lower()


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_preflight_allows_the_methods_the_app_uses(
    client: TestClient, method: str
) -> None:
    response = preflight(client, ALLOWED_ORIGIN, method=method)

    assert response.status_code == 200

    allowed = response.headers["access-control-allow-methods"]

    assert method in allowed
    assert "OPTIONS" in allowed
    # Nada de comodines ni de verbos que la API no expone.
    assert "*" not in allowed
    assert "DELETE" not in allowed
    assert "PUT" not in allowed


def test_unknown_origin_gets_no_allow_origin_header(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": UNKNOWN_ORIGIN})

    # La respuesta existe, pero el navegador no dejara leerla.
    assert response.status_code == 200
    assert ALLOW_ORIGIN_HEADER not in response.headers


def test_unknown_origin_is_rejected_in_preflight(client: TestClient) -> None:
    response = preflight(client, UNKNOWN_ORIGIN)

    assert ALLOW_ORIGIN_HEADER not in response.headers


def test_cors_does_not_replace_authentication(client: TestClient) -> None:
    """Un origen permitido no da acceso: la sesion sigue siendo obligatoria."""
    response = client.post(
        "/bounties", json={}, headers={"Origin": ALLOWED_ORIGIN}
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}
    assert response.headers[ALLOW_ORIGIN_HEADER] == ALLOWED_ORIGIN


# ─────────────────────────────────────────
# 15 a 17. Lectura de la configuracion.
# ─────────────────────────────────────────


def origins_for(value: str) -> list[str]:
    return Settings(cors_allowed_origins=value).cors_origins


def test_default_origins_are_the_local_frontend() -> None:
    assert settings.cors_origins == [ALLOWED_ORIGIN, OTHER_ALLOWED_ORIGIN]


@pytest.mark.parametrize(
    "value", ["*", " * ", "http://localhost:5173,*", "*,http://localhost:5173"]
)
def test_wildcard_origin_is_rejected(value: str) -> None:
    with pytest.raises(ValueError) as error:
        origins_for(value)

    assert "explicit origins" in str(error.value)


def test_whitespace_and_empty_entries_are_cleaned_up() -> None:
    value = "  http://localhost:5173 , ,https://mergepay.vercel.app,,  "

    assert origins_for(value) == [
        "http://localhost:5173",
        "https://mergepay.vercel.app",
    ]


def test_duplicates_are_removed_keeping_the_order() -> None:
    value = (
        "https://b.example.com,https://a.example.com,"
        "https://b.example.com, https://a.example.com "
    )

    assert origins_for(value) == ["https://b.example.com", "https://a.example.com"]


def test_a_single_origin_needs_no_commas() -> None:
    assert origins_for("https://mergepay.vercel.app") == [
        "https://mergepay.vercel.app"
    ]


def test_the_app_exposes_the_configured_origins() -> None:
    """El middleware monta exactamente lo que dice la configuracion."""
    cors = [
        middleware
        for middleware in app.user_middleware
        if middleware.cls.__name__ == "CORSMiddleware"
    ]

    assert len(cors) == 1

    options = cors[0].kwargs

    assert options["allow_origins"] == settings.cors_origins
    assert options["allow_credentials"] is False
    assert options["allow_methods"] == ["GET", "POST", "OPTIONS"]
    assert options["allow_headers"] == ["Accept", "Authorization", "Content-Type"]


# ─────────────────────────────────────────
# /health: barato y sin dependencias.
# ─────────────────────────────────────────


def test_health_is_exact_and_needs_nothing(
    client: TestClient, github, stellar
) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}

    # Ni GitHub, ni Stellar, ni sesion.
    assert github.requests == []
    assert stellar.builds == 0
