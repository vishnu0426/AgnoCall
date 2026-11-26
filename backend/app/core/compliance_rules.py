"""
One name and one category per compliance rule.

The AI writes a free-text `category` for every violation ("Security", "security", "Identity Verification",
"Process", "procedure", ...), so the same rule showed up under dozens of labels. The rule code is stable, so
the label and category are derived from it here and the AI's wording is ignored.
"""
import re

# rule_code -> (label shown to people, category)
RULES: dict[str, tuple[str, str]] = {
    "GREETING_MISSING": ("Greeting missing", "Process"),
    "CLOSING_MISSING": ("Closing missing", "Process"),
    "IDENTITY_VERIFICATION_MISSING": ("Identity not verified", "Security"),
    "ABUSIVE_LANGUAGE": ("Abusive language", "Conduct"),
}


def normalise_code(code: str | None) -> str:
    """'Greeting missing', 'greeting-missing' and 'GREETING_MISSING' are the same rule."""
    c = re.sub(r"[^A-Za-z0-9]+", "_", (code or "").strip()).strip("_").upper()
    return c or "UNKNOWN"


def rule_label(code: str | None) -> str:
    c = normalise_code(code)
    return RULES[c][0] if c in RULES else c.replace("_", " ").capitalize()


def rule_category(code: str | None, raw_category: str | None = None) -> str:
    c = normalise_code(code)
    if c in RULES:
        return RULES[c][1]
    raw = (raw_category or "").strip()
    return raw.replace("_", " ").title() if raw else "Other"
