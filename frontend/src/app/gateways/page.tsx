"use client";

import { Fragment, useState } from "react";

import ActionForm from "@/components/ActionForm";
import { Badge, Flag, Legend, Unknown } from "@/components/badges";
import PageHeader from "@/components/PageHeader";
import TimelineDrawer from "@/components/TimelineDrawer";
import type { Gateway, GatewayStatus } from "@/lib/api";
import { ago, duration, label, stamp } from "@/lib/format";
import { usePoll } from "@/lib/usePoll";

const STATUSES: GatewayStatus[] = ["new", "spare", "connected", "stale", "disconnected", "suspended", "retired"];

/** The operator actions the gateway's current state allows (the server still checks). */
function actionsFor(g: Gateway): string[] {
  if (g.status === "retired") return [];
  const actions: string[] = [];
  if (g.status === "suspended") actions.push("unsuspend");
  else actions.push("suspend");
  if (g.status === "new") actions.push("mark_spare");
  if (["running", "stop_failed", "resume_pending", "resume_failed"].includes(g.command_state)) actions.push("stop");
  if (["stop_pending", "stopped", "stop_failed", "resume_failed"].includes(g.command_state)) actions.push("resume");
  actions.push("retire");
  return actions;
}

function When({ iso, now, never }: { iso: string | null; now: Date | null; never: string }) {
  if (!iso) return <Unknown text={never} />;
  return (
    <span title={stamp(iso)} className="whitespace-nowrap text-slate-700">
      {ago(iso, now)}
    </span>
  );
}

export default function FleetPage() {
  const [status, setStatus] = useState("");
  const [pending, setPending] = useState<{ gateway: string; action: string } | null>(null);
  const [timelineOf, setTimelineOf] = useState<string | null>(null);
  const path = status ? `/api/v1/gateways?status=${status}` : "/api/v1/gateways";
  const { data, serverNow, error, refresh } = usePoll<Gateway[]>(path);

  return (
    <main className="mx-auto w-full max-w-7xl px-6 py-6">
      <PageHeader title="Fleet" serverNow={serverNow} error={error}>
        <div className="flex flex-col items-end gap-2">
          <Legend />
          <label className="text-sm text-slate-600">
            Status{" "}
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="rounded border border-slate-300 bg-white px-2 py-1"
            >
              <option value="">all</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {label(s)}
                </option>
              ))}
            </select>
          </label>
        </div>
      </PageHeader>

      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-2">Gateway</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Last heartbeat</th>
              <th className="px-3 py-2">Last qualifying</th>
              <th className="px-3 py-2">Command</th>
              <th className="px-3 py-2">Coverage</th>
              <th className="px-3 py-2">Flags</th>
              <th className="px-3 py-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {data?.length === 0 && (
              <tr>
                <td colSpan={8} className="px-3 py-6 text-center text-slate-500">
                  No gateways{status && ` with status ${label(status)}`}.
                </td>
              </tr>
            )}
            {data?.map((g) => (
              <Fragment key={g.gateway_id}>
                <tr className="border-b border-slate-100 align-top">
                  <td className="px-3 py-2">
                    <button
                      onClick={() => setTimelineOf(g.gateway_id)}
                      title="Show timeline"
                      className="font-mono text-slate-900 underline decoration-slate-300 underline-offset-2 hover:decoration-slate-900"
                    >
                      {g.gateway_id}
                    </button>
                    <div className="text-xs text-slate-500">{g.name}</div>
                  </td>
                  <td className="whitespace-nowrap px-3 py-2">
                    <Badge value={g.status} />{" "}
                    <span className="text-xs text-slate-600" title={`since ${stamp(g.status_since)}`}>
                      · {serverNow ? duration(serverNow.getTime() - new Date(g.status_since).getTime()) : ""}
                    </span>
                    {g.disconnected_since && (
                      <div className="mt-0.5 text-xs text-red-700">failing since {stamp(g.disconnected_since)}</div>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <When iso={g.last_heartbeat_at} now={serverNow} never="never" />
                  </td>
                  <td className="px-3 py-2">
                    <When iso={g.last_qualifying_at} now={serverNow} never="never" />
                  </td>
                  <td className="px-3 py-2">
                    <Badge value={g.command_state} />
                  </td>
                  <td className="px-3 py-2">
                    <Badge value={g.coverage_class} />
                  </td>
                  <td className="px-3 py-2">
                    {g.flags.length ? g.flags.map((f) => <Flag key={f} flag={f} />) : <span className="text-slate-400">none</span>}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap gap-1">
                      {actionsFor(g).map((action) => (
                        <button
                          key={action}
                          onClick={() => setPending({ gateway: g.gateway_id, action })}
                          className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100"
                        >
                          {label(action)}
                        </button>
                      ))}
                    </div>
                  </td>
                </tr>
                {pending?.gateway === g.gateway_id && (
                  <tr className="border-b border-slate-100">
                    <td colSpan={8} className="px-3 pb-2">
                      <ActionForm
                        path={`/api/v1/gateways/${g.gateway_id}/actions`}
                        action={pending.action}
                        reasonRequired={pending.action === "suspend"}
                        onCancel={() => setPending(null)}
                        onDone={() => {
                          setPending(null);
                          refresh();
                        }}
                      />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      {timelineOf && <TimelineDrawer entity="gateways" id={timelineOf} onClose={() => setTimelineOf(null)} />}
    </main>
  );
}
