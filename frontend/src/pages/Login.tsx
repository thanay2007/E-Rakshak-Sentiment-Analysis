import { motion } from "framer-motion";
import { AlertCircle, Loader2, Lock, Shield, User } from "lucide-react";
import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import BackgroundFX from "../components/BackgroundFX";
import { useAuth } from "../hooks/useAuth";
import { safeInternalPath } from "../lib/safeUrl";
import { changePassword } from "../services/auth";

export default function Login() {
  const { signIn, sessionEndedReason, refreshUser } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  // Constrained to an in-app path: an unchecked redirect target here is the
  // classic phishing hop — sign in for real, get bounced to a look-alike.
  const from = safeInternalPath((location.state as { from?: string } | null)?.from);

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Second stage: the server flagged this account as needing a new password
  // (first sign-in, or an admin reset). No other screen is reachable until
  // it is done, which is what stops a bootstrap credential becoming permanent.
  const [mustChange, setMustChange] = useState(false);
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  async function handleSignIn(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const user = await signIn(username.trim(), password);
      if (user.must_change_password) {
        setMustChange(true);
      } else {
        navigate(from, { replace: true });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  }

  async function handleChangePassword(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (newPassword !== confirmPassword) {
      setError("The two new passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await changePassword(password, newPassword);
      refreshUser();
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not change the password.");
    } finally {
      setBusy(false);
    }
  }

  const field =
    "w-full rounded-xl border border-white/[0.08] bg-white/[0.04] py-2.5 pl-10 pr-3 text-sm " +
    "text-slate-100 placeholder-slate-500 outline-none focus:border-accent/50";

  return (
    <div className="relative flex min-h-screen items-center justify-center p-4">
      <BackgroundFX />
      <motion.div
        initial={{ opacity: 0, y: 18, filter: "blur(6px)" }}
        animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
        transition={{ duration: 0.5, ease: "easeOut" }}
        className="w-full max-w-sm rounded-2xl border border-white/[0.08] bg-base-900/70 p-6 backdrop-blur-xl"
      >
        <div className="mb-6 flex items-center gap-2.5">
          <span className="grid h-9 w-9 place-items-center rounded-xl border border-accent/40 bg-accent/15">
            <Shield size={17} className="text-accent" />
          </span>
          <div>
            <h1 className="text-sm font-bold tracking-wide text-slate-100">E-RAKSHAK · SENTINEL</h1>
            <p className="text-[11px] text-slate-500">Authorised personnel only</p>
          </div>
        </div>

        {sessionEndedReason && !error && !mustChange && (
          <p className="mb-4 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-300">
            {sessionEndedReason}
          </p>
        )}

        {error && (
          <p className="mb-4 flex items-start gap-2 rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-[11px] text-red-300">
            <AlertCircle size={13} className="mt-px shrink-0" />
            <span>{error}</span>
          </p>
        )}

        {!mustChange ? (
          <form onSubmit={handleSignIn} className="space-y-3">
            <div className="relative">
              <User size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                className={field}
                placeholder="Username"
                autoComplete="username"
                autoFocus
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
              />
            </div>
            <div className="relative">
              <Lock size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                className={field}
                type="password"
                placeholder="Password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            <button
              type="submit"
              disabled={busy}
              className="glow-accent mt-2 flex w-full items-center justify-center gap-2 rounded-xl border border-accent/50 bg-accent/15 px-4 py-2.5 text-xs font-bold text-accent hover:bg-accent hover:text-base-900 disabled:opacity-50"
            >
              {busy && <Loader2 size={14} className="animate-spin" />}
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>
        ) : (
          <form onSubmit={handleChangePassword} className="space-y-3">
            <p className="mb-1 text-[11px] leading-relaxed text-slate-400">
              This account requires a new password before it can be used. Choose at least 12
              characters mixing three of: lowercase, uppercase, digits, symbols.
            </p>
            <div className="relative">
              <Lock size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                className={field}
                type="password"
                placeholder="New password"
                autoComplete="new-password"
                autoFocus
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
              />
            </div>
            <div className="relative">
              <Lock size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                className={field}
                type="password"
                placeholder="Confirm new password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
              />
            </div>
            <button
              type="submit"
              disabled={busy}
              className="glow-accent mt-2 flex w-full items-center justify-center gap-2 rounded-xl border border-accent/50 bg-accent/15 px-4 py-2.5 text-xs font-bold text-accent hover:bg-accent hover:text-base-900 disabled:opacity-50"
            >
              {busy && <Loader2 size={14} className="animate-spin" />}
              {busy ? "Saving…" : "Set password and continue"}
            </button>
          </form>
        )}

        <p className="mt-5 text-center text-[10px] leading-relaxed text-slate-600">
          Access is logged. Every search, export and record change is recorded against your
          badge for chain-of-custody purposes.
        </p>
      </motion.div>
    </div>
  );
}
