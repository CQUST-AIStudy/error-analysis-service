"""Learning warning detection with AI-driven analysis (single student).

PDF 3号成员要求：当错误次数 > 5，自动串联三个功能：
  1. 预警检测 (/analyze/warning)
  2. 错误代码分析 (/analyze/error)
  3. 学习建议生成 (/analyze/learning)

当后端传入 submission 数据时，/analyze/warning 内部自动调用另外两个接口，
一次性返回完整结果。
"""

import logging

from app.schemas.requests import (
    ErrorAnalysisData,
    ErrorAnalysisRequest,
    ErrorTypeCount,
    LearningSuggestData,
    LearningSuggestRequest,
    SkillState,
    SubmissionRecord,
    WarningAnalyzeRequest,
    WarningCombinedData,
    WarningResult,
)
from app.services.deepseek_client import DeepSeekClient

logger = logging.getLogger(__name__)

# ── Warning detection prompt ─────────────────────────────

WARNING_SYSTEM_PROMPT = """你是重庆科技大学的学习预警分析师。基于单个学生的提交统计数据，判断该学生是否需要教学干预。

分析要求：
1. 根据提交次数、通过率、错误类型分布判断预警等级
2. 分析学生卡住的原因（知识点薄弱？时间管理？基础语法不熟？）
3. 生成面向学生的预警提示语（温和鼓励的语气，不要打击学生）
4. 生成面向教师的教学干预建议

预警等级定义：
- HIGH: 需要立即干预（提交次数>5且通过率<20%）
- MEDIUM: 需要关注（编译错误占比高，或有卡住趋势）
- LOW: 暂时不需要干预
- OK: 表现正常，无需任何干预

输出格式（严格JSON）：
{
  "level": "HIGH",
  "triggered": true,
  "warningType": "FREQUENT_FAILURE",
  "warningMessage": "面向学生的提示语（≤100字，温和鼓励）",
  "teacherNote": "面向教师的分析备注",
  "suggestedActions": ["建议1", "建议2"],
  "autoNotify": true
}

warningType可选值：
- FREQUENT_FAILURE: 频繁提交但通过率极低
- BASIC_SYNTAX: 编译错误占比过高，基础语法薄弱
- STUCK: 卡在某个问题上
- DEADLINE_RISK: 截止日期风险
- OK: 表现正常"""


def _build_warning_prompt(request: WarningAnalyzeRequest) -> str:
    """Build the user message for warning analysis."""
    total = request.total_submissions
    ac = request.accepted_count
    ac_rate = (ac / total * 100) if total > 0 else 0
    compile_pct = (request.compile_errors / total * 100) if total > 0 else 0
    runtime_pct = (request.runtime_errors / total * 100) if total > 0 else 0
    deadline_info = f"\n截止日期: {request.deadline}" if request.deadline else ""

    return f"""学生信息：
- 学号: {request.student_id}
- 姓名: {request.student_name}
- 实验: {request.experiment_name} (ID: {request.experiment_id}){deadline_info}
- 总题数: {request.total_problems}
- 总提交: {total}次, 通过: {ac}题, 通过率: {ac_rate:.0f}%
- 编译错误: {request.compile_errors}次 ({compile_pct:.0f}%)
- 运行时错误: {request.runtime_errors}次 ({runtime_pct:.0f}%)
- 答案错误: {request.wrong_answers}次
- 超时: {request.time_limit_exceeded}次
- 最近提交: {request.last_submission_at}

请判断该学生是否需要教学干预（严格按JSON格式输出）。"""


def _needs_ai_analysis(request: WarningAnalyzeRequest) -> bool:
    """Pre-filter: only send to AI if there's meaningful data."""
    if request.total_submissions == 0:
        return False
    if request.accepted_count >= request.total_problems:
        return False
    return True


def _rule_based_warning(request: WarningAnalyzeRequest) -> WarningResult:
    """Generate a basic warning using rule engine (AI fallback)."""
    total = max(request.total_submissions, 1)
    ac = request.accepted_count
    ac_rate = ac / request.total_problems if request.total_problems > 0 else 0

    level = "OK"
    warning_type = "OK"
    warning_message = ""
    teacher_note = ""
    triggered = False
    auto_notify = False

    if ac_rate < 0.2 and total > 5:
        level = "HIGH"
        warning_type = "FREQUENT_FAILURE"
        triggered = True
        auto_notify = True
        warning_message = f"你已提交{total}次但通过率较低，建议暂停提交，先查看AI错误分析报告再继续。"
        teacher_note = f"提交{total}次，通过率仅{ac_rate:.0%}，需要重点关注。"
    elif request.compile_errors / total > 0.3:
        level = "MEDIUM"
        warning_type = "BASIC_SYNTAX"
        triggered = True
        auto_notify = True
        warning_message = "编译错误占比较高，建议加强C语言基础语法学习。"
        teacher_note = f"编译错误占比{request.compile_errors / total:.0%}，基础语法有待加强。"
    elif request.runtime_errors >= 3:
        level = "MEDIUM"
        warning_type = "STUCK"
        triggered = True
        auto_notify = False
        warning_message = "运行时错误较多，建议检查代码中的边界条件处理和指针使用。"
        teacher_note = f"运行时错误{request.runtime_errors}次，可能是边界处理或指针问题。"

    if not triggered:
        warning_message = "当前表现正常，请继续保持。"
        teacher_note = "暂不需要干预。"

    return WarningResult(
        studentId=request.student_id,
        level=level,
        triggered=triggered,
        warningType=warning_type,
        warningMessage=warning_message,
        teacherNote=teacher_note if triggered else None,
        suggestedActions=(
            ["查看AI错误分析报告", "复习相关知识点", "向教师请教"]
            if triggered
            else []
        ),
        autoNotify=auto_notify,
        aiGenerated=False,
    )


def _count_errors(request: WarningAnalyzeRequest) -> int:
    """Count total non-ACCEPTED submissions from the stats."""
    return (
        request.compile_errors
        + request.runtime_errors
        + request.wrong_answers
        + request.time_limit_exceeded
    )


# ── Main analysis function ──────────────────────────────


def analyze_warning(request: WarningAnalyzeRequest, deepseek: DeepSeekClient):
    """Run warning analysis for a single student.

    PDF要求：当错误次数 > 5 且后端传入了 submissions 数据，
    内部自动串联调用 /analyze/error 和 /analyze/learning，
    一次性返回完整结果 (WarningCombinedData)。
    """

    error_count = _count_errors(request)
    logger.info(
        "Warning analysis: student=%s exp=%d errors=%d hasSubmissions=%s",
        request.student_id,
        request.experiment_id,
        error_count,
        request.submissions is not None and len(request.submissions) > 0,
    )

    # ── 1. 判断是否触发 ───────────────────────────────
    if not _needs_ai_analysis(request):
        logger.info(
            "Student %s has no submission data or all accepted, returning OK",
            request.student_id,
        )
        return WarningResult(
            studentId=request.student_id,
            level="OK",
            triggered=False,
            warningType="OK",
            warningMessage="当前表现正常，请继续保持。",
            teacherNote=None,
            suggestedActions=[],
            autoNotify=False,
            aiGenerated=False,
        )

    if error_count <= 5:
        logger.info(
            "Student %s error count %d <= 5, no intervention needed",
            request.student_id,
            error_count,
        )
        return WarningResult(
            studentId=request.student_id,
            level="LOW",
            triggered=False,
            warningType="OK",
            warningMessage=f"当前错误{error_count}次，暂未达到干预阈值，请继续保持。",
            teacherNote=None,
            suggestedActions=[],
            autoNotify=False,
            aiGenerated=False,
        )

    # ── 2. 生成预警结果 ────────────────────────────────
    if not deepseek.settings.deepseek_api_key:
        logger.warning("DEEPSEEK_API_KEY not configured, using rule engine")
        warning = _rule_based_warning(request)
    else:
        prompt = _build_warning_prompt(request)
        result = deepseek.chat_json(
            system_prompt=WARNING_SYSTEM_PROMPT,
            user_message=prompt,
            temperature=0.5,
            max_tokens=2048,
        )

        if result is None:
            logger.warning("DeepSeek call failed, using rule engine")
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
                logger.error("Failed to parse AI warning response: %s", e, exc_info=True)
                warning = _rule_based_warning(request)

    # ── 3. 串联：如果触发且后端传了 submissions，自动调 error+learning ──
    if not warning.triggered:
        return warning

    has_submissions = request.submissions is not None and len(request.submissions) > 0
    if not has_submissions:
        logger.info(
            "Warning triggered but no submission data provided, returning warning only"
        )
        return warning

    # ── 3a. 内部调用错误分析 (/analyze/error) ───────────
    error_analysis = None
    try:
        # 动态导入避免循环依赖
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
        logger.info(
            "Chained error analysis completed: analysisId=%s",
            error_analysis.analysis_id if error_analysis else "null",
        )
    except Exception as e:
        logger.error("Chained error analysis failed: %s", e, exc_info=True)

    # ── 3b. 内部调用学习建议 (/analyze/learning) ────────
    learning_suggestions = None
    try:
        from app.services.learning_advisor import generate_suggestions as _generate_suggestions

        # 用请求中的 error_history，如果没有则从 submissions 构造
        eh = request.error_history
        if eh is None or len(eh) == 0:
            eh = _build_error_history_from_submissions(request.submissions)

        ss = request.skill_states or []

        learning_request = LearningSuggestRequest(
            studentId=request.student_id,
            studentName=request.student_name,
            errorHistory=eh,
            skillStates=ss,
            previousRemark=None,
        )
        learning_suggestions = _generate_suggestions(learning_request, deepseek)
        logger.info("Chained learning suggestions completed")
    except Exception as e:
        logger.error("Chained learning suggestions failed: %s", e, exc_info=True)

    # ── 3c. 返回合并结果 ─────────────────────────────
    return WarningCombinedData(
        triggered=True,
        warning=warning,
        errorAnalysis=error_analysis,
        learningSuggestions=learning_suggestions,
    )


def _build_error_history_from_submissions(
    submissions: list[SubmissionRecord],
) -> list[ErrorTypeCount]:
    """Build error type distribution from submission records."""
    counts: dict[str, int] = {}
    for sub in submissions:
        status = sub.judge_status.upper() if sub.judge_status else "UNKNOWN"
        if status in ("ACCEPTED", "AC"):
            continue
        counts[status] = counts.get(status, 0) + 1
    return [
        ErrorTypeCount(errorType=k, count=v)
        for k, v in sorted(counts.items(), key=lambda x: -x[1])
    ]
