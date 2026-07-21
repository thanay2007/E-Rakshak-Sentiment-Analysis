import { Bot, Languages, ShieldAlert } from "lucide-react";
import { SEVERITY_COLORS, THREAT_COLORS, THREAT_SHORT } from "../data/constants";

/** Threat class badge — color + text label together (never color alone). */
export function ThreatBadge({ label, score }: { label: string; score?: number }) {
  const color = THREAT_COLORS[label] ?? "#64748B";
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold"
      style={{ color, borderColor: `${color}55`, backgroundColor: `${color}14` }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: color }} />
      {THREAT_SHORT[label] ?? label}
      {score !== undefined && <span className="font-mono opacity-80">{Math.round(score)}</span>}
    </span>
  );
}

export function LanguageChip({ language, mixed }: { language: string; mixed?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/[0.04] px-1.5 py-0.5 text-[10px] font-medium text-slate-400">
      <Languages size={10} />
      {language}
      {mixed && <span className="text-accent">·mix</span>}
    </span>
  );
}

export function SeverityChip({ severity }: { severity: string }) {
  const color = SEVERITY_COLORS[severity] ?? "#64748B";
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider"
      style={{ color, borderColor: `${color}55`, backgroundColor: `${color}14` }}
    >
      <ShieldAlert size={10} />
      {severity}
    </span>
  );
}

export function BotChip() {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-threat-critical/50 bg-threat-critical/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-threat-critical">
      <Bot size={10} /> bot-like
    </span>
  );
}

const PLATFORM_META: Record<string, { short: string; color: string }> = {
  X: { short: "𝕏", color: "#E7E9EA" },
  Facebook: { short: "f", color: "#1877F2" },
  Instagram: { short: "IG", color: "#E1306C" },
  Reddit: { short: "R", color: "#FF4500" },
  Telegram: { short: "TG", color: "#229ED9" },
};

export function PlatformIcon({ platform, size = 22 }: { platform: string; size?: number }) {
  const meta = PLATFORM_META[platform] ?? { short: "?", color: "#64748B" };
  return (
    <span
      title={platform}
      className="inline-flex shrink-0 items-center justify-center rounded-lg border font-mono font-semibold"
      style={{
        width: size,
        height: size,
        fontSize: size * 0.48,
        color: meta.color,
        borderColor: `${meta.color}44`,
        backgroundColor: `${meta.color}12`,
      }}
    >
      {meta.short}
    </span>
  );
}
