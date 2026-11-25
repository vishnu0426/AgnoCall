"use client";

import { useState } from "react";
import { AlertTriangle } from "lucide-react";
import { ComplianceViolation, api } from "@/lib/api";
import EmptyState from "@/components/EmptyState";
import Badge, { BadgeTone } from "@/components/Badge";

const SEVERITY_TONE: Record<string, BadgeTone> = {
  low: "muted",
  medium: "warn",
  high: "bad",
  critical: "bad",
};

type Outcome = "confirmed" | "rejected" | null;

export default function ComplianceList({ violations, onJump }: { violations: ComplianceViolation[]; onJump: (t: number) => void }) {
  // A reviewer upholds ("Correct") or rejects ("Wrong") each AI flag. This is what lets the
  // Calibration page say how often the AI's compliance flags are right.
  const [outcomes, setOutcomes] = useState<Record<string, Outcome>>(
    () => Object.fromEntries(violations.map((v) => [v.id, (v.review_outcome as Outcome) ?? null]))
  );
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function decide(id: string, outcome: Outcome) {
    setBusy(id);
    setError(null);
    try {
      await api.reviewComplianceFlag(id, outcome);
      setOutcomes((o) => ({ ...o, [id]: outcome }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save");
    } finally {
      setBusy(null);
    }
  }

  if (violations.length === 0) {
    return (
      <EmptyState
        variant="good"
        icon={AlertTriangle}
        title="No compliance violations detected"
        description="This call was checked against every active compliance rule and came back clean."
      />
    );
  }

  return (
    <div className="space-y-2.5">
      {error && <div className="text-[12px] text-bad">{error}</div>}
      {violations.map((v) => {
        const outcome = outcomes[v.id] ?? null;
        return (
          <div key={v.id} className="border border-hairline rounded-md px-3.5 py-3">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-[12px] font-mono text-muted">{v.rule_code}</span>
              <Badge tone={SEVERITY_TONE[v.severity] || "muted"}>{v.severity}</Badge>
            </div>
            {v.explanation && <p className="text-[12.5px] text-ink leading-relaxed mb-1.5">{v.explanation}</p>}
            {v.evidence && (
              <button
                onClick={() => v.timestamp_ref != null && onJump(v.timestamp_ref)}
                className="text-left text-[12px] font-mono text-accent hover:underline block"
              >
                &quot;{v.evidence}&quot;
                {v.timestamp_ref != null && <span className="text-faint ml-1.5">@ {v.timestamp_ref.toFixed(0)}s</span>}
              </button>
            )}
            <div className="mt-2.5 flex items-center gap-2 text-[12px]">
              <span className="text-faint">Is this flag right?</span>
              <button
                disabled={busy === v.id}
                onClick={() => decide(v.id, outcome === "confirmed" ? null : "confirmed")}
                className={`px-2 py-0.5 rounded border ${outcome === "confirmed" ? "border-good text-good bg-good/10" : "border-hairline text-muted hover:bg-panelRaised"}`}
              >
                Correct
              </button>
              <button
                disabled={busy === v.id}
                onClick={() => decide(v.id, outcome === "rejected" ? null : "rejected")}
                className={`px-2 py-0.5 rounded border ${outcome === "rejected" ? "border-bad text-bad bg-bad/10" : "border-hairline text-muted hover:bg-panelRaised"}`}
              >
                Wrong
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
