"""Request/response models for error-analysis-service.

Three internal API endpoints called by the Java backend:
  POST /analyze/error     — AI error code analysis
  POST /analyze/warning   — AI proactive intervention
  POST /analyze/learning  — AI learning suggestion generation
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ── Shared config ────────────────────────────────────────


class BaseSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", str_strip_whitespace=True)


# ── Shared types ─────────────────────────────────────────

SeverityLevel = Literal["HIGH", "MEDIUM", "LOW"]
WarningType = Literal["FREQUENT_FAILURE", "BASIC_SYNTAX", "STUCK", "DEADLINE_RISK", "OK"]

# ── POST /analyze/error ──────────────────────────────────


class SubmissionRecord(BaseSchema):
    """A single PTA submission attempt."""

    attempt_no: int = Field(
        ...,
        alias="attemptNo",
        ge=1,
        description="Attempt sequence number (1-based)",
    )
    judge_status: str = Field(
        ...,
        alias="judgeStatus",
        description="PTA judge status: COMPILE_ERROR, RUNTIME_ERROR, TIME_LIMIT_EXCEEDED, "
        "WRONG_ANSWER, MEMORY_LIMIT_EXCEEDED, ACCEPTED, etc.",
    )
    compiler: str | None = Field(None, description="Compiler used, e.g. GCC, G++")
    error_message: str | None = Field(
        None,
        alias="errorMessage",
        description="Compiler/runtime error output text",
    )
    code: str = Field(..., description="Student's submitted C/C++ source code")
    submitted_at: str | None = Field(
        None,
        alias="submittedAt",
        description="ISO-8601 submission timestamp",
    )


class ErrorAnalysisRequest(BaseSchema):
    """Request for AI error code analysis."""

    student_id: str = Field(
        ...,
        alias="studentId",
        min_length=1,
        max_length=64,
        description="Student ID / student_no",
    )
    student_name: str = Field(
        ...,
        alias="studentName",
        min_length=1,
        max_length=128,
        description="Student display name",
    )
    experiment_id: int = Field(
        ...,
        alias="experimentId",
        ge=1,
        description="Experiment / assignment_offering ID",
    )
    experiment_name: str = Field(
        ...,
        alias="experimentName",
        min_length=1,
        max_length=256,
        description="Experiment display name",
    )
    problem_title: str = Field(
        ...,
        alias="problemTitle",
        min_length=1,
        max_length=256,
        description="Problem title / label",
    )
    problem_description: str | None = Field(
        None,
        alias="problemDescription",
        description="Problem statement for AI context",
    )
    submissions: list[SubmissionRecord] = Field(
        ...,
        min_length=1,
        description="Submission history for this student on this problem",
    )


class ErrorCategory(BaseSchema):
    """A single error category identified by AI."""

    type: str = Field(
        ...,
        description="Error type: COMPILE_ERROR, RUNTIME_ERROR, TIME_LIMIT_EXCEEDED, "
        "WRONG_ANSWER, MEMORY_LIMIT_EXCEEDED",
    )
    count: int = Field(..., ge=1, description="Number of occurrences")
    root_cause: str = Field(
        ...,
        alias="rootCause",
        description="AI-identified root cause in Chinese",
    )
    specific_issues: list[str] = Field(
        default_factory=list,
        alias="specificIssues",
        description="Specific sub-issues found",
    )
    suggestions: list[str] = Field(
        default_factory=list,
        description="Actionable suggestions for this error type",
    )
    is_systemic: bool = Field(
        default=False,
        alias="isSystemic",
        description="True if this error recurred systematically (>= 3 times)",
    )


class LearningSuggestion(BaseSchema):
    """A targeted learning recommendation."""

    topic: str = Field(..., description="Knowledge point or topic to review")
    priority: SeverityLevel = Field(
        default="MEDIUM",
        description="Recommendation priority",
    )
    reason: str = Field(..., description="Why this suggestion is being made")
    suggested_resources: str | None = Field(
        None,
        alias="suggestedResources",
        description="Recommended textbook chapter or resource",
    )


class ErrorAnalysisData(BaseSchema):
    """Response payload for /analyze/error."""

    analysis_id: str = Field(
        ...,
        alias="analysisId",
        description="Unique analysis run ID, format: err_YYYYMMDD_hex8",
    )
    overall_assessment: str = Field(
        ...,
        alias="overallAssessment",
        description="Overall evaluation summary in Chinese",
    )
    error_categories: list[ErrorCategory] = Field(
        default_factory=list,
        alias="errorCategories",
    )
    learning_suggestions: list[LearningSuggestion] = Field(
        default_factory=list,
        alias="learningSuggestions",
    )
    intervention_triggered: bool = Field(
        default=False,
        alias="interventionTriggered",
        description="Whether active teaching intervention is needed",
    )
    intervention_message: str | None = Field(
        None,
        alias="interventionMessage",
        description="Student-facing intervention message (mild, encouraging tone)",
    )
    severity: SeverityLevel = Field(
        default="LOW",
        description="Overall severity level",
    )
    ai_generated: bool = Field(
        default=True,
        alias="aiGenerated",
        description="True if AI produced this analysis; false = rule-engine fallback",
    )


# ── POST /analyze/warning ────────────────────────────────


class WarningAnalyzeRequest(BaseSchema):
    """Request for AI proactive intervention detection (single student)."""

    student_id: str = Field(
        ...,
        alias="studentId",
        min_length=1,
        max_length=64,
        description="Student ID / student_no",
    )
    student_name: str = Field(
        ...,
        alias="studentName",
        min_length=1,
        max_length=128,
        description="Student display name",
    )
    experiment_id: int = Field(
        ...,
        alias="experimentId",
        ge=1,
        description="Experiment / assignment_offering ID",
    )
    experiment_name: str = Field(
        ...,
        alias="experimentName",
        min_length=1,
        max_length=256,
        description="Experiment display name",
    )
    deadline: str | None = Field(
        None,
        description="Experiment deadline (ISO-8601), used for DEADLINE_RISK detection",
    )
    total_submissions: int = Field(
        ...,
        alias="totalSubmissions",
        ge=0,
        description="Total submission count across all problems in this experiment",
    )
    accepted_count: int = Field(
        ...,
        alias="acceptedCount",
        ge=0,
        description="Number of problems with ACCEPTED status",
    )
    total_problems: int = Field(
        ...,
        alias="totalProblems",
        ge=1,
        description="Total number of problems in this experiment",
    )
    compile_errors: int = Field(
        0,
        alias="compileErrors",
        ge=0,
        description="Count of COMPILE_ERROR submissions",
    )
    runtime_errors: int = Field(
        0,
        alias="runtimeErrors",
        ge=0,
        description="Count of RUNTIME_ERROR submissions",
    )
    wrong_answers: int = Field(
        0,
        alias="wrongAnswers",
        ge=0,
        description="Count of WRONG_ANSWER submissions",
    )
    time_limit_exceeded: int = Field(
        0,
        alias="timeLimitExceeded",
        ge=0,
        description="Count of TIME_LIMIT_EXCEEDED submissions",
    )
    last_submission_at: str = Field(
        ...,
        alias="lastSubmissionAt",
        description="ISO-8601 timestamp of most recent submission",
    )


class WarningResult(BaseSchema):
    """Warning detection result for a single student."""

    student_id: str = Field(
        ...,
        alias="studentId",
        description="Student ID",
    )
    level: Literal["HIGH", "MEDIUM", "LOW", "OK"] = Field(
        ...,
        description="Warning severity level",
    )
    triggered: bool = Field(
        ...,
        description="Whether this warning is active (requires attention)",
    )
    warning_type: WarningType = Field(
        ...,
        alias="warningType",
    )
    warning_message: str = Field(
        ...,
        alias="warningMessage",
        description="Student-facing message (mild, encouraging tone, Chinese)",
    )
    teacher_note: str | None = Field(
        None,
        alias="teacherNote",
        description="Teacher-facing analysis note with actionable details",
    )
    suggested_actions: list[str] = Field(
        default_factory=list,
        alias="suggestedActions",
        description="Concrete steps the teacher can take",
    )
    auto_notify: bool = Field(
        default=False,
        alias="autoNotify",
        description="Whether the platform should auto-send a notification to this student",
    )
    ai_generated: bool = Field(
        default=True,
        alias="aiGenerated",
        description="True if AI produced this result; false = rule-engine fallback",
    )


# ── POST /analyze/learning ───────────────────────────────


class ErrorTypeCount(BaseSchema):
    """Error type distribution entry."""

    error_type: str = Field(
        ...,
        alias="errorType",
        description="Error type: COMPILE_ERROR, RUNTIME_ERROR, WRONG_ANSWER, etc.",
    )
    count: int = Field(..., ge=1, description="Number of occurrences")


class SkillState(BaseSchema):
    """Student skill mastery state from student_skill_state table."""

    tag_name: str = Field(
        ...,
        alias="tagName",
        description="Skill tag name, e.g. '指针', '链表', '递归'",
    )
    mastery_score: float = Field(
        ...,
        alias="masteryScore",
        ge=0.0,
        le=100.0,
        description="Mastery score (0-100)",
    )
    attempt_count: int = Field(
        0,
        alias="attemptCount",
        ge=0,
        description="Total practice attempts for this skill",
    )


class LearningSuggestRequest(BaseSchema):
    """Request for AI learning suggestion generation."""

    student_id: str = Field(
        ...,
        alias="studentId",
        min_length=1,
        max_length=64,
        description="Student ID / student_no",
    )
    student_name: str = Field(
        ...,
        alias="studentName",
        min_length=1,
        max_length=128,
        description="Student display name",
    )
    error_history: list[ErrorTypeCount] = Field(
        ...,
        alias="errorHistory",
        min_length=1,
        description="Error type distribution for this student",
    )
    skill_states: list[SkillState] = Field(
        default_factory=list,
        alias="skillStates",
        description="Current skill mastery states (from student_skill_state table)",
    )
    previous_remark: str | None = Field(
        None,
        alias="previousRemark",
        description="Previous AI remark text for progressive analysis",
    )


class WeakPoint(BaseSchema):
    """A student knowledge weakness identified by AI."""

    tag_name: str = Field(
        ...,
        alias="tagName",
        description="Weak knowledge point, e.g. '指针', '边界条件'",
    )
    severity: SeverityLevel = Field(
        ...,
        description="Weakness severity",
    )
    reason: str = Field(
        ...,
        description="Why this is identified as a weak point",
    )


class StudyPlanItem(BaseSchema):
    """A single item in the personalized study plan."""

    topic: str = Field(
        ...,
        description="Topic or knowledge point to study",
    )
    priority: SeverityLevel = Field(
        default="MEDIUM",
        description="Study priority",
    )
    suggested_resources: str | None = Field(
        None,
        alias="suggestedResources",
        description="Recommended resources (textbook, video, exercise)",
    )
    estimated_time: str | None = Field(
        None,
        alias="estimatedTime",
        description="Estimated study time, e.g. '30分钟', '2小时'",
    )


class LearningSuggestData(BaseSchema):
    """Response payload for /analyze/learning."""

    suggestion_id: str = Field(
        ...,
        alias="suggestionId",
        description="Unique suggestion run ID, format: lrn_YYYYMMDD_hex8",
    )
    weak_points: list[WeakPoint] = Field(
        default_factory=list,
        alias="weakPoints",
        description="Identified knowledge weaknesses",
    )
    study_plan: list[StudyPlanItem] = Field(
        default_factory=list,
        alias="studyPlan",
        description="Personalized study plan",
    )
    recommended_problems: list[str] | None = Field(
        None,
        alias="recommendedProblems",
        description="Recommended problem directions",
    )
    summary_message: str = Field(
        ...,
        alias="summaryMessage",
        description="Student-facing summary and encouragement message",
    )
    ai_generated: bool = Field(
        default=True,
        alias="aiGenerated",
        description="True if AI produced this; false = rule-engine fallback",
    )
