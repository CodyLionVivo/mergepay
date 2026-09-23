"""Sesion autenticada y autorizacion por recurso.

No hay roles globales: la misma wallet puede ser client en un bounty y
developer en otro, asi que el permiso se decide comparando la wallet de la
sesion con las wallets de ese bounty concreto.
"""

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app import auth_service
from app.database import get_db
from app.models import Bounty, BountyStatus

BEARER_SCHEME = "bearer"

AUTH_REQUIRED_DETAIL = "Authentication required"
INVALID_SESSION_DETAIL = "Authentication session is invalid or expired"

CLIENT_REQUIRED_DETAIL = "Client wallet required for this task"
DEVELOPER_REQUIRED_DETAIL = "Developer wallet required for this task"
PARTICIPANT_REQUIRED_DETAIL = "Task participant wallet required"


@dataclass(frozen=True)
class AuthenticatedWallet:
    """Lo unico que el codigo de negocio necesita saber de la sesion.

    El token en crudo se queda en la cabecera: aqui solo viaja su hash, que es
    lo que hace falta para revocarla.
    """

    wallet: str
    expires_at_unix: int
    token_hash: str


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def _read_bearer_token(authorization: str | None) -> str:
    if authorization is None:
        raise _unauthorized(AUTH_REQUIRED_DETAIL)

    scheme, _, token = authorization.partition(" ")

    if scheme.lower() != BEARER_SCHEME or not token.strip():
        raise _unauthorized(AUTH_REQUIRED_DETAIL)

    return token.strip()


def require_auth(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthenticatedWallet:
    """Dependencia de FastAPI: exige una sesion viva."""
    token = _read_bearer_token(authorization)

    session = auth_service.resolve_session(db, token)

    if session is None:
        raise _unauthorized(INVALID_SESSION_DETAIL)

    return AuthenticatedWallet(
        wallet=session.wallet,
        expires_at_unix=session.expires_at_unix,
        token_hash=session.token_hash,
    )


def optional_auth(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthenticatedWallet | None:
    """La sesion si la hay, y None si no. Nunca lanza.

    Una cabecera ausente, mal formada o con una sesion caducada o revocada
    valen lo mismo: no identifican a nadie y por tanto no dan acceso. Quien
    decide que se puede ver es `can_read_bounty`.
    """
    if authorization is None:
        return None

    try:
        token = _read_bearer_token(authorization)
    except HTTPException:
        return None

    session = auth_service.resolve_session(db, token)

    if session is None:
        return None

    return AuthenticatedWallet(
        wallet=session.wallet,
        expires_at_unix=session.expires_at_unix,
        token_hash=session.token_hash,
    )


def can_read_bounty(bounty: Bounty, auth: AuthenticatedWallet | None) -> bool:
    """Unica regla de visibilidad de una task en MergePay.

    Una task financiada y sin developer es publica: es la oferta del
    marketplace. En cuanto se acepta, y mientras es un borrador, solo la ven
    quienes participan en ella. Lo que haya en Stellar sigue siendo publico
    fuera de MergePay.
    """
    if bounty.status == BountyStatus.OPEN_FUNDED:
        return True

    if auth is None:
        return False

    if bounty.status == BountyStatus.DRAFT:
        return auth.wallet == bounty.client_wallet

    return auth.wallet == bounty.client_wallet or (
        bounty.developer_wallet is not None and auth.wallet == bounty.developer_wallet
    )


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def require_client(bounty: Bounty, wallet: str) -> None:
    if bounty.client_wallet is None or bounty.client_wallet != wallet:
        raise _forbidden(CLIENT_REQUIRED_DETAIL)


def require_developer(bounty: Bounty, wallet: str) -> None:
    if bounty.developer_wallet is None or bounty.developer_wallet != wallet:
        raise _forbidden(DEVELOPER_REQUIRED_DETAIL)


def require_participant(bounty: Bounty, wallet: str) -> None:
    """Client o developer de ese bounty. Ambos pueden pedir verificacion."""
    if wallet not in (bounty.client_wallet, bounty.developer_wallet):
        raise _forbidden(PARTICIPANT_REQUIRED_DETAIL)
