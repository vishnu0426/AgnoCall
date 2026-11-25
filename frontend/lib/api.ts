// 127.0.0.1, not "localhost": on Windows "localhost" tries IPv6 first and adds ~200 ms to every new connection.
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000/api/v1";

/** How long a normal API call may take before the page gives up and shows an error. */
const REQUEST_TIMEOUT_MS = 20_000;

/**
 * fetch() with a deadline. Without one, a server that accepts the connection but never answers (for
 * example an API whose worker process died) leaves the page on its loading skeleton forever: the request
 * never fails, so nothing ever reports a problem.
 */
async function fetchWithTimeout(url: string, init: RequestInit = {}, ms = REQUEST_TIMEOUT_MS): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ms);
  try {
    return await fetch(url, { ...init, signal: init.signal ?? controller.signal });
  } catch (e) {
    if (controller.signal.aborted) {
      throw new Error("The server did not respond in time. Check that the API is running, then try again.");
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetchWithTimeout(`${API_BASE}${path}`, {
    ...init,
    headers: { ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}: ${body}`);
  }
  return res.json();
}

export interface CallSummary {
  id: string;
  status: "uploaded" | "validating" | "processing" | "processed" | "failed";
  agent_name: string | null;
  duration_seconds: number | null;
  call_date: string | null;
  overall_qa_score: number | null;
  compliance_violation_count: number;
  risk_level: "low" | "medium" | "high" | null;
  original_filename: string;
  category?: string | null;
  health_score?: number | null;
  labels?: LabelName[];
  failure_reason?: string | null;
  processing_duration_seconds?: number | null;
  manual_reviewed?: boolean;
  manual_qa_score?: number | null;
  violation_severities?: Record<string, number>;
  failure_category?: string | null;
  failure_label?: string | null;
  failure_advice?: string | null;
  failure_retryable?: boolean | null;
}

export interface CallsQuery {
  status?: string; riskLevel?: string; page?: number; pageSize?: number;
  agentId?: string; days?: number; hasViolations?: boolean; search?: string;
  reviewed?: boolean; sort?: string; order?: "asc" | "desc";
}

export interface BulkReprocessResult {
  queued: number;
  busy: number;
  cap: number;
  not_found: number;
}

function callsQueryString(params?: CallsQuery): string {
  const q = new URLSearchParams();
  if (params?.agentId) q.set("agent_id", params.agentId);
  if (params?.days) q.set("days", String(params.days));
  if (params?.hasViolations !== undefined) q.set("has_violations", String(params.hasViolations));
  if (params?.reviewed !== undefined) q.set("reviewed", String(params.reviewed));
  if (params?.search) q.set("search", params.search);
  if (params?.status) q.set("status", params.status);
  if (params?.riskLevel) q.set("risk_level", params.riskLevel);
  if (params?.sort) q.set("sort", params.sort);
  if (params?.sort && params?.order) q.set("order", params.order);
  if (params?.page) q.set("page", String(params.page));
  if (params?.pageSize) q.set("page_size", String(params.pageSize));
  return q.toString();
}

export interface DashboardSummary {
  total_calls: number;
  processed: number;
  processing: number;
  failed: number;
  average_qa: number | null;
  compliance_percent: number | null;
  high_risk_calls: number;
  recent_calls: CallSummary[];
  failed_expected: number;
  failed_actionable: number;
  failed_retryable: number;
  period_days: number | null;
  agent_id: string | null;
  previous: PeriodMetrics | null;
  qa_target: number;
  compliance_target: number;
  qa_trend: QATrendPoint[];
}

export interface PeriodMetrics {
  total_calls: number;
  processed: number;
  failed_actionable: number;
  average_qa: number | null;
  compliance_percent: number | null;
  high_risk_calls: number;
}

export interface QATrendPoint {
  day: string;
  avg_qa: number;
  calls: number;
}

export interface ReviewQueueItem {
  call_id: string;
  filename: string;
  agent_name: string | null;
  call_date: string | null;
  overall_qa_score: number | null;
  reasons: string[];
  priority: number;
}

export interface ReviewQueue {
  total: number;
  items: ReviewQueueItem[];
}

export interface AIFormStat {
  form_id: string;
  title: string;
  version: number;
  scored_calls: number;
  average_score: number | null;
  total_score: number;
  compared_with_human: number;
  agreement_percent: number | null;
}

export interface AIEvaluationSummary {
  enabled_forms: number;
  items: AIFormStat[];
}

export interface AgentOption {
  id: string;
  name: string;
}

export interface CriterionCalibration {
  criterion: string;
  n: number;
  bias: number | null;
  mean_abs_error: number | null;
  agreement_percent: number | null;
}

export interface RuleCalibration {
  rule_code: string;
  reviewed: number;
  confirmed: number;
  rejected: number;
  precision_percent: number | null;
}

export interface CalibrationSummary {
  reviewed_calls: number;
  target_reviews: number;
  bias: number | null;
  mean_abs_error: number | null;
  agreement_percent: number | null;
  verdict_level: "not_enough_data" | "about_right" | "harsh" | "generous";
  verdict_text: string;
  ai_average_qa: number | null;
  human_average_qa: number | null;
  flagged_call_percent: number | null;
  by_criterion: CriterionCalibration[];
  compliance: {
    reviewed: number;
    confirmed: number;
    rejected: number;
    precision_percent: number | null;
    unreviewed_flags: number;
    by_rule: RuleCalibration[];
  };
  rubric_version: string;
  reviewed_on_current_rubric: number;
}

export interface SampleCall {
  call_id: string;
  filename: string;
  agent_name: string | null;
  ai_qa: number | null;
  violations: number;
  reason: string;
}

function authHeader(): Record<string, string> {
  if (typeof window === "undefined") return {};
  try {
    const t = window.localStorage.getItem("forms_jwt");
    return t ? { Authorization: `Bearer ${t}` } : {};
  } catch {
    return {};
  }
}

export interface AppSetting {
  key: string;
  group: string;
  label: string;
  help: string;
  kind: "float" | "int" | "bool";
  unit: string;
  minimum: number | null;
  maximum: number | null;
  value: number | boolean;
  default: number | boolean;
  is_default: boolean;
  updated_by: string | null;
  updated_at: string | null;
}

async function sendJson<T>(path: string, method: string, body?: unknown): Promise<T> {
  const res = await fetchWithTimeout(`${API_BASE}${path}`, {
    method,
    headers: { "Content-Type": "application/json", ...authHeader() },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    let detail = text;
    try {
      detail = JSON.parse(text).detail ?? text;
    } catch {
      /* not JSON */
    }
    throw new Error(typeof detail === "string" && detail ? detail : `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export interface FailureGroup {
  category: string;
  label: string;
  retryable: boolean;
  expected: boolean;
  count: number;
  sample_reason: string | null;
  advice: string;
}

export interface FailureSummary {
  total_failed: number;
  expected: number;
  actionable: number;
  retryable: number;
  groups: FailureGroup[];
}

export interface RetryResult {
  retried: number;
  skipped_not_retryable: number;
  skipped_retry_cap: number;
  truncated: boolean;
}

export interface IngestionStatus {
  state: "healthy" | "degraded" | "down";
  issues: string[];
  minio_reachable: boolean;
  bucket: string;
  webhook_last_seen_seconds_ago: number | null;
  poller_last_run_seconds_ago: number | null;
  poll_interval_seconds: number;
  pending: number;
  processing: number;
  ingested_last_24h: number;
  last_ingested_at: string | null;
}

export interface TranscriptSegment {
  sequence: number;
  speaker_role: string;
  start_time: number;
  end_time: number;
  text: string;
  stt_confidence: number;
}

export interface QACriterion {
  criterion: string;
  score: number;
  explanation: string | null;
  timestamp_ref: number | null;
  transcript_evidence: string | null;
  confidence: number;
}

export interface QAEvaluation {
  overall_score: number;
  strengths: string | null;
  weaknesses: string | null;
  coaching_suggestions: string | null;
  improvement_plan: string | null;
  criteria: QACriterion[];
}

export interface ComplianceViolation {
  id: string;
  rule_code: string;
  category: string;
  severity: "low" | "medium" | "high" | "critical";
  timestamp_ref: number | null;
  explanation: string | null;
  evidence: string | null;
  reviewed: boolean;
  review_outcome: string | null;
}

export interface TimelineEvent {
  event_type: string;
  start_time: number;
  end_time: number | null;
  description: string | null;
}

export interface ConversationAnalytics {
  duration_seconds: number | null;
  avg_silence_seconds: number | null;
  longest_silence_seconds: number | null;
  talk_ratio_agent: number | null;
  talk_ratio_customer: number | null;
  interruption_count: number;
  questions_asked: number;
  questions_answered: number;
  hold_count: number;
  hold_duration_seconds: number;
  audio_quality_score: number | null;
  health_score: number | null;
}

export interface CustomerAnalytics {
  intent: string | null;
  mood: string | null;
  risk_level: "low" | "medium" | "high" | null;
  repeat_call_probability: number | null;
  escalation_risk: number | null;
  churn_risk: number | null;
  csat_prediction: number | null;
}

export interface CallAnalytics {
  conversation: ConversationAnalytics | null;
  customer: CustomerAnalytics | null;
}

export interface SentimentTimelinePoint {
  timestamp: number;
  score: number;
  label: string;
}

export interface SentimentAnalysis {
  overall_sentiment: string;
  beginning_sentiment: string | null;
  middle_sentiment: string | null;
  end_sentiment: string | null;
  timeline: SentimentTimelinePoint[];
}

export interface EmotionTimelinePoint {
  timestamp: number;
  emotion: string;
  confidence: number;
}

export interface EmotionAnalysis {
  dominant_customer_emotion: string | null;
  dominant_agent_emotion: string | null;
  timeline: EmotionTimelinePoint[];
}

export interface CallExtraction {
  customer_name: string | null;
  customer_phone: string | null;
  customer_email: string | null;
  customer_account_id: string | null;
  call_reason_primary: string | null;
  call_reason_secondary: string | null;
  resolution_summary: string | null;
  follow_up_required: boolean;
  follow_up_reason: string | null;
}

export interface CallClassification {
  category: string | null;
  subcategory: string | null;
  complexity: "low" | "medium" | "high" | null;
  confidence: number;
}

export type LabelName =
  | "urgent"
  | "escalation_required"
  | "follow_up_needed"
  | "satisfaction_survey"
  | "training_opportunity"
  | "upsell_opportunity";

export interface CallLabel {
  label: LabelName;
  confidence: number;
  reason: string | null;
}

export interface PauseEvent {
  start_time: number;
  end_time: number;
  duration_seconds: number;
  severity: "notable" | "excessive";
  preceding_speaker: string | null;
  following_speaker: string | null;
}

export interface AIObservation {
  observation_text: string;
  timestamp_ref: number | null;
  category: string | null;
}

export interface Recommendation {
  category: string;
  text: string;
  priority: "low" | "medium" | "high";
}

export interface AgentSummary {
  id: string;
  name: string;
  team: string | null;
  external_agent_id: string | null;
  call_count: number;
  avg_qa_score: number | null;
  avg_health_score: number | null;
  violation_count: number;
  high_risk_call_count: number;
}

export interface AgentDetail extends AgentSummary {
  recent_calls: CallSummary[];
}

export interface ComplianceRuleBreakdown {
  rule_code: string;
  category: string;
  count: number;
}

export interface ComplianceViolationWithCall extends ComplianceViolation {
  call_id: string;
  call_filename: string;
  agent_name: string | null;
}

export interface ComplianceSummary {
  total_processed_calls: number;
  calls_with_violations: number;
  clean_call_percent: number | null;
  by_rule: ComplianceRuleBreakdown[];
  by_severity: Record<string, number>;
  recent_violations: ComplianceViolationWithCall[];
}

export interface CallInsight {
  main_topic: string | null;
  intent: string | null;
  outcome: string | null;
  root_cause: string | null;
  executive_summary: string | null;
  detailed_summary: string | null;
  sub_topics: string[];
  keywords: string[];
  key_discussion_points: string[];
  action_items: { description: string; owner: string }[];
}

export interface ManualQACriterion {
  criterion: string;
  ai_score: number | null;
  manual_score: number | null; // null = reviewer marked N/A
  comment: string | null;
}

export interface ManualQAReview {
  reviewer_name: string;
  status: "draft" | "completed";
  overall_score: number | null;
  notes: string | null;
  updated_at?: string | null;
  criteria: ManualQACriterion[];
}

export interface HeatmapCell {
  row: string;
  col: string;
  value: number | null;
  n: number;
}

export interface CategoryStat {
  category: string;
  count: number;
  avg_sentiment: number | null;
  avg_qa: number | null;
}

export interface KeywordStat {
  keyword: string;
  count: number;
  avg_sentiment: number | null;
}

export interface SentimentTrendDay {
  day: string;
  positive: number;
  neutral: number;
  negative: number;
}

export interface CriterionDelta {
  criterion: string;
  avg_delta: number;
  n: number;
}

export interface QACalibration {
  reviewed_calls: number;
  mean_abs_delta: number | null;
  agreement_percent: number | null;
  by_criterion: CriterionDelta[];
}

export interface AnalyticsOverview {
  kpis: {
    processed_calls: number;
    avg_qa_score: number | null;
    avg_health_score: number | null;
    negative_end_percent: number | null;
    avg_duration_seconds: number | null;
    follow_up_required: number;
    needs_attention: number;
  };
  volume_heatmap: HeatmapCell[];
  agent_criteria_heatmap: HeatmapCell[];
  category_stats: CategoryStat[];
  keywords: KeywordStat[];
  sentiment_trend: SentimentTrendDay[];
  emotion_distribution: Record<string, number>;
  qa_calibration: QACalibration;
}

export interface ProcessingJob {
  stage: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  duration_seconds: number | null;
  error_message: string | null;
}

export interface CallListResponse {
  items: CallSummary[];
  total: number;
  page: number;
  page_size: number;
}

export const api = {
  dashboardSummary: (params?: { days?: number; agentId?: string }) => {
    const q = new URLSearchParams();
    if (params?.days) q.set("days", String(params.days));
    if (params?.agentId) q.set("agent_id", params.agentId);
    const qs = q.toString();
    return request<DashboardSummary>(`/dashboard/summary${qs ? `?${qs}` : ""}`);
  },
  reviewQueue: (params?: { days?: number; agentId?: string; limit?: number }) => {
    const q = new URLSearchParams();
    if (params?.days) q.set("days", String(params.days));
    if (params?.agentId) q.set("agent_id", params.agentId);
    if (params?.limit) q.set("limit", String(params.limit));
    const qs = q.toString();
    return request<ReviewQueue>(`/review/queue${qs ? `?${qs}` : ""}`);
  },
  aiEvaluation: () => request<AIEvaluationSummary>("/dashboard/ai-evaluation"),
  agentOptions: () => request<AgentOption[]>("/agents/options"),
  renameAgent: (id: string, name: string) => sendJson<AgentOption>(`/agents/${id}`, "PATCH", { name }),
  detectAgents: () =>
    sendJson<{ assigned: number; agents_created: number; unrecognised: number }>(
      "/agents/backfill-from-filenames", "POST"),
  calibrationSummary: () => request<CalibrationSummary>("/calibration/summary"),
  calibrationSample: (n = 20) => request<SampleCall[]>(`/calibration/sample?n=${n}`),
  reviewComplianceFlag: (id: string, outcome: "confirmed" | "rejected" | null) =>
    sendJson<{ id: string; reviewed: boolean; review_outcome: string | null }>(
      `/calibration/compliance/${id}`, "PUT", { outcome }),
  listSettings: () => request<AppSetting[]>("/settings"),
  updateSetting: (key: string, value: number | boolean) => sendJson<AppSetting[]>(`/settings/${key}`, "PUT", { value }),
  resetSetting: (key: string) => sendJson<AppSetting[]>(`/settings/${key}`, "DELETE"),
  changePassword: (current_password: string, new_password: string) =>
    sendJson<{ ok: boolean }>("/account/change-password", "POST", { current_password, new_password }),
  reprocessCall: (id: string) => sendJson<{ call_id: string; status: string }>(`/calls/${id}/reprocess`, "POST"),
  failureSummary: () => request<FailureSummary>("/failures/summary"),
  ingestionStatus: () => request<IngestionStatus>("/ingestion/status"),
  retryFailed: (body: { call_ids?: string[]; category?: string }) =>
    request<RetryResult>("/failures/retry", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  listCalls: (params?: CallsQuery) => {
    const qs = callsQueryString(params);
    return request<CallListResponse>(`/calls${qs ? `?${qs}` : ""}`);
  },
  /** Link for the CSV of the current filtered list (opened by the browser, not fetched). */
  callsExportUrl: (params?: CallsQuery) => {
    const qs = callsQueryString({ ...params, page: undefined, pageSize: undefined });
    return `${API_BASE}/calls/export.csv${qs ? `?${qs}` : ""}`;
  },
  reprocessMany: (callIds: string[]) => sendJson<BulkReprocessResult>("/calls/reprocess", "POST", { call_ids: callIds }),
  getCall: (id: string) => request<CallSummary>(`/calls/${id}`),
  getAudioUrl: (id: string) =>
    request<{
      url: string;
      expires_minutes: number;
      source: "playback" | "original";
      peaks: number[] | null;
      duration: number | null;
    }>(`/calls/${id}/audio`),
  getTranscript: (id: string) => request<{ call_id: string; pii_masked: boolean; segments: TranscriptSegment[] }>(`/calls/${id}/transcript`),
  getQA: (id: string) => request<QAEvaluation>(`/calls/${id}/qa`),
  getCompliance: (id: string) => request<ComplianceViolation[]>(`/calls/${id}/compliance`),
  getSentiment: (id: string) => request<SentimentAnalysis>(`/calls/${id}/sentiment`),
  getTimeline: (id: string) => request<TimelineEvent[]>(`/calls/${id}/timeline`),
  getAnalytics: (id: string) => request<CallAnalytics>(`/calls/${id}/analytics`),
  getExtraction: (id: string) => request<CallExtraction>(`/calls/${id}/extraction`),
  getClassification: (id: string) => request<CallClassification>(`/calls/${id}/classification`),
  getLabels: (id: string) => request<CallLabel[]>(`/calls/${id}/labels`),
  getPauses: (id: string) => request<PauseEvent[]>(`/calls/${id}/pauses`),
  getEmotion: (id: string) => request<EmotionAnalysis>(`/calls/${id}/emotion`),
  getObservations: (id: string) => request<AIObservation[]>(`/calls/${id}/observations`),
  getInsights: (id: string) => request<CallInsight>(`/calls/${id}/insights`),
  getManualQA: (id: string) => request<ManualQAReview>(`/calls/${id}/manual-qa`),
  saveManualQA: (id: string, review: Omit<ManualQAReview, "overall_score" | "updated_at">) =>
    request<ManualQAReview>(`/calls/${id}/manual-qa`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(review),
    }),
  analyticsOverview: () => request<AnalyticsOverview>(`/analytics/overview`),
  getRecommendations: (id: string) => request<Recommendation[]>(`/calls/${id}/recommendations`),
  listAgents: () => request<AgentSummary[]>(`/agents`),
  getAgent: (id: string) => request<AgentDetail>(`/agents/${id}`),
  complianceSummary: () => request<ComplianceSummary>(`/compliance/summary`),
  getJobs: (id: string) => request<ProcessingJob[]>(`/calls/${id}/jobs`),
  uploadCall: async (file: File, agentName?: string) => {
    const form = new FormData();
    form.append("file", file);
    if (agentName) form.append("agent_name", agentName);
    const res = await fetch(`${API_BASE}/calls`, { method: "POST", body: form });
    if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
    return res.json() as Promise<{ call_id: string; status: string }>;
  },
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** [year, month 1-12, day] of a timestamp. The date part of an ISO string is used as stored, so the
 *  result never depends on the time zone or locale of the machine doing the formatting. */
function dateParts(value: string): [number, number, number] | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (m) return [Number(m[1]), Number(m[2]), Number(m[3])];
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : [d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate()];
}

/**
 * "25 Nov 2026". Deliberately NOT toLocaleDateString(undefined, ...): that uses the machine's locale, so
 * the Next server (e.g. "Nov 25, 2026") and the browser (e.g. "25 Nov 2026") produced different text and
 * React threw "Hydration failed" and re-rendered the whole page.
 */
export function formatDate(value: string | null): string {
  if (!value) return "—";
  const p = dateParts(value);
  return p ? `${p[2]} ${MONTHS[p[1] - 1]} ${p[0]}` : "—";
}

/** "25 Nov" (for chart axes). Same locale-independence as formatDate. */
export function formatDayMonth(value: string | null): string {
  if (!value) return "";
  const p = dateParts(value);
  return p ? `${p[2]} ${MONTHS[p[1] - 1]}` : "";
}

/**
 * Calls ingested from call-records/ (PBX/FreeSWITCH drops, see
 * call_ingest.py) keep the raw external UUID + millisecond timestamps in
 * `original_filename`, e.g.
 * "a507fa8b-3dc9-4366-9580-da1b325b85ab-1784543284561-call_1005_1001_agnoshin.com_1784542998721.wav" --
 * meaningless to a human reader, and not needed here since the Call's own
 * `id` already carries identity. Strips a leading UUID, a leading or
 * trailing bare timestamp segment, leaving the human-relevant part (e.g.
 * "call_1005_1001_agnoshin.com.wav"). Falls back to the original filename
 * untouched for anything that doesn't match this convention (e.g. a normal
 * file a user uploaded through the dashboard).
 */
export function formatCallName(filename: string): string {
  let name = filename;
  name = name.replace(/^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}-/, "");
  name = name.replace(/^\d{10,13}-/, "");
  name = name.replace(/_\d{10,13}(\.[a-zA-Z0-9]+)$/, "$1");
  return name || filename;
}

export function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function riskColor(risk: string | null): string {
  switch (risk) {
    case "high": return "text-bad";
    case "medium": return "text-warn";
    case "low": return "text-good";
    default: return "text-muted";
  }
}

export function scoreColor(score: number | null): string {
  if (score == null) return "text-muted";
  if (score >= 85) return "text-good";
  if (score >= 65) return "text-warn";
  return "text-bad";
}
