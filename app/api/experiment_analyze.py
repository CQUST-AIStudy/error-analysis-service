"""POST /ai/experiment/analyze — Experiment completion analysis endpoint."""

import logging

from fastapi import APIRouter, Depends

from app.core.responses import ApiError, api_success
from app.schemas.requests import ExperimentAnalysisResponse, ExperimentAnalyzeRequest
from app.services.deepseek_client import DeepSeekClient, get_deepseek_client
from app.services.experiment_analyzer import analyze_experiment

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["experiment-analysis"])


@router.post("/experiment/analyze", response_model=ExperimentAnalysisResponse)
def experiment_analyze(
    request: ExperimentAnalyzeRequest,
    deepseek: DeepSeekClient = Depends(get_deepseek_client),
):
    """Analyze experiment completion data with AI.

    Receives class-level completion statistics and error distributions,
    calls AI for teaching-quality analysis with actionable suggestions.
    """
    try:
        result = analyze_experiment(request, deepseek)
        return api_success(result.model_dump(by_alias=True))
    except ApiError:
        raise
    except Exception as e:
        logger.error("Experiment analysis failed: %s", e, exc_info=True)
        raise ApiError(500, f"Experiment analysis failed: {e}") from e
