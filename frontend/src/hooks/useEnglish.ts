import { useEffect, useState } from "react";
import { api } from "../services/api";

/**
 * Automatic English for non-English posts.
 *
 * Ingestion translates most non-English posts, but not all of them (its batch
 * is capped and it skips when the LLM budget is drained). Any post that reaches
 * the screen without a translation is requested here. Requests from every card
 * on the page are pooled into one call, and the backend stores the result on
 * the post, so each post is translated once for everyone.
 */

// Scripts that are certainly not English: Cyrillic, Arabic, Indic, Thai/Tibetan, CJK, Hangul.
// Code-point ranges rather than a regex class: these blocks contain combining
// marks, which a character class handles misleadingly.
const NON_LATIN: [number, number][] = [
  [0x0400, 0x04ff], [0x0600, 0x06ff], [0x0900, 0x0dff], [0x0e00, 0x0fff],
  [0x3040, 0x9fff], [0xac00, 0xd7af],
];

function hasNonLatin(text: string): boolean {
  for (const ch of text) {
    const cp = ch.codePointAt(0)!;
    if (NON_LATIN.some(([lo, hi]) => cp >= lo && cp <= hi)) return true;
  }
  return false;
}

export function needsEnglish(text?: string, language?: string): boolean {
  if (!text?.trim()) return false;
  return (!!language && language !== "English" && language !== "Unknown") || hasNonLatin(text);
}

const MAX_BATCH = 40;
const FLUSH_MS = 60;
/** id -> English, or null when the server had none to give (already English). */
const cache = new Map<string, string | null>();
const waiting = new Map<string, Set<(english: string | null) => void>>();
const queue = new Set<string>();
let timer: ReturnType<typeof setTimeout> | null = null;

function schedule() {
  if (!timer) timer = setTimeout(() => void flush(), FLUSH_MS);
}

async function flush() {
  timer = null;
  const ids = [...queue].slice(0, MAX_BATCH);
  ids.forEach((id) => queue.delete(id));
  if (queue.size) schedule();
  let got: Record<string, string> | null = null;
  try {
    const res = await api.translatePosts(ids);
    if (res.available) got = res.translations;
  } catch {
    // Leave the original on screen; a later render may ask again.
  }
  for (const id of ids) {
    const english = got?.[id] ?? null;
    if (got) cache.set(id, english); // failures are not cached, so they are retried
    waiting.get(id)?.forEach((cb) => cb(english));
    waiting.delete(id);
  }
}

function request(id: string, cb: (english: string | null) => void): () => void {
  let subs = waiting.get(id);
  if (!subs) {
    subs = new Set();
    waiting.set(id, subs);
    queue.add(id);
    schedule();
  }
  subs.add(cb);
  return () => {
    subs?.delete(cb);
  };
}

/** English for a post: its stored translation, or one fetched automatically
 *  when the post is not English and has none yet. `english` is null for an
 *  English post (or when no translation could be produced). */
export function useEnglish(
  id: string | undefined,
  text: string | undefined,
  translation?: string | null,
  language?: string,
): { english: string | null; pending: boolean } {
  const stored = translation && translation !== text ? translation : null;
  const wanted = !stored && !!id && needsEnglish(text, language);
  const [fetched, setFetched] = useState<string | null>(() => (wanted && id ? cache.get(id) ?? null : null));
  const [pending, setPending] = useState(() => wanted && !!id && !cache.has(id));

  useEffect(() => {
    if (!wanted || !id) {
      setPending(false);
      return;
    }
    if (cache.has(id)) {
      setFetched(cache.get(id) ?? null);
      setPending(false);
      return;
    }
    setPending(true);
    let alive = true;
    const unsubscribe = request(id, (english) => {
      if (!alive) return;
      setFetched(english);
      setPending(false);
    });
    return () => {
      alive = false;
      unsubscribe();
    };
  }, [id, wanted]);

  const english = stored ?? (fetched && fetched !== text ? fetched : null);
  return { english, pending: !stored && pending };
}
