"""Autenticacion por wallet: challenge, firma SEP-53 y sesion.

La identidad es una address Stellar G..., y la prueba de control es una firma
SEP-53 de un mensaje que MergePay genera. No hay contrasenas, ni usuarios, ni
roles globales: lo que una wallet puede hacer depende de su relacion con cada
bounty.

Del token de sesion solo se guarda su sha256. El valor en crudo se devuelve una
vez y no se registra ni se persiste en ningun sitio.
"""

import base64
import hashlib
import secrets
import time

from fastapi import HTTPException, status
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from stellar_sdk import Keypair
from stellar_sdk.exceptions import BadSignatureError

from app.models import AuthChallenge, AuthSession

CHALLENGE_TTL_SECONDS = 300
SESSION_TTL_SECONDS = 28_800

AUTH_MESSAGE_HEADER = "MergePay authentication v1"

# Prefijo de SEP-53: lo que Freighter antepone al mensaje antes de firmar.
SEP53_PREFIX = b"Stellar Signed Message:\n"

# El MVP solo funciona en Testnet.
NETWORK = "TESTNET"

INVALID_CHALLENGE_DETAIL = "Authentication challenge is invalid or expired"
INVALID_SIGNATURE_DETAIL = "Wallet signature is invalid"


def now_unix() -> int:
    return int(time.time())


def build_authentication_message(
    *,
    wallet: str,
    challenge_id: str,
    issued_at_unix: int,
    expires_at_unix: int,
) -> str:
    """Mensaje que firma la wallet: una linea por campo, sin salto final.

    El frontend no lo reconstruye: firma exactamente el que devuelve el
    backend, y aqui se vuelve a construir desde la fila para verificarlo.
    """
    return "\n".join(
        [
            AUTH_MESSAGE_HEADER,
            f"wallet={wallet}",
            f"challenge={challenge_id}",
            f"issued_at={issued_at_unix}",
            f"expires_at={expires_at_unix}",
            f"network={NETWORK}",
        ]
    )


def message_for(challenge: AuthChallenge) -> str:
    return build_authentication_message(
        wallet=challenge.wallet,
        challenge_id=challenge.id,
        issued_at_unix=challenge.issued_at_unix,
        expires_at_unix=challenge.expires_at_unix,
    )


def _sep53_digest(message: str) -> bytes:
    return hashlib.sha256(SEP53_PREFIX + message.encode("utf-8")).digest()


def signature_is_valid(public_key: str, message: str, wallet_signature: str) -> bool:
    """Verifica una firma SEP-53 de `message` hecha por `public_key`."""
    try:
        signature = base64.b64decode(wallet_signature, validate=True)
    except ValueError:
        # El schema ya lo valido; esto solo cubre llamadas directas.
        return False

    try:
        Keypair.from_public_key(public_key).verify(_sep53_digest(message), signature)
    except BadSignatureError:
        return False

    return True


def hash_token(access_token: str) -> str:
    return hashlib.sha256(access_token.encode("utf-8")).hexdigest()


def _commit(db: Session) -> None:
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise


def create_challenge(db: Session, wallet: str) -> AuthChallenge:
    """Emite un challenge para esa wallet. El id es el nonce."""
    issued_at = now_unix()

    challenge = AuthChallenge(
        id=secrets.token_urlsafe(32),
        wallet=wallet,
        issued_at_unix=issued_at,
        expires_at_unix=issued_at + CHALLENGE_TTL_SECONDS,
        used_at_unix=None,
    )

    db.add(challenge)
    _commit(db)

    return challenge


def _invalid_challenge() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_CHALLENGE_DETAIL
    )


def _consume_challenge(db: Session, challenge_id: str, now: int) -> None:
    """Marca el challenge como usado, solo si nadie lo uso antes.

    El UPDATE condicionado es lo que hace el canje realmente de un solo uso:
    dos peticiones simultaneas con la misma firma compiten por la misma fila y
    solo una ve rowcount == 1.
    """
    consumed = db.execute(
        update(AuthChallenge)
        .where(
            AuthChallenge.id == challenge_id,
            AuthChallenge.used_at_unix.is_(None),
            AuthChallenge.expires_at_unix >= now,
        )
        .values(used_at_unix=now)
        .execution_options(synchronize_session=False)
    ).rowcount

    if consumed != 1:
        db.rollback()
        raise _invalid_challenge()


def verify_challenge(
    db: Session, challenge_id: str, wallet_signature: str
) -> tuple[str, AuthSession]:
    """Canjea un challenge firmado por una sesion.

    Devuelve el token en crudo y la sesion. El token no se guarda: en la base
    solo queda su sha256.
    """
    challenge = db.get(AuthChallenge, challenge_id)
    now = now_unix()

    if (
        challenge is None
        or challenge.used_at_unix is not None
        or now > challenge.expires_at_unix
    ):
        raise _invalid_challenge()

    if not signature_is_valid(
        challenge.wallet, message_for(challenge), wallet_signature
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_SIGNATURE_DETAIL
        )

    _consume_challenge(db, challenge_id, now)

    access_token = secrets.token_urlsafe(32)

    session = AuthSession(
        token_hash=hash_token(access_token),
        wallet=challenge.wallet,
        created_at_unix=now,
        expires_at_unix=now + SESSION_TTL_SECONDS,
        revoked_at_unix=None,
    )

    db.add(session)
    _commit(db)

    return access_token, session


def resolve_session(db: Session, access_token: str) -> AuthSession | None:
    """La sesion viva de ese token, o None si no sirve."""
    session = db.get(AuthSession, hash_token(access_token))

    if session is None or session.revoked_at_unix is not None:
        return None

    if now_unix() > session.expires_at_unix:
        return None

    return session


def revoke_session(db: Session, token_hash: str) -> None:
    """Cierra la sesion. Un token revocado ya no vuelve a valer."""
    db.execute(
        update(AuthSession)
        .where(
            AuthSession.token_hash == token_hash,
            AuthSession.revoked_at_unix.is_(None),
        )
        .values(revoked_at_unix=now_unix())
        .execution_options(synchronize_session=False)
    )

    _commit(db)
