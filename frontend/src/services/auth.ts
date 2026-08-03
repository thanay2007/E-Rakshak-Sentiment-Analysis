/** Session handling for the dashboard.
 *
 *  Storage choice: sessionStorage, not localStorage. These are shared station
 *  terminals — sessionStorage is scoped to the tab and is gone the moment the
 *  browser closes, so an officer walking away from a machine does not leave a
 *  live session behind for whoever sits down next. The cost is that a new tab
 *  needs a fresh sign-in, which is the right trade for this deployment.
 *
 *  It is still script-readable, so it is only as safe as the app's XSS posture.
 *  That is why every crawled URL goes through safeHref() before it reaches an
 *  href, and why the API sends no HTML.
 */
import { API_BASE } from "./api";

const TOKEN_KEY = "sentinel.token";
const USER_KEY = "sentinel.user";

export interface CurrentUser {
  id: string;
  username: string;
  full_name: string;
  badge_number: string;
  unit: string;
  role: "analyst" | "supervisor" | "admin";
  active: boolean;
  must_change_password: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface LoginResult {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: CurrentUser;
}

type Listener = (user: CurrentUser | null) => void;
const listeners = new Set<Listener>();

export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function getUser(): CurrentUser | null {
  const raw = sessionStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as CurrentUser;
  } catch {
    return null;
  }
}

function publish() {
  const u = getUser();
  listeners.forEach((fn) => fn(u));
}

export function onAuthChange(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function setSession(result: LoginResult) {
  sessionStorage.setItem(TOKEN_KEY, result.access_token);
  sessionStorage.setItem(USER_KEY, JSON.stringify(result.user));
  publish();
}

export function clearSession() {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(USER_KEY);
  publish();
}

/** Rank comparison mirroring the backend hierarchy in app/security/roles.py.
 *  This drives what the UI *offers*; it is not a security control. The server
 *  re-checks every call, because anything decided in the browser is decided by
 *  whoever controls the browser. */
const RANK: Record<string, number> = { analyst: 0, supervisor: 1, admin: 2 };

export function atLeast(role: string | undefined, minimum: string): boolean {
  if (!role) return false;
  return (RANK[role] ?? -1) >= (RANK[minimum] ?? 99);
}

export async function login(username: string, password: string): Promise<LoginResult> {
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(body?.detail || "Sign-in failed. Check your username and password.");
  }
  setSession(body as LoginResult);
  return body as LoginResult;
}

export async function logout(): Promise<void> {
  const token = getToken();
  if (token) {
    // Best-effort: tell the server to revoke the token family. Even if this
    // fails (offline, server down), the local session is cleared regardless —
    // a sign-out must never appear to fail and leave the officer signed in.
    try {
      await fetch(`${API_BASE}/api/auth/logout`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
    } catch {
      /* ignore */
    }
  }
  clearSession();
}

export async function changePassword(current: string, next: string): Promise<LoginResult> {
  const token = getToken();
  const res = await fetch(`${API_BASE}/api/auth/change-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ current_password: current, new_password: next }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body?.detail || "Could not change the password.");
  // The server rotates the token on a password change (it revokes the old
  // family), so the new one must replace what we hold or the next call 401s.
  setSession(body as LoginResult);
  return body as LoginResult;
}
