from fastapi import APIRouter, Depends, HTTPException, status

from app.auth_dependencies import AuthenticatedWallet, require_auth
from app.criteria_service import (
    CriteriaGenerationError,
    generate_criteria,
)
from app.gemini_client import (
    GeminiConfigurationError,
    GeminiGenerationError,
)
from app.schemas import (
    GenerateCriteriaRequest,
    GenerateCriteriaResponse,
)

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post(
    "/generate-criteria",
    response_model=GenerateCriteriaResponse,
)
def generate_criteria_endpoint(
    payload: GenerateCriteriaRequest,
    _: AuthenticatedWallet = Depends(require_auth),
) -> GenerateCriteriaResponse:
    try:
        criteria = generate_criteria(
            title=payload.title,
            description=payload.description,
        )
    except GeminiConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gemini service is not configured",
        ) from error
    except (GeminiGenerationError, CriteriaGenerationError) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Gemini could not generate acceptance criteria",
        ) from error

    return GenerateCriteriaResponse(criteria=criteria)