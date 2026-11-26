from datetime import datetime
from typing import Optional, List, Any, Dict
from pydantic import BaseModel, computed_field, model_validator


class CallAccepted(BaseModel):
    call_id: str
    status: str
    # True when this exact recording was already uploaded: call_id is the existing call, nothing new was made.
    duplicate: bool = False


class CallSummary(BaseModel):
    id: str
    status: str
    agent_name: Optional[str] = None
    duration_seconds: Optional[int] = None
    call_date: Optional[datetime] = None
    overall_qa_score: Optional[float] = None
    compliance_violation_count: int = 0
    risk_level: Optional[str] = None
    original_filename: str
    category: Optional[str] = None
    health_score: Optional[float] = None
    labels: List[str] = []
    failure_reason: Optional[str] = None
    processing_duration_seconds: Optional[float] = None
    manual_reviewed: bool = False
    manual_qa_score: Optional[float] = None
    violation_severities: Dict[str, int] = {}
    failure_category: Optional[str] = None
    failure_label: Optional[str] = None
    failure_advice: Optional[str] = None
    failure_retryable: Optional[bool] = None

    class Config:
        from_attributes = True


class CallListResponse(BaseModel):
    items: List[CallSummary]
    total: int
    page: int
    page_size: int


class TranscriptSegmentOut(BaseModel):
    sequence: int
    speaker_role: str
    start_time: float
    end_time: float
    text: str
    stt_confidence: float

    class Config:
        from_attributes = True


class TranscriptOut(BaseModel):
    call_id: str
    pii_masked: bool
    segments: List[TranscriptSegmentOut]


class QACriterionOut(BaseModel):
    criterion: str
    score: float
    explanation: Optional[str]
    timestamp_ref: Optional[float]
    transcript_evidence: Optional[str]
    confidence: float

    class Config:
        from_attributes = True


class QAEvaluationOut(BaseModel):
    overall_score: float
    strengths: Optional[str]
    weaknesses: Optional[str]
    coaching_suggestions: Optional[str]
    improvement_plan: Optional[str]
    criteria: List[QACriterionOut]

    class Config:
        from_attributes = True


class ComplianceViolationOut(BaseModel):
    id: str
    rule_code: str
    category: str
    severity: str
    timestamp_ref: Optional[float]
    explanation: Optional[str]
    evidence: Optional[str]
    reviewed: bool
    review_outcome: Optional[str]

    @model_validator(mode="after")
    def _tidy_rule(self):
        # One name per rule, whatever wording the AI used (see app/core/compliance_rules.py).
        from app.core import compliance_rules as cr
        self.category = cr.rule_category(self.rule_code, self.category)
        self.rule_code = cr.normalise_code(self.rule_code)
        return self

    @computed_field
    @property
    def rule_label(self) -> str:
        from app.core import compliance_rules as cr
        return cr.rule_label(self.rule_code)

    class Config:
        from_attributes = True


class SentimentOut(BaseModel):
    overall_sentiment: str
    beginning_sentiment: Optional[str]
    middle_sentiment: Optional[str]
    end_sentiment: Optional[str]
    timeline: List[Any]

    class Config:
        from_attributes = True


class TimelineEventOut(BaseModel):
    event_type: str
    start_time: float
    end_time: Optional[float]
    description: Optional[str]

    class Config:
        from_attributes = True


class CallAnalyticsOut(BaseModel):
    conversation: Optional[dict]
    customer: Optional[dict]


class DashboardSummary(BaseModel):
    total_calls: int
    processed: int
    processing: int
    failed: int
    average_qa: Optional[float]
    compliance_percent: Optional[float]
    high_risk_calls: int
    recent_calls: List[CallSummary]
    # Failure triage: `failed` is the raw total; `failed_expected` (e.g. silent
    # recordings) is not a system fault, `failed_actionable` is what needs attention,
    # `failed_retryable` is how many of those a retry could fix.
    failed_expected: int = 0
    failed_actionable: int = 0
    failed_retryable: int = 0
    # Period/agent filter echo, previous-period figures for trend arrows, targets, daily QA series.
    period_days: Optional[int] = None
    agent_id: Optional[str] = None
    previous: Optional["PeriodMetrics"] = None
    qa_target: float = 80.0
    compliance_target: float = 95.0
    qa_trend: List["QATrendPoint"] = []


class CallExtractionOut(BaseModel):
    customer_name: Optional[str]
    customer_phone: Optional[str]
    customer_email: Optional[str]
    customer_account_id: Optional[str]
    call_reason_primary: Optional[str]
    call_reason_secondary: Optional[str]
    resolution_summary: Optional[str]
    follow_up_required: bool
    follow_up_reason: Optional[str]

    class Config:
        from_attributes = True


class CallClassificationOut(BaseModel):
    category: Optional[str]
    subcategory: Optional[str]
    complexity: Optional[str]
    confidence: float

    class Config:
        from_attributes = True


class CallLabelOut(BaseModel):
    label: str
    confidence: float
    reason: Optional[str]

    class Config:
        from_attributes = True


class PauseEventOut(BaseModel):
    start_time: float
    end_time: float
    duration_seconds: float
    severity: str
    preceding_speaker: Optional[str]
    following_speaker: Optional[str]

    class Config:
        from_attributes = True


class EmotionOut(BaseModel):
    dominant_customer_emotion: Optional[str]
    dominant_agent_emotion: Optional[str]
    timeline: List[Any]

    class Config:
        from_attributes = True


class AIObservationOut(BaseModel):
    observation_text: str
    timestamp_ref: Optional[float]
    category: Optional[str]

    class Config:
        from_attributes = True


class RecommendationOut(BaseModel):
    category: str
    text: str
    priority: str

    class Config:
        from_attributes = True


class AgentSummary(BaseModel):
    id: str
    name: str
    team: Optional[str]
    external_agent_id: Optional[str]
    call_count: int
    avg_qa_score: Optional[float]
    avg_health_score: Optional[float]
    violation_count: int
    high_risk_call_count: int


class AgentDetail(AgentSummary):
    recent_calls: List[CallSummary]


class ComplianceRuleBreakdown(BaseModel):
    rule_code: str
    label: str
    category: str
    count: int


class ComplianceViolationWithCallOut(ComplianceViolationOut):
    call_id: str
    call_filename: str
    agent_name: Optional[str]
    call_date: Optional[datetime] = None


class ProcessingJobOut(BaseModel):
    stage: str
    status: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    duration_seconds: Optional[float]
    error_message: Optional[str]

    class Config:
        from_attributes = True


class ComplianceSummary(BaseModel):
    total_processed_calls: int
    calls_with_violations: int
    clean_call_percent: Optional[float]
    by_rule: List[ComplianceRuleBreakdown]
    by_severity: dict
    recent_violations: List[ComplianceViolationWithCallOut]


class CallInsightOut(BaseModel):
    main_topic: Optional[str]
    intent: Optional[str]
    outcome: Optional[str]
    root_cause: Optional[str]
    executive_summary: Optional[str]
    detailed_summary: Optional[str]
    sub_topics: List[Any] = []
    keywords: List[Any] = []
    key_discussion_points: List[Any] = []
    action_items: List[Any] = []

    class Config:
        from_attributes = True


class ManualQACriterionIn(BaseModel):
    criterion: str
    ai_score: Optional[float] = None
    manual_score: Optional[float] = None  # null = N/A, excluded from the overall score
    comment: Optional[str] = None


class ManualQAReviewIn(BaseModel):
    reviewer_name: str
    status: str = "draft"  # draft | completed
    notes: Optional[str] = None
    criteria: List[ManualQACriterionIn] = []


class ManualQACriterionOut(ManualQACriterionIn):
    class Config:
        from_attributes = True


class ManualQAReviewOut(BaseModel):
    reviewer_name: str
    status: str
    overall_score: Optional[float]
    notes: Optional[str]
    updated_at: Optional[datetime]
    criteria: List[ManualQACriterionOut]

    class Config:
        from_attributes = True


class HeatmapCell(BaseModel):
    row: str
    col: str
    value: Optional[float]
    n: int = 0


class KeywordStat(BaseModel):
    keyword: str
    count: int
    avg_sentiment: Optional[float] = None


class SentimentTrendDay(BaseModel):
    day: str
    positive: int
    neutral: int
    negative: int


class CriterionDelta(BaseModel):
    criterion: str
    avg_delta: float
    n: int


class QACalibration(BaseModel):
    reviewed_calls: int
    mean_abs_delta: Optional[float]
    agreement_percent: Optional[float]
    by_criterion: List[CriterionDelta]


class CategoryStat(BaseModel):
    category: str
    key: Optional[str] = None  # raw category value, what the Calls page filters on
    count: int
    avg_sentiment: Optional[float] = None
    avg_qa: Optional[float] = None


class AnalyticsOverview(BaseModel):
    kpis: dict
    kpis_previous: Optional[dict] = None   # same KPIs for the period before (only when a period is chosen)
    quality: dict                          # how much of what was processed is a real conversation
    attention: dict                        # {"total": n, "items": [calls to look at first, with reasons]}
    generated_at: str
    days: Optional[int] = None
    volume_heatmap: List[HeatmapCell]
    agent_criteria_heatmap: List[HeatmapCell]
    category_stats: List[CategoryStat]
    keywords: List[KeywordStat]
    sentiment_trend: List[SentimentTrendDay]
    emotion_distribution: dict
    qa_calibration: QACalibration


# ---------------------------------------------------------------------------
# Forms module (ported from the standalone Form Builder project's REST API).
# `form_content`, `responses` and `tags` cross the wire as JSON-encoded
# strings, mirroring the original Node/GraphQL behaviour.
# ---------------------------------------------------------------------------

class EvaluationFormOut(BaseModel):
    id: str
    form_id: str
    title: str
    form_content: str  # JSON string
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class EvaluationFormUpsertIn(BaseModel):
    form_id: str
    title: str
    form_content: str  # JSON string


class EvaluationResponseOut(BaseModel):
    id: str
    inum: Optional[str] = None
    form_id: str
    call_id: Optional[str] = None
    responses: Optional[str] = None  # JSON string
    tags: Optional[str] = None  # JSON string
    user_id: Optional[int] = None
    score: Optional[float] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class EvaluationResponseIn(BaseModel):
    inum: Optional[str] = None
    form_id: str
    call_id: Optional[str] = None
    responses: Optional[str] = None  # JSON string
    tags: Optional[str] = None  # JSON string
    user_id: Optional[int] = None
    score: Optional[float] = None


class EvaluationResponseUpdateIn(BaseModel):
    """Partial update: only the fields present in the payload are applied."""

    inum: Optional[str] = None
    form_id: Optional[str] = None
    call_id: Optional[str] = None
    responses: Optional[str] = None  # JSON string
    tags: Optional[str] = None  # JSON string
    user_id: Optional[int] = None
    score: Optional[float] = None


class UserAuthIn(BaseModel):
    username: str
    password: str


class UserRegisterIn(BaseModel):
    username: str
    password: str
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class UserOut(BaseModel):
    id: int
    username: str
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: Optional[str] = None


class TokenOut(BaseModel):
    token: str
    user: UserOut


class RegisteredUserOut(BaseModel):
    id: int
    username: str


class UploadOut(BaseModel):
    url: str


class FailureGroup(BaseModel):
    category: str
    label: str
    retryable: bool
    expected: bool
    count: int
    sample_reason: Optional[str] = None
    advice: str = ""


class FailureSummary(BaseModel):
    total_failed: int
    expected: int
    actionable: int
    retryable: int
    groups: List[FailureGroup]


class RetryRequest(BaseModel):
    call_ids: Optional[List[str]] = None
    category: Optional[str] = None


class RetryResult(BaseModel):
    retried: int
    skipped_not_retryable: int
    skipped_retry_cap: int
    truncated: bool = False


class IngestionStatus(BaseModel):
    state: str  # healthy | degraded | down
    issues: List[str]
    minio_reachable: bool
    bucket: str
    webhook_last_seen_seconds_ago: Optional[float]
    poller_last_run_seconds_ago: Optional[float]
    poll_interval_seconds: float
    pending: int
    processing: int
    ingested_last_24h: int
    last_ingested_at: Optional[datetime]


class PeriodMetrics(BaseModel):
    total_calls: int
    processed: int
    failed_actionable: int
    average_qa: Optional[float]
    compliance_percent: Optional[float]
    high_risk_calls: int


class QATrendPoint(BaseModel):
    day: str
    avg_qa: float
    calls: int


class ReviewQueueItem(BaseModel):
    call_id: str
    filename: str
    agent_name: Optional[str]
    call_date: Optional[datetime]
    overall_qa_score: Optional[float]
    reasons: List[str]
    priority: int


class ReviewQueue(BaseModel):
    total: int
    items: List[ReviewQueueItem]


class AIFormStat(BaseModel):
    form_id: str
    title: str
    version: int
    scored_calls: int
    average_score: Optional[float]
    total_score: float
    compared_with_human: int
    agreement_percent: Optional[float]


class AIEvaluationSummary(BaseModel):
    enabled_forms: int
    items: List[AIFormStat]


class AgentOption(BaseModel):
    id: str
    name: str


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    team: Optional[str] = None


class AgentBackfillResult(BaseModel):
    assigned: int
    agents_created: int
    unrecognised: int
