"""Core error analysis logic with DeepSeek AI integration."""

import logging
import uuid
from datetime import datetime

from app.schemas.requests import (
    ErrorAnalysisData,
    ErrorAnalysisRequest,
    ErrorCategory,
    LearningSuggestion,
    SubmissionRecord,
)
from app.services.deepseek_client import DeepSeekClient
from app.services.learning_advisor import SKILL_TAG_MAP

# Build Chinese name list for AI prompt constraint
_SKILL_CHINESE_NAMES = [v[0] for v in SKILL_TAG_MAP.values()]
_SKILL_TAGS_CSV = "、".join(_SKILL_CHINESE_NAMES)

logger = logging.getLogger(__name__)

ERROR_ANALYSIS_SYSTEM_PROMPT = """你是重庆科技大学数据结构课程的AI助教，专精于C/C++代码错误诊断。
你需要分析学生的PTA提交记录，找出错误的根本原因并给出学习建议。

分析要求：
1. 逐次分析每次提交的错误类型和可能原因
2. 识别错误演变模式（是同一个bug反复出现，还是解决一个又引入新的？）
3. 如果同一类型错误反复出现（≥3次），标注为"系统性薄弱点"
4. 给出具体的学习建议，指向具体的知识点
5. 所有中文内容要专业、温和、鼓励学生

输出格式（严格JSON）：
{
  "overallAssessment": "整体评价（50-150字，中文）",
  "errorPattern": "错误演变模式描述（中文）",
  "errorCategories": [
    {
      "type": "COMPILE_ERROR",
      "count": 2,
      "rootCause": "根本原因（中文）",
      "specificIssues": ["具体问题1", "具体问题2"],
      "suggestions": ["改进建议1", "改进建议2"],
      "isSystemic": true
    }
  ],
  "learningSuggestions": [
    {
      "topic": "知识点名称",
      "priority": "HIGH",
      "reason": "建议原因（中文）",
      "suggestedResources": "推荐练习方向或在线资源"
    }
  ],
  "interventionTriggered": true,
  "interventionMessage": "面向学生的干预提示语（温和鼓励的语气，≤80字）",
  "severity": "HIGH"
}

重要：learningSuggestions.topic 必须从以下知识点标签中选择：
""" + _SKILL_TAGS_CSV


def _build_error_analysis_prompt(request: ErrorAnalysisRequest) -> str:
    """Build the user message for error analysis."""

    # Pre-classify errors
    error_stats: dict[str, int] = {}
    submission_entries: list[str] = []

    for sub in request.submissions:
        status = sub.judge_status.upper() if sub.judge_status else "UNKNOWN"
        error_stats[status] = error_stats.get(status, 0) + 1

        truncated_code = _truncate_code(sub.code)

        entry_parts = [
            f"--- 第{sub.attempt_no}次提交 ---",
            f"判题状态: {sub.judge_status}",
        ]
        if sub.error_message:
            entry_parts.append(f"错误信息: {sub.error_message}")
        if sub.runtime_ms is not None:
            entry_parts.append(f"运行时间: {sub.runtime_ms}ms")
        if sub.memory_kb is not None:
            entry_parts.append(f"内存: {sub.memory_kb}KB")
        entry_parts.append(f"编译器: {sub.compiler or '未知'}")
        entry_parts.append(f"提交时间: {sub.submitted_at or '未知'}")
        entry_parts.append(f"\n代码:\n```c\n{truncated_code}\n```\n")
        submission_entries.append("\n".join(entry_parts))

    # Build summary
    total = len(request.submissions)
    error_summary = ", ".join(f"{k}: {v}次" for k, v in sorted(error_stats.items()))

    prompt = f"""学生信息：
- 学号: {request.student_id}
- 姓名: {request.student_name or '未知'}
- 实验: {request.experiment_name or '未知'} (ID: {request.experiment_id})
- 题目: {request.problem_title or '未知'}
- 总提交次数: {total}
- 错误类型分布: {error_summary}

题目描述（如有）：
{request.problem_description or '（未提供）'}

提交历史（共{total}次）：
{"".join(submission_entries)}

当前技能掌握度（来自student_skill_state表）：
""" + (_format_skill_states(request) or "（无技能状态数据）") + """

请根据以上提交记录和技能掌握度，分析该学生的错误原因并生成学习建议（严格按JSON格式输出）。"""
    return prompt


def _truncate_code(code: str, max_lines: int = 3000) -> str:
    """Truncate code to max_lines, keeping the beginning."""
    if not code:
        return "(空代码)"
    lines = code.split("\n")
    if len(lines) > max_lines:
        return "\n".join(lines[:max_lines]) + f"\n\n... [代码过长，已截断，原{len(lines)}行仅保留前{max_lines}行]"
    return code


def _first_submission_code(request: ErrorAnalysisRequest) -> str | None:
    """Return code text of the first/latest submission for frontend display."""
    if request.submissions:
        return request.submissions[0].code or None
    return None


def _first_submission_status(request: ErrorAnalysisRequest) -> str | None:
    """Return judge status of the first/latest submission for frontend display."""
    if request.submissions:
        return request.submissions[0].judge_status or None
    return None


def _format_skill_states(request: ErrorAnalysisRequest) -> str | None:
    """Format skill states for the AI prompt (Chinese names via SKILL_TAG_MAP)."""
    if not request.skill_states:
        return None
    lines = []
    for sk in request.skill_states[:10]:  # top 10
        chinese_name, _ = SKILL_TAG_MAP.get(sk.tag_name, (sk.tag_name, ""))
        lines.append(f"- {chinese_name}: 掌握度{sk.mastery_score:.0f}/100, 练习{sk.attempt_count}次")
    return "\n".join(lines)


# ── Rule-based fallback analysis (no AI) ─────────────────


def _rule_based_fallback(request: ErrorAnalysisRequest) -> ErrorAnalysisData:
    """Fallback analysis using rule engine when AI is unavailable."""
    error_stats: dict[str, list[SubmissionRecord]] = {}
    for sub in request.submissions:
        status = sub.judge_status.upper() if sub.judge_status else "UNKNOWN"
        error_stats.setdefault(status, []).append(sub)

    error_categories: list[ErrorCategory] = []
    for error_type, subs in sorted(error_stats.items()):
        if error_type in ("ACCEPTED", "AC"):
            continue
        cat = ErrorCategory(
            type=error_type,
            count=len(subs),
            rootCause=_describe_error_type(error_type),
            specificIssues=[_first_error_line(s.error_message) for s in subs if s.error_message][:3],
            suggestions=_generic_suggestions(error_type),
            isSystemic=len(subs) >= 3,
        )
        error_categories.append(cat)

    total = len(request.submissions)
    ac_count = len(error_stats.get("ACCEPTED", []))
    triggered = total > 3 and ac_count < total * 0.3

    # Generate learning suggestions from skillStates or error types
    learning_suggestions = _generate_fallback_suggestions(request)

    return ErrorAnalysisData(
        analysisId=f"err_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}",
        overallAssessment=f"该学生在{request.experiment_name or '本次实验'}中共提交{total}次，"
        f"通过{ac_count}次。AI分析暂时不可用，以下为基于规则的分析。",
        errorCategories=error_categories,
        learningSuggestions=learning_suggestions,
        interventionTriggered=triggered,
        interventionMessage=(
            f"检测到你已连续提交{total}次，建议暂停提交，先仔细分析错误原因再继续。"
            if triggered
            else None
        ),
        severity="HIGH" if triggered else ("MEDIUM" if error_categories else "LOW"),
        aiGenerated=False,
        latestCode=_first_submission_code(request),
        latestJudgeStatus=_first_submission_status(request),
    )


def _generate_fallback_suggestions(request: ErrorAnalysisRequest) -> list[LearningSuggestion]:
    """Generate learning suggestions from skillStates (preferred) or error types."""
    if request.skill_states:
        # Use weakest 3 skills
        sorted_skills = sorted(request.skill_states, key=lambda s: s.mastery_score)[:3]
        suggestions = []
        for sk in sorted_skills:
            chinese_name, resource = SKILL_TAG_MAP.get(sk.tag_name, (sk.tag_name, "针对性地巩固相关知识"))
            if sk.mastery_score < 30:
                priority, reason = "HIGH", f"{chinese_name}掌握度仅{sk.mastery_score:.0f}分，急需系统性学习"
            elif sk.mastery_score < 60:
                priority, reason = "MEDIUM", f"{chinese_name}掌握度{sk.mastery_score:.0f}分，需要针对性强化练习"
            else:
                priority, reason = "LOW", f"{chinese_name}掌握度{sk.mastery_score:.0f}分，尚有提升空间"
            suggestions.append(LearningSuggestion(
                topic=chinese_name, priority=priority, reason=reason, suggestedResources=resource,
            ))
        return suggestions
    else:
        # Infer from error types
        return _infer_suggestions_from_errors(request)


def _infer_suggestions_from_errors(request: ErrorAnalysisRequest) -> list[LearningSuggestion]:
    """Infer likely skill weaknesses from error type distribution."""
    error_to_skills: dict[str, list[str]] = {
        "COMPILE_ERROR": ["数组", "字符串", "排序"],
        "RUNTIME_ERROR": ["链表", "栈", "深度优先搜索"],
        "WRONG_ANSWER": ["查找", "贪心", "动态规划"],
        "TIME_LIMIT_EXCEEDED": ["排序", "二分查找", "动态规划"],
        "MEMORY_LIMIT_EXCEEDED": ["堆", "并查集", "字典树"],
    }
    seen: set[str] = set()
    suggestions: list[LearningSuggestion] = []
    for sub in request.submissions[:5]:
        status = sub.judge_status.upper() if sub.judge_status else "UNKNOWN"
        for skill_name in error_to_skills.get(status, []):
            if skill_name not in seen and len(suggestions) < 3:
                seen.add(skill_name)
                suggestions.append(LearningSuggestion(
                    topic=skill_name,
                    priority="MEDIUM",
                    reason=f"根据{status}错误类型推断，{skill_name}可能是薄弱环节",
                    suggestedResources=f"建议练习PTA-{skill_name}专题，巩固相关知识点",
                ))
    if not suggestions:
        suggestions.append(LearningSuggestion(
            topic="基础语法", priority="MEDIUM",
            reason="存在多次提交错误，建议从基础知识点排查",
            suggestedResources="针对性地练习相关题目，巩固基础知识点",
        ))
    return suggestions


def _describe_error_type(error_type: str) -> str:
    descriptions = {
        "COMPILE_ERROR": "代码存在语法错误，编译阶段未通过",
        "RUNTIME_ERROR": "程序运行时发生错误（如段错误、除零、空指针访问等）",
        "TIME_LIMIT_EXCEEDED": "程序运行超时，算法效率不足或存在死循环",
        "WRONG_ANSWER": "程序逻辑错误，输出结果与预期不符",
        "SEGMENTATION_FAULT": "非法内存访问，常见于数组越界或空指针解引用",
    }
    return descriptions.get(error_type, f"{error_type}类型错误")


def _first_error_line(error_message: str | None) -> str:
    if not error_message:
        return "（无具体错误信息）"
    return error_message.strip().split("\n")[0][:200]


def _generic_suggestions(error_type: str) -> list[str]:
    suggestions_map: dict[str, list[str]] = {
        "COMPILE_ERROR": [
            "仔细阅读编译器错误信息，从第一个报错开始修复",
            "确认变量、类型在使用前已正确声明",
            "检查头文件包含是否完整",
        ],
        "RUNTIME_ERROR": [
            "检查数组索引是否在合法范围内",
            "检查所有指针使用前是否已分配内存且非空",
            "确认递归函数有正确的终止条件",
        ],
        "TIME_LIMIT_EXCEEDED": [
            "分析算法时间复杂度，考虑使用更高效的数据结构",
            "检查是否存在不必要的重复计算",
            "确认循环是否有正确的退出条件，避免死循环",
        ],
        "WRONG_ANSWER": [
            "仔细审题，确认理解题意和边界条件",
            "使用极端测试用例验证代码（空输入、单元素、最大值等）",
            "对比期望输出和实际输出，定位逻辑偏差",
        ],
        "SEGMENTATION_FAULT": [
            "检查数组越界访问",
            "检查指针是否为空再使用",
            "检查动态内存分配是否成功",
        ],
    }
    return suggestions_map.get(error_type, ["分析错误信息，定位问题根源", "针对性地练习相关题目", "向教师或同学请教"])


# ── Main analysis function ──────────────────────────────


def analyze_errors(request: ErrorAnalysisRequest, deepseek: DeepSeekClient) -> ErrorAnalysisData:
    """Run full error analysis: AI-driven with rule-based fallback."""

    analysis_id = f"err_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"

    # Pre-check: has a valid API key?
    if not deepseek.settings.deepseek_api_key:
        logger.warning("DEEPSEEK_API_KEY not configured, using rule-based fallback")
        fallback = _rule_based_fallback(request)
        fallback.analysis_id = analysis_id
        return fallback

    # Build prompt and call AI
    prompt = _build_error_analysis_prompt(request)
    result = deepseek.chat_json(
        system_prompt=ERROR_ANALYSIS_SYSTEM_PROMPT,
        user_message=prompt,
        temperature=0.3,
        max_tokens=4096,
    )

    if result is None:
        logger.warning("DeepSeek call failed, using rule-based fallback")
        fallback = _rule_based_fallback(request)
        fallback.analysis_id = analysis_id
        return fallback

    # Parse AI response
    try:
        return ErrorAnalysisData(
            analysisId=analysis_id,
            overallAssessment=result.get("overallAssessment", ""),
            errorCategories=[
                ErrorCategory(
                    type=c.get("type", "UNKNOWN"),
                    count=c.get("count", 0),
                    rootCause=c.get("rootCause", ""),
                    specificIssues=c.get("specificIssues", []),
                    suggestions=c.get("suggestions", []),
                    isSystemic=c.get("isSystemic", False),
                )
                for c in result.get("errorCategories", [])
            ],
            learningSuggestions=[
                LearningSuggestion(
                    topic=s.get("topic", ""),
                    priority=s.get("priority", "MEDIUM"),
                    reason=s.get("reason", ""),
                    suggestedResources=s.get("suggestedResources"),
                )
                for s in result.get("learningSuggestions", [])
            ],
            interventionTriggered=result.get("interventionTriggered", False),
            interventionMessage=result.get("interventionMessage"),
            severity=result.get("severity", "LOW"),
            aiGenerated=True,
            latestCode=_first_submission_code(request),
            latestJudgeStatus=_first_submission_status(request),
        )
    except Exception as e:
        logger.error("Failed to parse AI response: %s", e, exc_info=True)
        fallback = _rule_based_fallback(request)
        fallback.analysis_id = analysis_id
        return fallback
