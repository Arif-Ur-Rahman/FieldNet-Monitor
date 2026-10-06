// The console's visual vocabulary. Unknown, paused, not-checked, zero and
// healthy must never look alike:
//   healthy      solid green badge
//   zero         a plain muted 0
//   unknown      grey italic text in a dashed outline ("never", "unknown")
//   paused       amber badge with a pause sign
//   not checked  grey badge with diagonal stripes

import { label } from "@/lib/format";

type Tone = "healthy" | "neutral" | "info" | "warn" | "bad" | "dead" | "notChecked";

const TONES: Record<Tone, string> = {
  healthy: "bg-emerald-600 text-white",
  neutral: "bg-slate-100 text-slate-700 ring-1 ring-slate-300",
  info: "bg-sky-100 text-sky-800 ring-1 ring-sky-300",
  warn: "bg-amber-100 text-amber-900 ring-1 ring-amber-400",
  bad: "bg-red-600 text-white",
  dead: "bg-slate-700 text-slate-100",
  notChecked: "text-slate-600 ring-1 ring-slate-300",
};

const STRIPES = {
  backgroundImage: "repeating-linear-gradient(135deg, #f1f5f9 0 6px, #e2e8f0 6px 12px)",
};

const TONE_OF: Record<string, Tone> = {
  // gateway status
  connected: "healthy",
  new: "neutral",
  spare: "neutral",
  stale: "warn",
  disconnected: "bad",
  suspended: "dead",
  retired: "dead",
  // command state
  running: "neutral",
  stop_pending: "warn",
  stopped: "info",
  stop_failed: "bad",
  resume_pending: "warn",
  resume_failed: "bad",
  // coverage
  available: "healthy",
  recoverable: "warn",
  dead: "dead",
  none: "bad",
  // lifecycle
  pending: "neutral",
  active: "healthy",
  dormant: "info",
  sampling: "warn",
  decommissioned: "dead",
  // collection
  readings: "healthy",
  no_readings: "info",
  could_not_read: "bad",
  timed_out: "bad",
  not_checked: "notChecked",
  collection_stopped: "info",
};

export function Badge({ value, title }: { value: string; title?: string }) {
  const tone = TONE_OF[value] ?? "neutral";
  return (
    <span
      title={title}
      style={tone === "notChecked" ? STRIPES : undefined}
      className={`inline-block whitespace-nowrap rounded px-2 py-0.5 text-xs font-medium ${TONES[tone]}`}
    >
      {label(value)}
    </span>
  );
}

/** A value the server doesn't have: never seen, not known. */
export function Unknown({ text = "unknown", title }: { text?: string; title?: string }) {
  return (
    <span
      title={title}
      className="inline-block rounded border border-dashed border-slate-400 px-1.5 text-xs italic text-slate-500"
    >
      {text}
    </span>
  );
}

/** A wait or window that is paused because coverage isn't available. */
export function Paused({ title = "Paused: coverage is not available" }: { title?: string }) {
  return (
    <span
      title={title}
      className="inline-block rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900 ring-1 ring-amber-400"
    >
      ⏸ paused
    </span>
  );
}

/** A count: zero is shown plainly and muted, never as a dash or a badge. */
export function Count({ n }: { n: number }) {
  return <span className={n === 0 ? "text-slate-400" : "font-semibold tabular-nums"}>{n}</span>;
}

export function Flag({ flag }: { flag: string }) {
  return (
    <span className="inline-block rounded bg-fuchsia-100 px-2 py-0.5 text-xs font-medium text-fuchsia-900 ring-1 ring-fuchsia-400">
      ⚑ {label(flag)}
    </span>
  );
}

/** The legend shown on each page, so operators can read the badges. */
export function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500">
      <span className="flex items-center gap-1">
        <Badge value="available" /> healthy
      </span>
      <span className="flex items-center gap-1">
        <Count n={0} /> zero
      </span>
      <span className="flex items-center gap-1">
        <Unknown text="never" /> unknown
      </span>
      <span className="flex items-center gap-1">
        <Paused /> paused
      </span>
      <span className="flex items-center gap-1">
        <Badge value="not_checked" /> not checked
      </span>
    </div>
  );
}
