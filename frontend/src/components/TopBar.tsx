import { Bell, HelpCircle, LogOut, Moon, Search, Sun, UserRound } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { LANGUAGES } from "../data/constants";
import { useAuth } from "../hooks/useAuth";
import { useLiveAlerts, useLiveStatus } from "../hooks/useLive";
import IntelGuideModal from "./IntelGuideModal";

export default function TopBar() {
  const navigate = useNavigate();
  const { user, signOut } = useAuth();
  const connected = useLiveStatus();
  const liveAlerts = useLiveAlerts();
  const [q, setQ] = useState("");
  const [seen, setSeen] = useState(0);
  const [guideOpen, setGuideOpen] = useState(false);
  const unread = Math.max(0, liveAlerts.length - seen);
  const [clock, setClock] = useState(new Date());
  const searchInputRef = useRef<HTMLInputElement>(null);
  
  const [isLight, setIsLight] = useState(() => document.documentElement.classList.contains("light"));

  useEffect(() => {
    const id = window.setInterval(() => setClock(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);

  // Keyboard shortcut: pressing '/' focuses the search bar if not already in an input
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "/" && document.activeElement?.tagName !== "INPUT" && document.activeElement?.tagName !== "TEXTAREA") {
        e.preventDefault();
        searchInputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const toggleTheme = () => {
    if (isLight) {
      document.documentElement.classList.remove("light");
      document.documentElement.classList.add("dark");
      setIsLight(false);
    } else {
      document.documentElement.classList.remove("dark");
      document.documentElement.classList.add("light");
      setIsLight(true);
    }
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    navigate(`/app/feed?q=${encodeURIComponent(q)}`);
  };

  return (
    <>
      {/* Everything on this bar is sized to one 36px control height and
          vertically centred against it. Before, the clock, the LIVE pill, the
          icon buttons and the identity block each set their own padding, so
          nothing shared a baseline — and the identity block's two lines,
          having no width limit, wrapped a long unit name ("SURAT CITY POLICE
          COMMISSIONERATE") onto a third line and pushed the sign-out button
          off the end of the bar. */}
      <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-white/[0.08] bg-base-900/80 px-5 backdrop-blur-xl sm:px-6">
        <form onSubmit={submit} className="relative h-9 w-full max-w-xs sm:max-w-sm md:max-w-md">
          <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            ref={searchInputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search posts, handles, hashtags… (press /)"
            className="h-full w-full rounded-xl border border-white/[0.1] bg-white/[0.05] pl-9 pr-8 text-xs text-slate-100 transition-all placeholder:text-slate-500 focus:border-accent/60 focus:bg-white/[0.07] focus:outline-none"
            aria-label="Global search"
          />
          <kbd className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 rounded border border-white/10 bg-white/[0.06] px-1.5 py-0.5 font-mono text-[9px] text-slate-400">
            /
          </kbd>
        </form>

        <select
          onChange={(e) =>
            navigate(e.target.value ? `/app/feed?language=${encodeURIComponent(e.target.value)}` : "/app/feed")
          }
          defaultValue=""
          className="hidden h-9 shrink-0 rounded-xl border border-white/[0.1] bg-base-800 pl-2.5 pr-8 text-xs text-slate-300 hover:border-white/20 focus:border-accent/60 focus:outline-none sm:block"
          aria-label="Language quick filter"
        >
          <option value="">All languages</option>
          {LANGUAGES.map((l) => (
            <option key={l} value={l}>
              {l}
            </option>
          ))}
        </select>

        <div className="ml-auto flex items-center gap-2.5">
          {/* Fixed width and tabular figures: a clock that reflows the whole
              bar once a second as digit widths change is its own bug. */}
          <span className="hidden w-[5.75rem] shrink-0 text-right font-mono text-[11px] tabular-nums leading-none text-slate-400 lg:block">
            {clock.toLocaleTimeString("en-IN", { hour12: false })} IST
          </span>

          <span className="hidden h-9 shrink-0 items-center gap-1.5 rounded-xl border border-white/[0.08] bg-white/[0.03] px-2.5 text-[11px] font-bold tracking-widest md:inline-flex">
            <span
              className={`pulse-dot inline-block h-2 w-2 shrink-0 rounded-full ${
                connected ? "bg-threat-neutral text-threat-neutral" : "bg-slate-500 text-slate-500"
              }`}
            />
            <span className={connected ? "text-threat-neutral" : "text-slate-400"}>
              {connected ? "LIVE" : "OFFLINE"}
            </span>
          </span>

          <button
            onClick={() => setGuideOpen(true)}
            className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-xl border border-accent/30 bg-accent/10 px-2.5 text-xs font-semibold text-accent transition-colors hover:bg-accent/20"
            aria-label="Open Guide"
            title="Operations Guide"
          >
            <HelpCircle size={14} />
            <span className="hidden sm:inline">Guide</span>
          </button>

          <button
            onClick={toggleTheme}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-white/[0.08] text-slate-300 hover:bg-white/[0.08]"
            aria-label="Toggle theme"
            title="Toggle Day/Night Mode"
          >
            {isLight ? <Moon size={15} /> : <Sun size={15} />}
          </button>

          <button
            onClick={() => {
              setSeen(liveAlerts.length);
              navigate("/app/alerts");
            }}
            className="relative grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-white/[0.08] text-slate-300 hover:bg-white/[0.08]"
            aria-label={`Alerts (${unread} unread)`}
            title="Incidents & Alerts"
          >
            <Bell size={15} />
            {unread > 0 && (
              <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-threat-critical px-1 font-mono text-[9px] font-bold text-white shadow-md">
                {unread}
              </span>
            )}
          </button>

          <div className="flex h-9 shrink-0 items-center gap-2.5 border-l border-white/[0.08] pl-3">
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full border border-accent/40 bg-accent/15 text-accent shadow-sm">
              <UserRound size={15} />
            </span>
            {/* Capped and truncated on both lines. The full name and unit stay
                available on hover, which is the right trade for a bar that has
                to keep the sign-out button reachable. */}
            <div className="hidden max-w-[13rem] min-w-0 leading-tight xl:block">
              <div
                className="truncate text-xs font-semibold text-slate-200"
                title={user?.full_name || user?.username || ""}
              >
                {user?.full_name || user?.username || "—"}
              </div>
              <div
                className="truncate font-mono text-[10px] uppercase text-slate-400"
                title={[user?.role, user?.badge_number || user?.unit].filter(Boolean).join(" · ")}
              >
                {[user?.role, user?.badge_number || user?.unit].filter(Boolean).join(" · ") || "—"}
              </div>
            </div>
            <button
              onClick={async () => {
                await signOut();
                navigate("/login", { replace: true });
              }}
              className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-white/[0.08] text-slate-400 hover:border-red-500/30 hover:bg-red-500/10 hover:text-red-300"
              aria-label="Sign out"
              title="Sign out"
            >
              <LogOut size={15} />
            </button>
          </div>
        </div>
      </header>

      <IntelGuideModal open={guideOpen} onClose={() => setGuideOpen(false)} />
    </>
  );
}
