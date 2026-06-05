"""Tests for error analyzer service (rule-based fallback paths)."""

import pytest

from app.schemas.requests import ErrorAnalysisRequest, SubmissionRecord
from app.services.deepseek_client import DeepSeekClient
from app.services.error_analyzer import _rule_based_fallback, _truncate_code, analyze_errors


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

    def test_degraded_analysis_via_main_function(self, single_submission_request, empty_key_client):
        result = analyze_errors(single_submission_request, empty_key_client)
        assert result.analysis_id.startswith("err_")
        assert "AI分析暂时不可用" in result.overall_assessment
        assert result.ai_generated is False
