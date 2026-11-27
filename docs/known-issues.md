# Known issues

## BUG-001: a compliance flag can contradict itself (found 2026-11-27)
**Where:** call `719001003654400.wav`, flag `GREETING_MISSING` (low). The explanation reads "The agent greeted
the customer and stated their name." and the evidence quotes the greeting ("Welcome to Telstra. My name is
Justin."). The flag says the opposite of what it reports.

**Cause:** the AI listed a rule the agent met in `compliance_violations`. Nothing checked the explanation
against the flag.

**Scale:** 1 of 297 stored violations contradicts itself by wording. A transcript check finds 2 more where the
agent did greet and gave a name in the first 20 seconds but the flag says otherwise (different wording, so a
judgement error rather than a contradiction): calls `cf1f21dd` and `14f9a56b`.

**Fix (in the code):**
- The prompt now says to list a rule only when it was broken.
- `contradicts_itself()` (`app/core/compliance_rules.py`) drops a flag whose explanation affirms the rule was met
  and contains no negative word. It runs when a call is analysed and logs each dropped flag.
- `scripts/clean_contradicting_flags.py` lists existing ones; `--apply` deletes them. The bad flag on the call
  above is still in the database until that is run.

**Not fixed:** flags that are wrong but worded as a failure ("Agent did not greet..." when they did). Those need
human review (Calibration) or a stricter check against the transcript.
