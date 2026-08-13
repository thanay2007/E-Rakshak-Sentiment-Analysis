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
