"""
Database indexes the application's access patterns need.

PostgreSQL does NOT create an index for a foreign key, so every
`WHERE call_id = ...` / join from `calls` to its 1:1 and 1:N result tables was
a sequential scan. The calls list, dashboard and per-call pages all do those.

Single source of truth: used by the startup shim (app.main) and by the Alembic
migration 0003. Every statement is idempotent. On a very large production
table prefer building these with CREATE INDEX CONCURRENTLY during a quiet
window (plain CREATE INDEX blocks writes while it runs).
"""
import logging

from sqlalchemy import inspect, text

# (index name, table, columns)
INDEXES: list[tuple[str, str, str]] = [
    ("ix_calls_status_uploaded_at", "calls", "status, uploaded_at"),
    ("ix_calls_uploaded_at", "calls", "uploaded_at"),
    ("ix_calls_call_date", "calls", "call_date"),
    ("ix_calls_agent_id", "calls", "agent_id"),
    ("ix_processing_jobs_call_stage", "processing_jobs", "call_id, stage"),
    ("ix_transcripts_call_id", "transcripts", "call_id"),
    ("ix_transcript_segments_tx_seq", "transcript_segments", "transcript_id, sequence"),
    ("ix_qa_evaluations_call_id", "qa_evaluations", "call_id"),
    ("ix_qa_criteria_scores_eval", "qa_criteria_scores", "qa_evaluation_id"),
    ("ix_compliance_violations_call_id", "compliance_violations", "call_id"),
    ("ix_sentiment_analysis_call_id", "sentiment_analysis", "call_id"),
    ("ix_emotion_analysis_call_id", "emotion_analysis", "call_id"),
    ("ix_conversation_analytics_call_id", "conversation_analytics", "call_id"),
    ("ix_customer_analytics_call_id", "customer_analytics", "call_id"),
    ("ix_customer_analytics_risk", "customer_analytics", "risk_level"),
    ("ix_timeline_events_call_id", "timeline_events", "call_id"),
    ("ix_ai_observations_call_id", "ai_observations", "call_id"),
    ("ix_recommendations_call_id", "recommendations", "call_id"),
    ("ix_call_extractions_call_id", "call_extractions", "call_id"),
    ("ix_call_classifications_call_id", "call_classifications", "call_id"),
    ("ix_call_labels_call_id", "call_labels", "call_id"),
    ("ix_pause_events_call_id", "pause_events", "call_id"),
    ("ix_call_insights_call_id", "call_insights", "call_id"),
    ("ix_manual_qa_reviews_call_id", "manual_qa_reviews", "call_id"),
    ("ix_manual_qa_criteria_review", "manual_qa_criteria_scores", "review_id"),
    ("ix_eval_responses_form_id", "rec_app_evaluation_responses", "form_id"),
]


# (index name, table, columns, WHERE predicate): UNIQUE partial indexes.
UNIQUE_INDEXES: list[tuple[str, str, str, str]] = [
    # One agent per PBX extension; makes get-or-create from filenames race-safe.
    ("uq_agents_external_agent_id", "agents", "external_agent_id", "external_agent_id IS NOT NULL"),
]


def ensure_indexes(bind) -> int:
    """Create any missing index whose table exists. Returns how many statements ran."""
    tables = set(inspect(bind).get_table_names())
    ran = 0
    for name, table, cols in INDEXES:
        if table not in tables:
            continue
        bind.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols})"))
        ran += 1
    for name, table, cols, where in UNIQUE_INDEXES:
        if table not in tables:
            continue
        # In a savepoint: if existing data already violates uniqueness (e.g. duplicate agents
        # from before this index existed) the index is skipped with a warning instead of
        # failing the whole startup/migration transaction.
        try:
            with bind.begin_nested():
                bind.execute(text(f"CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {table} ({cols}) WHERE {where}"))
            ran += 1
        except Exception as exc:  # noqa: BLE001
            logging.getLogger("agnocall.indexes").warning(
                "could not create unique index %s (resolve duplicates, then restart): %s", name, exc)
    return ran
