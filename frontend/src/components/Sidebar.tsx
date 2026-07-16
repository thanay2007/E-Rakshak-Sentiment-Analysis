import {
  Bell, ChevronsLeft, Eye, FileText, LayoutDashboard, Radar, ScanSearch, Settings,
  Share2, TrendingUp,
} from "lucide-react";
import { NavLink } from "react-router-dom";

const NAV = [
  { to: "/app", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/app/feed", label: "Threat Feed", icon: Radar },
  { to: "/app/investigate", label: "Investigate", icon: ScanSearch },
  { to: "/app/network", label: "Network", icon: Share2 },
  { to: "/app/trends", label: "Trends", icon: TrendingUp },
  { to: "/app/alerts", label: "Alerts", icon: Bell },
  { to: "/app/reports", label: "Reports", icon: FileText },
  { to: "/app/watchlist", label: "Watchlist", icon: Eye },
  { to: "/app/settings", label: "Settings", icon: Settings },
];

export function Logo({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" aria-hidden>
      <polygon
        points="50,6 90,26 90,60 50,94 10,60 10,26"
        fill="none"
        stroke="#14B8C4"
        strokeWidth="6"
      />
      <circle cx="50" cy="47" r="12" fill="#14B8C4" />
      <line x1="50" y1="62" x2="50" y2="80" stroke="#14B8C4" strokeWidth="6" strokeLinecap="round" />
    </svg>
  );
}

export default function Sidebar({
  collapsed,
  onToggle,
}: {
  collapsed: boolean;
  onToggle: () => void;
}) {
  return (
    <aside
      className={`fixed left-0 top-0 z-30 flex h-full flex-col border-r border-white/[0.06] bg-base-800/80 backdrop-blur-xl transition-[width] duration-300 ${
        collapsed ? "w-[64px]" : "w-[220px]"
      }`}
    >
      <div className="flex h-14 items-center gap-2.5 border-b border-white/[0.06] px-4">
        <Logo size={26} />
        {!collapsed && (
          <span className="text-glow font-mono text-sm font-bold tracking-[0.25em] text-slate-100">
            SENTINEL
          </span>
        )}
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto p-2.5" aria-label="Primary">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            title={label}
            className={({ isActive }) =>
              `group flex items-center gap-3 rounded-xl px-3 py-2.5 text-[13px] font-medium transition-all duration-200 ${
                isActive
                  ? "border border-accent/25 bg-accent/10 text-accent"
                  : "border border-transparent text-slate-400 hover:bg-white/[0.05] hover:text-slate-200"
              }`
            }
          >
            <Icon size={17} className="shrink-0" />
            {!collapsed && <span>{label}</span>}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-white/[0.06] p-2.5">
        <button
          onClick={onToggle}
          className="flex w-full items-center justify-center gap-2 rounded-xl px-3 py-2 text-slate-500 hover:bg-white/[0.05] hover:text-slate-300"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          <ChevronsLeft
            size={16}
            className={`transition-transform duration-300 ${collapsed ? "rotate-180" : ""}`}
          />
          {!collapsed && <span className="text-xs">Collapse</span>}
        </button>
      </div>
    </aside>
  );
}
