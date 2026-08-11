import { AlertTriangle, ExternalLink, FileWarning, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../services/api";
import { safeHref } from "../lib/safeUrl";

/**
 * One image or video attached to a post.
 *
 * The bytes come from `/api/media`, which fetches them server-side — the
 * browser never contacts Telegram's or Instagram's CDN, so a platform cannot
 * learn which post an officer opened or from what address (see
 * backend/app/routers/media.py).
 *
 * That endpoint is authenticated with a bearer token, and `<img src>` cannot
 * carry an Authorization header. So the bytes are fetched with `fetch()` and
 * handed to the element as an object URL, which is revoked on unmount — an
 * un-revoked object URL pins its blob in memory for the life of the document,
 * and an analyst scrolling a feed of image posts would leak steadily.
 *
 * Failure is shown, never hidden: a blank space where a photo should be reads
 * as "this post had no image", which is a different and wrong fact.
 */
const VIDEO_RE = /\.(mp4|webm|mov|m4v)(\?|$)/i;

export default function PostMedia({
  url, className = "", maxHeight = 160,
}: {
  url: string;
  className?: string;
  maxHeight?: number;
}) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [reason, setReason] = useState("");

  useEffect(() => {
    let live = true;
    let created: string | null = null;
    setState("loading");
    setReason("");

    api
      .media(url)
      .then((blob) => {
        if (!live) return;
        created = URL.createObjectURL(blob);
        setObjectUrl(created);
        setState("ready");
      })
      .catch((e: unknown) => {
        if (!live) return;
        setReason(e instanceof Error ? e.message : "could not be loaded");
        setState("error");
      });

    return () => {
      live = false;
      // Revoke whichever URL this effect created, not whatever is in state —
      // state may already belong to the next `url` by the time this runs.
      if (created) URL.revokeObjectURL(created);
    };
  }, [url]);

  const isVideo = VIDEO_RE.test(url);

  if (state === "loading") {
    return (
      <div
        className={`grid place-items-center rounded-xl border border-white/10 bg-white/[0.03] ${className}`}
        style={{ height: maxHeight, minWidth: maxHeight }}
      >
        <Loader2 size={16} className="animate-spin text-slate-500" />
      </div>
    );
  }

  if (state === "error" || !objectUrl) {
    return (
      <a
        href={safeHref(url)}
        target="_blank"
        rel="noreferrer"
        title={reason}
        className={`grid place-items-center gap-1 rounded-xl border border-amber-500/30 bg-amber-500/[0.06] px-3 text-center ${className}`}
        style={{ height: maxHeight, minWidth: maxHeight }}
      >
        <FileWarning size={16} className="text-amber-400" />
        <span className="text-[10px] leading-tight text-amber-200/80">
          Media unavailable
        </span>
        <span className="inline-flex items-center gap-1 text-[10px] text-sky-400">
          open at source <ExternalLink size={9} />
        </span>
      </a>
    );
  }

  if (isVideo) {
    return (
      <video
        src={objectUrl}
        controls
        preload="metadata"
        className={`rounded-xl border border-white/10 object-cover ${className}`}
        style={{ maxHeight }}
      />
    );
  }

  return (
    <a href={safeHref(url)} target="_blank" rel="noreferrer" title="Open at source">
      <img
        src={objectUrl}
        alt="Media attached to this post"
        className={`rounded-xl border border-white/10 object-cover ${className}`}
        style={{ maxHeight }}
        loading="lazy"
      />
    </a>
  );
}

/** Grid of every attachment on a post. */
export function PostMediaGrid({
  urls, maxHeight = 160,
}: {
  urls: string[];
  maxHeight?: number;
}) {
  if (!urls.length) return null;
  return (
    <div className="flex flex-wrap gap-2">
      {urls.map((m) => (
        <PostMedia key={m} url={m} maxHeight={maxHeight} />
      ))}
    </div>
  );
}

export { AlertTriangle };
