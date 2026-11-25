"""
Org-wide analytics aggregates for the /analytics page.

Everything is served from one endpoint so the page renders atomically from a
single fetch. Aggregation happens in Python over narrow column queries —
volumes here are per-tenant call recordings (hundreds to low thousands of
rows), far below where pushing GROUP BYs into SQL would matter, and it keeps
the weekday/keyword logic portable across Postgres/SQLite dev setups.
"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.parallel import run_parallel

from app.core.database import get_db, get_read_db
from app.models.models import (
    Call, CallStatus, Agent, QAEvaluation, QACriteriaScore,
    SentimentAnalysis, EmotionAnalysis, CallClassification, CallInsight,
    CallExtraction, ConversationAnalytics, ManualQAReview, ManualQACriteriaScore,
)
from app.schemas.schemas import (
    AnalyticsOverview, HeatmapCell, KeywordStat, SentimentTrendDay,
    QACalibration, CriterionDelta,
)

router = APIRouter(prefix="/analytics", tags=["Analytics"])

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

SENTIMENT_VALUE = {"positive": 1.0, "neutral": 0.0, "negative": -1.0}


def _kpis(db: Session) -> dict:
    """Every KPI in ONE statement (scalar subqueries), over PROCESSED calls only so a stale result on a
    failed or re-running call never counts. Previously this loaded every processed call in full."""
    done = Call.status == CallStatus.processed
    n_processed = select(func.count(Call.id)).where(done).scalar_subquery()
    avg_duration = select(func.avg(Call.duration_seconds)).where(done, Call.duration_seconds > 0).scalar_subquery()
    avg_qa = (select(func.avg(QAEvaluation.overall_score)).select_from(QAEvaluation)
              .join(Call, Call.id == QAEvaluation.call_id).where(done).scalar_subquery())
    avg_health = (select(func.avg(ConversationAnalytics.health_score)).select_from(ConversationAnalytics)
                  .join(Call, Call.id == ConversationAnalytics.call_id).where(done).scalar_subquery())
    sentiments = select(func.count(SentimentAnalysis.id)).select_from(SentimentAnalysis) \
        .join(Call, Call.id == SentimentAnalysis.call_id).where(done)
    n_sentiment = sentiments.scalar_subquery()
    n_negative = sentiments.where(SentimentAnalysis.end_sentiment == "negative").scalar_subquery()
    follow_ups = (select(func.count(CallExtraction.id)).select_from(CallExtraction)
                  .join(Call, Call.id == CallExtraction.call_id)
                  .where(done, CallExtraction.follow_up_required.is_(True)).scalar_subquery())
    unresolved = (select(func.count(CallInsight.id)).select_from(CallInsight)
                  .join(Call, Call.id == CallInsight.call_id)
                  .where(done, CallInsight.outcome.in_(["escalated", "unresolved", "callback_required"])).scalar_subquery())
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


def _volume_heatmap(db: Session) -> list[HeatmapCell]:
    counts = Counter()
    for (call_date,) in db.query(Call.call_date).filter(Call.call_date.isnot(None)).all():
        counts[(WEEKDAYS[call_date.weekday()], str(call_date.hour))] += 1
    return [
        HeatmapCell(row=day, col=str(hour), value=float(counts.get((day, str(hour)), 0)),
                    n=counts.get((day, str(hour)), 0))
        for day in WEEKDAYS for hour in range(24)
        if counts.get((day, str(hour)), 0) > 0
    ]


def _agent_criteria_heatmap(db: Session) -> list[HeatmapCell]:
    rows = (
        db.query(Agent.name, QACriteriaScore.criterion, QACriteriaScore.score)
        .select_from(QACriteriaScore)
        .join(QAEvaluation, QACriteriaScore.qa_evaluation_id == QAEvaluation.id)
        .join(Call, QAEvaluation.call_id == Call.id)
        .outerjoin(Agent, Call.agent_id == Agent.id)
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


def _category_stats(db: Session) -> list[dict]:
    """Treemap feed: one node per call category, sized by volume, colored by
    avg sentiment — the 'Discover Trends' style categories panel."""
    rows = (
        db.query(CallClassification.category, SentimentAnalysis.overall_sentiment, QAEvaluation.overall_score)
        .join(Call, Call.id == CallClassification.call_id)
        .outerjoin(SentimentAnalysis, SentimentAnalysis.call_id == Call.id)
        .outerjoin(QAEvaluation, QAEvaluation.call_id == Call.id)
        .filter(CallClassification.category.isnot(None))
        .all()
    )
    acc: dict[str, dict] = {}
    for category, sentiment, qa in rows:
        entry = acc.setdefault(category.replace("_", " "), {"count": 0, "sent": [], "qa": []})
        entry["count"] += 1
        if sentiment in SENTIMENT_VALUE:
            entry["sent"].append(SENTIMENT_VALUE[sentiment])
        if qa is not None:
            entry["qa"].append(qa)
    return [
        {
            "category": cat,
            "count": e["count"],
            "avg_sentiment": round(sum(e["sent"]) / len(e["sent"]), 2) if e["sent"] else None,
            "avg_qa": round(sum(e["qa"]) / len(e["qa"]), 1) if e["qa"] else None,
        }
        for cat, e in sorted(acc.items(), key=lambda kv: -kv[1]["count"])
    ]


def _keywords(db: Session, limit: int = 60) -> list[KeywordStat]:
    rows = (
        db.query(CallInsight.keywords, SentimentAnalysis.overall_sentiment)
        .outerjoin(SentimentAnalysis, SentimentAnalysis.call_id == CallInsight.call_id)
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


def _sentiment_trend(db: Session, days: int = 30) -> list[SentimentTrendDay]:
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(Call.call_date, SentimentAnalysis.overall_sentiment)
        .join(SentimentAnalysis, SentimentAnalysis.call_id == Call.id)
        .filter(Call.call_date.isnot(None), Call.call_date >= since)
        .all()
    )
    per_day = defaultdict(lambda: {"positive": 0, "neutral": 0, "negative": 0})
    for call_date, overall in rows:
        bucket = per_day[call_date.strftime("%Y-%m-%d")]
        bucket[overall if overall in bucket else "neutral"] += 1
    return [
        SentimentTrendDay(day=day, **counts) for day, counts in sorted(per_day.items())
    ]


def _emotion_distribution(db: Session) -> dict:
    rows = db.query(EmotionAnalysis.dominant_customer_emotion).all()
    counts = Counter(e.strip().lower() for (e,) in rows if e)
    return dict(counts.most_common(12))


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
def analytics_overview(db: Session = Depends(get_read_db)):
    # Independent queries: run side by side (see app/core/parallel.py).
    kpis, heat, criteria, categories, keywords, trend, emotions, calibration = run_parallel(
        db, [_kpis, _volume_heatmap, _agent_criteria_heatmap, _category_stats, _keywords,
             _sentiment_trend, _emotion_distribution, _qa_calibration])
    return AnalyticsOverview(
        kpis=kpis, volume_heatmap=heat, agent_criteria_heatmap=criteria, category_stats=categories,
        keywords=keywords, sentiment_trend=trend, emotion_distribution=emotions, qa_calibration=calibration,
    )
