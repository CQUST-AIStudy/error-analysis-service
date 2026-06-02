"""Learning warning detection with AI-driven analysis."""

import logging

from app.schemas.requests import StudentWarning, StudentWarningInput, WarningAnalysisData, WarningAnalyzeRequest
from app.services.deepseek_client import DeepSeekClient

logger = logging.getLogger(__name__)

WARNING_SYSTEM_PROMPT = """你是重庆科技大学的学习预警分析师。基于学生的提交统计数据，判断哪些学生需要教学干预。

分析要求：
1. 对每个学生独立判断预警等级
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
  "warnings": [
    {
      "studentId": "学号",
      "level": "HIGH",
      "triggered": true,
      "warningType": "FREQUENT_FAILURE",
      "warningMessage": "面向学生的提示语（≤50字，温和鼓励）",
      "teacherNote": "面向教师的分析备注",
      "suggestedActions": ["建议1", "建议2"],
      "autoNotify": true
    }
  ],
  "classSummary": "班级整体分析（50-100字，中文）"
}

warningType可选值：
- FREQUENT_FAILURE: 频繁提交但通过率极低
- BASIC_SYNTAX: 编译错误占比过高，基础语法薄弱
- STUCK: 卡在某个问题上
- DEADLINE_RISK: 截止日期风险
- OK: 表现正常"""


def _build_warning_prompt(request: WarningAnalyzeRequest) -> str:
    """Build the user message for warning analysis."""
    student_lines: list[str] = []
    for s in request.students:
        total = s.total_submissions
        ac = s.accepted_count
        ac_rate = (ac / total * 100) if total > 0 else 0
        compile_pct = (s.compile_errors / total * 100) if total > 0 else 0
        runtime_pct = (s.runtime_errors / total * 100) if total > 0 else 0

        student_lines.append(
            f"- 学号: {s.student_id}, 姓名: {s.student_name or '未知'}, "
            f"提交{total}次, AC{ac}次, 通过率{ac_rate:.0f}%, "
            f"编译错误{s.compile_errors}次({compile_pct:.0f}%), "
            f"运行时错误{s.runtime_errors}次({runtime_pct:.0f}%), "
            f"答案错误{s.wrong_answers}次, 超时{s.time_limit_exceeded}次, "
            f"最近提交: {s.last_submission_at or '未知'}"
        )

    deadline_info = f"\n截止日期: {request.deadline}" if request.deadline else ""

    return f"""班级ID: {request.class_id}
实验: {request.experiment_name or '未知'} (ID: {request.experiment_id}){deadline_info}

学生提交统计（共{len(request.students)}人）：
{chr(10).join(student_lines)}

请逐个分析每个学生的预警情况，判断是否需要教学干预（严格按JSON格式输出）。"""


# ── Rule-based pre-filter ────────────────────────────────


def _needs_ai_analysis(student: StudentWarningInput) -> bool:
    """Pre-filter: only send students needing attention to AI."""
    total = student.total_submissions
    if total == 0:
        return False  # no data, skip
    ac = student.accepted_count
    if ac >= total:  # all accepted
        return False
    return True


def _rule_based_warning(student: StudentWarningInput) -> StudentWarning:
    """Generate a basic warning using rule engine (AI fallback)."""
    total = max(student.total_submissions, 1)
    ac = student.accepted_count
    ac_rate = ac / total

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
        teacher_note = f"提交{total}次，AC率仅{ac_rate:.0%}，需要重点关注。"
    elif student.compile_errors / total > 0.3:
        level = "MEDIUM"
        warning_type = "BASIC_SYNTAX"
        triggered = True
        auto_notify = True
        warning_message = "编译错误占比较高，建议加强C语言基础语法学习。"
        teacher_note = f"编译错误占比{student.compile_errors / total:.0%}，基础语法有待加强。"
    elif student.runtime_errors >= 3:
        level = "MEDIUM"
        warning_type = "STUCK"
        triggered = True
        auto_notify = False
        warning_message = "运行时错误较多，建议检查代码中的边界条件处理和指针使用。"
        teacher_note = f"运行时错误{student.runtime_errors}次，可能是边界处理或指针问题。"

    if not triggered:
        warning_message = "当前表现正常，请继续保持。"
        teacher_note = "暂不需要干预。"

    return StudentWarning(
        studentId=student.student_id,
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
    )


# ── Main analysis function ──────────────────────────────


def analyze_warnings(request: WarningAnalyzeRequest, deepseek: DeepSeekClient) -> WarningAnalysisData:
    """Run warning analysis: rule pre-filter → AI analysis → results."""

    # Pre-filter: find students needing AI analysis
    needs_ai = [s for s in request.students if _needs_ai_analysis(s)]
    no_ai = [s for s in request.students if not _needs_ai_analysis(s)]

    logger.info(
        "Warning analysis: %d total, %d need AI, %d trivial",
        len(request.students),
        len(needs_ai),
        len(no_ai),
    )

    ai_warnings: list[StudentWarning] = []

    if needs_ai and deepseek.settings.deepseek_api_key:
        prompt = _build_warning_prompt(
            WarningAnalyzeRequest(
                classId=request.class_id,
                experimentId=request.experiment_id,
                experimentName=request.experiment_name,
                deadline=request.deadline,
                students=needs_ai,
            )
        )

        result = deepseek.chat_json(
            system_prompt=WARNING_SYSTEM_PROMPT,
            user_message=prompt,
            temperature=0.5,
            max_tokens=2048,
        )

        if result:
            try:
                class_summary = result.get("classSummary", "")
                for w in result.get("warnings", []):
                    ai_warnings.append(
                        StudentWarning(
                            studentId=w.get("studentId", ""),
                            level=w.get("level", "MEDIUM"),
                            triggered=w.get("triggered", False),
                            warningType=w.get("warningType", "OK"),
                            warningMessage=w.get("warningMessage", ""),
                            teacherNote=w.get("teacherNote"),
                            suggestedActions=w.get("suggestedActions", []),
                            autoNotify=w.get("autoNotify", False),
                        )
                    )
            except Exception as e:
                logger.error("Failed to parse AI warning response: %s", e, exc_info=True)
                ai_warnings = []
                class_summary = "AI分析失败，使用规则引擎结果。"
        else:
            logger.warning("AI warning analysis failed, using rule engine for all students")
            class_summary = "AI分析暂不可用，以下为规则引擎预警结果。"
            # Fallback: use rule engine for students that needed AI
            for s in needs_ai:
                ai_warnings.append(_rule_based_warning(s))
    else:
        class_summary = "AI未配置或无需AI分析，以下为规则引擎结果。"
        # Rule engine for all students
        for s in needs_ai:
            ai_warnings.append(_rule_based_warning(s))

    # Trivial students get OK status
    trivial_warnings = [_rule_based_warning(s) for s in no_ai]

    all_warnings = ai_warnings + trivial_warnings
    # Sort: triggered first, then by level severity
    severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "OK": 3}
    all_warnings.sort(key=lambda w: (not w.triggered, severity_order.get(w.level, 99)))

    if not class_summary:
        triggered_count = sum(1 for w in all_warnings if w.triggered)
        total = len(request.students)
        class_summary = f"班级共{total}人，{triggered_count}人触发预警（{triggered_count / max(total, 1) * 100:.0f}%）。"

    return WarningAnalysisData(
        warnings=all_warnings,
        classSummary=class_summary,
    )
