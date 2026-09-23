import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker
from stellar_sdk import Keypair, StrKey

from app import auth_service
from app.auth_service import CHALLENGE_TTL_SECONDS, SESSION_TTL_SECONDS
from app.models import AuthChallenge, AuthSession
from tests.conftest import sep53_signature

WALLET_KEYPAIR = Keypair.random()
WALLET = WALLET_KEYPAIR.public_key

OTHER_KEYPAIR = Keypair.random()

VALID_SIGNATURE_LENGTH = 64


def request_challenge(client: TestClient, wallet: str = WALLET):
    return client.post("/auth/challenge", json={"wallet": wallet})


def verify(client: TestClient, challenge_id: str, wallet_signature: str):
    return client.post(
        "/auth/verify",
        json={"challenge_id": challenge_id, "wallet_signature": wallet_signature},
    )


def signed_verify(client: TestClient, keypair: Keypair = WALLET_KEYPAIR):
    """Pide un challenge y lo canjea firmando el mensaje tal cual llega."""
    issued = request_challenge(client, keypair.public_key).json()

    return verify(
        client, issued["challenge_id"], sep53_signature(keypair, issued["message"])
    )


def count(session_factory: sessionmaker[Session], model: type) -> int:
    with session_factory() as db:
        return db.scalar(select(func.count()).select_from(model)) or 0


# ─────────────────────────────────────────
# 1 a 6. Challenge.
# ─────────────────────────────────────────


def test_challenge_for_a_valid_wallet_returns_200(client: TestClient) -> None:
    response = request_challenge(client)

    assert response.status_code == 200

    body = response.json()

    assert set(body) == {"challenge_id", "message", "expires_at_unix"}
    assert len(body["challenge_id"]) >= 32


@pytest.mark.parametrize(
    "wallet",
    [
        "",
        "   ",
        "not-a-wallet",
        WALLET.lower(),
        WALLET[:-1],
        StrKey.encode_contract(b"\x11" * 32),
        Keypair.random().secret,
    ],
)
def test_challenge_for_an_invalid_wallet_returns_422(
    client: TestClient, session_factory: sessionmaker[Session], wallet: str
) -> None:
    assert request_challenge(client, wallet).status_code == 422
    assert count(session_factory, AuthChallenge) == 0


def test_challenge_message_has_the_exact_format(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    body = request_challenge(client).json()

    with session_factory() as db:
        challenge = db.get(AuthChallenge, body["challenge_id"])
        assert challenge is not None
        issued_at = challenge.issued_at_unix
        expires_at = challenge.expires_at_unix

    # Reescrito a mano: los tests comprueban el formato acordado, no que el
    # backend coincida consigo mismo.
    assert body["message"] == (
        "MergePay authentication v1\n"
        f"wallet={WALLET}\n"
        f"challenge={body['challenge_id']}\n"
        f"issued_at={issued_at}\n"
        f"expires_at={expires_at}\n"
        "network=TESTNET"
    )


def test_challenge_message_has_no_trailing_newline(client: TestClient) -> None:
    message = request_challenge(client).json()["message"]

    assert not message.endswith("\n")
    assert len(message.splitlines()) == 6


def test_challenge_expires_five_minutes_after_it_was_issued(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    body = request_challenge(client).json()

    with session_factory() as db:
        challenge = db.get(AuthChallenge, body["challenge_id"])
        assert challenge is not None

        assert challenge.expires_at_unix - challenge.issued_at_unix == 300
        assert CHALLENGE_TTL_SECONDS == 300
        assert challenge.used_at_unix is None
        assert challenge.wallet == WALLET

    assert body["expires_at_unix"] == challenge.expires_at_unix


def test_every_challenge_is_different(client: TestClient) -> None:
    ids = {request_challenge(client).json()["challenge_id"] for _ in range(5)}

    assert len(ids) == 5


# ─────────────────────────────────────────
# 7 a 13. Canje rechazado.
# ─────────────────────────────────────────


def test_unknown_challenge_returns_401(client: TestClient) -> None:
    issued = request_challenge(client).json()
    signature = sep53_signature(WALLET_KEYPAIR, issued["message"])

    response = verify(client, "does-not-exist", signature)

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Authentication challenge is invalid or expired"
    }


def test_expired_challenge_returns_401(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    issued = request_challenge(client).json()
    signature = sep53_signature(WALLET_KEYPAIR, issued["message"])

    with session_factory() as db:
        db.execute(
            update(AuthChallenge)
            .where(AuthChallenge.id == issued["challenge_id"])
            .values(expires_at_unix=auth_service.now_unix() - 1)
        )
        db.commit()

    response = verify(client, issued["challenge_id"], signature)

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Authentication challenge is invalid or expired"
    }
    assert count(session_factory, AuthSession) == 0


def test_used_challenge_returns_401(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    issued = request_challenge(client).json()
    signature = sep53_signature(WALLET_KEYPAIR, issued["message"])

    assert verify(client, issued["challenge_id"], signature).status_code == 200

    response = verify(client, issued["challenge_id"], signature)

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Authentication challenge is invalid or expired"
    }


def test_missing_signature_returns_422(client: TestClient) -> None:
    issued = request_challenge(client).json()

    response = client.post(
        "/auth/verify", json={"challenge_id": issued["challenge_id"]}
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "signature",
    ["", "   ", "not base64!!", "QUJD", "****", "YWJj YWJj", "0" * 88],
)
def test_invalid_base64_signature_returns_422(
    client: TestClient, signature: str
) -> None:
    issued = request_challenge(client).json()

    assert verify(client, issued["challenge_id"], signature).status_code == 422


@pytest.mark.parametrize("length", [32, 63, 65, 128])
def test_signature_of_the_wrong_length_returns_422(
    client: TestClient, length: int
) -> None:
    import base64

    issued = request_challenge(client).json()
    signature = base64.b64encode(b"\x01" * length).decode("ascii")

    assert verify(client, issued["challenge_id"], signature).status_code == 422


def test_signature_from_another_wallet_returns_401(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    issued = request_challenge(client).json()

    # Firma bien formada del mensaje correcto, pero de otra wallet.
    signature = sep53_signature(OTHER_KEYPAIR, issued["message"])

    response = verify(client, issued["challenge_id"], signature)

    assert response.status_code == 401
    assert response.json() == {"detail": "Wallet signature is invalid"}
    assert count(session_factory, AuthSession) == 0

    # Una firma invalida no gasta el challenge.
    with session_factory() as db:
        challenge = db.get(AuthChallenge, issued["challenge_id"])
        assert challenge is not None
        assert challenge.used_at_unix is None


def test_signature_of_another_message_returns_401(client: TestClient) -> None:
    issued = request_challenge(client).json()
    tampered = issued["message"].replace("network=TESTNET", "network=PUBLIC")

    response = verify(
        client, issued["challenge_id"], sep53_signature(WALLET_KEYPAIR, tampered)
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Wallet signature is invalid"}


# ─────────────────────────────────────────
# 14 a 22. Sesion creada y challenge consumido.
# ─────────────────────────────────────────


def test_valid_signature_creates_a_session(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    response = signed_verify(client)

    assert response.status_code == 200

    body = response.json()

    assert set(body) == {"access_token", "token_type", "wallet", "expires_at_unix"}
    assert body["wallet"] == WALLET
    assert body["token_type"] == "bearer"
    assert len(body["access_token"]) >= 32
    assert count(session_factory, AuthSession) == 1


def test_session_lasts_eight_hours(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    body = signed_verify(client).json()

    with session_factory() as db:
        session = db.scalars(select(AuthSession)).one()

        assert session.expires_at_unix - session.created_at_unix == 28_800
        assert SESSION_TTL_SECONDS == 28_800
        assert session.wallet == WALLET
        assert session.revoked_at_unix is None

    assert body["expires_at_unix"] == session.expires_at_unix


def test_database_never_stores_the_raw_token(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    access_token = signed_verify(client).json()["access_token"]

    with session_factory() as db:
        session = db.scalars(select(AuthSession)).one()

        assert session.token_hash != access_token
        assert access_token not in session.token_hash

        # Ninguna columna de la fila guarda el token en crudo.
        stored = [
            str(getattr(session, column.key))
            for column in AuthSession.__table__.columns
        ]

        assert all(access_token not in value for value in stored)


def test_database_stores_the_sha256_of_the_token(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    access_token = signed_verify(client).json()["access_token"]

    expected = hashlib.sha256(access_token.encode("utf-8")).hexdigest()

    with session_factory() as db:
        session = db.scalars(select(AuthSession)).one()

        assert session.token_hash == expected
        assert len(session.token_hash) == 64


def test_verified_challenge_is_consumed(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    issued = request_challenge(client).json()
    signature = sep53_signature(WALLET_KEYPAIR, issued["message"])

    assert verify(client, issued["challenge_id"], signature).status_code == 200

    with session_factory() as db:
        challenge = db.get(AuthChallenge, issued["challenge_id"])
        assert challenge is not None
        assert challenge.used_at_unix is not None


def test_same_challenge_never_creates_a_second_session(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    issued = request_challenge(client).json()
    signature = sep53_signature(WALLET_KEYPAIR, issued["message"])

    assert verify(client, issued["challenge_id"], signature).status_code == 200

    for _ in range(3):
        assert verify(client, issued["challenge_id"], signature).status_code == 401

    assert count(session_factory, AuthSession) == 1


def test_challenge_consumed_by_a_racing_request_is_rejected(
    client: TestClient,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La carrera se corta en el UPDATE condicionado, no en la lectura previa.

    Se simula que otro request consume el challenge justo despues de que este
    haya comprobado la firma: la comprobacion inicial ya paso, asi que lo unico
    que puede rechazarlo es el rowcount del UPDATE.
    """
    issued = request_challenge(client).json()
    signature = sep53_signature(WALLET_KEYPAIR, issued["message"])

    original = auth_service.signature_is_valid

    def racing_signature_is_valid(*args: object, **kwargs: object) -> bool:
        valid = original(*args, **kwargs)

        with session_factory() as other:
            other.execute(
                update(AuthChallenge)
                .where(
                    AuthChallenge.id == issued["challenge_id"],
                    AuthChallenge.used_at_unix.is_(None),
                )
                .values(used_at_unix=auth_service.now_unix())
            )
            other.commit()

        return valid

    monkeypatch.setattr(
        auth_service, "signature_is_valid", racing_signature_is_valid
    )

    response = verify(client, issued["challenge_id"], signature)

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Authentication challenge is invalid or expired"
    }
    assert count(session_factory, AuthSession) == 0


# ─────────────────────────────────────────
# 23 a 30. Uso de la sesion.
# ─────────────────────────────────────────


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_me_without_authorization_returns_401(client: TestClient) -> None:
    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


@pytest.mark.parametrize(
    "header",
    ["", "Bearer", "Bearer ", "Basic abc", "token abc", "abc"],
)
def test_malformed_authorization_header_returns_401(
    client: TestClient, header: str
) -> None:
    response = client.get("/auth/me", headers={"Authorization": header})

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_unknown_token_returns_401(client: TestClient) -> None:
    response = client.get("/auth/me", headers=bearer("not-a-real-token"))

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Authentication session is invalid or expired"
    }


def test_expired_token_returns_401(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    access_token = signed_verify(client).json()["access_token"]

    with session_factory() as db:
        db.execute(
            update(AuthSession).values(expires_at_unix=auth_service.now_unix() - 1)
        )
        db.commit()

    response = client.get("/auth/me", headers=bearer(access_token))

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Authentication session is invalid or expired"
    }


def test_revoked_token_returns_401(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    access_token = signed_verify(client).json()["access_token"]

    with session_factory() as db:
        db.execute(
            update(AuthSession).values(revoked_at_unix=auth_service.now_unix())
        )
        db.commit()

    response = client.get("/auth/me", headers=bearer(access_token))

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Authentication session is invalid or expired"
    }


def test_valid_token_reads_the_session(client: TestClient) -> None:
    body = signed_verify(client).json()

    response = client.get("/auth/me", headers=bearer(body["access_token"]))

    assert response.status_code == 200
    assert response.json() == {
        "wallet": WALLET,
        "expires_at_unix": body["expires_at_unix"],
    }


def test_logout_returns_204(client: TestClient) -> None:
    access_token = signed_verify(client).json()["access_token"]

    response = client.post("/auth/logout", headers=bearer(access_token))

    assert response.status_code == 204
    assert response.content == b""


def test_token_stops_working_after_logout(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    access_token = signed_verify(client).json()["access_token"]

    assert client.post("/auth/logout", headers=bearer(access_token)).status_code == 204

    response = client.get("/auth/me", headers=bearer(access_token))

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Authentication session is invalid or expired"
    }

    # La fila se conserva, marcada como revocada.
    with session_factory() as db:
        session = db.scalars(select(AuthSession)).one()
        assert session.revoked_at_unix is not None

    assert client.post("/auth/logout", headers=bearer(access_token)).status_code == 401


def test_two_wallets_hold_independent_sessions(client: TestClient) -> None:
    first = signed_verify(client).json()
    second = signed_verify(client, OTHER_KEYPAIR).json()

    assert first["access_token"] != second["access_token"]

    assert client.post(
        "/auth/logout", headers=bearer(first["access_token"])
    ).status_code == 204

    # Cerrar una sesion no toca la otra.
    still_open = client.get("/auth/me", headers=bearer(second["access_token"]))

    assert still_open.status_code == 200
    assert still_open.json()["wallet"] == OTHER_KEYPAIR.public_key
