"""Form drafts, published-version history, restore and duplicate."""
import json

import pytest

pytest.importorskip("strawberry")

from app.models.models import EvaluationForm, EvaluationFormVersion  # noqa: E402
from tests.test_form_eval_graphql import _settings, content, run, save  # noqa: E402,F401

DRAFT = """
mutation($form_id: String!, $title: String!, $content: String!, $ai: Boolean) {
  saveEvaluationFormDraft(form_id: $form_id, title: $title, form_content: $content, ai_enabled: $ai) {
    form_id title version ai_enabled form_content has_draft draft_title draft_content draft_ai_enabled
  }
}"""
DISCARD = "mutation($f: String!) { discardEvaluationFormDraft(form_id: $f) { has_draft version } }"
VERSIONS = "query($f: String!) { getEvaluationFormVersions(form_id: $f) { version title is_current } }"
RESTORE = "mutation($f: String!, $v: Int!) { restoreEvaluationFormVersion(form_id: $f, version: $v) { has_draft draft_content version } }"
DUPLICATE = "mutation($f: String!, $t: String) { duplicateEvaluationForm(form_id: $f, title: $t) { form_id title version ai_enabled form_content } }"


def draft(db, form_id, body, title="Draft title", ai=None):
    return run(db, DRAFT, {"form_id": form_id, "title": title, "content": body, "ai": ai})


def test_draft_never_touches_the_live_form(db):
    save(db, "f1", ai=True, body=content(1, "Live"))
    res = draft(db, "f1", content(2, "Edited"), title="Renamed", ai=False)
    assert res.errors is None
    out = res.data["saveEvaluationFormDraft"]
    assert out["has_draft"] and out["draft_title"] == "Renamed" and out["draft_ai_enabled"] is False
    # live side unchanged: same title, same content, same version, AI still on
    assert out["title"] == "f1" and out["version"] == 1 and out["ai_enabled"] is True
    assert json.loads(out["form_content"])["fields"][0]["label"] == "Live 0"
    assert len(json.loads(out["draft_content"])["fields"]) == 2


def test_publishing_applies_the_draft_clears_it_and_bumps_the_version(db):
    save(db, "f1", body=content(1, "Live"))
    draft(db, "f1", content(2, "Edited"))
    assert save(db, "f1", body=content(2, "Edited")).errors is None
    form = db.query(EvaluationForm).filter_by(form_id="f1").one()
    assert form.version == 2 and form.draft_content is None and form.draft_title is None


def test_draft_for_unknown_form_or_bad_json_is_rejected(db):
    assert draft(db, "nope", content()).errors
    save(db, "f1")
    assert draft(db, "f1", "not json").errors
    assert draft(db, "f1", json.dumps([1, 2])).errors
    assert draft(db, "f1", json.dumps({"fields": "x"})).errors
    assert draft(db, "f1", content(), title="   ").errors
    assert db.query(EvaluationForm).filter_by(form_id="f1").one().draft_content is None


def test_discard_draft(db):
    save(db, "f1")
    draft(db, "f1", content(2))
    res = run(db, DISCARD, {"f": "f1"})
    assert res.data["discardEvaluationFormDraft"] == {"has_draft": False, "version": 1}


def test_every_published_revision_is_kept_once(db):
    save(db, "f1", body=content(1, "A"))
    save(db, "f1", body=content(2, "B"))
    save(db, "f1", body=content(2, "B"))          # republish unchanged: no new revision
    save(db, "f1", body=content(3, "C"))
    versions = run(db, VERSIONS, {"f": "f1"}).data["getEvaluationFormVersions"]
    assert [v["version"] for v in versions] == [3, 2, 1]
    assert [v["is_current"] for v in versions] == [True, False, False]
    assert db.query(EvaluationFormVersion).count() == 3


def test_a_form_that_predates_history_gets_its_old_revision_saved_on_next_publish(db):
    db.add(EvaluationForm(form_id="old", title="old", form_content=json.loads(content(1, "Legacy")), created_by=1))
    db.commit()                                    # no version row, as for forms created before this feature
    save(db, "old", body=content(2, "New"))
    rows = {v.version: v for v in db.query(EvaluationFormVersion).filter_by(form_id="old")}
    assert set(rows) == {1, 2} and rows[1].form_content["fields"][0]["label"] == "Legacy 0"


def test_restore_goes_to_the_draft_not_live(db):
    save(db, "f1", body=content(1, "A"))
    save(db, "f1", body=content(2, "B"))
    out = run(db, RESTORE, {"f": "f1", "v": 1}).data["restoreEvaluationFormVersion"]
    assert out["has_draft"] and out["version"] == 2                      # still live v2
    assert json.loads(out["draft_content"])["fields"][0]["label"] == "A 0"
    assert run(db, RESTORE, {"f": "f1", "v": 99}).errors


def test_duplicate_copies_live_content_with_ai_off(db):
    save(db, "f1", ai=True, body=content(2, "Src"))
    draft(db, "f1", content(5, "Unpublished"))                           # drafts are not copied
    out = run(db, DUPLICATE, {"f": "f1", "t": None}).data["duplicateEvaluationForm"]
    assert out["title"] == "Copy of f1" and out["ai_enabled"] is False and out["version"] == 1
    assert out["form_id"] != "f1" and len(json.loads(out["form_content"])["fields"]) == 2
    assert run(db, DUPLICATE, {"f": "missing", "t": None}).errors
    named = run(db, DUPLICATE, {"f": "f1", "t": "  Q4 form "}).data["duplicateEvaluationForm"]
    assert named["title"] == "Q4 form"


def test_deleting_a_form_removes_its_history(db):
    save(db, "f1")
    save(db, "f1", body=content(2))
    form = db.query(EvaluationForm).filter_by(form_id="f1").one()
    res = run(db, "mutation($i: ID!) { deleteEvaluationForm(id: $i) }", {"i": form.id})
    assert res.data["deleteEvaluationForm"] is True
    assert db.query(EvaluationFormVersion).count() == 0
