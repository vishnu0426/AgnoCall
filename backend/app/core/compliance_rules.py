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


# A violation whose own explanation says the rule was MET is the AI listing a passed check as a failure.
_NEGATION = re.compile(
    r"\b(not|n't|no|never|without|fail\w*|lack\w*|missing|absent|omit\w*|skip\w*|neither|nor|did not|didn't|"
    r"incomplete|insufficient|improper\w*|inappropriate\w*|unprofessional\w*)\b", re.I)
_AFFIRMATION = re.compile(
    r"\b(greeted|did greet|stated (their|his|her) name|introduced (themselves|himself|herself)|did verify|"
    r"verified the customer|properly|appropriately|correctly|thanked|closed the call|complied|"
    r"met the (requirement|rule)|followed the|was satisfied|no violation)\b", re.I)


def contradicts_itself(explanation: str | None) -> bool:
    """True when the explanation affirms the agent did the right thing and says nothing negative.
    Deliberately narrow: a real violation almost always contains a negative word ("did not greet")."""
    text = (explanation or "").strip()
    return bool(text) and bool(_AFFIRMATION.search(text)) and not _NEGATION.search(text)
