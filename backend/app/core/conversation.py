"""
What counts as a real conversation.

IVR surveys ("Press 1, very satisfied"), "Hello? Hello?" calls and one-line recordings are processed like
any other call, but scoring them as agent performance drags every average toward zero. Analytics only
averages the calls that pass this test, and says how many it left out. The Calls page can list either side,
so every number on the analytics page can be opened as a list of calls.

The thresholds are editable in Settings (analytics_min_words, analytics_min_seconds).
"""
from sqlalchemy import Integer, and_, case, func, select

from app.models.models import Call, Transcript, TranscriptSegment


def call_stats():
    """Per call: words spoken and segments per side. One grouped statement, portable (no regex), so
    it behaves the same on PostgreSQL and in the SQLite tests."""
    text = TranscriptSegment.text_masked
    words = case((func.length(func.trim(text)) == 0, 0),
                 else_=func.length(text) - func.length(func.replace(text, " ", "")) + 1)
    return (
        select(
            Transcript.call_id.label("call_id"),
            func.coalesce(func.sum(words), 0).label("words"),
            func.sum(case((TranscriptSegment.speaker_role == "agent", 1), else_=0)).cast(Integer).label("agent_segs"),
            func.sum(case((TranscriptSegment.speaker_role == "customer", 1), else_=0)).cast(Integer).label("customer_segs"),
        )
        .select_from(Transcript)
        .join(TranscriptSegment, TranscriptSegment.transcript_id == Transcript.id)
        .group_by(Transcript.call_id)
        .subquery("call_stats")
    )


def conversation_ids(min_words: int, min_seconds: int):
    """Subquery of call ids that are real conversations (enough words and long enough)."""
    stats = call_stats()
    return (
        select(Call.id)
        .join(stats, stats.c.call_id == Call.id)
        .where(and_(stats.c.words >= min_words, func.coalesce(Call.duration_seconds, 0) >= min_seconds))
    )
