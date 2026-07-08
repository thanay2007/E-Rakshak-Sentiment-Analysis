/** Reconnecting WebSocket client for /ws/live. One shared connection drives
 *  the live feed, alert toasts and the LIVE status dot. */
import { WS_URL } from "./api";
import type { Alert, Post } from "./api";

export type LiveMessage =
  | { type: "post"; data: Post }
  | { type: "alert"; data: Alert };

type Listener = (msg: LiveMessage) => void;
type StatusListener = (connected: boolean) => void;

class LiveSocket {
  private ws: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private statusListeners = new Set<StatusListener>();
  private retry = 0;
  private pingTimer: number | undefined;
  connected = false;

  start() {
    if (this.ws) return;
    this.open();
  }

  private open() {
    try {
      this.ws = new WebSocket(WS_URL);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws.onopen = () => {
      this.retry = 0;
      this.setConnected(true);
      // server expects occasional client text as keepalive
      this.pingTimer = window.setInterval(() => this.ws?.send("ping"), 25000);
    };
    this.ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data) as LiveMessage;
        this.listeners.forEach((l) => l(msg));
      } catch {
        /* ignore malformed frames */
      }
    };
    this.ws.onclose = () => {
      this.setConnected(false);
      window.clearInterval(this.pingTimer);
      this.ws = null;
      this.scheduleReconnect();
    };
    this.ws.onerror = () => this.ws?.close();
  }

  private scheduleReconnect() {
    const delay = Math.min(15000, 1000 * 2 ** this.retry++);
    window.setTimeout(() => this.open(), delay);
  }

  private setConnected(v: boolean) {
    this.connected = v;
    this.statusListeners.forEach((l) => l(v));
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  onStatus(fn: StatusListener): () => void {
    this.statusListeners.add(fn);
    fn(this.connected);
    return () => this.statusListeners.delete(fn);
  }
}

export const liveSocket = new LiveSocket();
