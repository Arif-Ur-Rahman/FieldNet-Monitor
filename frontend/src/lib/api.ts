// Types and calls for the FieldNet API. The browser talks to /api/*, which the
// Next.js route handler proxies to Django (see app/api/[...path]/route.ts).

export type GatewayStatus = "new" | "spare" | "connected" | "stale" | "disconnected" | "suspended" | "retired";
export type CommandState =
  | "running"
  | "stop_pending"
  | "stopped"
  | "stop_failed"
  | "resume_pending"
  | "resume_failed";
export type CoverageClass = "available" | "stopped" | "recoverable" | "dead";
export type SensorCoverage = "available" | "stopped" | "recoverable" | "none";
export type Lifecycle = "pending" | "active" | "dormant" | "sampling" | "retired" | "decommissioned";
export type Collection =
  | "readings"
  | "no_readings"
  | "could_not_read"
  | "timed_out"
  | "not_checked"
  | "collection_stopped";

export interface Gateway {
  gateway_id: string;
  name: string;
  status: GatewayStatus;
  status_since: string;
  command_state: CommandState;
  coverage_class: CoverageClass;
  last_heartbeat_at: string | null;
  last_qualifying_at: string | null;
  disconnected_since: string | null;
  flags: string[];
}

export interface Sensor {
  sensor_id: string;
  type: "temperature" | "rain" | "wind";
  lifecycle: Lifecycle;
  lifecycle_reason: string | null;
  lifecycle_since: string;
  collection: Collection;
  coverage: SensorCoverage;
  quiet_checked_days: number;
  sampling_cycles_done: number;
  next_evaluation_at: string | null;
}

export interface TimelineEntry {
  seq: number;
  kind: "transition" | "correction" | "action" | "ack" | "flag" | "rule_change";
  axis: string | null;
  from: string | null;
  to: string | null;
  effective_at: string;
  recorded_at: string;
  rule: string;
  evidence_ids: string[];
  detail: Record<string, unknown> | null;
}

export type Counts = Record<string, number>;

export interface Dashboard {
  gateways: { total: number; status: Counts; command_state: Counts; coverage_class: Counts; flags: Counts };
  sensors: { total: number; lifecycle: Counts; retired_reason: Counts; coverage: Counts; collection: Counts };
  batches: { total: number; processing: Counts };
}

export interface ApiError {
  error: string;
  detail: string;
}

/** A response body plus the server clock it was measured at. */
export interface Fetched<T> {
  data: T;
  serverNow: Date | null;
}

export async function get<T>(path: string, signal?: AbortSignal): Promise<Fetched<T>> {
  const resp = await fetch(path, { cache: "no-store", signal });
  if (!resp.ok) {
    const body = (await resp.json().catch(() => null)) as ApiError | null;
    throw new Error(body ? `${body.error}: ${body.detail}` : `HTTP ${resp.status}`);
  }
  const header = resp.headers.get("x-server-now");
  return { data: (await resp.json()) as T, serverNow: header ? new Date(header) : null };
}

/** POST a JSON body; resolves to the error message on failure, null on success. */
export async function post(path: string, body: unknown): Promise<string | null> {
  const resp = await fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (resp.ok) return null;
  const err = (await resp.json().catch(() => null)) as ApiError | null;
  return err ? err.detail : `HTTP ${resp.status}`;
}
