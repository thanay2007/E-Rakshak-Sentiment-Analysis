/** Reconnecting WebSocket client for /ws/live. One shared connection drives
 *  the live feed, alert toasts and the LIVE status dot. */
import { WS_URL } from "./api";
import type { Alert, Post } from "./api";
import { getToken } from "./auth";

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
  private reconnectTimer: number | undefined;
  private stopped = false;
  connected = false;

  start() {
    // `ws` is null while a reconnect is merely *scheduled*, so checking it
    // alone would let a component mounting during backoff open a second
    // socket alongside the pending one — duplicating every post and alert.
    if (this.ws || this.reconnectTimer !== undefined) return;
    if (!getToken()) return;   // nothing to authenticate with yet
    this.open();
  }

  /** Drop the connection on sign-out. Without this the socket keeps streaming
   *  live threat data to a browser whose user has just signed off. */
  stop() {
    this.stopped = true;
    if (this.reconnectTimer !== undefined) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = undefined;
    }
    window.clearInterval(this.pingTimer);
    this.ws?.close();
    this.ws = null;
    this.setConnected(false);
  }

  /** Called after a successful sign-in to allow reconnects again. */
  resume() {
    this.stopped = false;
    this.retry = 0;
    this.start();
  }

  private open() {
    this.reconnectTimer = undefined;
    try {
      this.ws = new WebSocket(WS_URL);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws.onopen = () => {
      this.retry = 0;
      // The socket is open but NOT yet authenticated: the server sends nothing
      // until it has verified the first frame, and closes with 1008 if it does
      // not arrive. Sent as a frame rather than a query parameter so the token
      // stays out of access logs and browser history.
      const token = getToken();
      if (!token) {
        this.ws?.close();
        return;
      }
      this.ws?.send(JSON.stringify({ type: "auth", token }));
      // Keepalive only starts once the server confirms the session below.
    };
    this.ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data) as LiveMessage | { type: "auth_ok"; user: string };
        if (msg.type === "auth_ok") {
          this.setConnected(true);
          this.pingTimer = window.setInterval(() => this.ws?.send("ping"), 25000);
          return;
        }
        this.listeners.forEach((l) => l(msg as LiveMessage));
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
    if (this.reconnectTimer !== undefined) return;
    // No token means the session ended; reconnecting would just loop against a
    // server that will refuse the handshake every time.
    if (this.stopped || !getToken()) return;
    const delay = Math.min(15000, 1000 * 2 ** this.retry++);
    this.reconnectTimer = window.setTimeout(() => this.open(), delay);
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
