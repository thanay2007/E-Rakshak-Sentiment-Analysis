import { Bot, Globe, Languages, ShieldAlert } from "lucide-react";
import {
  siFacebook, siInstagram, siReddit, siTelegram, siX, siYoutube,
} from "simple-icons";
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

/** Real brand marks, straight from simple-icons — official path data and
 *  official brand hex, so nothing here is hand-traced or approximated.
 *
 *  `tint` drives the chip's border/background wash and is kept separate from
 *  the glyph colour for X's sake: its official brand colour is pure black,
 *  which disappears against the dark theme, so its glyph follows the theme via
 *  `className` while the chip keeps X's grey as its wash. Every other brand
 *  colour is saturated enough to read on both themes as-is. */
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

  // Unknown source (RSS/news desks, the simulator, anything added later) gets a
  // neutral globe rather than a broken-looking empty chip.
  if (!meta) {
    return (
      <span
        title={platform}
        className="inline-flex shrink-0 items-center justify-center rounded-lg border border-slate-500/30 bg-slate-500/10 text-slate-400"
        style={{ width: size, height: size }}
      >
        <Globe size={size * 0.58} />
      </span>
    );
  }

  return (
    <span
      title={platform}
      className="inline-flex shrink-0 items-center justify-center rounded-lg border"
      style={{
        width: size,
        height: size,
        borderColor: `${meta.tint}44`,
        backgroundColor: `${meta.tint}12`,
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
