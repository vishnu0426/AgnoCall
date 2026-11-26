"use client";

import { useState } from "react";
import { useRouter, usePathname, useSearchParams } from "next/navigation";

const STATUS_OPTIONS = [
  { value: "", label: "All statuses" },
  { value: "uploaded", label: "Uploaded" },
  { value: "validating", label: "Validating" },
  { value: "processing", label: "Processing" },
  { value: "processed", label: "Processed" },
  { value: "failed", label: "Failed" },
];

const RISK_OPTIONS = [
  { value: "", label: "All risk levels" },
  { value: "low", label: "Low risk" },
  { value: "medium", label: "Medium risk" },
  { value: "high", label: "High risk" },
];

const PERIOD_OPTIONS = [
  { value: "", label: "Any date" },
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
];

const VIOLATION_OPTIONS = [
  { value: "", label: "Any compliance" },
  { value: "true", label: "Has violations" },
  { value: "false", label: "No violations" },
];

const REVIEWED_OPTIONS = [
  { value: "", label: "Reviewed or not" },
  { value: "true", label: "Reviewed by a person" },
  { value: "false", label: "Not reviewed yet" },
];

const CONVERSATION_OPTIONS = [
  { value: "", label: "All recordings" },
  { value: "true", label: "Real conversations" },
  { value: "false", label: "IVR, silent or very short" },
];

const CATEGORY_OPTIONS = [
  "billing", "technical_support", "account_management", "sales", "cancellation", "complaint",
  "general_inquiry", "other",
];

const SELECT_CLASS =
  "text-[13px] border border-hairline rounded-md px-2.5 py-1.5 bg-panel text-ink hover:border-accent/50 transition-colors focus:outline-none focus:ring-1 focus:ring-accent";

export default function CallsFilterBar() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const status = searchParams.get("status") ?? "";
  const riskLevel = searchParams.get("risk_level") ?? "";
  const days = searchParams.get("days") ?? "";
  const hasViolations = searchParams.get("has_violations") ?? "";
  const reviewed = searchParams.get("reviewed") ?? "";
  const agentId = searchParams.get("agent_id") ?? "";
  const urlSearch = searchParams.get("search") ?? "";
  const conversation = searchParams.get("conversation") ?? "";
  const category = searchParams.get("category") ?? "";
  const [searchText, setSearchText] = useState(urlSearch);
  const hasFilters = status !== "" || riskLevel !== "" || days !== "" || hasViolations !== ""
    || agentId !== "" || urlSearch !== "" || reviewed !== "" || conversation !== "" || category !== "";

  function updateFilter(key: string, value: string) {
    const params = new URLSearchParams(searchParams.toString());
    if (value) {
      params.set(key, value);
    } else {
      params.delete(key);
    }
    // Any filter change invalidates the current page's meaning -- always
    // land back on page 1 rather than risk landing past the end of a
    // suddenly-shorter filtered result set.
    params.delete("page");
    const qs = params.toString();
    router.push(`${pathname}${qs ? `?${qs}` : ""}`);
  }

  return (
    <div className="flex flex-wrap items-center gap-2 mb-4">
      <form
        onSubmit={(e) => { e.preventDefault(); updateFilter("search", searchText.trim()); }}
        className="flex"
      >
        <input
          type="search"
          aria-label="Search by file name"
          placeholder="Search file name…"
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          className="text-[13px] border border-hairline rounded-md px-2.5 py-1.5 bg-panel text-ink placeholder-faint w-52 focus:outline-none focus:ring-1 focus:ring-accent"
        />
      </form>
      <select
        aria-label="Filter by status"
        className={SELECT_CLASS}
        value={status}
        onChange={(e) => updateFilter("status", e.target.value)}
      >
        {STATUS_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
      <select
        aria-label="Filter by risk level"
        className={SELECT_CLASS}
        value={riskLevel}
        onChange={(e) => updateFilter("risk_level", e.target.value)}
      >
        {RISK_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
      <select
        aria-label="Filter by date"
        className={SELECT_CLASS}
        value={days}
        onChange={(e) => updateFilter("days", e.target.value)}
      >
        {PERIOD_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
      <select
        aria-label="Filter by compliance"
        className={SELECT_CLASS}
        value={hasViolations}
        onChange={(e) => updateFilter("has_violations", e.target.value)}
      >
        {VIOLATION_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
      <select
        aria-label="Filter by review"
        className={SELECT_CLASS}
        value={reviewed}
        onChange={(e) => updateFilter("reviewed", e.target.value)}
      >
        {REVIEWED_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
      <select
        aria-label="Filter by conversation type"
        className={SELECT_CLASS}
        value={conversation}
        onChange={(e) => updateFilter("conversation", e.target.value)}
        title="Real conversations are what Analytics averages. IVR surveys, silent and very short recordings are listed apart."
      >
        {CONVERSATION_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
      <select
        aria-label="Filter by category"
        className={SELECT_CLASS}
        value={category}
        onChange={(e) => updateFilter("category", e.target.value)}
      >
        <option value="">All categories</option>
        {CATEGORY_OPTIONS.map((c) => (
          <option key={c} value={c}>{c.replace("_", " ")}</option>
        ))}
      </select>
      {hasFilters && (
        <button
          type="button"
          onClick={() => { setSearchText(""); router.push(pathname); }}
          className="text-[13px] text-muted hover:text-ink transition-colors px-2 py-1.5"
        >
          Clear filters
        </button>
      )}
    </div>
  );
}
