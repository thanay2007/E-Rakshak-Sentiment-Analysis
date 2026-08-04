import { Navigate, Outlet } from "react-router-dom";
import { ShieldAlert } from "lucide-react";

import { useAuth } from "../hooks/useAuth";

/** Route guard for rank-restricted areas.
 *
 *  Like RequireAuth, this shapes the UI and nothing more. Every endpoint the
 *  Admin Panel calls re-checks the caller's rank server-side (security/deps.py),
 *  because a role held in browser state is a role the browser's owner can edit.
 *  Hiding the page is courtesy; the 403 is the control.
 */
export default function RequireRole({
  minimum,
}: {
  minimum: "analyst" | "supervisor" | "admin";
}) {
  const { signedIn, can } = useAuth();

  if (!signedIn) return <Navigate to="/login" replace />;

  if (!can(minimum)) {
    return (
      <div className="glass mx-auto mt-16 max-w-md p-8 text-center">
        <ShieldAlert size={28} className="mx-auto mb-3 text-amber-400" />
        <h2 className="text-sm font-semibold text-slate-200">Insufficient rank</h2>
        <p className="mt-2 text-xs leading-relaxed text-slate-500">
          This area requires the {minimum} role. Your access attempt is recorded
          against your badge.
        </p>
      </div>
    );
  }
  return <Outlet />;
}
