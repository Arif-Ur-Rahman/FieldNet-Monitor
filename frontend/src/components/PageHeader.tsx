import { stamp } from "@/lib/format";

/** Title, the server clock the data was measured at, and any load error. */
export default function PageHeader({
  title,
  serverNow,
  error,
  children,
}: {
  title: string;
  serverNow: Date | null;
  error: string | null;
  children?: React.ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">{title}</h1>
        <p className="text-xs text-slate-500">
          Server clock: {serverNow ? stamp(serverNow.toISOString()) : "…"} · refreshes every 5s
        </p>
        {error && <p className="mt-1 text-sm text-red-700">Could not load: {error}</p>}
      </div>
      {children}
    </div>
  );
}
