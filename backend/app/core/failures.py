"""
Failure triage: turn the free-text `Call.failure_reason` into a category a QA
manager can act on, and say whether retrying can possibly help.

Derived on the fly from the stored text (no schema change), so historical
failures are classified too. Order matters: the first matching rule wins.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class FailureInfo:
    category: str
    label: str
    retryable: bool
    # Not a fault of the system or the pipeline (e.g. a silent recording).
    # Shown separately so it doesn't inflate the failure rate.
    expected: bool = False
    # One plain sentence for a non-technical reader: what happened and what to do.
    advice: str = ""


NO_SPEECH = FailureInfo("no_speech", "No speech detected", retryable=False, expected=True,
                        advice="The recording is silent or has no audible speech, so there is nothing to analyse.")
BAD_AUDIO = FailureInfo("bad_audio", "Audio could not be decoded", retryable=False,
                        advice="The audio file is damaged or in an unsupported format. Ask for a new recording.")
TOOL_MISSING = FailureInfo("tool_missing", "A processing tool was unavailable", retryable=True,
                           advice="A required processing tool was missing when this ran. A retry should fix it.")
TIMEOUT = FailureInfo("timeout", "Processing timed out", retryable=True,
                      advice="Processing took too long. A retry usually works.")
EXTERNAL = FailureInfo("external_service", "A connected service did not respond", retryable=True,
                       advice="An AI or speech service did not respond. A retry usually works.")
CRASHED = FailureInfo("worker_crashed", "Processing stopped unexpectedly", retryable=True,
                      advice="Processing stopped several times in a row. Retry once; if it keeps failing, contact support.")
UNEXPECTED = FailureInfo("unexpected", "Something unexpected went wrong", retryable=True,
                         advice="Retry once. If it fails again, report it to support with the technical details.")

# (needle (lower-case), info) checked against the first 600 chars, lower-cased
_RULES: list[tuple[tuple[str, ...], FailureInfo]] = [
    (("no speech detected",), NO_SPEECH),
    (("could not decode this audio", "invalid data found when processing input"), BAD_AUDIO),
    (("winerror 2", "no such file or directory", "filenotfounderror", "ffmpeg: not found",
      "executable doesn't exist"), TOOL_MISSING),
    (("timed out", "timeouterror", "read timeout", "connect timeout"), TIMEOUT),
    (("stuck in", "giving up automatically"), CRASHED),
    (("rate limit", "429", "503", "502", "connection error", "connection refused", "connectionerror",
      "api key", "openai", "deepgram", "authentication"), EXTERNAL),
]


def classify_failure(reason: str | None) -> FailureInfo:
    text = (reason or "")[:600].lower()
    if not text.strip():
        return UNEXPECTED
    for needles, info in _RULES:
        if any(n in text for n in needles):
            return info
    return UNEXPECTED
