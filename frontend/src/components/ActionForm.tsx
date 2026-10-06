"use client";

import { useState } from "react";

import { post } from "@/lib/api";
import { label } from "@/lib/format";

/** Inline confirmation for an operator action, with a reason field. No browser dialogs. */
export default function ActionForm({
  path,
  action,
  reasonRequired,
  onDone,
  onCancel,
}: {
  path: string;
  action: string;
  reasonRequired: boolean;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const err = await post(path, reason.trim() ? { action, reason: reason.trim() } : { action });
    setBusy(false);
    if (err) setError(err);
    else onDone();
  }

  return (
    <form onSubmit={submit} className="flex flex-wrap items-center gap-2 rounded bg-slate-100 p-2 text-sm">
      <span className="font-medium">{label(action)}</span>
      <input
        autoFocus
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder={reasonRequired ? "Reason (required)" : "Reason (optional)"}
        className="min-w-56 flex-1 rounded border border-slate-300 bg-white px-2 py-1"
      />
      <button
        type="submit"
        disabled={busy || (reasonRequired && !reason.trim())}
        className="rounded bg-slate-900 px-3 py-1 text-white disabled:opacity-40"
      >
        Confirm
      </button>
      <button type="button" onClick={onCancel} className="rounded px-2 py-1 text-slate-600 hover:bg-slate-200">
        Cancel
      </button>
      {error && <span className="w-full text-red-700">{error}</span>}
    </form>
  );
}
