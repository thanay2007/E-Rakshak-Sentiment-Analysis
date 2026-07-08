import { useEffect, useState } from "react";
import type { Alert, Post } from "../services/api";
import { liveSocket } from "../services/ws";

/** Live post stream (newest first, capped). */
export function useLivePosts(cap = 40) {
  const [posts, setPosts] = useState<Post[]>([]);
  useEffect(() => {
    liveSocket.start();
    return liveSocket.subscribe((msg) => {
      if (msg.type === "post") {
        setPosts((prev) => [msg.data, ...prev].slice(0, cap));
      }
    });
  }, [cap]);
  return posts;
}

/** Live alert stream. */
export function useLiveAlerts(cap = 20) {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  useEffect(() => {
    liveSocket.start();
    return liveSocket.subscribe((msg) => {
      if (msg.type === "alert") {
        setAlerts((prev) => [msg.data, ...prev].slice(0, cap));
      }
    });
  }, [cap]);
  return alerts;
}

/** WS connection status for the LIVE dot. */
export function useLiveStatus() {
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    liveSocket.start();
    return liveSocket.onStatus(setConnected);
  }, []);
  return connected;
}

/** "last updated Xs ago" ticker. */
export function useAgo(iso?: string) {
  const [, force] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => force((n) => n + 1), 1000);
    return () => window.clearInterval(id);
  }, []);
  if (!iso) return "—";
  const secs = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  return `${Math.floor(secs / 3600)}h ago`;
}
