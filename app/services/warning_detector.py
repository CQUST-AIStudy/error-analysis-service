"""Learning warning detection — simplified, self-contained.

Rule: failed submissions require warning analysis; all-accepted submissions stay OK.
AI path: DeepSeek evaluates severity when API key available.
Rule path: simple threshold fallback.
"""

import logging

from app.schemas.requests import (
    ErrorAnalysisRequest,
    ErrorTypeCount,
    LearningSuggestRequest,
    SubmissionRecord,
    WarningAnalyzeRequest,
    WarningCombinedData,
    WarningResult,
)
from app.services.deepseek_client import DeepSeekClient

logger = logging.getLogger(__name__)

# ── AI prompt ────────────────────────────────────────────

WARNING_SYSTEM_PROMPT = """你是重庆科技大学的学习预警分析师。基于学生的提交统计数据，判断预警等级。

预警等级：
- HIGH: 提交次数多(>=10) 且通过率低(<30%)，需立即干预
- MEDIUM: 编译错误占比高或有一定卡住趋势
- LOW: 有少量错误，暂时观察
- OK: 表现正常

输出严格JSON：
{
  "level": "HIGH",
  "triggered": true,
  "warningType": "FREQUENT_FAILURE",
  "warningMessage": "面向学生的温和提示语（≤100字）",
  "teacherNote": "给教师的备注",
  "suggestedActions": ["建议1"],
  "autoNotify": true
}
warningType: FREQUENT_FAILURE | BASIC_SYNTAX | STUCK | OK"""


def _build_warning_prompt(request: WarningAnalyzeRequest) -> str:
    total = max(request.total_submissions, 1)
    ac = request.accepted_count
    ac_rate = (ac / total * 100) if total > 0 else 0
    return f"""学生: {request.student_id} {request.student_name}
实验: {request.experiment_name} (ID: {request.experiment_id})
总提交: {total}次  通过: {ac}次  通过率: {ac_rate:.0f}%
编译错误: {request.compile_errors}次  运行错误: {request.runtime_errors}次
答案错误: {request.wrong_answers}次  超时: {request.time_limit_exceeded}次
请判断预警等级（严格JSON）。"""


# ── Rule engine (no AI needed) ───────────────────────────

def _needs_ai_analysis(request: WarningAnalyzeRequest) -> bool:
    """Return whether the submission statistics include warning-worthy failures."""
    total = max(request.total_submissions, 0)
    if total == 0:
        return False
    if request.accepted_count >= total:
        return False
    failure_count = (
        request.compile_errors
        + request.runtime_errors
        + request.wrong_answers
        + request.time_limit_exceeded
    )
    return failure_count > 0


def _rule_based_warning(request: WarningAnalyzeRequest) -> WarningResult:
    """Classify warning severity using local submission statistics."""
    total = max(request.total_submissions, 1)

    if not _needs_ai_analysis(request):
        return WarningResult(
            studentId=request.student_id,
            level="OK", triggered=False, warningType="OK",
            warningMessage="当前表现正常，请继续保持。",
            teacherNote=None, suggestedActions=[], autoNotify=False,
            aiGenerated=False,
        )

    # Determine severity
    ac = request.accepted_count
    ac_rate = (ac / total * 100) if total > 0 else 0
    if total >= 10 and ac_rate < 30:
        level, wtype = "HIGH", "FREQUENT_FAILURE"
    elif request.compile_errors > 0 and request.compile_errors >= max(
        request.runtime_errors,
        request.wrong_answers,
        request.time_limit_exceeded,
    ):
        level, wtype = "MEDIUM", "BASIC_SYNTAX"
    elif request.runtime_errors > 0 or request.wrong_answers > 0 or request.time_limit_exceeded > 0:
        level, wtype = "MEDIUM", "STUCK"
    else:
        level, wtype = "MEDIUM", "FREQUENT_FAILURE"

    return WarningResult(
        studentId=request.student_id,
        level=level, triggered=True, warningType=wtype,
        warningMessage=f"你已提交{total}次（通过率{ac_rate:.0f}%），建议暂停提交，先查看AI错误分析报告再继续。",
        teacherNote=f"提交{total}次，AC {ac}次，编译错误{request.compile_errors}次，运行错误{request.runtime_errors}次。",
        suggestedActions=["查看AI错误分析报告", "复习相关知识点", "向教师请教"],
        autoNotify=(level == "HIGH"),
        aiGenerated=False,
    )


# ── Main ─────────────────────────────────────────────────

def analyze_warning(request: WarningAnalyzeRequest, deepseek: DeepSeekClient):
    """Run warning detection.

    Flow:
    1. total_submissions == 0       → OK (no data)
    2. no failed submission signals → OK
    3. total_submissions < 3        → LOW (below threshold)
    4. AI available                 → DeepSeek analysis
    5. AI unavailable               → rule engine
    6. If triggered + submissions present → chain error+learning
    """
    total = max(request.total_submissions, 0)

    # ── No data at all ──
    if total == 0:
        logger.info("Warning: student=%s has 0 submissions, returning OK", request.student_id)
        return WarningResult(
            studentId=request.student_id, level="OK", triggered=False,
            warningType="OK", warningMessage="暂无提交数据。",
            teacherNote=None, suggestedActions=[], autoNotify=False,
            aiGenerated=False,
        )

    logger.info(
        "Warning analysis: student=%s total=%d accept=%d compile=%d runtime=%d wrong=%d tle=%d",
        request.student_id, total, request.accepted_count,
        request.compile_errors, request.runtime_errors,
        request.wrong_answers, request.time_limit_exceeded,
    )

    # ── No failure signals ──
    if not _needs_ai_analysis(request):
        logger.info("Warning: student=%s has no failed submission signals, returning OK", request.student_id)
        return WarningResult(
            studentId=request.student_id, level="OK", triggered=False,
            warningType="OK", warningMessage="当前表现正常，请继续保持。",
            teacherNote=None, suggestedActions=[], autoNotify=False,
            aiGenerated=False,
        )

    # ── Below threshold ──
    if total < 3:
        logger.info("Warning: student=%s total=%d < 3, below threshold", request.student_id, total)
        return WarningResult(
            studentId=request.student_id, level="LOW", triggered=False,
            warningType="OK",
            warningMessage=f"提交{total}次，暂未达到预警阈值（≥3次），继续加油！",
            teacherNote=None, suggestedActions=[], autoNotify=False,
            aiGenerated=False,
        )

    # ── Generate warning ──
    if not deepseek.settings.deepseek_api_key:
        logger.info("Warning: no API key, using rule engine")
        warning = _rule_based_warning(request)
    else:
        result = deepseek.chat_json(
            system_prompt=WARNING_SYSTEM_PROMPT,
            user_message=_build_warning_prompt(request),
            temperature=0.5, max_tokens=2048,
        )
        if result is None:
            logger.warning("Warning: AI call failed, using rule engine")
            warning = _rule_based_warning(request)
        else:
            try:
                warning = WarningResult(
                    studentId=request.student_id,
                    level=result.get("level", "MEDIUM"),
                    triggered=result.get("triggered", True),
                    warningType=result.get("warningType", "FREQUENT_FAILURE"),
                    warningMessage=result.get("warningMessage", ""),
                    teacherNote=result.get("teacherNote"),
                    suggestedActions=result.get("suggestedActions", []),
                    autoNotify=result.get("autoNotify", True),
                    aiGenerated=True,
                )
            except Exception as e:
                logger.error("Failed to parse AI warning: %s", e, exc_info=True)
                warning = _rule_based_warning(request)

    # ── Not triggered → return immediately ──
    if not warning.triggered:
        return warning

    # ── Chained: if submissions provided, run error+learning internally ──
    has_submissions = request.submissions is not None and len(request.submissions) > 0
    if not has_submissions:
        return warning

    error_analysis = None
    try:
        from app.services.error_analyzer import analyze_errors as _analyze_errors
        error_request = ErrorAnalysisRequest(
            studentId=request.student_id,
            studentName=request.student_name,
            experimentId=request.experiment_id,
            experimentName=request.experiment_name,
            problemTitle=f"实验{request.experiment_id} - 全部题目",
            problemDescription=None,
            submissions=request.submissions,
        )
        error_analysis = _analyze_errors(error_request, deepseek)
        logger.info("Chained error analysis: analysisId=%s",
                     error_analysis.analysis_id if error_analysis else "null")
    except Exception as e:
        logger.error("Chained error analysis failed: %s", e, exc_info=True)

    learning_suggestions = None
    try:
        from app.services.learning_advisor import generate_suggestions as _generate
        eh = request.error_history
        if eh is None or len(eh) == 0:
            eh = _build_error_history(request.submissions)
        ss = request.skill_states or []
        learning_request = LearningSuggestRequest(
            studentId=request.student_id,
            studentName=request.student_name,
            errorHistory=eh, skillStates=ss, previousRemark=None,
        )
        learning_suggestions = _generate(learning_request, deepseek)
        logger.info("Chained learning suggestions completed")
    except Exception as e:
        logger.error("Chained learning suggestions failed: %s", e, exc_info=True)

    return WarningCombinedData(
        triggered=True, warning=warning,
        errorAnalysis=error_analysis,
        learningSuggestions=learning_suggestions,
    )


def _build_error_history(submissions: list[SubmissionRecord]) -> list[ErrorTypeCount]:
    counts: dict[str, int] = {}
    for sub in submissions:
        status = sub.judge_status.upper() if sub.judge_status else "UNKNOWN"
        if status in ("ACCEPTED", "AC"):
            continue
        counts[status] = counts.get(status, 0) + 1
    return [ErrorTypeCount(errorType=k, count=v)
            for k, v in sorted(counts.items(), key=lambda x: -x[1])]
