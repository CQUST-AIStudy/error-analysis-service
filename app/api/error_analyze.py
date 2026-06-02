"""POST /ai/error/analyze — AI error analysis endpoint."""

import logging

from fastapi import APIRouter, Depends

from app.core.responses import ApiError, api_success
from app.schemas.requests import ErrorAnalysisRequest, ErrorAnalysisResponse
from app.services.deepseek_client import DeepSeekClient, get_deepseek_client
from app.services.error_analyzer import analyze_errors

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["error-analysis"])


@router.post("/error/analyze", response_model=ErrorAnalysisResponse)
def error_analyze(
    request: ErrorAnalysisRequest,
    deepseek: DeepSeekClient = Depends(get_deepseek_client),
):
    """Analyze student code errors using AI.

    Receives a student's submission history (code + PTA judge results),
    calls DeepSeek for deep code-level error diagnosis, and returns
    categorized errors, root causes, and learning suggestions.
    """
    try:
        result = analyze_errors(request, deepseek)
        return api_success(result.model_dump(by_alias=True))
    except ApiError:
        raise
    except Exception as e:
        logger.error("Error analysis failed: %s", e, exc_info=True)
        raise ApiError(500, f"Error analysis failed: {e}") from e
