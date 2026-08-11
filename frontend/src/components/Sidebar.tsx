import {
  Bell,
  ChevronsLeft,
  Eye,
  FileText,
  LayoutDashboard,
  Radar,
  ScanSearch,
  Settings,
  Share2,
  ShieldCheck,
  TrendingUp,
} from "lucide-react";
import { NavLink } from "react-router-dom";

import { useAuth } from "../hooks/useAuth";

interface NavEntry {
  to: string;
  label: string;
  icon: typeof LayoutDashboard;
  end?: boolean;
  minimum?: "analyst" | "supervisor" | "admin";
  badge?: string;
  badgeColor?: string;
  section?: string;
}

const NAV_GROUPS: { name: string; items: NavEntry[] }[] = [
  {
    name: "OPERATIONS",
    items: [
      { to: "/app", label: "Dashboard", icon: LayoutDashboard, end: true },
      {
        to: "/app/feed",
        label: "Post Feed",
        icon: Radar,
        badge: "LIVE",
        badgeColor: "bg-emerald-600/20 text-emerald-800 border-emerald-600/50 dark:bg-emerald-500/20 dark:text-emerald-300 dark:border-emerald-500/40 font-black",
      },
      {
        to: "/app/alerts",
        label: "Alerts Triage",
        icon: Bell,
        badge: "HIGH",
        badgeColor: "bg-red-600/20 text-red-800 border-red-600/50 dark:bg-red-500/20 dark:text-red-300 dark:border-red-500/40 font-black",
      },
    ],
  },
  {
    name: "INTELLIGENCE",
    items: [
      { to: "/app/investigate", label: "Forensics Hub", icon: ScanSearch },
      { to: "/app/network", label: "Actor Network", icon: Share2 },
      { to: "/app/trends", label: "Sentiment Trends", icon: TrendingUp },
      { to: "/app/watchlist", label: "Target Watchlist", icon: Eye },
      { to: "/app/reports", label: "Incident Reports", icon: FileText },
    ],
  },
  {
    name: "SYSTEM",
    items: [
      { to: "/app/settings", label: "Settings", icon: Settings },
      { to: "/app/admin", label: "Admin Panel", icon: ShieldCheck, minimum: "admin" },
    ],
  },
];

export function Logo({ size = 30 }: { size?: number }) {
  return (
    <div className="relative flex items-center justify-center">
      <svg width={size} height={size} viewBox="0 0 100 100" aria-hidden className="shrink-0 drop-shadow-[0_0_8px_rgba(245,158,11,0.5)]">
        <circle cx="50" cy="50" r="44" fill="none" stroke="#F59E0B" strokeWidth="5" opacity="0.4" />
        <circle cx="50" cy="50" r="36" fill="none" stroke="#F59E0B" strokeWidth="2.5" />
        <circle cx="50" cy="50" r="10" fill="#F59E0B" />
        {Array.from({ length: 16 }).map((_, i) => (
          <line
            key={i}
            x1="50"
            y1="50"
            x2="50"
            y2="14"
            stroke="#F59E0B"
            strokeWidth="2.5"
            transform={`rotate(${i * 22.5} 50 50)`}
          />
        ))}
      </svg>
    </div>
  );
}

export default function Sidebar({
  collapsed,
  onToggle,
}: {
  collapsed: boolean;
  onToggle: () => void;
}) {
  const { can } = useAuth();

  return (
    <aside
      className={`fixed left-0 top-0 z-30 flex h-full flex-col border-r border-white/[0.08] bg-base-950/90 backdrop-blur-2xl transition-[width] duration-300 ease-in-out overflow-hidden ${
        collapsed ? "w-[68px]" : "w-[240px]"
      }`}
    >
      {/* Brand Header */}
      <div className="flex h-16 items-center gap-3 border-b border-white/[0.08] px-4 overflow-hidden">
        <div className="shrink-0 flex items-center justify-center">
          <Logo size={32} />
        </div>
        <div
          className={`whitespace-nowrap transition-all duration-300 ease-in-out overflow-hidden ${
            collapsed
              ? "w-0 max-w-0 opacity-0 -translate-x-3 pointer-events-none"
              : "w-auto max-w-[160px] opacity-100 translate-x-0"
          }`}
        >
          <div className="font-mono text-sm font-black tracking-[0.18em] text-white flex items-center gap-1.5 whitespace-nowrap">
            <span>E-RAKSHAK</span>
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400 animate-pulse" />
          </div>
        </div>
      </div>

      {/* Nav groups */}
      <nav className="flex-1 space-y-5 overflow-y-auto p-3 custom-scrollbar" aria-label="Primary">
        {NAV_GROUPS.map((group) => {
          const visibleItems = group.items.filter((item) => !item.minimum || can(item.minimum));
          if (!visibleItems.length) return null;

          return (
            <div key={group.name} className="space-y-1">
              <div
                className={`whitespace-nowrap overflow-hidden transition-all duration-300 ease-in-out ${
                  collapsed
                    ? "max-h-0 opacity-0 py-0 -translate-x-2"
                    : "max-h-6 opacity-100 px-3 pb-1 translate-x-0"
                }`}
              >
                <div className="text-[10px] font-extrabold uppercase tracking-widest text-slate-500 whitespace-nowrap">
                  {group.name}
                </div>
              </div>
              {visibleItems.map(({ to, label, icon: Icon, end, badge, badgeColor }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={end}
                  title={label}
                  className={({ isActive }) =>
                    `group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-xs font-semibold transition-all duration-150 overflow-hidden ${
                      isActive
                        ? "border border-accent/40 bg-accent/[0.12] text-accent shadow-[inset_0_1px_0_rgba(255,255,255,0.1),0_0_15px_-4px_rgba(245,158,11,0.3)]"
                        : "border border-transparent text-slate-400 hover:border-white/[0.06] hover:bg-white/[0.05] hover:text-slate-100"
                    }`
                  }
                >
                  <Icon size={18} className="shrink-0 transition-transform duration-200 group-hover:scale-110" />
                  <div
                    className={`flex flex-1 items-center justify-between min-w-0 whitespace-nowrap overflow-hidden transition-all duration-300 ease-in-out ${
                      collapsed
                        ? "w-0 max-w-0 opacity-0 -translate-x-3 pointer-events-none"
                        : "w-auto max-w-[160px] opacity-100 translate-x-0"
                    }`}
                  >
                    <span className="truncate">{label}</span>
                    {badge && (
                      <span className={`ml-2 rounded-md border px-1.5 py-0.2 font-mono text-[9px] font-black uppercase shrink-0 ${badgeColor ?? "bg-accent/20 text-accent border-accent/40"}`}>
                        {badge}
                      </span>
                    )}
                  </div>
                </NavLink>
              ))}
            </div>
          );
        })}
      </nav>

      {/* Collapse toggle */}
      <div className="border-t border-white/[0.08] p-3">
        <button
          onClick={onToggle}
          className="flex w-full items-center justify-center gap-2 rounded-xl border border-white/[0.04] bg-white/[0.02] px-3 py-2 text-slate-400 transition-all hover:border-white/10 hover:bg-white/[0.06] hover:text-slate-100 overflow-hidden"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          <ChevronsLeft
            size={16}
            className={`shrink-0 transition-transform duration-300 ease-in-out ${collapsed ? "rotate-180" : ""}`}
          />
          <span
            className={`text-xs font-medium whitespace-nowrap overflow-hidden transition-all duration-300 ease-in-out ${
              collapsed
                ? "w-0 max-w-0 opacity-0 -translate-x-2 pointer-events-none"
                : "w-auto max-w-[120px] opacity-100 translate-x-0"
            }`}
          >
            Collapse Menu
          </span>
        </button>
      </div>
    </aside>
  );
}

