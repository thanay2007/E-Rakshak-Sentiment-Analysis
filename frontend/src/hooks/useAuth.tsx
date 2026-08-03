/** Session state for the whole app.
 *
 *  The provider owns three responsibilities:
 *    1. hold the current user and re-render when it changes
 *    2. catch a 401 from anywhere in the app and end the session cleanly
 *    3. tear down the live WebSocket on sign-out, so a signed-off browser
 *       stops receiving threat data
 */
import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
} from "react";
import type { ReactNode } from "react";

import { setUnauthorizedHandler } from "../services/api";
import {
  atLeast, clearSession, getUser, login as doLogin, logout as doLogout,
  onAuthChange,
} from "../services/auth";
import type { CurrentUser } from "../services/auth";
import { liveSocket } from "../services/ws";

interface AuthState {
  user: CurrentUser | null;
  signedIn: boolean;
  /** Set when the previous session ended unexpectedly, so the sign-in screen
   *  can explain why the user is suddenly back here. */
  sessionEndedReason: string | null;
  signIn: (username: string, password: string) => Promise<CurrentUser>;
  signOut: () => Promise<void>;
  can: (minimumRole: "analyst" | "supervisor" | "admin") => boolean;
  refreshUser: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(() => getUser());
  const [sessionEndedReason, setReason] = useState<string | null>(null);

  // Keep in step with sessionStorage writes made outside React (auth.ts).
  useEffect(() => onAuthChange(setUser), []);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      clearSession();
      liveSocket.stop();
      setReason("Your session ended. Please sign in again.");
    });
  }, []);

  const signIn = useCallback(async (username: string, password: string) => {
    const result = await doLogin(username, password);
    setReason(null);
    liveSocket.resume();
    return result.user;
  }, []);

  const signOut = useCallback(async () => {
    liveSocket.stop();
    await doLogout();
    setReason(null);
  }, []);

  const can = useCallback(
    (minimumRole: "analyst" | "supervisor" | "admin") => atLeast(user?.role, minimumRole),
    [user],
  );

  const value = useMemo<AuthState>(
    () => ({
      user,
      signedIn: !!user,
      sessionEndedReason,
      signIn,
      signOut,
      can,
      refreshUser: () => setUser(getUser()),
    }),
    [user, sessionEndedReason, signIn, signOut, can],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
