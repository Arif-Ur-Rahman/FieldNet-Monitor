// Times and durations, always measured against the server clock.

/** "2h", "3d 4h", "45m", "12s". */
export function duration(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return h > 0 ? `${d}d ${h}h` : `${d}d`;
  if (h > 0) return m > 0 ? `${h}h ${m}m` : `${h}h`;
  if (m > 0) return `${m}m`;
  return `${s}s`;
}

/** How long ago `iso` was, by the server clock: "3h ago". */
export function ago(iso: string, now: Date | null): string {
  return now ? `${duration(now.getTime() - new Date(iso).getTime())} ago` : "";
}

/** How long until `iso`, by the server clock: "in 2d". */
export function until(iso: string, now: Date | null): string {
  if (!now) return "";
  const ms = new Date(iso).getTime() - now.getTime();
  return ms >= 0 ? `in ${duration(ms)}` : `${duration(-ms)} overdue`;
}

/** "2026-01-04 12:00 UTC". */
export function stamp(iso: string): string {
  return iso.replace("T", " ").replace(/:\d\d(\.\d+)?Z$/, " UTC");
}

export function label(value: string): string {
  return value.replaceAll("_", " ");
}
