"""Tests for warning detector service (single student mode)."""

import pytest

from app.schemas.requests import WarningAnalyzeRequest, WarningResult
from app.services.deepseek_client import DeepSeekClient
from app.services.warning_detector import _needs_ai_analysis, _rule_based_warning, analyze_warning


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


def make_request(
    sid: str = "s1",
    total: int = 0,
    ac: int = 0,
    total_problems: int = 5,
    compile_err: int = 0,
    runtime_err: int = 0,
    wrong: int = 0,
    tle: int = 0,
) -> WarningAnalyzeRequest:
    return WarningAnalyzeRequest(
        studentId=sid,
        studentName=f"学生{sid}",
        experimentId=1,
        experimentName="测试实验",
        totalSubmissions=total,
        acceptedCount=ac,
        totalProblems=total_problems,
        compileErrors=compile_err,
        runtimeErrors=runtime_err,
        wrongAnswers=wrong,
        timeLimitExceeded=tle,
        lastSubmissionAt="2026-06-03T10:00:00",
    )


class TestNeedsAiAnalysis:
    def test_zero_submissions_skipped(self):
        r = make_request(total=0)
        assert _needs_ai_analysis(r) is False

    def test_all_problems_accepted_skipped(self):
        r = make_request(total=5, ac=5, total_problems=5)
        assert _needs_ai_analysis(r) is False

    def test_some_failures_needs_ai(self):
        r = make_request(total=5, ac=2, total_problems=5, compile_err=2, wrong=1)
        assert _needs_ai_analysis(r) is True


class TestRuleBasedWarning:
    def test_high_frequent_failure(self):
        r = make_request(total=10, ac=0, total_problems=5, compile_err=3, runtime_err=2, wrong=5)
        w = _rule_based_warning(r)
        assert w.level == "HIGH"
        assert w.warning_type == "FREQUENT_FAILURE"
        assert w.triggered is True
        assert w.auto_notify is True

    def test_medium_basic_syntax(self):
        r = make_request(total=10, ac=5, total_problems=5, compile_err=5)
        w = _rule_based_warning(r)
        assert w.level == "MEDIUM"
        assert w.warning_type == "BASIC_SYNTAX"

    def test_ok_when_good(self):
        r = make_request(total=3, ac=3, total_problems=5, compile_err=0)
        w = _rule_based_warning(r)
        assert w.level == "OK"
        assert w.triggered is False
        assert w.auto_notify is False

    def test_teacher_note_only_when_triggered(self):
        r = make_request(total=3, ac=3, total_problems=5)
        w = _rule_based_warning(r)
        assert w.teacher_note is None

    def test_fallback_sets_ai_generated_false(self):
        r = make_request(total=10, ac=0, total_problems=5, compile_err=3, runtime_err=2, wrong=5)
        w = _rule_based_warning(r)
        assert w.ai_generated is False


class TestAnalyzeWarning:
    def test_empty_api_key_falls_back(self, empty_key_client):
        r = make_request(total=10, ac=0, total_problems=5, compile_err=3, runtime_err=2, wrong=5)
        result = analyze_warning(r, empty_key_client)
        assert isinstance(result, WarningResult)
        assert result.student_id == "s1"
        assert result.level == "HIGH"
        assert result.ai_generated is False

    def test_all_accepted_returns_ok(self, empty_key_client):
        r = make_request(total=5, ac=5, total_problems=5)
        result = analyze_warning(r, empty_key_client)
        assert result.level == "OK"
        assert result.triggered is False

    def test_medium_stuck(self, empty_key_client):
        r = make_request(total=10, ac=4, total_problems=5, compile_err=0, runtime_err=4, wrong=2)
        result = analyze_warning(r, empty_key_client)
        assert result.level == "MEDIUM"
        assert result.warning_type == "STUCK"
