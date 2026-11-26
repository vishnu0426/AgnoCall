"""
Org-wide analytics aggregates for the /analytics page.

Everything is served from one endpoint so the page renders atomically from a single fetch. Only REAL
conversations are averaged (see app/core/conversation.py): IVR surveys, "hello?" calls and one-liners are
counted in `quality` instead, so they cannot drag the averages down. A period filter and an agent filter
apply to every block, and KPIs come back for the previous period too so the page can show a change.

Aggregation happens in Python over narrow column queries — volumes here are per-tenant call recordings
(hundreds to low thousands of rows) — and it keeps the weekday/keyword logic portable across
Postgres/SQLite dev setups.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dashboard import call_time, normalise_days, window_conditions
from app.core import settings_store as store
from app.core.conversation import call_stats, conversation_ids
from app.core.database import get_read_db
from app.core.ids import is_uuid
from app.core.parallel import run_parallel
from app.models.models import (
    Call, CallStatus, Agent, QAEvaluation, QACriteriaScore,
    SentimentAnalysis, EmotionAnalysis, CallClassification, CallInsight,
    CallExtraction, ConversationAnalytics, ManualQAReview, ManualQACriteriaScore, ComplianceViolation,
)
from app.schemas.schemas import (
    AnalyticsOverview, HeatmapCell, KeywordStat, SentimentTrendDay,
    QACalibration, CriterionDelta,
)

router = APIRouter(prefix="/analytics", tags=["Analytics"])

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SENTIMENT_VALUE = {"positive": 1.0, "neutral": 0.0, "negative": -1.0}
UNRESOLVED_OUTCOMES = ("escalated", "unresolved", "callback_required")
SEVERITY_WEIGHT = {"critical": 4, "high": 3, "medium": 2, "low": 1}
LOW_QA = 40.0
WORKLIST_SIZE = 10


@dataclass(frozen=True)
class Scope:
    """One reporting window. `conds()` is every condition a call must meet to be counted: processed, inside
    the window, for the chosen agent, and a real conversation."""
    start: Optional[datetime]
    end: Optional[datetime]
    agent_id: Optional[str]
    min_words: int
    min_seconds: int

    def processed(self) -> list:
        return [Call.status == CallStatus.processed, *window_conditions(self.start, self.end, self.agent_id)]

    def conds(self) -> list:
        return [*self.processed(), Call.id.in_(conversation_ids(self.min_words, self.min_seconds))]


def _kpis(db: Session, scope: Scope) -> dict:
    """Every KPI in ONE statement (scalar subqueries), over real, processed conversations."""
    conds = scope.conds()
    n_processed = select(func.count(Call.id)).where(*conds).scalar_subquery()
    avg_duration = select(func.avg(Call.duration_seconds)).where(*conds, Call.duration_seconds > 0).scalar_subquery()
    avg_qa = (select(func.avg(QAEvaluation.overall_score)).select_from(QAEvaluation)
              .join(Call, Call.id == QAEvaluation.call_id).where(*conds).scalar_subquery())
    avg_health = (select(func.avg(ConversationAnalytics.health_score)).select_from(ConversationAnalytics)
                  .join(Call, Call.id == ConversationAnalytics.call_id).where(*conds).scalar_subquery())
    sentiments = select(func.count(SentimentAnalysis.id)).select_from(SentimentAnalysis) \
        .join(Call, Call.id == SentimentAnalysis.call_id).where(*conds)
    n_sentiment = sentiments.scalar_subquery()
    n_negative = sentiments.where(SentimentAnalysis.end_sentiment == "negative").scalar_subquery()
    follow_ups = (select(func.count(CallExtraction.id)).select_from(CallExtraction)
                  .join(Call, Call.id == CallExtraction.call_id)
                  .where(*conds, CallExtraction.follow_up_required.is_(True)).scalar_subquery())
    unresolved = (select(func.count(CallInsight.id)).select_from(CallInsight)
                  .join(Call, Call.id == CallInsight.call_id)
                  .where(*conds, CallInsight.outcome.in_(UNRESOLVED_OUTCOMES)).scalar_subquery())
    total, duration, qa, health, sent_n, neg_n, follow, needs = db.query(
        n_processed, avg_duration, avg_qa, avg_health, n_sentiment, n_negative, follow_ups, unresolved).one()

    return {
        "processed_calls": total or 0,
        "avg_qa_score": round(qa, 1) if qa is not None else None,
        "avg_health_score": round(health, 1) if health is not None else None,
        "negative_end_percent": round(100 * (neg_n or 0) / sent_n, 1) if sent_n else None,
        "avg_duration_seconds": round(duration) if duration else None,
        "follow_up_required": follow or 0,
        "needs_attention": needs or 0,
    }


def _quality(db: Session, scope: Scope) -> dict:
    """How much of what was processed is real conversation, and how much of that has trustworthy roles."""
    stats = call_stats()
    source = Call.call_metadata["speaker_roles"]["source"].as_string()
    rows = (
        db.query(Call.duration_seconds, stats.c.words, stats.c.agent_segs, stats.c.customer_segs, source)
        .outerjoin(stats, stats.c.call_id == Call.id)
        .filter(*scope.processed())
        .all()
    )
    real = [r for r in rows if (r[1] or 0) >= scope.min_words and (r[0] or 0) >= scope.min_seconds]
    failed = db.query(func.count(Call.id)).filter(
        Call.status == CallStatus.failed, *window_conditions(scope.start, scope.end, scope.agent_id)).scalar() or 0
    return {
        "processed": len(rows),
        "conversations": len(real),
        "excluded": len(rows) - len(real),
        "one_sided": sum(1 for r in real if not r[2] or not r[3]),
        "roles_from_channel": sum(1 for r in real if r[4] == "channel"),
        "failed": failed,
        "min_words": scope.min_words,
        "min_seconds": scope.min_seconds,
    }


def _volume_heatmap(db: Session, scope: Scope) -> list[HeatmapCell]:
    counts = Counter()
    for (when,) in db.query(call_time()).filter(*scope.conds()).all():
        if when is not None:
            counts[(WEEKDAYS[when.weekday()], str(when.hour))] += 1
    return [
        HeatmapCell(row=day, col=str(hour), value=float(counts.get((day, str(hour)), 0)),
                    n=counts.get((day, str(hour)), 0))
        for day in WEEKDAYS for hour in range(24)
        if counts.get((day, str(hour)), 0) > 0
    ]


def _agent_criteria_heatmap(db: Session, scope: Scope) -> list[HeatmapCell]:
    rows = (
        db.query(Agent.name, QACriteriaScore.criterion, QACriteriaScore.score)
        .select_from(QACriteriaScore)
        .join(QAEvaluation, QACriteriaScore.qa_evaluation_id == QAEvaluation.id)
        .join(Call, QAEvaluation.call_id == Call.id)
        .outerjoin(Agent, Call.agent_id == Agent.id)
        .filter(*scope.conds())
        .all()
    )
    acc = defaultdict(list)
    for agent_name, criterion, score in rows:
        if score is not None:
            acc[(agent_name or "Unassigned", criterion)].append(score)
    return [
        HeatmapCell(row=agent, col=criterion, value=round(sum(scores) / len(scores), 1), n=len(scores))
        for (agent, criterion), scores in sorted(acc.items())
    ]


def _category_stats(db: Session, scope: Scope) -> list[dict]:
    """Treemap feed: one node per call category, sized by volume, colored by avg sentiment. `key` is the raw
    value the Calls page filters on."""
    rows = (
        db.query(CallClassification.category, SentimentAnalysis.overall_sentiment, QAEvaluation.overall_score)
        .join(Call, Call.id == CallClassification.call_id)
        .outerjoin(SentimentAnalysis, SentimentAnalysis.call_id == Call.id)
        .outerjoin(QAEvaluation, QAEvaluation.call_id == Call.id)
        .filter(CallClassification.category.isnot(None), *scope.conds())
        .all()
    )
    acc: dict[str, dict] = {}
    for category, sentiment, qa in rows:
        entry = acc.setdefault(category, {"count": 0, "sent": [], "qa": []})
        entry["count"] += 1
        if sentiment in SENTIMENT_VALUE:
            entry["sent"].append(SENTIMENT_VALUE[sentiment])
        if qa is not None:
            entry["qa"].append(qa)
    return [
        {
            "category": key.replace("_", " "),
            "key": key,
            "count": e["count"],
            "avg_sentiment": round(sum(e["sent"]) / len(e["sent"]), 2) if e["sent"] else None,
            "avg_qa": round(sum(e["qa"]) / len(e["qa"]), 1) if e["qa"] else None,
        }
        for key, e in sorted(acc.items(), key=lambda kv: -kv[1]["count"])
    ]


def _keywords(db: Session, scope: Scope, limit: int = 60) -> list[KeywordStat]:
    rows = (
        db.query(CallInsight.keywords, SentimentAnalysis.overall_sentiment)
        .join(Call, Call.id == CallInsight.call_id)
        .outerjoin(SentimentAnalysis, SentimentAnalysis.call_id == CallInsight.call_id)
        .filter(*scope.conds())
        .all()
    )
    counts = Counter()
    sentiment_acc = defaultdict(list)
    for keywords, overall in rows:
        for kw in set(k.strip().lower() for k in (keywords or []) if isinstance(k, str) and k.strip()):
            counts[kw] += 1
            if overall in SENTIMENT_VALUE:
                sentiment_acc[kw].append(SENTIMENT_VALUE[overall])
    return [
        KeywordStat(
            keyword=kw,
            count=n,
            avg_sentiment=round(sum(sentiment_acc[kw]) / len(sentiment_acc[kw]), 2) if sentiment_acc[kw] else None,
        )
        for kw, n in counts.most_common(limit)
    ]


def _sentiment_trend(db: Session, scope: Scope, days: int) -> list[SentimentTrendDay]:
    since = datetime.utcnow() - timedelta(days=days)
    when = call_time()
    rows = (
        db.query(when, SentimentAnalysis.overall_sentiment)
        .select_from(Call)
        .join(SentimentAnalysis, SentimentAnalysis.call_id == Call.id)
        .filter(when >= since, *scope.conds())
        .all()
    )
    per_day = defaultdict(lambda: {"positive": 0, "neutral": 0, "negative": 0})
    for call_date, overall in rows:
        bucket = per_day[call_date.strftime("%Y-%m-%d")]
        bucket[overall if overall in bucket else "neutral"] += 1
    return [
        SentimentTrendDay(day=day, **counts) for day, counts in sorted(per_day.items())
    ]


def _emotion_distribution(db: Session, scope: Scope) -> dict:
    rows = (db.query(EmotionAnalysis.dominant_customer_emotion).select_from(EmotionAnalysis)
            .join(Call, Call.id == EmotionAnalysis.call_id).filter(*scope.conds()).all())
    counts = Counter(e.strip().lower() for (e,) in rows if e)
    return dict(counts.most_common(12))


def _attention(db: Session, scope: Scope) -> dict:
    """The calls to look at first, each with the reasons (not a bare count). Ranked by how serious the
    reasons are, then by the lowest QA score."""
    rows = (
        db.query(Call.id, Call.original_filename, Agent.name, QAEvaluation.overall_score,
                 CallInsight.outcome, SentimentAnalysis.end_sentiment)
        .select_from(Call)
        .outerjoin(Agent, Agent.id == Call.agent_id)
        .outerjoin(QAEvaluation, QAEvaluation.call_id == Call.id)
        .outerjoin(CallInsight, CallInsight.call_id == Call.id)
        .outerjoin(SentimentAnalysis, SentimentAnalysis.call_id == Call.id)
        .filter(*scope.conds())
        .all()
    )
    worst: dict[str, str] = {}
    flags = Counter()
    for call_id, severity in (db.query(ComplianceViolation.call_id, ComplianceViolation.severity)
                              .join(Call, Call.id == ComplianceViolation.call_id).filter(*scope.conds()).all()):
        flags[call_id] += 1
        if SEVERITY_WEIGHT.get(severity, 0) > SEVERITY_WEIGHT.get(worst.get(call_id), 0):
            worst[call_id] = severity
    items = []
    for call_id, filename, agent, qa, outcome, end_sentiment in rows:
        reasons, weight = [], 0
        if flags[call_id]:
            sev = worst.get(call_id, "")
            reasons.append(f"{flags[call_id]} compliance flag{'s' if flags[call_id] != 1 else ''}"
                           + (f" (worst: {sev})" if sev else ""))
            weight += 10 * SEVERITY_WEIGHT.get(sev, 1)
        if outcome in UNRESOLVED_OUTCOMES:
            reasons.append({"escalated": "Escalated", "unresolved": "Not resolved",
                            "callback_required": "Callback needed"}[outcome])
            weight += 5
        if end_sentiment == "negative":
            reasons.append("Ended on negative sentiment")
            weight += 2
        if qa is not None and qa < LOW_QA:
            reasons.append(f"Low QA score ({qa:.0f})")
            weight += 2
        if reasons:
            items.append({"call_id": call_id, "filename": filename, "agent": agent, "qa": None if qa is None else round(qa, 1),
                          "reasons": reasons, "_w": weight})
    items.sort(key=lambda i: (-i["_w"], i["qa"] if i["qa"] is not None else 101))
    for i in items:
        i.pop("_w")
    return {"total": len(items), "items": items[:WORKLIST_SIZE]}


def _qa_calibration(db: Session) -> QACalibration:
    reviews = db.query(ManualQAReview).filter(ManualQAReview.status == "completed").all()
    review_ids = [r.id for r in reviews]

    overall_deltas = []
    for r in reviews:
        ai = db.query(QAEvaluation.overall_score).filter(QAEvaluation.call_id == r.call_id).scalar()
        if ai is not None and r.overall_score is not None:
            overall_deltas.append(abs(ai - r.overall_score))

    by_criterion = defaultdict(list)
    if review_ids:
        for c in db.query(ManualQACriteriaScore).filter(
                ManualQACriteriaScore.review_id.in_(review_ids)).all():
            if c.ai_score is not None and c.manual_score is not None:
                by_criterion[c.criterion].append(c.manual_score - c.ai_score)

    return QACalibration(
        reviewed_calls=len(reviews),
        mean_abs_delta=round(sum(overall_deltas) / len(overall_deltas), 1) if overall_deltas else None,
        agreement_percent=round(100 * sum(1 for d in overall_deltas if d <= 10) / len(overall_deltas), 1)
        if overall_deltas else None,
        by_criterion=[
            CriterionDelta(criterion=crit, avg_delta=round(sum(ds) / len(ds), 1), n=len(ds))
            for crit, ds in sorted(by_criterion.items())
        ],
    )


@router.get("/overview", response_model=AnalyticsOverview)
def analytics_overview(days: Optional[int] = None, agent_id: Optional[str] = None, attention: bool = False,
                       db: Session = Depends(get_read_db)):
    # `attention` (the worklist of calls to open first) is off by default: the page does not show it,
    # and it costs several queries.
    if agent_id and not is_uuid(agent_id):
        raise HTTPException(400, "Invalid agent_id")
    days = normalise_days(days)
    cfg = store.effective(db)
    now = datetime.utcnow()
    start = now - timedelta(days=days) if days else None
    mk = lambda s, e: Scope(s, e, agent_id or None, cfg.analytics_min_words, cfg.analytics_min_seconds)
    scope = mk(start, None)
    previous = mk(start - timedelta(days=days), start) if days else None

    # Independent queries: run side by side (see app/core/parallel.py).
    tasks = [
        lambda s: _kpis(s, scope), lambda s: _quality(s, scope), lambda s: _volume_heatmap(s, scope),
        lambda s: _agent_criteria_heatmap(s, scope), lambda s: _category_stats(s, scope),
        lambda s: _keywords(s, scope), lambda s: _sentiment_trend(s, scope, days or 30),
        lambda s: _emotion_distribution(s, scope), _qa_calibration,
    ]
    if previous:
        tasks.append(lambda s: _kpis(s, previous))
    if attention:
        tasks.append(lambda s: _attention(s, scope))
    results = run_parallel(db, tasks)
    kpis, quality, heat, criteria, categories, keywords, trend, emotions, calibration = results[:9]
    extra = iter(results[9:])
    kpis_previous = next(extra) if previous else None
    worklist = next(extra) if attention else {"total": 0, "items": []}
    return AnalyticsOverview(
        kpis=kpis, kpis_previous=kpis_previous, quality=quality, attention=worklist,
        generated_at=now.isoformat(timespec="seconds") + "Z", days=days,
        volume_heatmap=heat, agent_criteria_heatmap=criteria, category_stats=categories,
        keywords=keywords, sentiment_trend=trend, emotion_distribution=emotions, qa_calibration=calibration,
    )
