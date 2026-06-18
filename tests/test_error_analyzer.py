"""Tests for error analyzer service (rule-based fallback paths)."""

import pytest

from app.schemas.requests import (
    ErrorAnalysisRequest,
    SkillState,
    SubmissionRecord,
)
from app.services.deepseek_client import DeepSeekClient
from app.services.error_analyzer import (
    _generate_fallback_suggestions,
    _infer_suggestions_from_errors,
    _rule_based_fallback,
    _truncate_code,
    analyze_errors,
)


class FakeSettings:
    deepseek_api_key = "sk-test-key"
    deepseek_base_url = "https://api.deepseek.com/v1"
    deepseek_model = "deepseek-chat"
    request_timeout = 30
    max_code_lines = 3000


class EmptyKeySettings:
    deepseek_api_key = ""
    deepseek_base_url = "https://api.deepseek.com/v1"
    deepseek_model = "deepseek-chat"
    request_timeout = 30
    max_code_lines = 3000


@pytest.fixture
def fake_client():
    return DeepSeekClient(FakeSettings())


@pytest.fixture
def empty_key_client():
    return DeepSeekClient(EmptyKeySettings())


@pytest.fixture
def single_submission_request():
    return ErrorAnalysisRequest(
        studentId="20220101",
        studentName="测试学生",
        experimentId=1,
        experimentName="测试实验",
        problemTitle="测试题",
        submissions=[
            SubmissionRecord(
                attemptNo=1,
                judgeStatus="COMPILE_ERROR",
                compiler="GCC",
                errorMessage="error: 'ListNode' was not declared in this scope",
                code="ListNode* reverse(ListNode* head) { return NULL; }",
                submittedAt="2026-06-03T10:00:00",
            )
        ],
    )


@pytest.fixture
def multi_submission_request():
    submissions = []
    for i in range(6):
        status = "COMPILE_ERROR" if i < 3 else "RUNTIME_ERROR"
        submissions.append(
            SubmissionRecord(
                attemptNo=i + 1,
                judgeStatus=status,
                compiler="GCC",
                errorMessage=f"error #{i + 1}" if i < 3 else "Segmentation fault",
                code=f"int main() {{ /* attempt {i + 1} */ }}",
                submittedAt=f"2026-06-03T{i + 10:02d}:00:00",
            )
        )
    return ErrorAnalysisRequest(
        studentId="20220102",
        studentName="多次提交学生",
        experimentId=1,
        experimentName="测试实验",
        problemTitle="测试题",
        submissions=submissions,
    )


class TestTruncateCode:
    def test_short_code_unchanged(self):
        code = "int main() { return 0; }"
        assert _truncate_code(code, max_lines=10) == code

    def test_empty_code(self):
        assert _truncate_code("") == "(空代码)"

    def test_none_code(self):
        assert _truncate_code(None) == "(空代码)"

    def test_long_code_truncated(self):
        lines = [f"// line {i}" for i in range(100)]
        code = "\n".join(lines)
        result = _truncate_code(code, max_lines=50)
        assert "代码过长" in result
        assert result.split("\n")[0] == "// line 0"


class TestRuleBasedFallback:
    def test_returns_valid_analysis_id(self, single_submission_request):
        result = _rule_based_fallback(single_submission_request)
        assert result.analysis_id.startswith("err_")

    def test_categorizes_compile_errors(self, single_submission_request):
        result = _rule_based_fallback(single_submission_request)
        compile_cats = [c for c in result.error_categories if c.type == "COMPILE_ERROR"]
        assert len(compile_cats) == 1
        assert compile_cats[0].count == 1

    def test_no_intervention_when_under_threshold(self, single_submission_request):
        result = _rule_based_fallback(single_submission_request)
        assert result.intervention_triggered is False
        assert result.severity == "MEDIUM"

    def test_triggers_intervention_with_many_failures(self, multi_submission_request):
        result = _rule_based_fallback(multi_submission_request)
        assert result.intervention_triggered is True
        assert result.severity == "HIGH"

    def test_separates_error_categories(self, multi_submission_request):
        result = _rule_based_fallback(multi_submission_request)
        types = {c.type for c in result.error_categories}
        assert "COMPILE_ERROR" in types
        assert "RUNTIME_ERROR" in types

    def test_mark_systemic_weakness(self, multi_submission_request):
        result = _rule_based_fallback(multi_submission_request)
        compile_cat = next(c for c in result.error_categories if c.type == "COMPILE_ERROR")
        assert compile_cat.is_systemic is True
        assert compile_cat.count == 3

    def test_ignores_accepted(self):
        request = ErrorAnalysisRequest(
            studentId="s1",
            studentName="测试",
            experimentId=1,
            experimentName="测试实验",
            problemTitle="测试题",
            submissions=[
                SubmissionRecord(
                    attemptNo=1,
                    judgeStatus="ACCEPTED",
                    code="int main(){return 0;}",
                )
            ],
        )
        result = _rule_based_fallback(request)
        assert len(result.error_categories) == 0

    def test_fallback_sets_ai_generated_false(self, single_submission_request):
        result = _rule_based_fallback(single_submission_request)
        assert result.ai_generated is False

    def test_latest_code_and_status_returned(self, single_submission_request):
        """latestCode + latestJudgeStatus echo back the submission data."""
        result = _rule_based_fallback(single_submission_request)
        assert result.latest_judge_status == "COMPILE_ERROR"
        assert "reverse" in result.latest_code

    def test_latest_fields_via_main(self, single_submission_request, empty_key_client):
        """AI path also populates latestCode + latestJudgeStatus."""
        result = analyze_errors(single_submission_request, empty_key_client)
        assert result.latest_judge_status == "COMPILE_ERROR"
        assert result.latest_code is not None

    def test_degraded_analysis_via_main_function(self, single_submission_request, empty_key_client):
        result = analyze_errors(single_submission_request, empty_key_client)
        assert result.analysis_id.startswith("err_")
        assert "AI分析暂时不可用" in result.overall_assessment
        assert result.ai_generated is False

    def test_generates_learning_suggestions_without_skill_states(self, single_submission_request):
        """learningSuggestions no longer empty — inferred from error types."""
        result = _rule_based_fallback(single_submission_request)
        assert len(result.learning_suggestions) > 0
        assert result.learning_suggestions[0].topic is not None

    def test_skill_states_field_accepted(self):
        """ErrorAnalysisRequest now accepts skillStates."""
        request = ErrorAnalysisRequest(
            studentId="s1", studentName="测试", experimentId=1,
            experimentName="实验一", problemTitle="题",
            submissions=[SubmissionRecord(
                attemptNo=1, judgeStatus="WRONG_ANSWER", code="int main(){}",
            )],
            skillStates=[
                SkillState(tagName="two_pointers", masteryScore=25.0, attemptCount=12),
            ],
        )
        assert len(request.skill_states) == 1
        assert request.skill_states[0].tag_name == "two_pointers"


class TestFallbackSuggestions:
    """Tests for _generate_fallback_suggestions and _infer_suggestions_from_errors."""

    @pytest.fixture
    def request_with_skills(self):
        return ErrorAnalysisRequest(
            studentId="s1", studentName="测试", experimentId=1,
            experimentName="实验一", problemTitle="题",
            submissions=[SubmissionRecord(
                attemptNo=1, judgeStatus="WRONG_ANSWER", code="int main(){}",
            )],
            skillStates=[
                SkillState(tagName="two_pointers", masteryScore=20.0, attemptCount=12),
                SkillState(tagName="linked_list", masteryScore=50.0, attemptCount=5),
                SkillState(tagName="binary_search", masteryScore=80.0, attemptCount=20),
            ],
        )

    @pytest.fixture
    def request_without_skills(self):
        return ErrorAnalysisRequest(
            studentId="s2", studentName="测试", experimentId=1,
            experimentName="实验一", problemTitle="题",
            submissions=[
                SubmissionRecord(attemptNo=1, judgeStatus="COMPILE_ERROR", code="x"),
                SubmissionRecord(attemptNo=2, judgeStatus="RUNTIME_ERROR", code="y"),
            ],
        )

    def test_uses_skill_states_when_available(self, request_with_skills):
        suggestions = _generate_fallback_suggestions(request_with_skills)
        assert len(suggestions) == 3
        # Weakest first: two_pointers (20) → HIGH
        assert suggestions[0].topic == "双指针"
        assert suggestions[0].priority == "HIGH"
        assert "20" in suggestions[0].reason

    def test_falls_back_to_error_inference(self, request_without_skills):
        suggestions = _generate_fallback_suggestions(request_without_skills)
        assert len(suggestions) > 0
        # Each suggestion should have a valid topic
        for s in suggestions:
            assert len(s.topic) > 0

    def test_infer_from_compile_error(self, request_without_skills):
        suggestions = _infer_suggestions_from_errors(request_without_skills)
        assert len(suggestions) > 0
        # COMPILE_ERROR maps to ["数组", "字符串", "排序"]
        assert any(s.topic in ("数组", "字符串", "排序") for s in suggestions)

    def test_infer_limits_to_3_suggestions(self):
        request = ErrorAnalysisRequest(
            studentId="s3", studentName="测试", experimentId=1,
            experimentName="实验一", problemTitle="题",
            submissions=[
                SubmissionRecord(attemptNo=i, judgeStatus="WRONG_ANSWER", code="x")
                for i in range(1, 6)
            ],
        )
        suggestions = _infer_suggestions_from_errors(request)
        assert len(suggestions) <= 3

    def test_rules_with_skills_produces_real_topics(self, request_with_skills):
        """End-to-end: _rule_based_fallback with skillStates → real Chinese topics."""
        result = _rule_based_fallback(request_with_skills)
        topics = [s.topic for s in result.learning_suggestions]
        assert "双指针" in topics
        assert "链表" in topics
        assert "二分查找" in topics
        # Should NOT contain the old empty list
        assert len(result.learning_suggestions) > 0
