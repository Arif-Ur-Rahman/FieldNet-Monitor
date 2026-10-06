"use client";

import { Fragment, useState } from "react";

import ActionForm from "@/components/ActionForm";
import { Badge, Count, Legend, Paused } from "@/components/badges";
import PageHeader from "@/components/PageHeader";
import type { Lifecycle, Sensor } from "@/lib/api";
import { duration, label, stamp, until } from "@/lib/format";
import { usePoll } from "@/lib/usePoll";

const LIFECYCLES: Lifecycle[] = ["pending", "active", "dormant", "sampling", "retired", "decommissioned"];

/** A dormant wait or sampling window runs in available time; with no end time it is paused. */
function NextEvaluation({ s, now }: { s: Sensor; now: Date | null }) {
  if (s.next_evaluation_at) {
    return (
      <span title={stamp(s.next_evaluation_at)} className="whitespace-nowrap text-slate-700">
        {until(s.next_evaluation_at, now)}
      </span>
    );
  }
  if (s.lifecycle === "dormant" || s.lifecycle === "sampling") return <Paused />;
  return <span className="text-slate-400">no wait</span>;
}

export default function SensorsPage() {
  const [lifecycle, setLifecycle] = useState("");
  const [decommissioning, setDecommissioning] = useState<string | null>(null);
  const path = lifecycle ? `/api/v1/sensors?lifecycle=${lifecycle}` : "/api/v1/sensors";
  const { data, serverNow, error, refresh } = usePoll<Sensor[]>(path);

  return (
    <main className="mx-auto w-full max-w-7xl px-6 py-6">
      <PageHeader title="Sensors" serverNow={serverNow} error={error}>
        <div className="flex flex-col items-end gap-2">
          <Legend />
          <label className="text-sm text-slate-600">
            Lifecycle{" "}
            <select
              value={lifecycle}
              onChange={(e) => setLifecycle(e.target.value)}
              className="rounded border border-slate-300 bg-white px-2 py-1"
            >
              <option value="">all</option>
              {LIFECYCLES.map((l) => (
                <option key={l} value={l}>
                  {label(l)}
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
              <th className="px-3 py-2">Sensor</th>
              <th className="px-3 py-2">Lifecycle</th>
              <th className="px-3 py-2">Reason</th>
              <th className="px-3 py-2">Collection</th>
              <th className="px-3 py-2">Coverage</th>
              <th className="px-3 py-2" title="Quiet checked days since the last reading day">
                Quiet days
              </th>
              <th className="px-3 py-2" title="Sampling windows ended with checks and no reading">
                Cycles
              </th>
              <th className="px-3 py-2">Next evaluation</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {data?.length === 0 && (
              <tr>
                <td colSpan={9} className="px-3 py-6 text-center text-slate-500">
                  No sensors{lifecycle && ` that are ${label(lifecycle)}`}.
                </td>
              </tr>
            )}
            {data?.map((s) => (
              <Fragment key={s.sensor_id}>
                <tr className="border-b border-slate-100 align-top">
                  <td className="px-3 py-2">
                    <div className="font-mono text-slate-900">{s.sensor_id}</div>
                    <div className="text-xs text-slate-500">{s.type}</div>
                  </td>
                  <td className="whitespace-nowrap px-3 py-2">
                    <Badge value={s.lifecycle} />{" "}
                    <span className="text-xs text-slate-600" title={`since ${stamp(s.lifecycle_since)}`}>
                      · {serverNow ? duration(serverNow.getTime() - new Date(s.lifecycle_since).getTime()) : ""}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-slate-700">
                    {s.lifecycle_reason ? label(s.lifecycle_reason) : <span className="text-slate-400">—</span>}
                  </td>
                  <td className="px-3 py-2">
                    <Badge value={s.collection} />
                  </td>
                  <td className="px-3 py-2">
                    <Badge value={s.coverage} />
                  </td>
                  <td className="px-3 py-2">
                    <Count n={s.quiet_checked_days} />
                  </td>
                  <td className="px-3 py-2">
                    <Count n={s.sampling_cycles_done} />
                  </td>
                  <td className="px-3 py-2">
                    <NextEvaluation s={s} now={serverNow} />
                  </td>
                  <td className="px-3 py-2 text-right">
                    {s.lifecycle !== "decommissioned" && (
                      <button
                        onClick={() => setDecommissioning(s.sensor_id)}
                        className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100"
                      >
                        decommission
                      </button>
                    )}
                  </td>
                </tr>
                {decommissioning === s.sensor_id && (
                  <tr className="border-b border-slate-100">
                    <td colSpan={9} className="px-3 pb-2">
                      <ActionForm
                        path={`/api/v1/sensors/${s.sensor_id}/actions`}
                        action="decommission"
                        reasonRequired
                        onCancel={() => setDecommissioning(null)}
                        onDone={() => {
                          setDecommissioning(null);
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
    </main>
  );
}
