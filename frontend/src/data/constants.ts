/** Shared visual + semantic constants.
 *
 *  A post carries exactly one tag — positive, negative or neutral — and a
 *  0-100 concern score. There is no threat taxonomy: the system reports tone
 *  and how far it travelled, not whether a post will cause harm.
 *
 *  Colour is never the only identity channel — every coloured chip in the UI
 *  ships with its text label alongside. */

export const SENTIMENT_COLORS: Record<string, string> = {
  positive: "#059669",
  neutral: "#64748B",
  negative: "#DC2626",
};

export const SENTIMENT_LABELS = ["negative", "neutral", "positive"] as const;
export type Sentiment = (typeof SENTIMENT_LABELS)[number];

/** Human-facing wording for each tag. */
export const SENTIMENT_TEXT: Record<string, string> = {
  positive: "Positive",
  neutral: "Neutral",
  negative: "Negative",
};

export const SEVERITY_COLORS: Record<string, string> = {
  critical: "#DC2626",
  high: "#EA580C",
  medium: "#F59E0B",
};

/** Concern-score bands — must match app/ml/score.py `band()`. */
export const CONCERN_BANDS = [
  { min: 74, label: "critical", color: "#DC2626" },
  { min: 65, label: "high", color: "#EA580C" },
  { min: 50, label: "elevated", color: "#F59E0B" },
  { min: 0, label: "routine", color: "#059669" },
];

export function concernColor(score: number): string {
  return CONCERN_BANDS.find((b) => score >= b.min)?.color ?? "#059669";
}

export function concernBand(score: number): string {
  return CONCERN_BANDS.find((b) => score >= b.min)?.label ?? "routine";
}

export function sentimentColor(label?: string): string {
  return SENTIMENT_COLORS[label ?? "neutral"] ?? "#64748B";
}

// "Other" is a post in a script none of the rest describe — Chinese, Korean,
// Arabic. It is a filter, not a bin: those posts are collected and scored like
// any other, and an officer needs to be able to pull them up (that is how a
// batch of off-topic YouTube results was found).
export const LANGUAGES = ["Gujarati", "Hindi", "Hinglish", "Gujlish", "English", "Mixed", "Other"];
export const PLATFORMS = ["X", "Facebook", "Instagram", "Reddit", "Telegram", "YouTube"];

export const ACCENT = "#F59E0B";
