"use client";

import { Badge, Count, Legend } from "@/components/badges";
import PageHeader from "@/components/PageHeader";
import type { Counts, Dashboard } from "@/lib/api";
import { label } from "@/lib/format";
import { usePoll } from "@/lib/usePoll";

function Tile({ title, counts, badges = true }: { title: string; counts: Counts; badges?: boolean }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <h2 className="mb-3 text-sm font-medium text-slate-700">{title}</h2>
      <ul className="space-y-1.5">
        {Object.entries(counts).map(([value, n]) => (
          <li key={value} className="flex items-center justify-between text-sm">
            {badges ? <Badge value={value} /> : <span className="text-slate-600">{label(value)}</span>}
            <Count n={n} />
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function DashboardPage() {
  const { data, serverNow, error } = usePoll<Dashboard>("/api/v1/dashboard");
  return (
    <main className="mx-auto w-full max-w-7xl px-6 py-6">
      <PageHeader title="Dashboard" serverNow={serverNow} error={error}>
        <Legend />
      </PageHeader>
      {data && (
        <div className="space-y-6">
          <div>
            <h2 className="mb-2 text-sm font-semibold text-slate-900">Gateways · {data.gateways.total}</h2>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Tile title="Status" counts={data.gateways.status} />
              <Tile title="Command state" counts={data.gateways.command_state} />
              <Tile title="Coverage class" counts={data.gateways.coverage_class} />
              <Tile title="Flags" counts={data.gateways.flags} badges={false} />
            </div>
          </div>
          <div>
            <h2 className="mb-2 text-sm font-semibold text-slate-900">Sensors · {data.sensors.total}</h2>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Tile title="Lifecycle" counts={data.sensors.lifecycle} />
              <Tile title="Retired, by reason" counts={data.sensors.retired_reason} badges={false} />
              <Tile title="Coverage" counts={data.sensors.coverage} />
              <Tile title="Collection" counts={data.sensors.collection} />
            </div>
          </div>
          <div>
            <h2 className="mb-2 text-sm font-semibold text-slate-900">Batches · {data.batches.total}</h2>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Tile title="Processing" counts={data.batches.processing} badges={false} />
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
