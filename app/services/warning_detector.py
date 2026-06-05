"""Learning warning detection with AI-driven analysis (single student)."""

import logging

from app.schemas.requests import WarningAnalyzeRequest, WarningResult
from app.services.deepseek_client import DeepSeekClient

logger = logging.getLogger(__name__)

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


def analyze_warning(request: WarningAnalyzeRequest, deepseek: DeepSeekClient) -> WarningResult:
    """Run warning analysis for a single student: AI-driven with rule-based fallback."""

    if not _needs_ai_analysis(request):
        logger.info("Student %s has no submission data or all accepted, returning OK", request.student_id)
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

    if not deepseek.settings.deepseek_api_key:
        logger.warning("DEEPSEEK_API_KEY not configured, using rule engine")
        return _rule_based_warning(request)

    prompt = _build_warning_prompt(request)
    result = deepseek.chat_json(
        system_prompt=WARNING_SYSTEM_PROMPT,
        user_message=prompt,
        temperature=0.5,
        max_tokens=2048,
    )

    if result is None:
        logger.warning("DeepSeek call failed, using rule engine")
        return _rule_based_warning(request)

    try:
        return WarningResult(
            studentId=request.student_id,
            level=result.get("level", "MEDIUM"),
            triggered=result.get("triggered", False),
            warningType=result.get("warningType", "OK"),
            warningMessage=result.get("warningMessage", ""),
            teacherNote=result.get("teacherNote"),
            suggestedActions=result.get("suggestedActions", []),
            autoNotify=result.get("autoNotify", False),
            aiGenerated=True,
        )
    except Exception as e:
        logger.error("Failed to parse AI warning response: %s", e, exc_info=True)
        return _rule_based_warning(request)
