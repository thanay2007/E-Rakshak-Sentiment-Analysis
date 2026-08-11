import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import PostDetail from "./PostDetail";
import { api, type Post } from "../services/api";

/**
 * One post-detail modal for the whole console.
 *
 * Every surface that lists posts — the dashboard, the feed, alert triage,
 * trends, the network graph, reports, the investigation tools — needs the same
 * thing when a post is clicked: the full record, its tag and score, the
 * translation, and the evidence behind both. Mounting a drawer per page meant
 * three pages had one and the rest silently did nothing on click.
 *
 * So it lives once, in the app shell, and any component opens it through
 * `usePostDetail()`. Two entry points, because callers have different things
 * in hand:
 *   • `openPost(post)`  — the caller already has the full Post row
 *   • `openPostId(id)`  — the caller only has a post_id (alerts, clusters,
 *     trend rows, dossier hits); the record is fetched on open
 */
type Ctx = {
  openPost: (p: Post) => void;
  openPostId: (id: string) => void;
  close: () => void;
};

const PostDetailContext = createContext<Ctx | null>(null);

export function usePostDetail(): Ctx {
  const ctx = useContext(PostDetailContext);
  if (!ctx) {
    throw new Error("usePostDetail must be used inside <PostDetailProvider>");
  }
  return ctx;
}

export default function PostDetailProvider({ children }: { children: React.ReactNode }) {
  const [post, setPost] = useState<Post | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const close = useCallback(() => {
    setPost(null);
    setPendingId(null);
    setError(null);
  }, []);

  const openPost = useCallback((p: Post) => {
    setError(null);
    setPendingId(null);
    setPost(p);
  }, []);

  const openPostId = useCallback((id: string) => {
    setError(null);
    setPost(null);
    setPendingId(id);
  }, []);

  // Fetch-on-open for the id-only callers. Guarded against a stale response
  // overwriting a newer one: an analyst clicking through a list faster than the
  // network answers would otherwise land on whichever request finished last.
  useEffect(() => {
    if (!pendingId) return;
    let live = true;
    api
      .post(pendingId)
      .then((p) => {
        if (!live) return;
        setPost(p);
        setPendingId(null);
      })
      .catch(() => {
        if (!live) return;
        setError("This post could not be loaded — it may have been purged by a retention run.");
        setPendingId(null);
      });
    return () => {
      live = false;
    };
  }, [pendingId]);

  const value = useMemo(() => ({ openPost, openPostId, close }), [openPost, openPostId, close]);

  return (
    <PostDetailContext.Provider value={value}>
      {children}
      <PostDetail post={post} loading={!!pendingId} error={error} onClose={close} />
    </PostDetailContext.Provider>
  );
}
