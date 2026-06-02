"""Tests for experiment analyzer service."""

import pytest

from app.schemas.requests import ExperimentAnalyzeRequest, ExperimentErrorStats
from app.services.deepseek_client import DeepSeekClient
from app.services.experiment_analyzer import _rule_based_experiment_analysis, analyze_experiment


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
    return ExperimentAnalyzeRequest(
        experimentId=1,
        experimentName="测试实验",
        classId=1,
        totalStudents=60,
        completed=45,
        inProgress=10,
        notStarted=5,
        avgSubmissions=6.3,
        avgPassRate=0.72,
        commonErrors=[
            ExperimentErrorStats(type="COMPILE_ERROR", count=45, percentage=35.0),
            ExperimentErrorStats(type="RUNTIME_ERROR", count=32, percentage=25.0),
        ],
        problemStats=[
            {"label": "1-1 链表反转", "avgSubmissions": 8.2, "passRate": 0.34},
            {"label": "1-2 栈实现", "avgSubmissions": 3.1, "passRate": 0.85},
        ],
    )


class TestRuleBasedExperimentAnalysis:
    def test_good_completion(self):
        request = ExperimentAnalyzeRequest(
            experimentId=1,
            experimentName="测试",
            totalStudents=60,
            completed=50,
            inProgress=8,
            notStarted=2,
            avgPassRate=0.85,
            commonErrors=[],
            problemStats=[],
        )
        result = _rule_based_experiment_analysis(request)
        assert "良好" in result.completion_assessment

    def test_low_completion(self):
        request = ExperimentAnalyzeRequest(
            experimentId=1,
            experimentName="测试",
            totalStudents=60,
            completed=15,
            inProgress=20,
            notStarted=25,
            avgPassRate=0.3,
            commonErrors=[],
            problemStats=[],
        )
        result = _rule_based_experiment_analysis(request)
        assert "偏低" in result.completion_assessment

    def test_finds_hardest_problem(self, basic_request):
        result = _rule_based_experiment_analysis(basic_request)
        assert result.difficulty_analysis is not None
        assert result.difficulty_analysis["hardestProblem"] == "1-1 链表反转"

    def test_generates_suggestions(self, basic_request):
        result = _rule_based_experiment_analysis(basic_request)
        assert len(result.teaching_suggestions) > 0

    def test_main_function_with_empty_key(self, basic_request, empty_key_client):
        result = analyze_experiment(basic_request, empty_key_client)
        assert result.completion_assessment
        assert len(result.teaching_suggestions) > 0
