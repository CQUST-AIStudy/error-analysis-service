"""POST /ai/warning/analyze — Learning warning analysis endpoint."""

import logging

from fastapi import APIRouter, Depends

from app.core.responses import ApiError, api_success
from app.schemas.requests import WarningAnalysisResponse, WarningAnalyzeRequest
from app.services.deepseek_client import DeepSeekClient, get_deepseek_client
from app.services.warning_detector import analyze_warnings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["warning-analysis"])


@router.post("/warning/analyze", response_model=WarningAnalysisResponse)
def warning_analyze(
    request: WarningAnalyzeRequest,
    deepseek: DeepSeekClient = Depends(get_deepseek_client),
):
    """Analyze student learning warnings using AI.

    Receives class-level submission statistics, pre-filters students
    needing attention, and calls AI for in-depth warning analysis.
    Returns per-student warning levels, messages, and suggested actions.
    """
    try:
        result = analyze_warnings(request, deepseek)
        return api_success(result.model_dump(by_alias=True))
    except ApiError:
        raise
    except Exception as e:
        logger.error("Warning analysis failed: %s", e, exc_info=True)
        raise ApiError(500, f"Warning analysis failed: {e}") from e
