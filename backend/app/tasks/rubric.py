"""
The scoring rubric the LLM is given for the built-in QA and compliance checks.

Why this exists: the QA prompt used to say only "score these criteria 0-100"
with bare names (greeting, empathy, ...). With no definition of what a good
score looks like, a model has to invent a scale, and it tends to invent a harsh
one: the live data showed a median QA of 12 and every processed call carrying
a compliance violation. A rubric gives each criterion a definition and score
anchors, and the compliance wording makes "flag only when clearly violated, with
an exact quote" explicit.

Bump RUBRIC_VERSION whenever any wording below changes. It is stored on every
analysed call (call_metadata["rubric_version"]) so scores produced by different
rubric versions are never silently mixed in calibration.
"""

RUBRIC_VERSION = "qa-rubric/v2"

# criterion -> (what is assessed, what a high score looks like, what a low score looks like)
QA_RUBRIC: dict[str, tuple[str, str, str]] = {
    "greeting": (
        "How the agent opened the call.",
        "Greets the customer, states the company and/or their own name, offers help.",
        "No greeting, or jumps straight into business with no opening at all.",
    ),
    "identity_verification": (
        "Whether the agent verified who they were speaking to before discussing account details.",
        "Asks for and confirms identifying details (name, email, last digits of a card, account id).",
        "Discusses account-specific information without any verification. "
        "Score null if the call needed no account access (e.g. a general question).",
    ),
    "listening": (
        "Whether the agent let the customer explain and understood the issue.",
        "Does not interrupt, reflects the problem back correctly, asks relevant follow-up questions.",
        "Repeatedly interrupts, ignores what was said, makes the customer repeat themselves.",
    ),
    "empathy": (
        "Whether the agent acknowledged the customer's situation and feelings.",
        "Acknowledges frustration or difficulty sincerely and responds to it.",
        "Dismissive or cold when the customer is clearly upset. "
        "A calm, neutral customer does not require emotional language: score on how well the tone matches.",
    ),
    "communication": (
        "Clarity of the agent's explanations.",
        "Clear, structured, jargon-free, confirms understanding.",
        "Confusing, contradictory, or full of unexplained jargon.",
    ),
    "professionalism": (
        "Tone and conduct.",
        "Courteous, patient, appropriate language throughout.",
        "Rude, sarcastic, argumentative or unprofessional.",
    ),
    "knowledge": (
        "Accuracy and confidence of the information given.",
        "Correct, complete answers; knows the process or finds the answer.",
        "Wrong information, repeated 'I don't know' with no path to an answer.",
    ),
    "resolution": (
        "Whether the customer's issue was actually handled.",
        "Issue resolved, or a clear, agreed next step with an owner and timeframe.",
        "Issue left unresolved with no next step.",
    ),
    "closing": (
        "How the agent ended the call.",
        "Summarises or confirms outcome, asks if anything else is needed, thanks the customer.",
        "Call ends abruptly with no wrap-up. Score null if the call was cut off before a natural close.",
    ),
}

SCORE_ANCHORS = (
    "Scoring scale (use the whole range, anchor to these bands):\n"
    "- 90-100: excellent, a model example of this behaviour\n"
    "- 75-89: good, meets the standard with minor gaps\n"
    "- 60-74: acceptable, meets the basics but with clear room to improve\n"
    "- 40-59: weak, the behaviour is attempted but falls short\n"
    "- 0-39: poor, the behaviour is missing or clearly wrong\n"
    "Judge each criterion only on evidence in the transcript. If a criterion genuinely cannot "
    "be assessed from this call, return score null (do not return 0). Do not lower a score "
    "because the call was short, unless the criterion itself was required and missing."
)

COMPLIANCE_GUIDANCE = (
    "Compliance rules: flag a rule ONLY if the transcript clearly shows it was broken. "
    "Every flag needs an exact quote from the transcript as evidence and its timestamp. "
    "If the evidence is ambiguous, or the rule did not apply to this call, do NOT flag it. "
    "An empty list is the correct answer for a compliant call."
)


def qa_rubric_text(criteria: list[str]) -> str:
    lines = []
    for c in criteria:
        what, high, low = QA_RUBRIC.get(c, (c, "", ""))
        lines.append(f"- {c}: {what}\n    high: {high}\n    low: {low}")
    return "\n".join(lines)
