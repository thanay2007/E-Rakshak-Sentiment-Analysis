import { Bell, Moon, Search, Sun, UserRound } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { LANGUAGES } from "../data/constants";
import { useLiveAlerts, useLiveStatus } from "../hooks/useLive";

export default function TopBar() {
  const navigate = useNavigate();
  const connected = useLiveStatus();
  const liveAlerts = useLiveAlerts();
  const [q, setQ] = useState("");
  const [seen, setSeen] = useState(0);
  const unread = Math.max(0, liveAlerts.length - seen);
  const [clock, setClock] = useState(new Date());
  
  const [isLight, setIsLight] = useState(() => document.documentElement.classList.contains("light"));

  useEffect(() => {
    const id = window.setInterval(() => setClock(new Date()), 1000);
    return () => window.clearInterval(id);
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
    <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-white/[0.06] bg-base-900/70 px-4 backdrop-blur-xl">
      <form onSubmit={submit} className="relative w-full max-w-sm">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search posts, handles, hashtags…"
          className="w-full rounded-xl border border-white/[0.08] bg-white/[0.04] py-2 pl-9 pr-3 text-xs text-slate-200 placeholder:text-slate-600 focus:border-accent/40 focus:outline-none"
          aria-label="Global search"
        />
      </form>

      <select
        onChange={(e) =>
          navigate(e.target.value ? `/app/feed?language=${encodeURIComponent(e.target.value)}` : "/app/feed")
        }
        defaultValue=""
        className="rounded-xl border border-white/[0.08] bg-base-800 px-2.5 py-2 text-xs text-slate-400 focus:border-accent/40 focus:outline-none"
        aria-label="Language quick filter"
      >
        <option value="">All languages</option>
        {LANGUAGES.map((l) => (
          <option key={l} value={l}>
            {l}
          </option>
        ))}
      </select>

      <div className="ml-auto flex items-center gap-4">
        <span className="hidden font-mono text-[11px] text-slate-500 md:block">
          {clock.toLocaleTimeString("en-IN", { hour12: false })} IST
        </span>

        <span className="flex items-center gap-2 text-[11px] font-bold tracking-widest">
          <span
            className={`pulse-dot inline-block h-2 w-2 rounded-full ${
              connected ? "bg-threat-neutral text-threat-neutral" : "bg-slate-600 text-slate-600"
            }`}
          />
          <span className={connected ? "text-threat-neutral" : "text-slate-600"}>
            {connected ? "LIVE" : "OFFLINE"}
          </span>
        </span>

        <button
          onClick={toggleTheme}
          className="relative rounded-xl p-2 text-slate-400 hover:bg-white/[0.06]"
          aria-label="Toggle theme"
          title="Toggle Day/Night Mode"
        >
          {isLight ? <Moon size={16} /> : <Sun size={16} />}
        </button>

        <button
          onClick={() => {
            setSeen(liveAlerts.length);
            navigate("/app/alerts");
          }}
          className="relative rounded-xl p-2 text-slate-400 hover:bg-white/[0.06]"
          aria-label={`Alerts (${unread} unread)`}
        >
          <Bell size={16} />
          {unread > 0 && (
            <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-threat-critical px-1 font-mono text-[9px] font-bold text-white">
              {unread}
            </span>
          )}
        </button>

        <div className="flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-full border border-accent/30 bg-accent/10 text-accent">
            <UserRound size={15} />
          </span>
          <div className="hidden leading-tight lg:block">
            <div className="text-xs font-semibold text-slate-300">Inspector K. Sharma</div>
            <div className="font-mono text-[10px] text-slate-600">CYBER CELL HQ</div>
          </div>
        </div>
      </div>
    </header>
  );
}
