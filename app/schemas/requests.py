"""Request/response models for error-analysis-service.

Defines the API contract between this service and the Java backend.
Aligned with Postman collection: 智能实验辅助系统.postman.json
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ── Shared ──────────────────────────────────────────────


class SubmissionRecord(BaseModel):
    """A single PTA submission attempt."""

    attempt_no: int = Field(..., alias="attemptNo", ge=1, description="Attempt number (1-based)")
    judge_status: str = Field(
        ...,
        alias="judgeStatus",
        description="PTA judge status: COMPILE_ERROR, RUNTIME_ERROR, TIME_LIMIT_EXCEEDED, WRONG_ANSWER, ACCEPTED, etc.",
    )
    compiler: str | None = Field(None, description="Compiler used, e.g. GCC, G++")
    error_message: str | None = Field(None, alias="errorMessage", description="Compiler/runtime error output text")
    code: str = Field(..., description="Student's submitted C/C++ source code")
    runtime_ms: int | None = Field(None, alias="runtimeMs", description="Execution time in ms")
    memory_kb: int | None = Field(None, alias="memoryKb", description="Memory usage in KB")
    submitted_at: str | None = Field(None, alias="submittedAt", description="ISO-8601 submission timestamp")


# ── POST /ai/error/analyze ─────────────────────────────


class ErrorAnalysisRequest(BaseModel):
    student_id: str = Field(..., alias="studentId", min_length=1, description="Student ID / student number")
    student_name: str | None = Field(None, alias="studentName", description="Student display name")
    experiment_id: int = Field(..., alias="experimentId", ge=1, description="Experiment ID")
    experiment_name: str | None = Field(None, alias="experimentName", description="Experiment display name")
    problem_title: str | None = Field(None, alias="problemTitle", description="Problem title / label")
    problem_description: str | None = Field(
        None, alias="problemDescription", description="Problem statement (for context)"
    )
    submissions: list[SubmissionRecord] = Field(..., min_length=1, description="Submission history for analysis")


class ErrorCategory(BaseModel):
    type: str = Field(..., description="Error type: COMPILE_ERROR, RUNTIME_ERROR, TIME_LIMIT_EXCEEDED, WRONG_ANSWER")
    count: int = Field(..., ge=1, description="Number of occurrences")
    root_cause: str = Field(..., alias="rootCause", description="AI-identified root cause (Chinese)")
    specific_issues: list[str] = Field(default_factory=list, alias="specificIssues", description="Specific sub-issues")
    suggestions: list[str] = Field(default_factory=list, description="Actionable suggestions per error type")
    is_systemic: bool = Field(False, alias="isSystemic", description="Whether this error category is a systemic weakness")


class LearningSuggestion(BaseModel):
    topic: str = Field(..., description="Topic / knowledge point to review")
    priority: str = Field("MEDIUM", description="HIGH | MEDIUM | LOW")
    reason: str = Field(..., description="Why this suggestion is made")
    suggested_resources: str | None = Field(None, alias="suggestedResources", description="Textbook chapter or resource")


class ErrorAnalysisData(BaseModel):
    analysis_id: str = Field(..., alias="analysisId", description="Unique analysis run ID")
    overall_assessment: str = Field(..., alias="overallAssessment", description="Overall evaluation (50-150 chars, Chinese)")
    error_pattern: str | None = Field(None, alias="errorPattern", description="Error evolution pattern description")
    error_categories: list[ErrorCategory] = Field(default_factory=list, alias="errorCategories")
    learning_suggestions: list[LearningSuggestion] = Field(default_factory=list, alias="learningSuggestions")
    intervention_triggered: bool = Field(False, alias="interventionTriggered", description="Whether active intervention is needed")
    intervention_message: str | None = Field(None, alias="interventionMessage", description="Student-facing intervention message")
    severity: str = Field("LOW", description="HIGH | MEDIUM | LOW")


class ErrorAnalysisResponse(BaseModel):
    code: int = 200
    message: str = "success"
    data: ErrorAnalysisData | None = None


# ── POST /ai/warning/analyze ────────────────────────────


class StudentWarningInput(BaseModel):
    student_id: str = Field(..., alias="studentId", min_length=1, description="Student ID")
    student_name: str | None = Field(None, alias="studentName")
    total_submissions: int = Field(0, alias="totalSubmissions", ge=0)
    accepted_count: int = Field(0, alias="acceptedCount", ge=0)
    compile_errors: int = Field(0, alias="compileErrors", ge=0)
    runtime_errors: int = Field(0, alias="runtimeErrors", ge=0)
    wrong_answers: int = Field(0, alias="wrongAnswers", ge=0)
    time_limit_exceeded: int = Field(0, alias="timeLimitExceeded", ge=0)
    last_submission_at: str | None = Field(None, alias="lastSubmissionAt")


class WarningAnalyzeRequest(BaseModel):
    class_id: int = Field(..., alias="classId", ge=1, description="Teaching class ID")
    experiment_id: int = Field(..., alias="experimentId", ge=1, description="Experiment ID")
    experiment_name: str | None = Field(None, alias="experimentName")
    deadline: str | None = Field(None, description="Experiment deadline (ISO-8601)")
    students: list[StudentWarningInput] = Field(..., min_length=1, description="Students to analyze")


class StudentWarning(BaseModel):
    student_id: str = Field(..., alias="studentId")
    level: str = Field(..., description="HIGH | MEDIUM | LOW")
    triggered: bool = Field(..., description="Whether warning is triggered")
    warning_type: str = Field(..., alias="warningType", description="FREQUENT_FAILURE | BASIC_SYNTAX | STUCK | DEADLINE_RISK | OK")
    warning_message: str = Field(..., alias="warningMessage", description="Student-facing message (≤50 chars, Chinese)")
    teacher_note: str | None = Field(None, alias="teacherNote", description="Teacher-facing analysis note")
    suggested_actions: list[str] = Field(default_factory=list, alias="suggestedActions")
    auto_notify: bool = Field(False, alias="autoNotify")


class WarningAnalysisData(BaseModel):
    warnings: list[StudentWarning] = Field(default_factory=list)
    class_summary: str | None = Field(None, alias="classSummary", description="Overall class-level analysis (50-100 chars)")


class WarningAnalysisResponse(BaseModel):
    code: int = 200
    message: str = "success"
    data: WarningAnalysisData | None = None


# ── POST /ai/experiment/analyze ─────────────────────────


class ExperimentErrorStats(BaseModel):
    type: str = Field(..., description="Error type")
    count: int = Field(..., ge=0)
    percentage: float | None = Field(None, ge=0, le=100)


class ExperimentAnalyzeRequest(BaseModel):
    experiment_id: int = Field(..., alias="experimentId", ge=1)
    experiment_name: str | None = Field(None, alias="experimentName")
    class_id: int | None = Field(None, alias="classId", ge=1)
    total_students: int = Field(0, alias="totalStudents", ge=0)
    completed: int = Field(0, ge=0)
    in_progress: int = Field(0, alias="inProgress", ge=0)
    not_started: int = Field(0, alias="notStarted", ge=0)
    avg_submissions: float | None = Field(None, alias="avgSubmissions", ge=0)
    avg_pass_rate: float | None = Field(None, alias="avgPassRate", ge=0, le=1)
    common_errors: list[ExperimentErrorStats] = Field(default_factory=list, alias="commonErrors")
    problem_stats: list[dict[str, Any]] = Field(default_factory=list, alias="problemStats", description="Per-problem stats")


class ExperimentAnalysisData(BaseModel):
    completion_assessment: str = Field(..., alias="completionAssessment", description="Completion quality evaluation")
    difficulty_analysis: dict[str, Any] | None = Field(None, alias="difficultyAnalysis")
    common_error_analysis: str | None = Field(None, alias="commonErrorAnalysis", description="Common error pattern analysis")
    teaching_suggestions: list[str] = Field(default_factory=list, alias="teachingSuggestions")
    risk_students: list[str] | None = Field(None, alias="riskStudents", description="Student IDs needing attention")


class ExperimentAnalysisResponse(BaseModel):
    code: int = 200
    message: str = "success"
    data: ExperimentAnalysisData | None = None
