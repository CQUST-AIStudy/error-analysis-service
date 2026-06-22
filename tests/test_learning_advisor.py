"""Tests for learning advisor service (rule-based fallback paths)."""

import pytest

from app.schemas.requests import ErrorTypeCount, LearningSuggestRequest, SkillState
from app.services.deepseek_client import DeepSeekClient
from app.services.learning_advisor import (
    SKILL_TAG_MAP,
    _error_based_suggestions,
    _rule_based_suggestions,
    _skill_based_suggestions,
    generate_suggestions,
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
def basic_request():
    """Request with real skill states (English tag names from DB)."""
    return LearningSuggestRequest(
        studentId="s1",
        studentName="测试学生",
        errorHistory=[
            ErrorTypeCount(errorType="COMPILE_ERROR", count=5),
            ErrorTypeCount(errorType="RUNTIME_ERROR", count=3),
        ],
        skillStates=[
            SkillState(tagName="two_pointers", masteryScore=25.0, attemptCount=12),
            SkillState(tagName="linked_list", masteryScore=55.0, attemptCount=5),
            SkillState(tagName="binary_search", masteryScore=75.0, attemptCount=20),
        ],
    )


class TestRuleBasedSuggestions:
    """Tests for _rule_based_suggestions (dispatcher)."""

    def test_returns_valid_suggestion_id(self, basic_request):
        result = _rule_based_suggestions(basic_request)
        assert result.suggestion_id.startswith("lrn_")

    def test_generates_weak_points(self, basic_request):
        result = _rule_based_suggestions(basic_request)
        assert len(result.weak_points) == 3

    def test_generates_study_plan(self, basic_request):
        result = _rule_based_suggestions(basic_request)
        assert len(result.study_plan) == 3

    def test_includes_summary_message(self, basic_request):
        result = _rule_based_suggestions(basic_request)
        assert "加油" in result.summary_message

    def test_recommended_problems(self, basic_request):
        result = _rule_based_suggestions(basic_request)
        assert len(result.recommended_problems) == 3
        assert any("双指针" in p for p in result.recommended_problems)

    def test_fallback_sets_ai_generated_false(self, basic_request):
        result = _rule_based_suggestions(basic_request)
        assert result.ai_generated is False

    def test_without_skill_states_falls_back_to_error_based(self):
        """Empty skillStates → _error_based_suggestions."""
        request = LearningSuggestRequest(
            studentId="s2",
            studentName="无技能数据",
            errorHistory=[ErrorTypeCount(errorType="WRONG_ANSWER", count=2)],
        )
        result = _rule_based_suggestions(request)
        assert len(result.weak_points) == 1
        assert result.weak_points[0].severity == "MEDIUM"
        # error-based uses generic recommendedProblems
        assert "PTA同类题目练习" in result.recommended_problems


class TestSkillBasedSuggestions:
    """Tests for _skill_based_suggestions (new)."""

    @pytest.fixture
    def skill_request(self):
        return LearningSuggestRequest(
            studentId="s3",
            studentName="技能测试",
            errorHistory=[ErrorTypeCount(errorType="WRONG_ANSWER", count=1)],
            skillStates=[
                SkillState(tagName="array", masteryScore=15.0, attemptCount=3),
                SkillState(tagName="stack", masteryScore=40.0, attemptCount=10),
                SkillState(tagName="heap", masteryScore=65.0, attemptCount=25),
                SkillState(tagName="trie", masteryScore=90.0, attemptCount=50),
            ],
        )

    def test_weakest_first_ordering(self, skill_request):
        """Scores 15, 40, 65, 90 → weakest first."""
        result = _skill_based_suggestions(skill_request, "lrn_test")
        assert result.weak_points[0].tag_name == "数组"  # 15 → HIGH
        assert result.weak_points[3].tag_name == "字典树"  # 90 → LOW

    def test_severity_from_mastery_score(self, skill_request):
        """<30→HIGH, 30-59→MEDIUM, >=60→LOW."""
        result = _skill_based_suggestions(skill_request, "lrn_test")
        assert result.weak_points[0].severity == "HIGH"    # 15
        assert result.weak_points[1].severity == "MEDIUM"   # 40
        assert result.weak_points[2].severity == "LOW"      # 65
        assert result.weak_points[3].severity == "LOW"      # 90

    def test_chinese_names_in_output(self, skill_request):
        """Skill tags are translated to Chinese display names."""
        result = _skill_based_suggestions(skill_request, "lrn_test")
        names = [wp.tag_name for wp in result.weak_points]
        assert "数组" in names
        assert "栈" in names
        assert "堆" in names
        assert "字典树" in names

    def test_skill_specific_resources(self, skill_request):
        """Each weak skill gets a targeted learning resource."""
        result = _skill_based_suggestions(skill_request, "lrn_test")
        for item in result.study_plan:
            assert item.suggested_resources is not None
            assert len(item.suggested_resources) > 10  # non-trivial resource

    def test_recommended_problems_from_skills(self, skill_request):
        """Recommended problems mention actual weak skills."""
        result = _skill_based_suggestions(skill_request, "lrn_test")
        assert len(result.recommended_problems) == 4
        assert "PTA-数组专题练习" in result.recommended_problems
        assert "PTA-栈专题练习" in result.recommended_problems

    def test_summary_mentions_weak_skills(self, skill_request):
        """Summary message names the weakest skill areas."""
        result = _skill_based_suggestions(skill_request, "lrn_test")
        assert "数组" in result.summary_message
        assert "栈" in result.summary_message

    def test_top_5_limit(self):
        """Only the 5 weakest skills are included."""
        request = LearningSuggestRequest(
            studentId="s4",
            studentName="大量技能",
            errorHistory=[ErrorTypeCount(errorType="WRONG_ANSWER", count=1)],
            skillStates=[
                SkillState(tagName=tag, masteryScore=float(i), attemptCount=1)
                for i, tag in enumerate([
                    "array", "linked_list", "stack", "queue", "tree",
                    "heap", "graph", "sorting",
                ])
            ],
        )
        result = _skill_based_suggestions(request, "lrn_test")
        assert len(result.weak_points) == 5  # capped at 5

    def test_unknown_skill_tag_fallback(self):
        """Tag not in SKILL_TAG_MAP uses raw tag name."""
        request = LearningSuggestRequest(
            studentId="s5",
            studentName="未知标签",
            errorHistory=[ErrorTypeCount(errorType="WRONG_ANSWER", count=1)],
            skillStates=[
                SkillState(tagName="quantum_computing", masteryScore=10.0, attemptCount=1),
            ],
        )
        result = _skill_based_suggestions(request, "lrn_test")
        # Falls back to raw tag name
        assert result.weak_points[0].tag_name == "quantum_computing"


class TestErrorBasedSuggestions:
    """Tests for _error_based_suggestions (preserved fallback)."""

    @pytest.fixture
    def error_request(self):
        return LearningSuggestRequest(
            studentId="s6",
            studentName="错误测试",
            errorHistory=[
                ErrorTypeCount(errorType="COMPILE_ERROR", count=6),
                ErrorTypeCount(errorType="WRONG_ANSWER", count=3),
                ErrorTypeCount(errorType="TIME_LIMIT_EXCEEDED", count=1),
            ],
        )

    def test_generic_recommended_problems(self, error_request):
        result = _error_based_suggestions(error_request, "lrn_test")
        assert "PTA同类题目练习" in result.recommended_problems
        assert "教材课后习题" in result.recommended_problems

    def test_error_type_to_chinese_label(self, error_request):
        result = _error_based_suggestions(error_request, "lrn_test")
        assert result.weak_points[0].tag_name == "基础语法"  # COMPILE_ERROR
        assert result.weak_points[1].tag_name == "算法逻辑"  # WRONG_ANSWER

    def test_top_3_error_types(self, error_request):
        result = _error_based_suggestions(error_request, "lrn_test")
        assert len(result.weak_points) == 3

    def test_severity_from_error_count(self, error_request):
        result = _error_based_suggestions(error_request, "lrn_test")
        assert result.weak_points[0].severity == "HIGH"   # count=6 >= 5
        assert result.weak_points[1].severity == "MEDIUM"  # count=3


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


class TestSkillTagMap:
    """Verify SKILL_TAG_MAP integrity."""

    def test_all_30_tags_present(self):
        """Ensure the complete set of 30 skill tags is mapped."""
        expected_tags = {
            "array", "linked_list", "stack", "queue", "tree",
            "binary_tree", "heap", "hash_table", "graph", "string",
            "sorting", "searching", "binary_search", "dfs", "bfs",
            "backtracking", "greedy", "divide_conquer", "graph_traversal",
            "shortest_path", "two_pointers", "sliding_window",
            "dynamic_programming", "bit_manipulation", "math",
            "simulation", "prefix_sum", "monotonic_stack", "union_find", "trie",
        }
        assert set(SKILL_TAG_MAP.keys()) == expected_tags

    def test_each_tag_has_chinese_name_and_resource(self):
        """Every entry must be (chinese_name, resource_string)."""
        for _tag, (name, resource) in SKILL_TAG_MAP.items():
            assert isinstance(name, str) and len(name) > 0
            assert isinstance(resource, str) and len(resource) > 10
