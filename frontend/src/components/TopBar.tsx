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
      <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-white/[0.08] bg-base-900/80 px-4 backdrop-blur-xl">
        <form onSubmit={submit} className="relative w-full max-w-sm">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            ref={searchInputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search posts, handles, hashtags… (press /)"
            className="w-full rounded-xl border border-white/[0.1] bg-white/[0.05] py-2 pl-9 pr-8 text-xs text-slate-100 placeholder:text-slate-500 focus:border-accent/60 focus:bg-white/[0.07] focus:outline-none"
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
          className="rounded-xl border border-white/[0.1] bg-base-800 pl-2.5 pr-8 py-2 text-xs text-slate-300 hover:border-white/20 focus:border-accent/60 focus:outline-none"
          aria-label="Language quick filter"
        >
          <option value="">All languages</option>
          {LANGUAGES.map((l) => (
            <option key={l} value={l}>
              {l}
            </option>
          ))}
        </select>

        <div className="ml-auto flex items-center gap-3 sm:gap-4">
          <span className="hidden font-mono text-[11px] text-slate-400 md:block">
            {clock.toLocaleTimeString("en-IN", { hour12: false })} IST
          </span>

          <span className="flex items-center gap-2 text-[11px] font-bold tracking-widest">
            <span
              className={`pulse-dot inline-block h-2 w-2 rounded-full ${
                connected ? "bg-threat-neutral text-threat-neutral" : "bg-slate-500 text-slate-500"
              }`}
            />
            <span className={connected ? "text-threat-neutral" : "text-slate-400"}>
              {connected ? "LIVE" : "OFFLINE"}
            </span>
          </span>

          <button
            onClick={() => setGuideOpen(true)}
            className="flex items-center gap-1.5 rounded-xl border border-accent/30 bg-accent/10 px-2.5 py-1.5 text-xs font-semibold text-accent transition-colors hover:bg-accent/20"
            aria-label="Open Intel Guide"
            title="Intel & Operations Guide"
          >
            <HelpCircle size={14} />
            <span className="hidden sm:inline">Intel Guide</span>
          </button>

          <button
            onClick={toggleTheme}
            className="relative rounded-xl border border-white/[0.08] p-2 text-slate-300 hover:bg-white/[0.08]"
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
            className="relative rounded-xl border border-white/[0.08] p-2 text-slate-300 hover:bg-white/[0.08]"
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

          <div className="flex items-center gap-2.5 border-l border-white/[0.08] pl-3">
            <span className="flex h-8 w-8 items-center justify-center rounded-full border border-accent/40 bg-accent/15 text-accent shadow-sm">
              <UserRound size={15} />
            </span>
            <div className="hidden leading-tight lg:block">
              <div className="text-xs font-semibold text-slate-200">
                {user?.full_name || user?.username || "—"}
              </div>
              <div className="font-mono text-[10px] uppercase text-slate-400">
                {[user?.role, user?.badge_number || user?.unit].filter(Boolean).join(" · ") || "—"}
              </div>
            </div>
            <button
              onClick={async () => {
                await signOut();
                navigate("/login", { replace: true });
              }}
              className="rounded-xl border border-white/[0.08] p-2 text-slate-400 hover:bg-red-500/10 hover:border-red-500/30 hover:text-red-300"
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
