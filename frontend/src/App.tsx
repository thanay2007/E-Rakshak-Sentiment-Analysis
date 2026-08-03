import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import RequireAuth from "./components/RequireAuth";
import { AuthProvider } from "./hooks/useAuth";

const Alerts = lazy(() => import("./pages/Alerts"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const Investigate = lazy(() => import("./pages/Investigate"));
const Landing = lazy(() => import("./pages/Landing"));
const Login = lazy(() => import("./pages/Login"));
const NetworkPage = lazy(() => import("./pages/NetworkPage"));
const Reports = lazy(() => import("./pages/Reports"));
const Settings = lazy(() => import("./pages/Settings"));
const ThreatFeed = lazy(() => import("./pages/ThreatFeed"));
const Trends = lazy(() => import("./pages/Trends"));
const Watchlist = lazy(() => import("./pages/Watchlist"));

const Fallback = () => (
  <div className="flex h-screen w-full items-center justify-center">
    <span className="h-8 w-8 animate-spin rounded-full border-4 border-slate-600 border-t-accent"></span>
  </div>
);

export default function App() {
  return (
    <AuthProvider>
      <Suspense fallback={<Fallback />}>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          {/* Everything under /app requires a session. The server enforces this
              independently on every request; this only shapes the UI. */}
          <Route element={<RequireAuth />}>
            <Route path="/app" element={<Layout />}>
              <Route index element={<Dashboard />} />
              <Route path="feed" element={<ThreatFeed />} />
              <Route path="investigate" element={<Investigate />} />
              <Route path="network" element={<NetworkPage />} />
              <Route path="trends" element={<Trends />} />
              <Route path="alerts" element={<Alerts />} />
              <Route path="reports" element={<Reports />} />
              <Route path="watchlist" element={<Watchlist />} />
              <Route path="settings" element={<Settings />} />
            </Route>
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </AuthProvider>
  );
}
