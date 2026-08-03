import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "../hooks/useAuth";

/** Route guard for the authenticated app shell.
 *
 *  This is a usability control, not a security one — it keeps signed-out users
 *  from seeing an empty dashboard full of failed requests. The actual
 *  enforcement is server-side on every endpoint, because anything decided in
 *  the browser is decided by whoever controls the browser.
 */
export default function RequireAuth() {
  const { signedIn, user } = useAuth();
  const location = useLocation();

  if (!signedIn) {
    // Remember where they were headed so sign-in can return them there.
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  if (user?.must_change_password) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <Outlet />;
}
