import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Alerts from "./pages/Alerts";
import Dashboard from "./pages/Dashboard";
import Investigate from "./pages/Investigate";
import Landing from "./pages/Landing";
import NetworkPage from "./pages/NetworkPage";
import Reports from "./pages/Reports";
import Settings from "./pages/Settings";
import ThreatFeed from "./pages/ThreatFeed";
import Trends from "./pages/Trends";
import Watchlist from "./pages/Watchlist";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
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
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
