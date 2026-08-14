import { motion } from "framer-motion";
import { AlertCircle, Loader2, Lock, User } from "lucide-react";
import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import BackgroundFX from "../components/BackgroundFX";
import { Logo } from "../components/Sidebar";
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
    "w-full rounded-xl border border-white/[0.12] bg-base-950/80 py-2.5 pl-10 pr-3 text-sm " +
    "text-white placeholder-slate-500 outline-none focus:border-accent/80 focus:ring-1 focus:ring-accent/40 transition-all";

  return (
    <div className="relative flex min-h-screen items-center justify-center p-4">
      <BackgroundFX />
      <motion.div
        initial={{ opacity: 0, y: 18, filter: "blur(6px)" }}
        animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
        transition={{ duration: 0.5, ease: "easeOut" }}
        className="w-full max-w-md rounded-3xl border border-white/[0.1] bg-base-950/90 p-8 backdrop-blur-2xl shadow-2xl"
      >
        <div className="mb-6 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-accent/40 bg-accent/15 shadow-[0_0_15px_rgba(245,158,11,0.25)]">
              <Logo size={28} />
            </div>
            <div>
              <h1 className="text-base font-black tracking-wide text-white">SENTINEL · AUTH</h1>
              <p className="text-[11px] font-semibold text-accent uppercase">State Cyber Intelligence</p>
            </div>
          </div>
          <button
            onClick={() => navigate("/")}
            className="text-xs text-slate-400 hover:text-white transition-colors"
          >
            Portal Home →
          </button>
        </div>

        {sessionEndedReason && !error && !mustChange && (
          <p className="mb-4 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3.5 py-2 text-xs text-amber-300">
            {sessionEndedReason}
          </p>
        )}

        {error && (
          <p className="mb-4 flex items-start gap-2 rounded-xl border border-red-500/30 bg-red-500/10 px-3.5 py-2 text-xs text-red-300">
            <AlertCircle size={15} className="mt-0.5 shrink-0" />
            <span>{error}</span>
          </p>
        )}

        {!mustChange ? (
          <form onSubmit={handleSignIn} className="space-y-4">
            <div className="space-y-1">
              <label className="text-xs font-semibold uppercase tracking-wider text-slate-300">
                Officer Username / Badge ID
              </label>
              <div className="relative">
                <User size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                <input
                  className={field}
                  placeholder="e.g. admin or officer_sharma"
                  autoComplete="username"
                  autoFocus
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                />
              </div>
            </div>

            <div className="space-y-1">
              <label className="text-xs font-semibold uppercase tracking-wider text-slate-300">
                Encrypted Password
              </label>
              <div className="relative">
                <Lock size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                <input
                  className={field}
                  type="password"
                  placeholder="••••••••••••"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={busy}
              className="glow-accent mt-4 flex w-full items-center justify-center gap-2 rounded-xl border border-accent bg-accent/20 px-4 py-3 text-xs font-black tracking-wider text-accent transition-all duration-200 hover:bg-accent hover:text-slate-950 disabled:opacity-50"
            >
              {busy && <Loader2 size={15} className="animate-spin" />}
              {busy ? "AUTHENTICATING OFFICER…" : "SECURE SIGN IN"}
            </button>
          </form>
        ) : (
          <form onSubmit={handleChangePassword} className="space-y-3">
            <p className="mb-1 text-xs leading-relaxed text-slate-300">
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

        <div className="mt-6 border-t border-white/[0.08] pt-4 text-center text-[10.5px] leading-relaxed text-slate-500">
          State of Gujarat Cyber Security Cell · All terminal sessions are auditable for chain-of-custody.
        </div>
      </motion.div>
    </div>
  );
}

