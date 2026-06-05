"""AI learning suggestion generation service."""

import logging
import uuid
from datetime import datetime

from app.schemas.requests import (
    LearningSuggestData,
    LearningSuggestRequest,
    StudyPlanItem,
    WeakPoint,
)
from app.services.deepseek_client import DeepSeekClient

logger = logging.getLogger(__name__)

LEARNING_SYSTEM_PROMPT = """你是重庆科技大学数据结构课程的AI学习顾问。基于学生的错误历史和技能状态，生成个性化的学习建议。

分析要求：
1. 识别学生的薄弱知识点（对照错误类型和技能掌握度）
2. 按优先级制定学习计划
3. 给出具体的学习资源建议（教材章节、练习题方向）
4. 所有中文内容要专业、温和、鼓励学生
5. 建议要有可操作性，能真正帮助学生改进

输出格式（严格JSON）：
{
  "weakPoints": [
    {
      "tagName": "薄弱知识点名称（如'指针'、'链表边界处理'）",
      "severity": "HIGH",
      "reason": "识别原因（中文，一句话）"
    }
  ],
  "studyPlan": [
    {
      "topic": "学习主题",
      "priority": "HIGH",
      "suggestedResources": "推荐资源（教材章节或在线资源）",
      "estimatedTime": "预估学习时间（如'30分钟'、'1小时'）"
    }
  ],
  "recommendedProblems": ["练习方向1", "练习方向2"],
  "summaryMessage": "面向学生的总结鼓励语（100-200字，中文，温暖鼓励）"
}"""


def _build_learning_prompt(request: LearningSuggestRequest) -> str:
    """Build the user message for learning suggestion generation."""
    error_lines = []
    for eh in request.error_history:
        error_lines.append(f"- {eh.error_type}: {eh.count}次")

    skill_lines = []
    if request.skill_states:
        for s in request.skill_states:
            skill_lines.append(f"- {s.tag_name}: 掌握度{s.mastery_score:.0f}/100, 练习{s.attempt_count}次")
    else:
        skill_lines.append("（无技能状态数据）")

    prev = f"\n上次AI评语：{request.previous_remark}" if request.previous_remark else ""

    return f"""学生信息：
- 学号: {request.student_id}
- 姓名: {request.student_name}

错误类型分布：
{chr(10).join(error_lines)}

当前技能状态：
{chr(10).join(skill_lines)}{prev}

请根据以上信息，识别该学生的薄弱知识点，制定个性化学习计划（严格按JSON格式输出）。"""


def _rule_based_suggestions(request: LearningSuggestRequest) -> LearningSuggestData:
    """Generate basic suggestions using rule engine (AI fallback)."""
    error_map = {
        "COMPILE_ERROR": ("基础语法", "复习C语言语法基础，重点关注变量声明、类型匹配、头文件引用"),
        "RUNTIME_ERROR": ("边界处理与指针", "重点检查数组越界、空指针解引用、递归终止条件"),
        "WRONG_ANSWER": ("算法逻辑", "仔细审题，使用多种测试用例验证代码正确性"),
        "TIME_LIMIT_EXCEEDED": ("算法效率", "分析时间复杂度，考虑使用更高效的数据结构或算法"),
        "MEMORY_LIMIT_EXCEEDED": ("内存管理", "检查动态内存分配和释放，优化空间复杂度"),
    }

    weak_points: list[WeakPoint] = []
    study_plan: list[StudyPlanItem] = []

    for eh in request.error_history[:3]:  # top 3 error types
        tag, resource = error_map.get(eh.error_type, (eh.error_type, "分析错误原因，针对性地巩固相关知识"))
        weak_points.append(
            WeakPoint(
                tagName=tag,
                severity="HIGH" if eh.count >= 5 else "MEDIUM",
                reason=f"该类型错误出现{eh.count}次，需要针对性加强",
            )
        )
        study_plan.append(
            StudyPlanItem(
                topic=tag,
                priority="HIGH" if eh.count >= 5 else "MEDIUM",
                suggestedResources=resource,
                estimatedTime="1小时" if eh.count >= 5 else "30分钟",
            )
        )

    total_errors = sum(eh.count for eh in request.error_history)
    summary = (
        f"根据你的提交记录分析，共出现{total_errors}次错误。"
        f"建议优先攻克{weak_points[0].tag_name if weak_points else '薄弱知识点'}，"
        f"扎实打好基础，逐步提升编程能力。加油！"
    )

    return LearningSuggestData(
        suggestionId=f"lrn_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}",
        weakPoints=weak_points,
        studyPlan=study_plan,
        recommendedProblems=["PTA同类题目练习", "教材课后习题"],
        summaryMessage=summary,
        aiGenerated=False,
    )


def generate_suggestions(request: LearningSuggestRequest, deepseek: DeepSeekClient) -> LearningSuggestData:
    """Generate personalized learning suggestions: AI-driven with rule-based fallback."""

    suggestion_id = f"lrn_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"

    if not deepseek.settings.deepseek_api_key:
        logger.warning("DEEPSEEK_API_KEY not configured, using rule-based fallback")
        fallback = _rule_based_suggestions(request)
        fallback.suggestion_id = suggestion_id
        return fallback

    prompt = _build_learning_prompt(request)
    result = deepseek.chat_json(
        system_prompt=LEARNING_SYSTEM_PROMPT,
        user_message=prompt,
        temperature=0.5,
        max_tokens=2048,
    )

    if result is None:
        logger.warning("DeepSeek call failed, using rule-based fallback")
        fallback = _rule_based_suggestions(request)
        fallback.suggestion_id = suggestion_id
        return fallback

    try:
        return LearningSuggestData(
            suggestionId=suggestion_id,
            weakPoints=[
                WeakPoint(
                    tagName=w.get("tagName", ""),
                    severity=w.get("severity", "MEDIUM"),
                    reason=w.get("reason", ""),
                )
                for w in result.get("weakPoints", [])
            ],
            studyPlan=[
                StudyPlanItem(
                    topic=s.get("topic", ""),
                    priority=s.get("priority", "MEDIUM"),
                    suggestedResources=s.get("suggestedResources"),
                    estimatedTime=s.get("estimatedTime"),
                )
                for s in result.get("studyPlan", [])
            ],
            recommendedProblems=result.get("recommendedProblems"),
            summaryMessage=result.get("summaryMessage", "请继续努力，加强薄弱环节的练习。"),
            aiGenerated=True,
        )
    except Exception as e:
        logger.error("Failed to parse AI learning suggestion response: %s", e, exc_info=True)
        fallback = _rule_based_suggestions(request)
        fallback.suggestion_id = suggestion_id
        return fallback
