"""Filename parsing, rubric wiring and calibration maths (pure logic)."""
import pytest

from app.core import calibration as cal
from app.core.filename_meta import CallParties, parse_call_filename
from app.tasks import rubric


# ---- filename -> parties (real names from the bucket) ----------------------------------

@pytest.mark.parametrize("name,agent,customer,internal", [
    ("call_1002_1001_agnoshin.com.wav", "1001", None, True),
    ("call__919551818896_1002_agnoshin.com.wav", "1002", "919551818896", False),
    ("call__919025419508_1001_agnoshin.com.wav", "1001", "919025419508", False),
    ("3bb2d08c-dc02-453e-964e-2c8bed190215-1793693704913-call__918838559627_1006_agnoshin.com_1793693659252.wav",
     "1006", "918838559627", False),
    ("call_1001_919876543210_agnoshin.com.wav", "1001", "919876543210", False),   # outbound: agent first
])
def test_parse_real_filenames(name, agent, customer, internal):
    assert parse_call_filename(name) == CallParties(agent, customer, internal)


@pytest.mark.parametrize("name", ["719001004809577.wav", "", None, "recording.mp3", "call_abc_def.wav",
                                  "call_12345678_87654321.wav"])
def test_unparseable_names_infer_nothing(name):
    assert parse_call_filename(name) == CallParties()          # never guess an identity


# ---- rubric ---------------------------------------------------------------------------------

def test_rubric_covers_every_pipeline_criterion_with_definitions():
    from app.tasks.pipeline import QA_CRITERIA
    assert set(rubric.QA_RUBRIC) == set(QA_CRITERIA)
    for c, (what, high, low) in rubric.QA_RUBRIC.items():
        assert what and high and low, c
    text = rubric.qa_rubric_text(QA_CRITERIA)
    assert all(c in text for c in QA_CRITERIA)


def test_rubric_tells_the_model_how_to_score_and_when_not_to_flag():
    assert "null" in rubric.SCORE_ANCHORS and "90-100" in rubric.SCORE_ANCHORS
    assert "do NOT flag" in rubric.COMPLIANCE_GUIDANCE and "exact quote" in rubric.COMPLIANCE_GUIDANCE
    assert rubric.RUBRIC_VERSION.startswith("qa-rubric/")


def test_llm_prompt_contains_rubric_and_records_version(db, monkeypatch):
    pytest.importorskip("celery")
    from app.models.models import Call
    from app.tasks import pipeline
    captured = {}

    class Cap:
        def generate_json(self, system, prompt):
            captured["prompt"] = prompt
            return {"qa_scores": []}

    monkeypatch.setattr(pipeline, "get_llm_provider", lambda: Cap())
    c = Call(original_filename="a.wav", storage_path="x")
    db.add(c)
    db.commit()
    pipeline._stage_llm_analysis(db, c, [{"speaker_role": "agent", "start_time": 0, "end_time": 1, "text": "hi"}])
    p = captured["prompt"]
    assert "Scoring scale" in p and "high:" in p and "do NOT flag" in p
    assert "score\": number|null" in p
    assert c.call_metadata["rubric_version"] == rubric.RUBRIC_VERSION


# ---- calibration maths --------------------------------------------------------------------------

def test_pair_stats_bias_sign_convention():
    # human - AI: AI says 20, human says 70 -> +50 (AI is harsh)
    s = cal.pair_stats([(20, 70), (10, 40), (30, 55)])
    assert s.n == 3 and s.bias == pytest.approx(35.0)
    assert s.mean_abs_error == pytest.approx(35.0) and s.agreement_percent == 0.0
    over = cal.pair_stats([(90, 60), (80, 70)])
    assert over.bias < 0                                         # AI too generous


def test_pair_stats_agreement_and_empty():
    s = cal.pair_stats([(50, 55), (60, 52), (70, 95)])
    assert s.agreement_percent == pytest.approx(66.7)
    assert cal.pair_stats([]) == cal.PairStats(0, None, None, None)
    assert cal.pair_stats([(None, 5), (5, None)]).n == 0         # incomplete pairs ignored


@pytest.mark.parametrize("bias,n,level", [
    (None, 0, "not_enough_data"), (30, 4, "not_enough_data"),
    (2.0, 10, "about_right"), (-4.9, 10, "about_right"),
    (8.0, 10, "harsh"), (30.0, 10, "harsh"), (-8.0, 10, "generous"),
])
def test_verdict_levels(bias, n, level):
    assert cal.verdict(bias, n)[0] == level


def test_verdict_sentence_is_plain_and_scaled():
    assert "much lower" in cal.verdict(30, 10)[1] and "30 points" in cal.verdict(30, 10)[1]
    assert "much" not in cal.verdict(8, 10)[1]
    assert "higher" in cal.verdict(-20, 10)[1]


def test_compliance_stats_precision():
    s = cal.compliance_stats(["confirmed", "rejected", "rejected", "rejected", None, "other"])
    assert (s.reviewed, s.confirmed, s.rejected, s.precision_percent) == (4, 1, 3, 25.0)
    assert cal.compliance_stats([]).precision_percent is None


# ---- sample selection -------------------------------------------------------------------------------

def _cands(n, flagged_every=4):
    return [{"id": f"c{i:03d}", "qa": float(i), "violations": 1 if i % flagged_every == 0 else 0}
            for i in range(n)]


def test_sample_spans_the_score_range_and_includes_flagged_calls():
    out = cal.pick_review_sample(_cands(80), 20)
    assert len(out) == 20 and len({c["id"] for c in out}) == 20          # no duplicates
    scores = sorted(c["qa"] for c in out)
    assert scores[0] <= 10 and scores[-1] >= 70                           # low AND high calls both checked
    assert sum(1 for c in out if c["violations"] > 0) >= 5                # some flagged ones reserved


def test_sample_is_deterministic_and_handles_small_pools():
    a = cal.pick_review_sample(_cands(50), 10)
    assert a == cal.pick_review_sample(list(reversed(_cands(50))), 10)
    assert len(cal.pick_review_sample(_cands(3), 10)) == 3
    assert cal.pick_review_sample([], 5) == [] and cal.pick_review_sample(_cands(5), 0) == []
