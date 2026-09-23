from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app import auth_service
from app.auth_dependencies import AuthenticatedWallet, require_auth
from app.database import get_db
from app.schemas import (
    AuthChallengeCreate,
    AuthChallengeResponse,
    AuthMeResponse,
    AuthSessionResponse,
    AuthVerifyCreate,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/challenge", response_model=AuthChallengeResponse)
def create_challenge(
    payload: AuthChallengeCreate, db: Session = Depends(get_db)
) -> AuthChallengeResponse:
    """Emite el mensaje que la wallet debe firmar con SEP-53."""
    challenge = auth_service.create_challenge(db, payload.wallet)

    return AuthChallengeResponse(
        challenge_id=challenge.id,
        message=auth_service.message_for(challenge),
        expires_at_unix=challenge.expires_at_unix,
    )


@router.post("/verify", response_model=AuthSessionResponse)
def verify_challenge(
    payload: AuthVerifyCreate, db: Session = Depends(get_db)
) -> AuthSessionResponse:
    """Canjea el challenge firmado por una sesion de 8 horas."""
    access_token, session = auth_service.verify_challenge(
        db, payload.challenge_id, payload.wallet_signature
    )

    return AuthSessionResponse(
        access_token=access_token,
        token_type="bearer",
        wallet=session.wallet,
        expires_at_unix=session.expires_at_unix,
    )


@router.get("/me", response_model=AuthMeResponse)
def read_me(auth: AuthenticatedWallet = Depends(require_auth)) -> AuthMeResponse:
    """Con que wallet esta abierta la sesion. Sirve para rehacerla tras un refresh."""
    return AuthMeResponse(wallet=auth.wallet, expires_at_unix=auth.expires_at_unix)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    auth: AuthenticatedWallet = Depends(require_auth),
    db: Session = Depends(get_db),
) -> Response:
    auth_service.revoke_session(db, auth.token_hash)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
