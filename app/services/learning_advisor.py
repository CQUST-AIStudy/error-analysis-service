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
3. 给出具体的学习资源建议（练习方向、在线资源）
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
      "suggestedResources": "推荐练习方向或在线资源",
      "estimatedTime": "预估学习时间（如'30分钟'、'1小时'）"
    }
  ],
  "recommendedProblems": ["练习方向1", "练习方向2"],
  "summaryMessage": "面向学生的总结鼓励语（100-200字，中文，温暖鼓励）"
}"""


# 30 个数据结构技能标签 → (中文名, 学习资源建议)
SKILL_TAG_MAP: dict[str, tuple[str, str]] = {
    "array": ("数组", "复习数组的声明、初始化和遍历操作，重点练习PTA数组相关题目"),
    "linked_list": ("链表", "掌握单链表/双链表的插入删除操作，注意头结点和尾结点边界处理"),
    "stack": ("栈", "理解栈的后进先出特性，练习括号匹配、表达式求值等经典题目"),
    "queue": ("队列", "掌握队列的先进先出特性，练习BFS辅助队列的使用"),
    "tree": ("树", "复习树的遍历（前序/中序/后序/层序），掌握递归与非递归实现"),
    "binary_tree": ("二叉树", "重点练习二叉树的构建、遍历和性质判断题目"),
    "heap": ("堆", "理解堆的性质和堆排序，练习优先队列相关题目"),
    "hash_table": ("哈希表", "掌握哈希表的原理和冲突解决，练习使用哈希表优化查找"),
    "graph": ("图", "复习图的存储方式（邻接矩阵/邻接表），理解图的基本概念"),
    "string": ("字符串", "练习字符串匹配、KMP算法和字符串处理函数的使用"),
    "sorting": ("排序", "掌握快排、归并排序等经典排序算法，理解不同场景下的选择"),
    "searching": ("查找", "复习顺序查找、二分查找及其变体，练习查找类题目"),
    "binary_search": ("二分查找", "重点练习二分查找的边界条件处理和变体应用"),
    "dfs": ("深度优先搜索", "掌握DFS的递归与栈实现，练习全排列、子集等经典问题"),
    "bfs": ("广度优先搜索", "掌握BFS的队列实现，练习最短路径、层序遍历等问题"),
    "backtracking": ("回溯", "理解回溯算法的剪枝策略，练习N皇后、组合总和等题目"),
    "greedy": ("贪心", "掌握贪心策略的证明方法，练习区间调度、哈夫曼编码等题目"),
    "divide_conquer": ("分治", "理解分治思想（分解→解决→合并），练习归并排序、快速幂等"),
    "graph_traversal": ("图遍历", "练习DFS/BFS在图中的应用，包括连通分量、拓扑排序等"),
    "shortest_path": ("最短路径", "掌握Dijkstra和Floyd算法，练习单源/多源最短路径问题"),
    "two_pointers": ("双指针", "练习快慢指针、对撞指针技巧，应用于数组和链表问题"),
    "sliding_window": ("滑动窗口", "掌握滑动窗口模板，练习子数组/子串相关题目"),
    "dynamic_programming": ("动态规划", "理解DP的状态定义和转移方程，从背包问题、LCS等经典题目入手"),
    "bit_manipulation": ("位运算", "掌握与或非异或等位运算技巧，练习位运算优化类题目"),
    "math": ("数学", "复习数论基础（素数、GCD、模运算等），练习数学推理类题目"),
    "simulation": ("模拟", "练习按照题意逐步模拟的题目，注意边界条件和效率"),
    "prefix_sum": ("前缀和", "掌握一维/二维前缀和技巧，练习区间求和类题目"),
    "monotonic_stack": ("单调栈", "理解单调栈的应用场景，练习下一个更大元素等经典问题"),
    "union_find": ("并查集", "掌握并查集的查找与合并操作，练习连通性判断类题目"),
    "trie": ("字典树", "理解Trie的插入与查找，练习字符串前缀匹配类题目"),
}


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
    """Generate basic suggestions using rule engine (AI fallback).

    When skillStates are available (from student_skill_state table), identify
    weak knowledge points by mastery score.  Otherwise fall back to error-type
    analysis.
    """
    suggestion_id = f"lrn_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"

    if request.skill_states:
        return _skill_based_suggestions(request, suggestion_id)
    else:
        return _error_based_suggestions(request, suggestion_id)


def _skill_based_suggestions(
    request: LearningSuggestRequest, suggestion_id: str
) -> LearningSuggestData:
    """Generate suggestions driven by real skill mastery data."""

    # Sort by mastery score ascending (weakest first), take top 5
    sorted_skills = sorted(request.skill_states, key=lambda s: s.mastery_score)[:5]

    weak_points: list[WeakPoint] = []
    study_plan: list[StudyPlanItem] = []
    recommended: list[str] = []

    for sk in sorted_skills:
        chinese_name, resource = SKILL_TAG_MAP.get(
            sk.tag_name, (sk.tag_name, "针对性地巩固相关知识")
        )

        # Determine severity from mastery score
        if sk.mastery_score < 30:
            severity = "HIGH"
            reason = f"{chinese_name}掌握度仅{sk.mastery_score:.0f}分，急需系统性学习"
            estimated_time = "1.5小时"
        elif sk.mastery_score < 60:
            severity = "MEDIUM"
            reason = f"{chinese_name}掌握度{sk.mastery_score:.0f}分，需要针对性强化练习"
            estimated_time = "1小时"
        else:
            severity = "LOW"
            reason = f"{chinese_name}掌握度{sk.mastery_score:.0f}分，尚有提升空间"
            estimated_time = "30分钟"

        weak_points.append(
            WeakPoint(tagName=chinese_name, severity=severity, reason=reason)
        )
        study_plan.append(
            StudyPlanItem(
                topic=chinese_name,
                priority=severity,
                suggestedResources=resource,
                estimatedTime=estimated_time,
            )
        )
        recommended.append(f"PTA-{chinese_name}专题练习")

    # Build student-facing summary
    weakest_names = [wp.tag_name for wp in weak_points[:3]]
    weak_str = "、".join(weakest_names) if weakest_names else "薄弱知识点"
    summary = (
        f"根据你的技能掌握度分析，当前薄弱环节为{weak_str}。"
        f"建议按计划逐个攻克，夯实数据结构基础。加油！"
    )

    return LearningSuggestData(
        suggestionId=suggestion_id,
        weakPoints=weak_points,
        studyPlan=study_plan,
        recommendedProblems=recommended,
        summaryMessage=summary,
        aiGenerated=False,
    )


def _error_based_suggestions(
    request: LearningSuggestRequest, suggestion_id: str
) -> LearningSuggestData:
    """Fallback: generate suggestions from error-type distribution only."""

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
        suggestionId=suggestion_id,
        weakPoints=weak_points,
        studyPlan=study_plan,
        recommendedProblems=["PTA同类题目练习", "在线评测平台同类题目"],
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
