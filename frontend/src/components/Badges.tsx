import { Bot, Globe, Languages, ShieldAlert, Smile, Meh, Frown } from "lucide-react";
import {
  siFacebook, siInstagram, siReddit, siTelegram, siX, siYoutube,
} from "simple-icons";
import { SEVERITY_COLORS, THREAT_COLORS, THREAT_SHORT, SENTIMENT_COLORS } from "../data/constants";

/** Threat class badge — color + text label together (never color alone). */
export function ThreatBadge({ label, score, size = "md" }: { label: string; score?: number; size?: "sm" | "md" | "lg" }) {
  const color = THREAT_COLORS[label] ?? "#64748B";
  const sizeClasses = size === "sm" ? "px-2 py-0.5 text-[10px]" : size === "lg" ? "px-3 py-1 text-xs" : "px-2.5 py-0.5 text-[11px]";

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border font-semibold shadow-sm tracking-wide ${sizeClasses}`}
      style={{ color, borderColor: `${color}60`, backgroundColor: `${color}18` }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: color }} />
      <span>{THREAT_SHORT[label] ?? label}</span>
      {score !== undefined && (
        <span
          className="rounded px-1 font-mono text-[10px] font-bold"
          style={{ backgroundColor: `${color}28`, color }}
        >
          {Math.round(score)}
        </span>
      )}
    </span>
  );
}

export function SentimentBadge({ label, score }: { label: string; score: number }) {
  const color = SENTIMENT_COLORS[label] ?? "#64748B";
  const Icon = label === "positive" ? Smile : label === "negative" ? Frown : Meh;
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 font-mono text-[11px] font-semibold"
      style={{ color, borderColor: `${color}40`, backgroundColor: `${color}12` }}
      title={`Sentiment Polarity Score: ${score > 0 ? "+" : ""}${score.toFixed(2)}`}
    >
      <Icon size={11} />
      <span className="capitalize">{label}</span>
      <span className="opacity-80">({score > 0 ? "+" : ""}{score.toFixed(2)})</span>
    </span>
  );
}

export function LanguageChip({ language, mixed }: { language: string; mixed?: boolean }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/[0.05] px-2 py-0.5 text-[11px] font-medium text-slate-300"
      title={mixed ? `${language} (Code-mixed vernacular: Hinglish/Gujlish)` : language}
    >
      <Languages size={11} className="text-slate-400" />
      {language}
      {mixed && (
        <span className="rounded bg-accent/20 px-1 py-px font-mono text-[9px] font-bold text-accent">
          MIXED
        </span>
      )}
    </span>
  );
}

export function SeverityChip({ severity }: { severity: string }) {
  const color = SEVERITY_COLORS[severity] ?? "#64748B";
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider shadow-sm"
      style={{ color, borderColor: `${color}60`, backgroundColor: `${color}18` }}
    >
      <ShieldAlert size={11} />
      {severity}
    </span>
  );
}

export function BotChip() {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-threat-critical/50 bg-threat-critical/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-threat-critical shadow-sm">
      <Bot size={11} /> bot-like
    </span>
  );
}

/** Real brand marks, straight from simple-icons — official path data and
 *  official brand hex, so nothing here is hand-traced or approximated. */
const PLATFORM_META: Record<
  string,
  { path: string; tint: string; color?: string; className?: string }
> = {
  X: {
    path: siX.path,
    tint: "#71767B",
    className: "text-neutral-900 dark:text-neutral-100",
  },
  Facebook: { path: siFacebook.path, tint: `#${siFacebook.hex}`, color: `#${siFacebook.hex}` },
  Instagram: { path: siInstagram.path, tint: `#${siInstagram.hex}`, color: `#${siInstagram.hex}` },
  Reddit: { path: siReddit.path, tint: `#${siReddit.hex}`, color: `#${siReddit.hex}` },
  Telegram: { path: siTelegram.path, tint: `#${siTelegram.hex}`, color: `#${siTelegram.hex}` },
  YouTube: { path: siYoutube.path, tint: `#${siYoutube.hex}`, color: `#${siYoutube.hex}` },
};

export function PlatformIcon({ platform, size = 22 }: { platform: string; size?: number }) {
  const meta = PLATFORM_META[platform];

  if (!meta) {
    return (
      <span
        title={platform}
        className="inline-flex shrink-0 items-center justify-center rounded-lg border border-slate-500/30 bg-slate-500/10 text-slate-300"
        style={{ width: size, height: size }}
      >
        <Globe size={size * 0.58} />
      </span>
    );
  }

  return (
    <span
      title={platform}
      className="inline-flex shrink-0 items-center justify-center rounded-lg border shadow-sm"
      style={{
        width: size,
        height: size,
        borderColor: `${meta.tint}44`,
        backgroundColor: `${meta.tint}14`,
      }}
    >
      <svg
        role="img"
        aria-label={platform}
        viewBox="0 0 24 24"
        width={size * 0.58}
        height={size * 0.58}
        fill="currentColor"
        className={meta.className}
        style={meta.color ? { color: meta.color } : undefined}
      >
        <path d={meta.path} />
      </svg>
    </span>
  );
}

