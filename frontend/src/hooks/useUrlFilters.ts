/** Page filters that live in the URL rather than in component state.
 *
 *  The threat feed already worked this way; this generalises it so the rest of
 *  the console does too. Three things follow from the URL being the source of
 *  truth, and the third is the one this exists for:
 *
 *  1. A filtered view is linkable — an officer can paste "the critical alerts
 *     I'm looking at" into a handover note and it survives.
 *  2. Back and forward step through filter changes, which is what every user
 *     already expects them to do.
 *  3. **The assistant can set them.** Its `navigate` tool resolves a page
 *     label against a fixed table and appends validated filter values as query
 *     parameters; a page holding its filters in `useState` would render that
 *     query string inert, showing an unfiltered screen while the assistant says
 *     it filtered one. Filters in the URL are the contract that makes "show me
 *     negative posts from Surat" land on an actually-filtered page.
 *
 *  Writes are `replace: true`: dragging a slider or clicking through four
 *  severities should not bury the previous page under four history entries.
 */
import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";

export function useUrlFilters() {
  const [params, setParams] = useSearchParams();

  const get = useCallback(
    (key: string, fallback = "") => params.get(key) ?? fallback,
    [params]
  );

  /** Reading a numeric control. Anything unparseable — including a value the
   *  assistant or a hand-edited URL invented — falls back rather than putting
   *  NaN into a request. */
  const getNumber = useCallback(
    (key: string, fallback: number, allowed?: readonly number[]) => {
      const raw = params.get(key);
      if (raw === null) return fallback;
      const value = Number(raw);
      if (!Number.isFinite(value)) return fallback;
      if (allowed && !allowed.includes(value)) return fallback;
      return value;
    },
    [params]
  );

  const set = useCallback(
    (key: string, value: string | number | null | undefined) => {
      setParams((prev) => {
        const next = new URLSearchParams(prev);
        const text = value === null || value === undefined ? "" : String(value);
        if (text) next.set(key, text);
        else next.delete(key);
        return next;
      }, { replace: true });
    },
    [setParams]
  );

  const clear = useCallback(
    (...keys: string[]) => {
      setParams((prev) => {
        const next = new URLSearchParams(prev);
        keys.forEach((key) => next.delete(key));
        return next;
      }, { replace: true });
    },
    [setParams]
  );

  return { get, getNumber, set, clear };
}
