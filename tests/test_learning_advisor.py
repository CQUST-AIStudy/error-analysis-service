"""Tests for learning advisor service (rule-based fallback paths)."""

import pytest

from app.schemas.requests import ErrorTypeCount, LearningSuggestRequest, SkillState
from app.services.deepseek_client import DeepSeekClient
from app.services.learning_advisor import _rule_based_suggestions, generate_suggestions


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
def basic_request():
    return LearningSuggestRequest(
        studentId="s1",
        studentName="测试学生",
        errorHistory=[
            ErrorTypeCount(errorType="COMPILE_ERROR", count=5),
            ErrorTypeCount(errorType="RUNTIME_ERROR", count=3),
        ],
        skillStates=[
            SkillState(tagName="指针", masteryScore=35.0, attemptCount=8),
            SkillState(tagName="链表", masteryScore=60.0, attemptCount=5),
        ],
    )


class TestRuleBasedSuggestions:
    def test_returns_valid_suggestion_id(self, basic_request):
        result = _rule_based_suggestions(basic_request)
        assert result.suggestion_id.startswith("lrn_")

    def test_generates_weak_points(self, basic_request):
        result = _rule_based_suggestions(basic_request)
        assert len(result.weak_points) == 2
        assert result.weak_points[0].severity == "HIGH"  # count >= 5

    def test_generates_study_plan(self, basic_request):
        result = _rule_based_suggestions(basic_request)
        assert len(result.study_plan) == 2
        assert result.study_plan[0].priority == "HIGH"

    def test_includes_summary_message(self, basic_request):
        result = _rule_based_suggestions(basic_request)
        assert "加油" in result.summary_message

    def test_recommended_problems(self, basic_request):
        result = _rule_based_suggestions(basic_request)
        assert len(result.recommended_problems) > 0

    def test_fallback_sets_ai_generated_false(self, basic_request):
        result = _rule_based_suggestions(basic_request)
        assert result.ai_generated is False

    def test_without_skill_states(self):
        request = LearningSuggestRequest(
            studentId="s2",
            studentName="无技能数据",
            errorHistory=[ErrorTypeCount(errorType="WRONG_ANSWER", count=2)],
        )
        result = _rule_based_suggestions(request)
        assert len(result.weak_points) == 1
        assert result.weak_points[0].severity == "MEDIUM"


class TestGenerateSuggestions:
    def test_empty_api_key_falls_back(self, basic_request, empty_key_client):
        result = generate_suggestions(basic_request, empty_key_client)
        assert result.suggestion_id.startswith("lrn_")
        assert result.ai_generated is False

    def test_returns_meaningful_content(self, basic_request, empty_key_client):
        result = generate_suggestions(basic_request, empty_key_client)
        assert len(result.weak_points) > 0
        assert len(result.study_plan) > 0
        assert len(result.summary_message) > 0
