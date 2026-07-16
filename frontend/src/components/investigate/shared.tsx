import type { ReactNode } from "react";
import { Loader2 } from "lucide-react";

/** Severity colour used across every investigation finding. */
export const LEVEL_COLORS: Record<string, string> = {
  high: "#EF4444",
  dangerous: "#EF4444",
  medium: "#F59E0B",
  suspicious: "#F59E0B",
  caution: "#F59E0B",
  low: "#A855F7",
  info: "#14B8C4",
  ok: "#10B981",
  clean: "#10B981",
};

export const BOT_COLORS: Record<string, string> = {
  likely_bot: "#EF4444",
  suspicious: "#F59E0B",
  authentic: "#10B981",
};

export const SENT_COLORS: Record<string, string> = {
  positive: "#10B981",
  neutral: "#64748B",
  negative: "#EF4444",
};

export function Pill({ color, children }: { color: string; children: ReactNode }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold"
      style={{ color, borderColor: `${color}55`, backgroundColor: `${color}14` }}
    >
      {children}
    </span>
  );
}

export function FindingRow({ level, text, on }: { level: string; text: string; on?: string }) {
  const color = LEVEL_COLORS[level] ?? "#64748B";
  return (
    <div className="flex items-start gap-2.5 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2">
      <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: color }} />
      <div className="text-[13px] leading-snug text-slate-300">
        {text}
        {on === "destination" && (
          <span className="ml-1.5 rounded bg-white/[0.06] px-1 py-0.5 text-[10px] uppercase tracking-wide text-slate-500">
            on destination
          </span>
        )}
      </div>
    </div>
  );
}

export function Meter({ value, color, label }: { value: number; color: string; label?: string }) {
  return (
    <div className="space-y-1">
      {label && <div className="flex justify-between text-[11px] text-slate-500"><span>{label}</span><span className="font-mono text-slate-300">{value}</span></div>}
      <div className="h-2 overflow-hidden rounded-full bg-white/[0.06]">
        <div className="h-full rounded-full transition-all duration-500" style={{ width: `${Math.min(value, 100)}%`, backgroundColor: color }} />
      </div>
    </div>
  );
}

export function Spinner({ label = "Analyzing…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500">
      <Loader2 size={16} className="animate-spin" /> {label}
    </div>
  );
}

export function EmptyHint({ children }: { children: ReactNode }) {
  return <div className="rounded-xl border border-dashed border-white/[0.08] px-4 py-8 text-center text-sm text-slate-500">{children}</div>;
}

export function KV({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-white/[0.05] py-1.5 last:border-0">
      <span className="text-[12px] uppercase tracking-wide text-slate-500">{k}</span>
      <span className="text-right font-mono text-[13px] text-slate-200">{v}</span>
    </div>
  );
}

export function RunButton({ onClick, disabled, children }: { onClick: () => void; disabled?: boolean; children: ReactNode }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="inline-flex items-center gap-2 rounded-xl border border-accent/30 bg-accent/10 px-4 py-2 text-sm font-semibold text-accent transition-all hover:bg-accent/20 disabled:cursor-not-allowed disabled:opacity-40"
    >
      {children}
    </button>
  );
}

export function TextInput({
  value, onChange, placeholder, onEnter, mono = false,
}: { value: string; onChange: (v: string) => void; placeholder?: string; onEnter?: () => void; mono?: boolean }) {
  return (
    <input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={(e) => { if (e.key === "Enter" && onEnter) onEnter(); }}
      placeholder={placeholder}
      className={`w-full rounded-xl border border-white/[0.08] bg-white/[0.04] px-3.5 py-2.5 text-sm text-slate-200 placeholder:text-slate-600 focus:border-accent/40 focus:outline-none ${mono ? "font-mono" : ""}`}
    />
  );
}

/** Account chip used by media-intel buckets, PR rosters and comment lists. */
export function AccountChip({
  handle, name, followers, verified, botScore, botVerdict, url,
}: {
  handle: string; name?: string; followers?: number; verified?: boolean;
  botScore?: number; botVerdict?: string; url?: string;
}) {
  const color = botVerdict ? BOT_COLORS[botVerdict] ?? "#64748B" : "#64748B";
  const inner = (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-white/[0.07] bg-white/[0.02] px-3 py-2 hover:border-white/[0.15]">
      <div className="min-w-0">
        <div className="flex items-center gap-1.5 truncate text-[13px] font-medium text-slate-200">
          @{handle}
          {verified && <span className="text-accent" title="verified">✓</span>}
        </div>
        {(name || followers !== undefined) && (
          <div className="truncate text-[11px] text-slate-500">
            {name}{followers !== undefined ? ` · ${followers.toLocaleString()} followers` : ""}
          </div>
        )}
      </div>
      {botScore !== undefined && (
        <span className="shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-mono font-semibold"
          style={{ color, borderColor: `${color}55`, backgroundColor: `${color}14` }}>
          bot {botScore}
        </span>
      )}
    </div>
  );
  return url ? <a href={url} target="_blank" rel="noreferrer">{inner}</a> : inner;
}
