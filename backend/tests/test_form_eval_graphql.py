"""Server-side guardrails of saveEvaluationForm(ai_enabled) — the real schema/resolvers."""
import json

import pytest

pytest.importorskip("strawberry")

from app.api.forms_graphql import GraphQLContext, schema  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.models.models import EvaluationForm, FormBuilderUser  # noqa: E402

SAVE = """
mutation($form_id: String!, $title: String!, $content: String!, $ai: Boolean) {
  saveEvaluationForm(form_id: $form_id, title: $title, form_content: $content, ai_enabled: $ai) {
    form_id ai_enabled version
  }
}"""
LIMITS = "{ getAIEvaluationLimits { feature_enabled enabled_count max_enabled_forms max_questions } }"


def content(n_fields=1, label="Greeting"):
    return json.dumps({"hasScoring": True, "total_score": 100, "fields": [
        {"id": f"f{i}", "type": "yesno", "label": f"{label} {i}", "max_score": 100 // n_fields}
        for i in range(n_fields)]})


ADMIN_USER = {"id": 1, "username": "admin", "role": "admin"}
ANON = object()          # a signed-out visitor


def run(db, query, variables=None, user=None):
    # The API requires a sign-in for everything except the public form-fill operations, so tests act as an
    # administrator unless they say otherwise.
    user = None if user is ANON else (user or ADMIN_USER)
    return schema.execute_sync(query, variable_values=variables or {},
                               context_value=GraphQLContext(db=db, user=user))


def save(db, form_id, ai=None, body=None, user=None):
    return run(db, SAVE, {"form_id": form_id, "title": form_id, "content": body or content(), "ai": ai}, user)


@pytest.fixture(autouse=True)
def _settings(db):
    get_settings.cache_clear()
    db.add(FormBuilderUser(username="admin", role="admin"))
    db.commit()
    yield
    get_settings.cache_clear()


def test_new_forms_default_to_ai_off(db):
    r = save(db, "a")
    assert r.errors is None
    assert r.data["saveEvaluationForm"]["ai_enabled"] is False


def test_enable_and_flag_is_sticky_when_client_omits_it(db):
    assert save(db, "a", ai=True).data["saveEvaluationForm"]["ai_enabled"] is True
    # an older client that doesn't send ai_enabled must not switch it off
    r = save(db, "a", ai=None, body=content(label="Changed"))
    assert r.data["saveEvaluationForm"]["ai_enabled"] is True
    assert db.query(EvaluationForm).one().ai_enabled_at is not None


def test_version_bumps_only_when_content_changes(db):
    assert save(db, "a").data["saveEvaluationForm"]["version"] == 1
    assert save(db, "a").data["saveEvaluationForm"]["version"] == 1            # same content
    assert save(db, "a", body=content(label="New")).data["saveEvaluationForm"]["version"] == 2


def test_cap_is_enforced_server_side(db, monkeypatch):
    monkeypatch.setenv("AI_FORM_EVAL_MAX_ENABLED_FORMS", "2")
    get_settings.cache_clear()
    assert save(db, "a", ai=True).errors is None
    assert save(db, "b", ai=True).errors is None
    r = save(db, "c", ai=True)
    assert r.errors and "Limit reached" in r.errors[0].message
    assert db.query(EvaluationForm).filter_by(form_id="c").count() == 0 \
        or not db.query(EvaluationForm).filter_by(form_id="c").one().ai_enabled
    # already-enabled forms can still be edited at the cap
    assert save(db, "a", ai=True, body=content(label="Edit")).errors is None
    # freeing a slot lets another in
    assert save(db, "b", ai=False).errors is None
    assert save(db, "c", ai=True).errors is None
    lim = run(db, LIMITS).data["getAIEvaluationLimits"]
    assert (lim["enabled_count"], lim["max_enabled_forms"]) == (2, 2)


def test_form_with_nothing_for_the_ai_to_answer_is_rejected(db):
    body = json.dumps({"hasScoring": False, "fields": [{"id": "s", "type": "signature", "label": "Sign"}]})
    r = save(db, "a", ai=True, body=body)
    assert r.errors and "no fields the AI can answer" in r.errors[0].message


def test_question_limit(db, monkeypatch):
    monkeypatch.setenv("AI_FORM_EVAL_MAX_QUESTIONS", "3")
    get_settings.cache_clear()
    r = save(db, "a", ai=True, body=content(n_fields=4))
    assert r.errors and "limit is 3" in r.errors[0].message


def test_authenticated_non_admin_cannot_enable(db):
    r = save(db, "a", ai=True, user={"id": 7, "username": "bob", "role": "agent"})
    assert r.errors and "administrators" in r.errors[0].message
    assert save(db, "a", ai=True, user={"id": 1, "username": "admin", "role": "admin"}).errors is None


def test_non_admin_can_be_forbidden_by_setting(db, monkeypatch):
    monkeypatch.setenv("AI_FORM_EVAL_REQUIRE_ADMIN", "true")
    get_settings.cache_clear()
    r = save(db, "a", ai=True, user={"id": 7, "username": "bob", "role": "agent"})
    assert r.errors and "administrator" in r.errors[0].message


def test_signed_out_visitors_are_refused_everything_but_the_public_form_page(db):
    assert save(db, "a", ai=True, user=ANON).errors                         # cannot save or enable AI
    assert run(db, LIMITS, user=ANON).errors                               # cannot read limits
    assert run(db, "{ __schema { types { name } } }", user=ANON).errors    # no introspection
    assert run(db, "{ getEvaluationForms { id } }", user=ANON).errors      # cannot list forms


def test_kill_switch_blocks_enabling(db, monkeypatch):
    monkeypatch.setenv("AI_FORM_EVAL_ENABLED", "false")
    get_settings.cache_clear()
    r = save(db, "a", ai=True)
    assert r.errors and "disabled on this deployment" in r.errors[0].message
    assert run(db, LIMITS).data["getAIEvaluationLimits"]["feature_enabled"] is False
