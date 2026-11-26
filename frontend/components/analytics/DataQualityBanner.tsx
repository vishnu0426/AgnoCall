"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, X } from "lucide-react";
import { AnalyticsQuality } from "@/lib/api";

const n = (v: number) => v.toLocaleString("en-US");

/**
 * Says what the numbers on this page are made of: how many recordings were processed, how many are real
 * conversations (the only ones averaged), what was left out and why, and how many have trustworthy
 * agent/customer roles. Every count links to the matching list of calls.
 */
const DISMISS_KEY = "analytics_data_notes_hidden";

export default function DataQualityBanner({ quality, scope }: { quality: AnalyticsQuality; scope: string }) {
  // Shown on first load (same as the server render), then hidden if the person closed it earlier.
  const [hidden, setHidden] = useState(false);
  useEffect(() => {
    try {
      setHidden(window.localStorage.getItem(DISMISS_KEY) === "1");
    } catch {
      /* storage unavailable: keep it visible */
    }
  }, []);
  function setDismissed(value: boolean) {
    setHidden(value);
    try {
      if (value) window.localStorage.setItem(DISMISS_KEY, "1");
      else window.localStorage.removeItem(DISMISS_KEY);
    } catch {
      /* the choice just will not be remembered */
    }
  }

  const href = (extra: string) => `/calls?${[scope, extra].filter(Boolean).join("&")}`;
  const { processed, conversations, excluded, one_sided, roles_from_channel, failed } = quality;
  const share = processed ? Math.round((100 * conversations) / processed) : 0;
  const rolesConfirmed = conversations ? Math.round((100 * roles_from_channel) / conversations) : 0;
  // Worth a warning: most of what was processed is not a conversation, or roles are mostly guessed.
  const warn = (processed > 0 && share < 60) || (conversations > 0 && rolesConfirmed < 50);
  const Icon = warn ? AlertTriangle : CheckCircle2;

  if (hidden) {
    return (
      <div className="mb-4 text-[12.5px]">
        <button type="button" onClick={() => setDismissed(false)} className="text-muted underline hover:text-ink">
          Show data notes
        </button>
      </div>
    );
  }

  return (
    <section
      aria-label="What these numbers are based on"
      className={`mb-6 rounded-lg border px-5 py-4 text-[13px] ${
        warn ? "border-warn/35 bg-warn/5" : "border-hairline bg-panel"
      }`}
    >
      <div className="flex items-start gap-3">
        <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${warn ? "text-warn" : "text-good"}`} aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="text-ink">
            <b className="font-semibold">{n(conversations)}</b> of {n(processed)} processed recording
            {processed === 1 ? "" : "s"} ({share}%) {conversations === 1 ? "is a real conversation and is" : "are real conversations and are"}{" "}
            scored below.
            {excluded > 0 && (
              <>
                {" "}
                <Link href={href("status=processed&conversation=false")} className="font-medium text-accent hover:underline">
                  {n(excluded)} left out
                </Link>{" "}
                (IVR surveys, silent or very short calls: under {quality.min_words} words or {quality.min_seconds} s)
                so they cannot drag the averages down.
              </>
            )}
          </p>
          <ul className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[12.5px] text-muted">
            {conversations > 0 && (
              <li>
                Agent / customer roles confirmed by recording channel:{" "}
                <b className={rolesConfirmed < 50 ? "text-warn" : "text-ink"}>{rolesConfirmed}%</b>
                {rolesConfirmed < 100 && " (mono recordings are a guess, so treat their agent scores with care)"}
              </li>
            )}
            {one_sided > 0 && (
              <li>
                <b className="text-ink">{n(one_sided)}</b> scored call{one_sided === 1 ? "" : "s"} have speech from only
                one side
              </li>
            )}
            {failed > 0 && (
              <li>
                <Link href={href("status=failed")} className="text-accent hover:underline">
                  {n(failed)} recording{failed === 1 ? "" : "s"} failed to process
                </Link>{" "}
                and are not counted
              </li>
            )}
          </ul>
        </div>
        <button
          type="button"
          onClick={() => setDismissed(true)}
          aria-label="Close data notes"
          title="Close (you can bring it back with 'Show data notes')"
          className="-mr-1 -mt-1 shrink-0 rounded p-1 text-faint hover:bg-black/5 hover:text-ink"
        >
          <X className="h-4 w-4" aria-hidden />
        </button>
      </div>
    </section>
  );
}
