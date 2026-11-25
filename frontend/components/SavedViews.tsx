"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Bookmark, X } from "lucide-react";

type View = { name: string; qs: string };

const STORAGE_KEY = "agnocall_saved_views";
const MAX_VIEWS = 12;

const BUILT_IN: View[] = [
  { name: "All calls", qs: "" },
  { name: "Failed", qs: "status=failed" },
  { name: "Worst QA first", qs: "status=processed&sort=qa&order=asc" },
  { name: "High risk", qs: "risk_level=high" },
  { name: "Flagged, not reviewed", qs: "has_violations=true&reviewed=false" },
];

/** Canonical form of a query string so "a=1&b=2" and "b=2&a=1" (and a page number) compare equal. */
function canon(qs: string): string {
  const p = new URLSearchParams(qs);
  p.delete("page");
  return [...p.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => `${k}=${v}`).join("&");
}

function load(): View[] {
  try {
    const raw = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "[]");
    return Array.isArray(raw)
      ? raw.filter((v) => v && typeof v.name === "string" && typeof v.qs === "string").slice(0, MAX_VIEWS)
      : [];
  } catch {
    return [];
  }
}

/**
 * One-click filter+sort combinations. The built-in ones are fixed; "Save this view" stores the
 * current filters under a name in THIS browser (localStorage), so there is nothing to sync or secure.
 */
export default function SavedViews() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [custom, setCustom] = useState<View[]>([]);
  useEffect(() => setCustom(load()), []);

  const current = canon(searchParams.toString());

  function persist(next: View[]) {
    setCustom(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      /* storage unavailable: the view just won't persist */
    }
  }

  function save() {
    const name = window.prompt("Name this view (for example: My failed calls)")?.trim().slice(0, 40);
    if (!name) return;
    const qs = canon(searchParams.toString());
    persist([...custom.filter((v) => v.name !== name), { name, qs }].slice(-MAX_VIEWS));
  }

  const go = (qs: string) => router.push(`${pathname}${qs ? `?${qs}` : ""}`);
  const chip = (active: boolean) =>
    `text-[12.5px] px-3 py-1 rounded-full border transition-colors ${
      active ? "bg-accent text-white border-accent" : "border-hairline bg-white text-muted hover:text-ink hover:border-accent/50"
    }`;

  return (
    <div className="flex flex-wrap items-center gap-2 mb-3">
      {BUILT_IN.map((v) => (
        <button key={v.name} type="button" onClick={() => go(v.qs)} className={chip(canon(v.qs) === current)}>
          {v.name}
        </button>
      ))}
      {custom.map((v) => (
        <span key={v.name} className="inline-flex items-center">
          <button type="button" onClick={() => go(v.qs)} className={`${chip(canon(v.qs) === current)} pr-2 rounded-r-none`}>
            {v.name}
          </button>
          <button
            type="button"
            aria-label={`Remove saved view ${v.name}`}
            onClick={() => persist(custom.filter((x) => x.name !== v.name))}
            className="text-[12.5px] px-1.5 py-1 rounded-r-full border border-l-0 border-hairline bg-white text-faint hover:text-bad"
          >
            <X className="w-3 h-3" />
          </button>
        </span>
      ))}
      {current !== "" && !BUILT_IN.some((v) => canon(v.qs) === current) && !custom.some((v) => canon(v.qs) === current) && (
        <button type="button" onClick={save} className="inline-flex items-center gap-1 text-[12.5px] text-accent hover:underline">
          <Bookmark className="w-3.5 h-3.5" /> Save this view
        </button>
      )}
    </div>
  );
}
