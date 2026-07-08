import { useCallback, useEffect, useRef, useState } from "react";

/** Fetch-and-refresh hook: loads immediately, refreshes every `intervalMs`,
 *  exposes loading/error and a manual refresh. */
export function usePolling<T>(fetcher: () => Promise<T>, intervalMs = 30000, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const load = useCallback(async () => {
    try {
      const d = await fetcherRef.current();
      setData(d);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    load();
    const id = window.setInterval(load, intervalMs);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, load, ...deps]);

  return { data, error, loading, refresh: load };
}
