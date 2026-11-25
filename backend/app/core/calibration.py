"""
AI-vs-human calibration statistics and review-sample selection.

Pure functions (no DB) so the maths is unit-tested. "bias" is always
`human - AI`: a NEGATIVE bias means the AI scores HIGHER than the reviewers, a
POSITIVE bias means the AI is HARSHER than the reviewers.
"""
from dataclasses import dataclass
from typing import Iterable, Optional

AGREEMENT_TOLERANCE = 10.0     # points: |AI - human| within this counts as agreement
TARGET_REVIEWS = 20            # reviews needed before the numbers are meaningful
BIAS_NOTICEABLE = 5.0          # points: below this the AI is called "about right"
BIAS_SEVERE = 15.0


@dataclass(frozen=True)
class PairStats:
    n: int
    bias: Optional[float]
    mean_abs_error: Optional[float]
    agreement_percent: Optional[float]


def pair_stats(pairs: Iterable[tuple[float, float]]) -> PairStats:
    """pairs of (ai_score, human_score)."""
    deltas = [h - a for a, h in pairs if a is not None and h is not None]
    if not deltas:
        return PairStats(0, None, None, None)
    n = len(deltas)
    return PairStats(
        n=n,
        bias=round(sum(deltas) / n, 1),
        mean_abs_error=round(sum(abs(d) for d in deltas) / n, 1),
        agreement_percent=round(100 * sum(1 for d in deltas if abs(d) <= AGREEMENT_TOLERANCE) / n, 1),
    )


def verdict(bias: Optional[float], n: int, target: int = TARGET_REVIEWS) -> tuple[str, str]:
    """(level, plain-English sentence). level: not_enough_data | about_right | harsh | generous"""
    if n < 5 or bias is None:
        return ("not_enough_data",
                f"Not enough reviewed calls yet ({n}). Review at least {target} for a reliable picture.")
    size = abs(bias)
    if size < BIAS_NOTICEABLE:
        return "about_right", "The AI's scores are close to your reviewers' on average."
    degree = "much " if size >= BIAS_SEVERE else ""
    if bias > 0:
        return ("harsh",
                f"The AI scores {degree}lower than your reviewers: about {size:.0f} points too harsh on average.")
    return ("generous",
            f"The AI scores {degree}higher than your reviewers: about {size:.0f} points too generous on average.")


@dataclass(frozen=True)
class ComplianceVerdictStats:
    reviewed: int
    confirmed: int
    rejected: int
    precision_percent: Optional[float]   # of reviewed AI flags, how many a human upheld


def compliance_stats(outcomes: Iterable[str]) -> ComplianceVerdictStats:
    confirmed = rejected = 0
    for o in outcomes:
        if o == "confirmed":
            confirmed += 1
        elif o == "rejected":
            rejected += 1
    reviewed = confirmed + rejected
    return ComplianceVerdictStats(
        reviewed, confirmed, rejected,
        round(100 * confirmed / reviewed, 1) if reviewed else None,
    )


def pick_review_sample(candidates: list[dict], n: int) -> list[dict]:
    """Choose calls for a human to score so the sample exercises the AI across its range.

    candidates: [{"id", "qa", "violations"}...] (processed, not yet reviewed).
    Spread across score bands (low / middle / high) so a harsh AI can't hide by only
    being checked on calls it already rates low, then reserve a few calls the AI
    flagged for compliance. Deterministic: ties are broken by id.
    """
    if n <= 0 or not candidates:
        return []
    ordered = sorted(candidates, key=lambda c: (c["qa"] if c["qa"] is not None else -1, c["id"]))
    flagged_quota = min(max(1, n // 4), n)
    chosen: list[dict] = []
    seen: set = set()

    flagged = [c for c in ordered if c.get("violations", 0) > 0]
    # evenly spaced picks from the flagged calls
    for c in _spread(flagged, flagged_quota):
        chosen.append(c)
        seen.add(c["id"])

    rest = [c for c in ordered if c["id"] not in seen]
    for c in _spread(rest, n - len(chosen)):
        chosen.append(c)
    return chosen[:n]


def _spread(items: list[dict], k: int) -> list[dict]:
    if k <= 0 or not items:
        return []
    if k >= len(items):
        return list(items)
    step = (len(items) - 1) / (k - 1) if k > 1 else 0
    idx = sorted({round(i * step) for i in range(k)})
    out = [items[i] for i in idx]
    # rounding can collapse picks; top up deterministically
    i = 0
    while len(out) < k and i < len(items):
        if items[i] not in out:
            out.append(items[i])
        i += 1
    return out
