"""
Who was on the call, read from the recording's filename.

PBX recordings in the bucket are named like

    call_1002_1001_agnoshin.com.wav                    internal call (two extensions)
    call__919551818896_1002_agnoshin.com.wav           customer number, then agent extension
    <uuid>-<epoch>-call__918838559627_1006_agnoshin.com_<epoch>.wav
    719001004809577.wav                                 no pattern -> nothing inferred

Rule: a *short* number (<= 6 digits) is an internal extension, a *long* number
(>= 7 digits) is an external phone number. With one of each, the extension is
the agent and the long number the customer, in either order. With two
extensions it is an internal call: the second is taken as the agent (the callee,
which is what the external-inbound pattern has in that position) and the call
is flagged `internal` so it can be told apart. Anything else yields nothing:
we never guess an identity.
"""
import re
from dataclasses import dataclass
from typing import Optional

_PATTERN = re.compile(r"call_+(\d+)_(\d+)(?:_|\.|$)")
_MAX_EXTENSION_DIGITS = 6
_MIN_PHONE_DIGITS = 7


@dataclass(frozen=True)
class CallParties:
    agent_extension: Optional[str] = None
    customer_number: Optional[str] = None
    internal: bool = False


def parse_call_filename(filename: str | None) -> CallParties:
    m = _PATTERN.search(filename or "")
    if not m:
        return CallParties()
    a, b = m.group(1), m.group(2)
    a_short, b_short = len(a) <= _MAX_EXTENSION_DIGITS, len(b) <= _MAX_EXTENSION_DIGITS
    a_long, b_long = len(a) >= _MIN_PHONE_DIGITS, len(b) >= _MIN_PHONE_DIGITS
    if a_short and b_long:
        return CallParties(agent_extension=a, customer_number=b)
    if b_short and a_long:
        return CallParties(agent_extension=b, customer_number=a)
    if a_short and b_short:
        return CallParties(agent_extension=b, internal=True)
    return CallParties()
