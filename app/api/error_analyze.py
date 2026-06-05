"""POST /analyze/error — AI error analysis endpoint."""

import logging

from fastapi import APIRouter, Depends

from app.core.responses import ApiError, ApiResponse
from app.schemas.requests import ErrorAnalysisData, ErrorAnalysisRequest
from app.services.deepseek_client import DeepSeekClient, get_deepseek_client
from app.services.error_analyzer import analyze_errors

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analyze", tags=["error-analysis"])


@router.post("/error", response_model=ApiResponse[ErrorAnalysisData])
def error_analyze(
    request: ErrorAnalysisRequest,
    deepseek: DeepSeekClient = Depends(get_deepseek_client),
):
    """Analyze student code errors using AI.

    Receives a student's submission history (code + PTA judge results),
    calls DeepSeek for deep code-level error diagnosis, and returns
    categorized errors, root causes, and learning suggestions.
    Called by Java backend when a student submits code with errors.
    """
    try:
        result = analyze_errors(request, deepseek)
        return ApiResponse(data=result)
    except ApiError:
        raise
    except Exception as e:
        logger.error("Error analysis failed: %s", e, exc_info=True)
        raise ApiError(500, f"Error analysis failed: {e}") from e
