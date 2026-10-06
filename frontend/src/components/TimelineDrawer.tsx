"use client";

import type { TimelineEntry } from "@/lib/api";
import { label, stamp } from "@/lib/format";
import { usePoll } from "@/lib/usePoll";

const KIND_STYLE: Record<TimelineEntry["kind"], string> = {
  transition: "border-slate-300",
  correction: "border-amber-500 bg-amber-50",
  action: "border-sky-500 bg-sky-50",
  ack: "border-emerald-500",
  flag: "border-fuchsia-500 bg-fuchsia-50",
  rule_change: "border-violet-500",
};

function Change({ e }: { e: TimelineEntry }) {
  if (e.kind === "action" || e.kind === "ack") return <span className="font-medium">{label(e.rule)}</span>;
  return (
    <span>
      {e.axis && <span className="text-slate-500">{label(e.axis)}: </span>}
      <span>{e.from ? label(e.from) : "—"}</span> → <span className="font-medium">{e.to ? label(e.to) : "—"}</span>
    </span>
  );
}

function Detail({ e }: { e: TimelineEntry }) {
  const d = e.detail;
  if (!d) return null;
  if (e.kind === "correction" && Array.isArray(d.transitions)) {
    const steps = d.transitions as { at: string; to: string; reason: string | null }[];
    return (
      <div className="mt-1 text-xs text-amber-900">
        Recomputed history:{" "}
        {steps.map((t, i) => (
          <span key={i}>
            {i > 0 && " → "}
            {label(t.to)}
            {t.reason ? ` (${label(t.reason)})` : ""} <span className="text-amber-700">{stamp(t.at)}</span>
          </span>
        ))}
      </div>
    );
  }
  if (typeof d.reason === "string") return <div className="mt-1 text-xs text-slate-600">Reason: {d.reason}</div>;
  return null;
}

/** A plain list of an entity's timeline entries, oldest first. */
export default function TimelineDrawer({
  entity,
  id,
  onClose,
}: {
  entity: "gateways" | "sensors";
  id: string;
  onClose: () => void;
}) {
  const { data, error } = usePoll<TimelineEntry[]>(`/api/v1/${entity}/${id}/timeline`);
  return (
    <aside className="fixed inset-y-0 right-0 z-10 flex w-full max-w-lg flex-col border-l border-slate-200 bg-white shadow-xl">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-500">Timeline · {entity === "gateways" ? "gateway" : "sensor"}</div>
          <div className="font-mono font-medium text-slate-900">{id}</div>
        </div>
        <button onClick={onClose} className="rounded px-2 py-1 text-slate-600 hover:bg-slate-100" aria-label="Close">
          ✕
        </button>
      </div>
      <ol className="flex-1 space-y-2 overflow-y-auto p-4 text-sm">
        {error && <li className="text-red-700">Could not load: {error}</li>}
        {data?.length === 0 && <li className="text-slate-500">No entries yet.</li>}
        {data?.map((e) => (
          <li key={e.seq} className={`rounded border-l-4 px-3 py-2 ${KIND_STYLE[e.kind]}`}>
            <div className="flex items-baseline justify-between gap-2">
              <Change e={e} />
              <span className="text-xs uppercase text-slate-500">{label(e.kind)}</span>
            </div>
            <div className="mt-0.5 text-xs text-slate-500">
              #{e.seq} · effective {stamp(e.effective_at)}
              {e.recorded_at !== e.effective_at && <> · recorded {stamp(e.recorded_at)}</>} · rule {label(e.rule)}
              {e.evidence_ids.length > 0 && <> · {e.evidence_ids.join(", ")}</>}
            </div>
            <Detail e={e} />
          </li>
        ))}
      </ol>
    </aside>
  );
}
