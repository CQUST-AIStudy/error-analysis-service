"""POST /analyze/warning — AI proactive intervention endpoint.

PDF 3号成员要求：错误次数 > 5 时自动串联三个功能：
  1. 预警检测
  2. 错误代码分析 (/analyze/error)
  3. 学习建议生成 (/analyze/learning)

当后端传入 submissions 数据时，返回 WarningCombinedData；
否则只返回 WarningResult。
"""

import logging

from fastapi import APIRouter, Depends

from app.core.responses import ApiError, ApiResponse
from app.schemas.requests import WarningAnalyzeRequest
from app.services.deepseek_client import DeepSeekClient, get_deepseek_client
from app.services.warning_detector import analyze_warning

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analyze", tags=["warning-analysis"])


@router.post("/warning")
def warning_analyze(
    request: WarningAnalyzeRequest,
    deepseek: DeepSeekClient = Depends(get_deepseek_client),
):
    """Detect whether a student needs teaching intervention.

    Receives per-student submission statistics. When error count > 5
    AND submissions data is provided, internally chains to /analyze/error
    and /analyze/learning, returning a combined result.

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
