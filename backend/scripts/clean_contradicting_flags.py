"""
Find (and optionally remove) compliance flags whose own explanation says the rule was met, e.g.
"GREETING_MISSING: The agent greeted the customer and stated their name." See docs/known-issues.md BUG-001.

  python scripts/clean_contradicting_flags.py            # list them only
  python scripts/clean_contradicting_flags.py --apply    # delete them
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.compliance_rules import contradicts_itself  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models.models import Call, ComplianceViolation  # noqa: E402


def main(apply: bool) -> None:
    db = SessionLocal()
    try:
        rows = [v for v in db.query(ComplianceViolation).all() if contradicts_itself(v.explanation)]
        for v in rows:
            call = db.query(Call).filter(Call.id == v.call_id).first()
            print(f"{v.rule_code:30} {v.severity:8} {call.original_filename if call else v.call_id}\n    {v.explanation}")
        print(f"\n{len(rows)} contradicting flag(s).", "Deleted." if apply else "Nothing changed (add --apply to delete).")
        if apply:
            for v in rows:
                db.delete(v)
            db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main("--apply" in sys.argv)
