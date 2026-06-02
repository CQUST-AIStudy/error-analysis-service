"""Tests for warning detector service."""

import pytest

from app.schemas.requests import StudentWarningInput, WarningAnalysisData, WarningAnalyzeRequest
from app.services.deepseek_client import DeepSeekClient
from app.services.warning_detector import _needs_ai_analysis, _rule_based_warning, analyze_warnings


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


def make_student(sid: str, total: int, ac: int, compile_err: int, runtime_err: int, wrong: int, tle: int = 0):
    return StudentWarningInput(
        studentId=sid,
        studentName=f"学生{sid}",
        totalSubmissions=total,
        acceptedCount=ac,
        compileErrors=compile_err,
        runtimeErrors=runtime_err,
        wrongAnswers=wrong,
        timeLimitExceeded=tle,
    )


class TestNeedsAiAnalysis:
    def test_zero_submissions_skipped(self):
        s = make_student("s1", 0, 0, 0, 0, 0)
        assert _needs_ai_analysis(s) is False

    def test_all_accepted_skipped(self):
        s = make_student("s1", 3, 3, 0, 0, 0)
        assert _needs_ai_analysis(s) is False

    def test_some_failures_needs_ai(self):
        s = make_student("s1", 3, 1, 2, 0, 0)
        assert _needs_ai_analysis(s) is True


class TestRuleBasedWarning:
    def test_high_frequent_failure(self):
        s = make_student("s1", 10, 1, 3, 2, 4)
        w = _rule_based_warning(s)
        assert w.level == "HIGH"
        assert w.warning_type == "FREQUENT_FAILURE"
        assert w.triggered is True
        assert w.auto_notify is True

    def test_medium_basic_syntax(self):
        s = make_student("s1", 10, 5, 5, 0, 0)
        w = _rule_based_warning(s)
        assert w.level == "MEDIUM"
        assert w.warning_type == "BASIC_SYNTAX"

    def test_ok_when_good(self):
        s = make_student("s1", 3, 3, 0, 0, 0)
        w = _rule_based_warning(s)
        assert w.level == "OK"
        assert w.triggered is False
        assert w.auto_notify is False

    def test_teacher_note_only_when_triggered(self):
        s = make_student("s1", 3, 3, 0, 0, 0)
        w = _rule_based_warning(s)
        assert w.teacher_note is None


class TestAnalyzeWarnings:
    def test_empty_api_key_falls_back(self, empty_key_client):
        students = [
            make_student("s1", 10, 1, 3, 2, 4),
            make_student("s2", 3, 3, 0, 0, 0),
        ]
        request = WarningAnalyzeRequest(
            classId=1,
            experimentId=1,
            experimentName="测试实验",
            students=students,
        )
        result = analyze_warnings(request, empty_key_client)
        assert isinstance(result, WarningAnalysisData)
        assert len(result.warnings) == 2
        by_id = {w.student_id: w for w in result.warnings}
        assert by_id["s1"].level == "HIGH"
        assert by_id["s2"].level == "OK"

    def test_sort_order_triggered_first(self, empty_key_client):
        students = [
            make_student("s_ok", 3, 3, 0, 0, 0),
            make_student("s_high", 10, 1, 3, 2, 4),
            make_student("s_med", 10, 5, 5, 0, 0),
        ]
        request = WarningAnalyzeRequest(
            classId=1,
            experimentId=1,
            students=students,
        )
        result = analyze_warnings(request, empty_key_client)
        assert result.warnings[0].triggered is True
