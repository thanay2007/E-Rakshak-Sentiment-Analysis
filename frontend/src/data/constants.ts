/** Shared visual + semantic constants. Threat colors always ship WITH text
 *  labels (validated palette: color is never the only identity channel). */

export const THREAT_COLORS: Record<string, string> = {
  "Incitement to Violence": "#DC2626",
  Inflammatory: "#EA580C",
  "Fake News": "#9333EA",
  Neutral: "#059669",
};

export const THREAT_SHORT: Record<string, string> = {
  "Incitement to Violence": "Incitement",
  Inflammatory: "Inflammatory",
  "Fake News": "Fake News",
  Neutral: "Neutral",
};

export const SEVERITY_COLORS: Record<string, string> = {
  critical: "#DC2626",
  high: "#EA580C",
  medium: "#F59E0B",
};

export const SENTIMENT_COLORS: Record<string, string> = {
  positive: "#059669",
  neutral: "#64748B",
  negative: "#DC2626",
};

export const LANGUAGES = ["Gujarati", "Hindi", "Hinglish", "Gujlish", "English", "Mixed"];
export const PLATFORMS = ["X", "Facebook", "Instagram", "Reddit", "Telegram", "YouTube"];
export const THREAT_LABELS = Object.keys(THREAT_COLORS);

export const ACCENT = "#F59E0B";

export function threatColor(score: number): string {
  if (score >= 65) return "#DC2626";
  if (score >= 45) return "#EA580C";
  if (score >= 25) return "#9333EA";
  return "#059669";
}
