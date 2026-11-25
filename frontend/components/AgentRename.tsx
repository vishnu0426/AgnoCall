"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Pencil } from "lucide-react";
import { api } from "@/lib/api";

/** Small inline rename. Renaming a placeholder like "Extension 1001" relabels all of that agent's calls. */
export default function AgentRename({ id, name }: { id: string; name: string }) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(name);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save() {
    const next = value.trim();
    if (!next || next === name) {
      setEditing(false);
      setValue(name);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.renameAgent(id, next);
      setEditing(false);
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not rename");
    } finally {
      setBusy(false);
    }
  }

  if (!editing) {
    return (
      <button
        onClick={() => setEditing(true)}
        aria-label={`Rename ${name}`}
        title="Rename"
        className="ml-2 text-faint hover:text-ink align-middle"
      >
        <Pencil className="w-3 h-3" />
      </button>
    );
  }
  return (
    <span className="ml-2 inline-flex items-center gap-1.5 align-middle">
      <input
        autoFocus
        value={value}
        maxLength={120}
        disabled={busy}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") save();
          if (e.key === "Escape") { setEditing(false); setValue(name); }
        }}
        className="text-[12.5px] border border-hairline rounded px-2 py-0.5 bg-white w-44 focus:outline-none focus:ring-1 focus:ring-accent"
      />
      <button onClick={save} disabled={busy} className="text-[12px] text-accent hover:underline">Save</button>
      {error && <span className="text-[11.5px] text-bad">{error}</span>}
    </span>
  );
}
