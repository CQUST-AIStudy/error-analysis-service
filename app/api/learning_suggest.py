"""POST /analyze/learning — AI learning suggestion generation endpoint."""

import logging

from fastapi import APIRouter, Depends

from app.core.responses import ApiError, ApiResponse
from app.schemas.requests import LearningSuggestData, LearningSuggestRequest
from app.services.deepseek_client import DeepSeekClient, get_deepseek_client
from app.services.learning_advisor import generate_suggestions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analyze", tags=["learning-suggestions"])


@router.post("/learning", response_model=ApiResponse[LearningSuggestData])
def learning_suggest(
    request: LearningSuggestRequest,
    deepseek: DeepSeekClient = Depends(get_deepseek_client),
):
    """Generate personalized learning suggestions using AI.

    Receives a student's error history and skill states,
    identifies weak points, and generates a targeted study plan.
    Called by Java backend after error analysis is complete.
    """
    try:
        result = generate_suggestions(request, deepseek)
        return ApiResponse(data=result)
    except ApiError:
        raise
    except Exception as e:
        logger.error("Learning suggestion generation failed: %s", e, exc_info=True)
        raise ApiError(500, f"Learning suggestion generation failed: {e}") from e
