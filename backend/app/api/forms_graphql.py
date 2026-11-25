"""GraphQL layer for the Forms module.

Direct port of the FB project's graphql/typeDefs.js + graphql/resolvers.js.
`auto_camel_case=False` keeps wire names verbatim (form_id, createdAt,
getEvaluationForms, saveEvaluationForm...) so the original Apollo Client
documents work unchanged. Like the original, auth is optional here: the JWT
is read when present, but resolvers fall back to the first user (or a
auto-created "system" user) so forms can always be saved.
"""

import json
import logging
import time
from datetime import datetime
from typing import List, Optional
from urllib.parse import urlencode

import httpx
import jwt
import strawberry
from fastapi import Depends, Request
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from strawberry.fastapi import BaseContext, GraphQLRouter
from strawberry.schema.config import StrawberryConfig

from app.core.config import get_settings
from app.core import settings_store as store
from app.core.database import get_db
from app.core.ids import is_uuid
from app.models.models import EvaluationForm, EvaluationFormVersion, EvaluationResponse, FormBuilderUser
from app.tasks import form_eval

logger = logging.getLogger("agnocall.form_eval")


class GraphQLContext(BaseContext):
    def __init__(self, db: Session, user: Optional[dict] = None):
        self.db = db
        self.user = user


def _user_from_request(request: Request) -> Optional[dict]:
    """Parse an optional `Authorization: Bearer <jwt>` header (never enforced)."""
    auth_header = request.headers.get("authorization")
    if not auth_header:
        return None
    token = auth_header.split(" ", 1)[1] if " " in auth_header else auth_header
    try:
        return jwt.decode(token, get_settings().forms_jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def get_context(request: Request, db: Session = Depends(get_db)) -> GraphQLContext:
    return GraphQLContext(db=db, user=_user_from_request(request))


def _get_creator_id(db: Session, context: GraphQLContext) -> int:
    # Ported from getCreatorId(): JWT user → first user → create system user.
    if context.user and context.user.get("id"):
        return int(context.user["id"])
    any_user = db.query(FormBuilderUser).order_by(FormBuilderUser.id.asc()).first()
    if any_user:
        return any_user.id
    system_user = FormBuilderUser(
        username="system",
        email="system@formbuilder.com",
        first_name="System",
        last_name="User",
        role="admin",
        is_active=True,
    )
    db.add(system_user)
    db.commit()
    db.refresh(system_user)
    return system_user.id


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


@strawberry.type
class EvaluationFormType:
    id: strawberry.ID
    form_id: str
    title: str
    form_content: str  # JSONB column exposed as a JSON-encoded string
    created_by: strawberry.ID
    ai_enabled: bool = False  # when true, every new call is scored by the LLM against this form
    version: int = 1  # increments whenever form_content changes
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
    # Unpublished edits (see EvaluationForm.draft_*). The fields above are always what is LIVE.
    has_draft: bool = False
    draft_title: Optional[str] = None
    draft_content: Optional[str] = None  # JSON string
    draft_ai_enabled: Optional[bool] = None
    draft_updatedAt: Optional[str] = None


@strawberry.type
class EvaluationFormVersionType:
    version: int
    title: str
    publishedAt: Optional[str] = None
    publishedBy: Optional[int] = None
    is_current: bool = False


@strawberry.type
class AITestAnswer:
    question_id: str
    label: str
    status: str  # answered | not_applicable | missing | invalid
    value: Optional[str] = None  # shown as the person would read it (an option's label, Yes/No, a number)
    evidence: Optional[str] = None
    timestamp: Optional[float] = None
    confidence: Optional[float] = None
    evidence_verified: Optional[bool] = None  # false = the quoted evidence was not found in the transcript
    reason: Optional[str] = None


@strawberry.type
class AITestResult:
    """What the AI WOULD record for one call. Nothing is saved."""
    score: Optional[float] = None
    total_score: float = 100
    questions: int = 0
    answered: int = 0
    coverage: float = 0.0
    unverified_evidence: int = 0
    model: str = ""
    answers: List[AITestAnswer] = strawberry.field(default_factory=list)


@strawberry.type
class TestCallOption:
    id: strawberry.ID
    filename: str
    call_date: Optional[str] = None
    duration_seconds: Optional[int] = None


@strawberry.type
class EvaluationResponseType:
    id: strawberry.ID
    form_id: str
    inum: Optional[str] = None
    call_id: Optional[str] = None  # AgnoCall: call the evaluation was scored on
    responses: Optional[str] = None  # JSON-encoded string
    tags: Optional[str] = None  # JSON-encoded string
    user_id: Optional[strawberry.ID] = None
    score: Optional[float] = None
    source: str = "human"  # "human" | "ai"
    form_version: Optional[int] = None  # revision of the form an AI response was scored with
    evidence: Optional[str] = None  # JSON string: per-answer audit trail (+ "_meta") for AI responses
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None


@strawberry.type
class AIRunResult:
    status: str  # queued | already_queued
    message: str


@strawberry.type
class AIBackfillResult:
    eligible: int  # processed calls in range with no AI evaluation of this form yet (capped)
    truncated: bool  # more eligible calls exist than the per-request cap
    queued: bool  # false for a dry run
    max_calls: int


@strawberry.type
class AIEvaluationLimits:
    feature_enabled: bool
    enabled_count: int
    max_enabled_forms: int
    max_questions: int


def _form_to_type(form: EvaluationForm) -> EvaluationFormType:
    return EvaluationFormType(
        id=strawberry.ID(str(form.id)),
        form_id=form.form_id,
        title=form.title,
        form_content=json.dumps(form.form_content),
        created_by=strawberry.ID(str(form.created_by)),
        ai_enabled=bool(form.ai_enabled),
        version=form.version or 1,
        createdAt=_iso(form.created_at),
        updatedAt=_iso(form.updated_at),
        has_draft=form.draft_content is not None,
        draft_title=form.draft_title,
        draft_content=json.dumps(form.draft_content) if form.draft_content is not None else None,
        draft_ai_enabled=form.draft_ai_enabled,
        draft_updatedAt=_iso(form.draft_updated_at),
    )


MAX_FORM_BYTES = 2 * 1024 * 1024


def _parse_form_content(raw: str) -> dict:
    """A form document is a JSON object with a `fields` list. Anything else is rejected before it can be
    stored (a draft that cannot be loaded back would lock the editor out of the form)."""
    if len(raw) > MAX_FORM_BYTES:
        raise ValueError("The form is too large to save.")
    try:
        content = json.loads(raw)
    except ValueError:
        raise ValueError("The form content is not valid JSON.")
    if not isinstance(content, dict) or not isinstance(content.get("fields", []), list):
        raise ValueError("The form content must be an object with a list of fields.")
    return content


def _record_version(db: Session, form: EvaluationForm, actor_id: Optional[int]) -> None:
    """Keep a snapshot of the form's CURRENT live revision (once per version number)."""
    exists = (db.query(EvaluationFormVersion.id)
              .filter(EvaluationFormVersion.form_id == form.form_id,
                      EvaluationFormVersion.version == (form.version or 1)).first())
    if exists:
        return
    db.add(EvaluationFormVersion(
        form_id=form.form_id, version=form.version or 1, title=form.title, form_content=form.form_content,
        published_by=actor_id, published_at=form.updated_at or datetime.utcnow(),
    ))


def _response_to_type(resp: EvaluationResponse) -> EvaluationResponseType:
    return EvaluationResponseType(
        id=strawberry.ID(str(resp.id)),
        form_id=resp.form_id,
        inum=resp.inum,
        call_id=str(resp.call_id) if resp.call_id else None,
        responses=json.dumps(resp.responses) if resp.responses is not None else None,
        tags=json.dumps(resp.tags) if resp.tags is not None else None,
        user_id=strawberry.ID(str(resp.user_id)) if resp.user_id is not None else None,
        score=resp.score,
        source=resp.source or "human",
        form_version=resp.form_version,
        evidence=json.dumps(resp.evidence) if resp.evidence is not None else None,
        createdAt=_iso(resp.created_at),
        updatedAt=_iso(resp.updated_at),
    )


def _actor(context: GraphQLContext) -> dict:
    user = context.user or {}
    uid = user.get("id")
    try:
        uid = int(uid) if uid is not None else None
    except (TypeError, ValueError):
        uid = None
    return {"id": uid, "label": user.get("username") or "anonymous", "role": user.get("role")}


def _require_ai_admin(context: GraphQLContext, what: str) -> None:
    """Anything that spends LLM budget needs an admin. Authenticated non-admins
    are always refused. Anonymous access is the pre-existing (unauthenticated)
    behaviour of this module and is refused only when
    AI_FORM_EVAL_REQUIRE_ADMIN=true."""
    if context.user is None and store.effective(context.db).ai_form_eval_require_admin:
        raise PermissionError(f"Sign in as an administrator to {what}.")
    if context.user is not None and _actor(context)["role"] != "admin":
        raise PermissionError(f"Only administrators can {what}.")


def _check_ai_enable_allowed(db: Session, context: GraphQLContext, form_id: str,
                             content: dict, enabling_now: bool) -> None:
    """Server-side guardrails for AI-enabling a form. Raises with a message the
    builder shows verbatim. The UI toggle is a convenience; this is the gate."""
    settings = store.effective(db)
    if not settings.ai_form_eval_enabled:
        raise ValueError("AI form evaluation is disabled on this deployment.")
    actor = _actor(context)
    if enabling_now:
        _require_ai_admin(context, "enable AI evaluation on a form")
    problems = form_eval.validate_form_for_ai(content, settings.ai_form_eval_max_questions)
    if problems:
        raise ValueError("Cannot enable AI evaluation: " + " ".join(problems))
    if enabling_now:
        # Serialise concurrent enables so two admins can't both slip under the cap.
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(947201)"))
        others = (
            db.query(func.count(EvaluationForm.id))
            .filter(EvaluationForm.ai_enabled.is_(True), EvaluationForm.form_id != form_id)
            .scalar()
        ) or 0
        if others >= settings.ai_form_eval_max_enabled_forms:
            raise ValueError(
                f"Limit reached: {others} forms already have AI evaluation enabled "
                f"(maximum {settings.ai_form_eval_max_enabled_forms}). Every enabled form adds one "
                "LLM call to every processed call. Disable another form first."
            )


def _display_value(q, value):
    """An answer as a person reads it: the option's label, Yes/No, or the plain value."""
    if value is None:
        return None
    if isinstance(value, list):
        return ", ".join(str(_display_value(q, v)) for v in value)
    for option in form_eval._options(q.field):
        if form_eval._option_value(option) == value:
            return str(form_eval._option_label(option))
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


@strawberry.type
class Query:
    @strawberry.field
    def getCallsForFormTest(self, info: strawberry.Info, limit: int = 25) -> List[TestCallOption]:
        """Recent processed calls that have a transcript: what "try it on a call" can be run against."""
        from app.models.models import Call, CallStatus, Transcript
        db = info.context.db
        rows = (db.query(Call).join(Transcript, Transcript.call_id == Call.id)
                .filter(Call.status == CallStatus.processed)
                .order_by(Call.uploaded_at.desc()).limit(max(1, min(limit, 50))).all())
        return [TestCallOption(id=strawberry.ID(str(c.id)), filename=c.original_filename,
                               call_date=_iso(c.call_date or c.uploaded_at), duration_seconds=c.duration_seconds)
                for c in rows]

    @strawberry.field
    def getEvaluationFormVersions(self, info: strawberry.Info, form_id: str) -> List[EvaluationFormVersionType]:
        """Published revisions of a form, newest first."""
        db = info.context.db
        form = db.query(EvaluationForm).filter(EvaluationForm.form_id == form_id).first()
        if not form:
            return []
        rows = (db.query(EvaluationFormVersion).filter(EvaluationFormVersion.form_id == form_id)
                .order_by(EvaluationFormVersion.version.desc()).limit(100).all())
        return [EvaluationFormVersionType(version=r.version, title=r.title, publishedAt=_iso(r.published_at),
                                          publishedBy=r.published_by, is_current=r.version == (form.version or 1))
                for r in rows]

    @strawberry.field
    def translateTexts(
        self,
        info: strawberry.Info,
        texts: List[str],
        target: str,
        source: Optional[str] = "en",
    ) -> List[Optional[str]]:
        """Auto-translate texts to `target` language (multilingual builder).
        Returns one entry per input text; None = translation unavailable."""
        results: List[Optional[str]] = []
        pending: list = []  # (result index, text)
        src = source or "en"
        for text in texts:
            if not text or not text.strip() or src == target:
                results.append(text)
                continue
            key = (src, target, text)
            if key in _translate_cache:
                results.append(_translate_cache[key])
                continue
            results.append(None)
            pending.append((len(results) - 1, text))

        for idx, text in pending:
            try:
                with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                    translated = ""
                    for provider in (_translate_one_gtx, _translate_one_mymemory):
                        try:
                            translated = provider(client, src, target, text)
                            if translated:
                                break
                        except Exception:
                            continue
                    if translated:
                        _translate_cache[(src, target, text)] = translated
                        results[idx] = translated
            except Exception:
                pass  # leave None - frontend falls back to source text
        return results

    @strawberry.field
    def getAIEvaluationLimits(self, info: strawberry.Info) -> AIEvaluationLimits:
        """Drives the builder's AI toggle: how many forms are AI-enabled vs the cap."""
        settings = store.effective(info.context.db)
        count = (
            info.context.db.query(func.count(EvaluationForm.id))
            .filter(EvaluationForm.ai_enabled.is_(True))
            .scalar()
        ) or 0
        return AIEvaluationLimits(
            feature_enabled=settings.ai_form_eval_enabled,
            enabled_count=count,
            max_enabled_forms=settings.ai_form_eval_max_enabled_forms,
            max_questions=settings.ai_form_eval_max_questions,
        )

    @strawberry.field
    def getEvaluationForms(self, info: strawberry.Info) -> Optional[List[EvaluationFormType]]:
        db = info.context.db
        forms = db.query(EvaluationForm).order_by(EvaluationForm.created_at.desc()).all()
        return [_form_to_type(f) for f in forms]

    @strawberry.field
    def getEvaluationForm(self, info: strawberry.Info, id: strawberry.ID) -> Optional[EvaluationFormType]:
        form = (
            info.context.db.query(EvaluationForm)
            .filter(EvaluationForm.id == str(id))
            .first()
        )
        return _form_to_type(form) if form else None

    @strawberry.field
    def getEvaluationResponses(
        self, info: strawberry.Info, call_id: Optional[str] = None
    ) -> Optional[List[EvaluationResponseType]]:
        db = info.context.db
        query = db.query(EvaluationResponse)
        if call_id:
            # AgnoCall: only the evaluations submitted for a given call.
            query = query.filter(EvaluationResponse.call_id == call_id)
        responses = query.order_by(EvaluationResponse.created_at.desc()).all()
        return [_response_to_type(r) for r in responses]

    @strawberry.field
    def getEvaluationResponse(self, info: strawberry.Info, id: strawberry.ID) -> Optional[EvaluationResponseType]:
        resp = (
            info.context.db.query(EvaluationResponse)
            .filter(EvaluationResponse.id == str(id))
            .first()
        )
        return _response_to_type(resp) if resp else None


# ---------------------------------------------------------------------------
# Auto-translation (multilingual form builder)
# ---------------------------------------------------------------------------
# Two providers, tried in order: Google's public gtx endpoint (best quality)
# then MyMemory (free, no key). Results are cached in-process; if both fail
# the entry stays None so the frontend falls back to the source text and the
# user can type the translation manually.
_TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
_MYMEMORY_URL = "https://api.mymemory.translated.net/get"
_translate_cache: dict = {}


def _fix_mojibake(text: str) -> str:
    """MyMemory sometimes returns UTF-8 bytes mis-decoded as cp1252/latin-1
    (e.g. 'à®•...' instead of Tamil). Repair it, or return "" if it can't be
    repaired so the next provider / source-text fallback is used."""
    if not text or not any(m in text for m in ("à®", "à¤", "Ã", "à¯", "â€")):
        return text
    for enc in ("cp1252", "latin-1"):
        try:
            fixed = text.encode(enc).decode("utf-8")
            if fixed:
                return fixed
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return ""


def _translate_one_gtx(client: "httpx.Client", src: str, target: str, text: str) -> str:
    resp = client.get(
        _TRANSLATE_URL,
        params={"client": "gtx", "sl": src, "tl": target, "dt": "t", "q": text},
    )
    resp.raise_for_status()
    data = resp.json()
    return _fix_mojibake("".join(seg[0] for seg in (data[0] or []) if seg and seg[0]).strip())


def _translate_one_mymemory(client: "httpx.Client", src: str, target: str, text: str) -> str:
    resp = client.get(
        _MYMEMORY_URL,
        params={"q": text, "langpair": f"{src}|{target}"},
    )
    resp.raise_for_status()
    data = resp.json()
    # MyMemory reports quota/errors in JSON rather than HTTP status
    translated = (data.get("responseData") or {}).get("translatedText") or ""
    if data.get("quotaFinished") or "MYMEMORY WARNING" in translated.upper():
        return ""
    translated = _fix_mojibake(translated.strip())
    # MyMemory's fuzzy memory can return an unrelated long sentence for short
    # words ("High" -> a whole sentence). Reject results wildly longer than the
    # source or with a weak match score so the source text is kept instead.
    if len(translated) > 4 * len(text) + 12:
        return ""
    matches = data.get("matches") or []
    best = max((float(m.get("match") or 0) for m in matches), default=1.0)
    if len(text.split()) <= 2 and best < 0.6:
        return ""
    return translated


@strawberry.type
class Mutation:
    @strawberry.mutation
    def saveEvaluationForm(
        self, info: strawberry.Info, form_id: str, title: str, form_content: str,
        ai_enabled: Optional[bool] = None,
    ) -> EvaluationFormType:
        db = info.context.db
        content = json.loads(form_content)
        existing = (
            db.query(EvaluationForm).filter(EvaluationForm.form_id == form_id).first()
        )
        # None = "leave the flag as it is" so older clients that don't send it
        # can't accidentally switch AI evaluation off (or on).
        will_be_enabled = bool(existing.ai_enabled) if (existing and ai_enabled is None) \
            else bool(ai_enabled)
        enabling_now = will_be_enabled and not (existing and existing.ai_enabled)
        if will_be_enabled:
            _check_ai_enable_allowed(db, info.context, form_id, content, enabling_now)
        actor = _actor(info.context)

        if existing:
            # The original stored the raw string (Sequelize coerced it); parsing
            # keeps the JSONB column an object so reads round-trip identically.
            _record_version(db, existing, existing.updated_by)       # keep what is being replaced
            if existing.form_content != content:
                existing.version = (existing.version or 1) + 1
            existing.title = title
            existing.form_content = content
            existing.draft_content = existing.draft_title = existing.draft_ai_enabled = None   # published
            existing.draft_updated_at = existing.draft_updated_by = None
            if ai_enabled is not None and bool(existing.ai_enabled) != ai_enabled:
                existing.ai_enabled = ai_enabled
                existing.ai_enabled_by = actor["id"]
                existing.ai_enabled_at = datetime.utcnow()
                logger.warning("AUDIT ai_form_eval %s form_id=%s actor=%s",
                               "ENABLED" if ai_enabled else "DISABLED", form_id, actor["label"])
            existing.updated_by = actor["id"]
            existing.updated_at = datetime.utcnow()
            _record_version(db, existing, actor["id"])
            db.commit()
            db.refresh(existing)
            return _form_to_type(existing)
        created = EvaluationForm(
            form_id=form_id,
            title=title,
            form_content=content,
            created_by=_get_creator_id(db, info.context),
            ai_enabled=will_be_enabled,
            ai_enabled_by=actor["id"] if will_be_enabled else None,
            ai_enabled_at=datetime.utcnow() if will_be_enabled else None,
        )
        if will_be_enabled:
            logger.warning("AUDIT ai_form_eval ENABLED form_id=%s actor=%s", form_id, actor["label"])
        db.add(created)
        db.flush()
        _record_version(db, created, actor["id"])
        db.commit()
        db.refresh(created)
        return _form_to_type(created)

    @strawberry.mutation
    def saveEvaluationFormDraft(
        self, info: strawberry.Info, form_id: str, title: str, form_content: str,
        ai_enabled: Optional[bool] = None,
    ) -> EvaluationFormType:
        """Store unpublished edits. The live form (what the AI and reviewers use) is not touched."""
        db = info.context.db
        content = _parse_form_content(form_content)
        form = db.query(EvaluationForm).filter(EvaluationForm.form_id == form_id).first()
        if not form:
            raise ValueError("Form not found.")
        if not title.strip():
            raise ValueError("The form needs a name.")
        actor = _actor(info.context)
        form.draft_content = content
        form.draft_title = title.strip()[:255]
        form.draft_ai_enabled = ai_enabled
        form.draft_updated_at = datetime.utcnow()
        form.draft_updated_by = actor["id"]
        db.commit()
        db.refresh(form)
        return _form_to_type(form)

    @strawberry.mutation
    def discardEvaluationFormDraft(self, info: strawberry.Info, form_id: str) -> EvaluationFormType:
        db = info.context.db
        form = db.query(EvaluationForm).filter(EvaluationForm.form_id == form_id).first()
        if not form:
            raise ValueError("Form not found.")
        form.draft_content = form.draft_title = form.draft_ai_enabled = None
        form.draft_updated_at = form.draft_updated_by = None
        db.commit()
        db.refresh(form)
        return _form_to_type(form)

    @strawberry.mutation
    def restoreEvaluationFormVersion(self, info: strawberry.Info, form_id: str, version: int) -> EvaluationFormType:
        """Load an older published revision into the DRAFT. Nothing goes live until it is published."""
        db = info.context.db
        form = db.query(EvaluationForm).filter(EvaluationForm.form_id == form_id).first()
        snap = (db.query(EvaluationFormVersion)
                .filter(EvaluationFormVersion.form_id == form_id, EvaluationFormVersion.version == version).first())
        if not form or not snap:
            raise ValueError("That version was not found.")
        form.draft_content = snap.form_content
        form.draft_title = snap.title
        form.draft_ai_enabled = form.ai_enabled
        form.draft_updated_at = datetime.utcnow()
        form.draft_updated_by = _actor(info.context)["id"]
        db.commit()
        db.refresh(form)
        return _form_to_type(form)

    @strawberry.mutation
    def duplicateEvaluationForm(self, info: strawberry.Info, form_id: str, title: Optional[str] = None) -> EvaluationFormType:
        """Copy a form's LIVE content into a new form. AI evaluation is always OFF on the copy: enabling
        it spends LLM budget on every call, so it must be a deliberate act (and is capped)."""
        db = info.context.db
        src = db.query(EvaluationForm).filter(EvaluationForm.form_id == form_id).first()
        if not src:
            raise ValueError("Form not found.")
        name = (title or "").strip() or f"Copy of {src.title}"
        actor = _actor(info.context)
        copy = EvaluationForm(
            form_id=f"form_{int(time.time() * 1000)}",
            title=name[:255],
            form_content=json.loads(json.dumps(src.form_content)),     # deep copy
            created_by=_get_creator_id(db, info.context),
            ai_enabled=False,
        )
        db.add(copy)
        db.flush()
        _record_version(db, copy, actor["id"])
        db.commit()
        db.refresh(copy)
        return _form_to_type(copy)

    @strawberry.mutation
    def testAIFormEvaluation(
        self, info: strawberry.Info, call_id: str, form_content: str, title: Optional[str] = None,
    ) -> AITestResult:
        """Dry run: have the AI answer THIS form (including unsaved edits) for one real call and show the
        answers, evidence and score, without saving anything. Costs one LLM request, so it needs the same
        permission as running AI evaluation, honours the kill switch, and is rate-limited per person."""
        from app.core import locks
        from app.models.models import Call, CallStatus
        from app.tasks import pipeline
        db = info.context.db
        _require_ai_admin(info.context, "test AI evaluation")
        settings = store.effective(db)
        if not settings.ai_form_eval_enabled:
            raise ValueError("AI form evaluation is disabled on this deployment.")
        content = _parse_form_content(form_content)
        call = db.query(Call).filter(Call.id == call_id).first() if is_uuid(call_id) else None
        if not call:
            raise ValueError("Call not found.")
        if call.status != CallStatus.processed:
            raise ValueError("The call has not finished processing yet.")
        segments = pipeline._load_segments(db, call.id)
        if not segments:
            raise ValueError("This call has no transcript to evaluate.")
        actor = _actor(info.context)
        if not locks.acquire(f"ai_form_test:{actor['label']}", 5):
            raise ValueError("Please wait a few seconds between tests.")

        transcript_text = pipeline._transcript_text(segments)
        try:
            payload, questions = pipeline.compute_form_evaluation(
                (title or "Form").strip() or "Form", content, pipeline.get_llm_provider(), transcript_text, settings,
                log_ctx=f"TEST call_id={call.id}",
            )
        except RuntimeError as exc:
            raise ValueError(f"The AI service did not respond: {exc}")
        logger.warning("AUDIT ai_form_eval TEST call_id=%s actor=%s", call.id, actor["label"])

        meta = payload["evidence"]["_meta"]
        answers = [
            AITestAnswer(
                question_id=q.id, label=q.label, status=a["status"],
                value=_display_value(q, a["value"]), evidence=a["evidence"] or None, timestamp=a["timestamp"],
                confidence=a["confidence"], evidence_verified=a["evidence_verified"], reason=a["reason"],
            )
            for q in questions for a in [payload["evidence"][q.id]]
        ]
        return AITestResult(
            score=payload["score"], total_score=float(content.get("total_score") or 100),
            questions=meta["questions"], answered=meta["counts"]["answered"], coverage=meta["coverage"],
            unverified_evidence=meta["unverified_evidence"], model=meta["model"], answers=answers,
        )

    @strawberry.mutation
    def runAIFormEvaluation(self, info: strawberry.Info, call_id: str, form_id: str) -> AIRunResult:
        """Evaluate one already-processed call against one AI-enabled form."""
        from app.models.models import Call, CallStatus
        from app.tasks import pipeline
        from app.tasks.celery_app import celery_app
        db = info.context.db
        _require_ai_admin(info.context, "run AI evaluation")
        if not store.effective(db).ai_form_eval_enabled:
            raise ValueError("AI form evaluation is disabled on this deployment.")
        form = db.query(EvaluationForm).filter(EvaluationForm.form_id == form_id).first()
        if not form or not form.ai_enabled:
            raise ValueError("AI evaluation is not enabled on this form.")
        call = db.query(Call).filter(Call.id == call_id).first()
        if not call:
            raise ValueError("Call not found.")
        if call.status != CallStatus.processed:
            raise ValueError("The call has not finished processing yet.")
        if not pipeline.claim_eval(call_id, form_id):
            return AIRunResult(status="already_queued", message="An evaluation for this call and form is already queued.")
        celery_app.send_task("app.tasks.pipeline.run_form_evaluation", args=[call_id, form_id])
        logger.warning("AUDIT ai_form_eval RUN call_id=%s form_id=%s actor=%s",
                       call_id, form_id, _actor(info.context)["label"])
        return AIRunResult(status="queued", message="Evaluation queued. Results appear on the call shortly.")

    @strawberry.mutation
    def backfillAIFormEvaluation(
        self, info: strawberry.Info, form_id: str,
        date_from: Optional[str] = None, date_to: Optional[str] = None, dry_run: bool = True,
    ) -> AIBackfillResult:
        """Score past calls with an AI-enabled form. Defaults to a DRY RUN that only
        reports how many calls would be evaluated, because every call costs one
        LLM request; the UI confirms the number, then re-sends with dry_run=false."""
        from app.tasks import pipeline
        from app.tasks.celery_app import celery_app
        db = info.context.db
        _require_ai_admin(info.context, "backfill AI evaluation")
        settings = store.effective(db)
        if not settings.ai_form_eval_enabled:
            raise ValueError("AI form evaluation is disabled on this deployment.")
        form = db.query(EvaluationForm).filter(EvaluationForm.form_id == form_id).first()
        if not form or not form.ai_enabled:
            raise ValueError("AI evaluation is not enabled on this form.")
        try:
            dfrom = datetime.fromisoformat(date_from) if date_from else None
            dto = datetime.fromisoformat(date_to) if date_to else None
        except ValueError:
            raise ValueError("Dates must be ISO-8601 (YYYY-MM-DD).")
        if dfrom and dto and dfrom > dto:
            raise ValueError("date_from must not be after date_to.")
        sel = pipeline.select_backfill_calls(db, form_id, dfrom, dto, settings.ai_form_eval_backfill_max_calls)
        if not dry_run and sel["call_ids"]:
            celery_app.send_task("app.tasks.pipeline.backfill_form_evaluation", args=[form_id, date_from, date_to])
            logger.warning("AUDIT ai_form_eval BACKFILL_REQUESTED form_id=%s eligible=%d actor=%s",
                           form_id, len(sel["call_ids"]), _actor(info.context)["label"])
        return AIBackfillResult(
            eligible=len(sel["call_ids"]), truncated=sel["truncated"],
            queued=bool(not dry_run and sel["call_ids"]), max_calls=settings.ai_form_eval_backfill_max_calls,
        )

    @strawberry.mutation
    def deleteEvaluationForm(self, info: strawberry.Info, id: strawberry.ID) -> bool:
        db = info.context.db
        form = db.query(EvaluationForm).filter(EvaluationForm.id == str(id)).first()
        if not form:
            return False
        db.query(EvaluationFormVersion).filter(EvaluationFormVersion.form_id == form.form_id).delete()
        db.delete(form)
        db.commit()
        return True

    @strawberry.mutation
    def saveEvaluationResponse(
        self,
        info: strawberry.Info,
        form_id: str,
        inum: Optional[str] = None,
        call_id: Optional[str] = None,
        responses: Optional[str] = None,
        tags: Optional[str] = None,
        user_id: Optional[strawberry.ID] = None,
        score: Optional[float] = None,
    ) -> EvaluationResponseType:
        db = info.context.db
        resolved_user_id: Optional[int] = None
        if user_id is not None:
            resolved_user_id = int(user_id)
        else:
            try:
                resolved_user_id = _get_creator_id(db, info.context)
            except Exception:
                resolved_user_id = None
        created = EvaluationResponse(
            inum=inum,
            form_id=form_id,
            call_id=call_id,
            responses=json.loads(responses) if responses else None,
            tags=json.loads(tags) if tags else [],
            user_id=resolved_user_id,
            score=score,
        )
        db.add(created)
        db.commit()
        db.refresh(created)
        return _response_to_type(created)

    @strawberry.mutation
    def updateEvaluationResponse(
        self,
        info: strawberry.Info,
        id: strawberry.ID,
        inum: Optional[str] = None,
        form_id: Optional[str] = None,
        call_id: Optional[str] = None,
        responses: Optional[str] = None,
        tags: Optional[str] = None,
        user_id: Optional[strawberry.ID] = None,
        score: Optional[float] = strawberry.UNSET,
    ) -> Optional[EvaluationResponseType]:
        # Edit an already-submitted evaluation: only the provided arguments are
        # applied (strawberry UNSET = not sent), so callers can update a subset
        # of fields without clobbering the rest.
        db = info.context.db
        resp = (
            db.query(EvaluationResponse)
            .filter(EvaluationResponse.id == str(id))
            .first()
        )
        if resp is None:
            return None
        if inum is not None:
            resp.inum = inum
        if form_id is not None:
            resp.form_id = form_id
        if call_id is not None:
            resp.call_id = call_id
        if responses is not None:
            resp.responses = json.loads(responses)
        if tags is not None:
            resp.tags = json.loads(tags)
        if user_id is not None:
            resp.user_id = int(user_id)
        if score is not strawberry.UNSET:
            # explicit null allowed: non-scoring forms store NULL
            resp.score = score
        resp.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(resp)
        return _response_to_type(resp)

    @strawberry.mutation
    def deleteEvaluationResponse(self, info: strawberry.Info, id: strawberry.ID) -> bool:
        deleted = (
            info.context.db.query(EvaluationResponse)
            .filter(EvaluationResponse.id == str(id))
            .delete()
        )
        info.context.db.commit()
        return deleted > 0


schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    # keep form_id / createdAt / getEvaluationForms verbatim on the wire
    config=StrawberryConfig(auto_camel_case=False),
)

# Mounted at /api/v1/graphql by main.py (the frontend's Apollo link targets
# `${NEXT_PUBLIC_API_BASE_URL}/graphql`).
graphql_router = GraphQLRouter(schema, context_getter=get_context, path="/graphql")
