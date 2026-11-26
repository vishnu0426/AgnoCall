"""Analytics: only real conversations are averaged, the page says what it left out, and every tile is a list."""
from datetime import timedelta

import pytest
from fastapi import HTTPException

pytest.importorskip("celery")

from app.api import analytics, calls as calls_api  # noqa: E402
from app.models.models import (  # noqa: E402
    CallClassification, CallInsight, SentimentAnalysis, Transcript, TranscriptSegment, CallStatus,
)
from tests.test_dashboard_calibration_api import NOW, mk  # noqa: E402

WORDS = " ".join(["word"] * 60)      # a real conversation: well over the 50-word minimum


def speak(db, call, agent_text=WORDS, customer_text=WORDS, seconds=120, meta=None):
    """Give a call a transcript. An empty text means that side never spoke."""
    t = Transcript(call_id=call.id)
    db.add(t)
    db.flush()
    seq = 0
    for role, text in (("agent", agent_text), ("customer", customer_text)):
        if text:
            db.add(TranscriptSegment(transcript_id=t.id, speaker_role=role, sequence=seq, start_time=seq,
                                     end_time=seq + 1, text_masked=text))
            seq += 1
    call.duration_seconds = seconds
    if meta is not None:
        call.call_metadata = meta
    db.commit()
    return call


def overview(db, **kw):
    return analytics.analytics_overview(db=db, **kw)


def test_ivr_survey_and_hello_calls_do_not_drag_the_average(db):
    real = speak(db, mk(db, "real.wav", qa=80))
    survey = speak(db, mk(db, "survey.wav", qa=2), agent_text="Press 1 very satisfied", customer_text="", seconds=40)
    hello = speak(db, mk(db, "hello.wav", qa=0), agent_text="Hello hello", customer_text="", seconds=8)
    o = overview(db)
    assert o.kpis["processed_calls"] == 1 and o.kpis["avg_qa_score"] == 80.0
    q = o.quality
    assert (q["processed"], q["conversations"], q["excluded"]) == (3, 1, 2)
    assert real and survey and hello


def test_short_but_wordy_call_is_excluded_by_length(db):
    speak(db, mk(db, "quick.wav", qa=70), seconds=5)
    o = overview(db)
    assert o.quality["conversations"] == 0 and o.kpis["avg_qa_score"] is None


def test_one_sided_and_channel_roles_are_reported(db):
    speak(db, mk(db, "stereo.wav", qa=70), meta={"speaker_roles": {"source": "channel"}})
    speak(db, mk(db, "guessed.wav", qa=70), customer_text="", meta={"speaker_roles": {"source": "assumed"}})
    q = overview(db).quality
    assert q["conversations"] == 2 and q["one_sided"] == 1 and q["roles_from_channel"] == 1


def test_thresholds_come_from_settings(db):
    from app.core import settings_store as store
    from app.models.models import AppSetting
    speak(db, mk(db, "a.wav", qa=70), agent_text="a few words here", customer_text="and some more", seconds=60)
    assert overview(db).quality["conversations"] == 0
    db.add(AppSetting(key="analytics_min_words", value=3))
    db.commit()
    store.invalidate()
    assert overview(db).quality["conversations"] == 1


def test_previous_period_kpis_only_with_a_period(db):
    speak(db, mk(db, "now.wav", qa=80, when=NOW - timedelta(days=1)))
    speak(db, mk(db, "before.wav", qa=40, when=NOW - timedelta(days=10)))
    assert overview(db).kpis_previous is None
    o = overview(db, days=7)
    assert o.kpis["avg_qa_score"] == 80.0
    assert o.kpis_previous is not None and o.kpis_previous["avg_qa_score"] == 40.0 and o.days == 7


def test_agent_filter_and_bad_agent_id(db):
    speak(db, mk(db, "x.wav", qa=70))
    with pytest.raises(HTTPException):
        overview(db, agent_id="not-a-uuid")


def test_attention_lists_calls_with_reasons_worst_first(db):
    bad = speak(db, mk(db, "bad.wav", qa=20, violations=("high",)))
    db.add(CallInsight(call_id=bad.id, outcome="escalated", keywords=[]))
    db.add(SentimentAnalysis(call_id=bad.id, overall_sentiment="negative", end_sentiment="negative"))
    meh = speak(db, mk(db, "meh.wav", qa=30))
    fine = speak(db, mk(db, "fine.wav", qa=90))
    db.commit()
    assert overview(db).attention == {"total": 0, "items": []}      # off unless asked for
    a = overview(db, attention=True).attention
    assert a["total"] == 2
    assert [i["filename"] for i in a["items"]] == ["bad.wav", "meh.wav"]
    assert any("compliance flag" in r and "high" in r for r in a["items"][0]["reasons"])
    assert "Escalated" in a["items"][0]["reasons"] and a["items"][1]["reasons"] == ["Low QA score (30)"]
    assert fine


def test_categories_carry_the_key_the_calls_page_filters_on(db):
    c = speak(db, mk(db, "b.wav", qa=70))
    db.add(CallClassification(call_id=c.id, category="technical_support"))
    db.commit()
    cat = overview(db).category_stats[0]
    assert cat.key == "technical_support" and cat.category == "technical support"


def test_calls_page_can_list_either_side_and_a_category(db):
    real = speak(db, mk(db, "real.wav", qa=70))
    ivr = speak(db, mk(db, "ivr.wav", qa=1), agent_text="Press 1", customer_text="", seconds=30)
    db.add(CallClassification(call_id=real.id, category="billing"))
    db.commit()
    names = lambda **kw: sorted(i.original_filename for i in calls_api.list_calls(db=db, **kw).items)
    assert names(conversation=True) == ["real.wav"]
    assert names(conversation=False) == ["ivr.wav"]
    assert names(category="billing") == ["real.wav"]
    assert names() == ["ivr.wav", "real.wav"]
    assert ivr


def test_failed_calls_are_counted_but_never_averaged(db):
    speak(db, mk(db, "ok.wav", qa=70))
    mk(db, "bad.wav", status=CallStatus.failed)
    o = overview(db)
    assert o.quality["failed"] == 1 and o.kpis["processed_calls"] == 1
