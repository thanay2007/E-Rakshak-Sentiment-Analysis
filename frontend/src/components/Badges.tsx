import { Bot, Frown, Globe, Languages, Meh, ShieldAlert, Smile } from "lucide-react";
import {
  siFacebook, siInstagram, siReddit, siTelegram, siX, siYoutube,
} from "simple-icons";
import {
  concernBand, concernColor, SENTIMENT_TEXT, SEVERITY_COLORS, sentimentColor,
} from "../data/constants";

const SENTIMENT_ICON = { positive: Smile, neutral: Meh, negative: Frown };

/** Normalize whatever the API returned into one of the three tags. */
function canon(label?: string): "positive" | "neutral" | "negative" {
  const l = (label || "neutral").toLowerCase();
  if (l.startsWith("pos")) return "positive";
  if (l.startsWith("neg")) return "negative";
  return "neutral";
}

/**
 * The post's tag — colour AND text together, never colour alone.
 *
 * Optionally shows the 0-100 concern score beside it. The two are deliberately
 * one chip: "negative" on its own says nothing about whether anyone read it,
 * and a score on its own says nothing about which direction it leans.
 */
export function SentimentBadge({
  label, score, size = "md",
}: { label?: string; score?: number; size?: "sm" | "md" | "lg" }) {
  const tag = canon(label);
  const color = sentimentColor(tag);
  const Icon = SENTIMENT_ICON[tag];
  const sizeClasses =
    size === "sm" ? "px-2 py-0.5 text-[10px]"
      : size === "lg" ? "px-3 py-1 text-xs"
        : "px-2.5 py-0.5 text-[11px]";

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border font-semibold tracking-wide shadow-sm ${sizeClasses}`}
      style={{ color, borderColor: `${color}60`, backgroundColor: `${color}18` }}
      title={score !== undefined
        ? `${SENTIMENT_TEXT[tag]} sentiment · concern score ${Math.round(score)}/100 (${concernBand(score)})`
        : `${SENTIMENT_TEXT[tag]} sentiment`}
    >
      <Icon size={size === "sm" ? 10 : 12} />
      <span>{SENTIMENT_TEXT[tag]}</span>
      {score !== undefined && (
        <span
          className="rounded px-1 font-mono text-[10px] font-bold"
          style={{ backgroundColor: `${concernColor(score)}28`, color: concernColor(score) }}
        >
          {Math.round(score)}
        </span>
      )}
    </span>
  );
}

/** The 0-100 concern score on its own, banded by colour. */

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

