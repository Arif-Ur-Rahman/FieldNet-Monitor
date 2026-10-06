"use client";

import { useCallback, useEffect, useState } from "react";

import { get } from "./api";

export const POLL_MS = 5000;

/** Fetch `path` now and every POLL_MS. `refresh()` fetches again at once (after an action). */
export function usePoll<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [serverNow, setServerNow] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const refresh = useCallback(() => setTick((n) => n + 1), []);

  useEffect(() => {
    if (path === null) return;
    const controller = new AbortController();
    const load = () =>
      get<T>(path, controller.signal)
        .then((r) => {
          setData(r.data);
          setServerNow(r.serverNow);
          setError(null);
        })
        .catch((e: Error) => {
          if (e.name !== "AbortError") setError(e.message);
        });
    load();
    const timer = setInterval(load, POLL_MS);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [path, tick]);

  return { data, serverNow, error, refresh };
}
