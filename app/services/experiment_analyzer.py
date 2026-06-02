"""Experiment completion analysis with AI teaching suggestions."""

import logging

from app.schemas.requests import ExperimentAnalysisData, ExperimentAnalyzeRequest
from app.services.deepseek_client import DeepSeekClient

logger = logging.getLogger(__name__)

EXPERIMENT_SYSTEM_PROMPT = """你是重庆科技大学的实验教学分析师。基于全班实验完成数据，分析教学效果，识别共性问题，给出教学建议。

分析要求：
1. 实验整体完成质量评价（注意要客观，不要一味批评）
2. 识别"拦路虎"题目——哪些题目通过率低、提交次数高
3. 高频错误的共性特征分析
4. 对教师的教学改进建议（具体、可操作）
5. 如果需要重点关注个别学生，列出学生ID

输出格式（严格JSON）：
{
  "completionAssessment": "完成情况评价（100-200字，中文）",
  "difficultyAnalysis": {
    "hardestProblem": "最难的题目标签/名称",
    "reason": "难度分析原因（中文）",
    "avgSubmissions": 8.2,
    "passRate": 0.34
  },
  "commonErrorAnalysis": "高频错误分析（100-200字，中文，从教师教学视角）",
  "teachingSuggestions": [
    "教学建议1（具体可操作）",
    "教学建议2"
  ],
  "riskStudents": ["学号1", "学号2"]
}"""


def _build_experiment_prompt(request: ExperimentAnalyzeRequest) -> str:
    """Build the user message for experiment analysis."""
    total = max(request.total_students, 1)
    completion_rate = request.completed / total * 100

    error_lines = "\n".join(
        f"  - {e.type}: {e.count}次 ({e.percentage or 0:.1f}%)" for e in request.common_errors
    )

    problem_lines = "\n".join(
        f"  - {p.get('label', '未知题')}: 平均提交{p.get('avgSubmissions', 0)}次, AC率{p.get('passRate', 0):.0%}"
        for p in request.problem_stats
    )

    return f"""实验信息：
- 实验: {request.experiment_name or '未知'} (ID: {request.experiment_id})
- 班级ID: {request.class_id or '未指定'}
- 总人数: {total}
- 已完成: {request.completed}人 ({completion_rate:.0f}%)
- 进行中: {request.in_progress}人
- 未开始: {request.not_started}人
- 平均提交次数: {request.avg_submissions or 0:.1f}
- 整体通过率(AC率): {(request.avg_pass_rate or 0) * 100:.0f}%

各题统计：
{problem_lines or '（未提供）'}

高频错误分布：
{error_lines or '（未提供）'}

请根据以上数据，从教学角度分析实验完成情况并给出改进建议（严格按JSON格式输出）。"""


def _rule_based_experiment_analysis(request: ExperimentAnalyzeRequest) -> ExperimentAnalysisData:
    """Fallback: generate analysis from statistics without AI."""
    total = max(request.total_students, 1)
    completion_rate = request.completed / total * 100

    if completion_rate >= 80:
        assessment = f"实验整体完成情况良好，{request.completed}/{total}人已完成（{completion_rate:.0f}%）。大部分学生能够按时完成实验任务。"
    elif completion_rate >= 50:
        assessment = f"实验整体完成情况中等，{request.completed}/{total}人已完成（{completion_rate:.0f}%）。仍有{request.not_started}人尚未开始。"
    else:
        assessment = f"实验整体完成率偏低，仅{request.completed}/{total}人完成（{completion_rate:.0f}%）。{request.not_started}人尚未开始，需要教师关注。"

    # Find hardest problem
    hardest = None
    if request.problem_stats:
        hardest = min(request.problem_stats, key=lambda p: p.get("passRate", 1.0))

    # Find most common error
    top_error = ""
    if request.common_errors:
        top_error = f"最常见错误为{request.common_errors[0].type}（{request.common_errors[0].count}次），"

    error_analysis = (
        f"{top_error}建议教师在课堂上针对性讲解相关知识点。"
        if top_error
        else "AI分析不可用，建议教师根据实际情况判断高频错误。"
    )

    suggestions = []
    if request.not_started > total * 0.2:
        suggestions.append(f"有{request.not_started}人尚未开始实验，建议逐个了解原因，可能是时间安排或知识点障碍。")
    if request.avg_pass_rate and request.avg_pass_rate < 0.5:
        suggestions.append("整体通过率偏低，建议在课堂上增加实验相关知识点的讲解和例题演示。")
    if hardest:
        suggestions.append(
            f"'{hardest.get('label', '未知题')}'通过率最低，建议在课堂或答疑时重点讲解该题。"
        )

    return ExperimentAnalysisData(
        completionAssessment=assessment,
        difficultyAnalysis=(
            {
                "hardestProblem": hardest.get("label", "未知"),
                "reason": f"该题通过率仅{hardest.get('passRate', 0):.0%}",
                "avgSubmissions": hardest.get("avgSubmissions", 0),
                "passRate": hardest.get("passRate", 0),
            }
            if hardest
            else None
        ),
        commonErrorAnalysis=error_analysis,
        teachingSuggestions=suggestions or ["建议教师根据实际数据制定教学改进计划。"],
        riskStudents=None,
    )


def analyze_experiment(request: ExperimentAnalyzeRequest, deepseek: DeepSeekClient) -> ExperimentAnalysisData:
    """Run experiment analysis: AI-driven with rule-based fallback."""

    if not deepseek.settings.deepseek_api_key:
        logger.warning("DEEPSEEK_API_KEY not configured, using rule-based fallback")
        return _rule_based_experiment_analysis(request)

    prompt = _build_experiment_prompt(request)
    result = deepseek.chat_json(
        system_prompt=EXPERIMENT_SYSTEM_PROMPT,
        user_message=prompt,
        temperature=0.5,
        max_tokens=2048,
    )

    if result is None:
        logger.warning("DeepSeek call failed, using rule-based fallback")
        return _rule_based_experiment_analysis(request)

    try:
        return ExperimentAnalysisData(
            completionAssessment=result.get("completionAssessment", ""),
            difficultyAnalysis=result.get("difficultyAnalysis"),
            commonErrorAnalysis=result.get("commonErrorAnalysis"),
            teachingSuggestions=result.get("teachingSuggestions", []),
            riskStudents=result.get("riskStudents"),
        )
    except Exception as e:
        logger.error("Failed to parse AI experiment response: %s", e, exc_info=True)
        return _rule_based_experiment_analysis(request)
