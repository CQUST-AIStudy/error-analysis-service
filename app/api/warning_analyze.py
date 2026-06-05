"""POST /analyze/warning — AI proactive intervention endpoint."""

import logging

from fastapi import APIRouter, Depends

from app.core.responses import ApiError, ApiResponse
from app.schemas.requests import WarningAnalyzeRequest, WarningResult
from app.services.deepseek_client import DeepSeekClient, get_deepseek_client
from app.services.warning_detector import analyze_warning

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analyze", tags=["warning-analysis"])


@router.post("/warning", response_model=ApiResponse[WarningResult])
def warning_analyze(
    request: WarningAnalyzeRequest,
    deepseek: DeepSeekClient = Depends(get_deepseek_client),
):
    """Detect whether a student needs teaching intervention.

    Receives per-student submission statistics, checks for warning
    conditions (triggered when error count > 5), and returns
    warning level, type, messages, and suggested actions.
    Called by Java backend when a student's error count exceeds threshold.
    """
    try:
        result = analyze_warning(request, deepseek)
        return ApiResponse(data=result)
    except ApiError:
        raise
    except Exception as e:
        logger.error("Warning analysis failed: %s", e, exc_info=True)
        raise ApiError(500, f"Warning analysis failed: {e}") from e
