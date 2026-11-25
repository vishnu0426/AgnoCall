"""
Attach calls to agents.

Agents come from three places: an explicit upload field, the extension parsed
from the recording filename (app/core/filename_meta.py), or a manager renaming a
placeholder. A call is only ever attached to an agent we can actually identify;
filename inference creates a placeholder ("Extension 1001") the manager can
rename once, after which every past and future call under that extension reads
with the real name.
"""
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.filename_meta import parse_call_filename
from app.models.models import Agent, Call


def agent_for_extension(db: Session, extension: str) -> Agent:
    """Get-or-create the agent for a PBX extension. A unique index on
    external_agent_id makes the create race-safe: if two workers create the same
    extension at once, the loser re-reads the winner's row."""
    agent = db.query(Agent).filter(Agent.external_agent_id == extension).first()
    if agent:
        return agent
    try:
        with db.begin_nested():
            agent = Agent(external_agent_id=extension, name=f"Extension {extension}")
            db.add(agent)
            db.flush()
    except IntegrityError:
        agent = db.query(Agent).filter(Agent.external_agent_id == extension).first()
    return agent


def agent_for_upload(db: Session, external_id: str | None, name: str | None) -> Agent | None:
    """Agent named in an upload form. Matches on the external id when given, else on the
    exact name; never on a NULL external id (that would match an arbitrary unrelated agent)."""
    external_id = (external_id or "").strip() or None
    name = (name or "").strip() or None
    if not external_id and not name:
        return None
    if external_id:
        agent = db.query(Agent).filter(Agent.external_agent_id == external_id).first()
    else:
        agent = db.query(Agent).filter(Agent.name == name, Agent.external_agent_id.is_(None)).first()
    if not agent:
        agent = Agent(external_agent_id=external_id, name=name or f"Extension {external_id}")
        db.add(agent)
        db.flush()
    return agent


def apply_filename_metadata(db: Session, call: Call) -> bool:
    """Fill in agent and customer number from the call's filename when they are not
    already known. Never overrides an agent that is already set. Returns whether the
    call changed; the caller commits."""
    parties = parse_call_filename(call.original_filename)
    changed = False
    meta = dict(call.call_metadata or {})
    if parties.customer_number and meta.get("customer_number") != parties.customer_number:
        meta["customer_number"] = parties.customer_number
        changed = True
    if parties.internal and not meta.get("internal_call"):
        meta["internal_call"] = True
        changed = True
    if parties.agent_extension and call.agent_id is None:
        call.agent_id = agent_for_extension(db, parties.agent_extension).id
        changed = True
    if changed:
        call.call_metadata = meta
    return changed
