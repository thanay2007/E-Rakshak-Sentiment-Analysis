/** Shared visual + semantic constants. Threat colors always ship WITH text
 *  labels (validated palette: color is never the only identity channel). */

export const THREAT_COLORS: Record<string, string> = {
  "Incitement to Violence": "#EF4444",
  Inflammatory: "#F59E0B",
  "Fake News": "#A855F7",
  Neutral: "#10B981",
};

export const THREAT_SHORT: Record<string, string> = {
  "Incitement to Violence": "Incitement",
  Inflammatory: "Inflammatory",
  "Fake News": "Fake News",
  Neutral: "Neutral",
};

export const SEVERITY_COLORS: Record<string, string> = {
  critical: "#EF4444",
  high: "#F59E0B",
  medium: "#14B8C4",
};

export const SENTIMENT_COLORS: Record<string, string> = {
  positive: "#10B981",
  neutral: "#64748B",
  negative: "#EF4444",
};

export const LANGUAGES = ["Gujarati", "Hindi", "Hinglish", "Gujlish", "English", "Mixed"];
export const PLATFORMS = ["X", "Facebook", "Instagram", "Reddit"];
export const THREAT_LABELS = Object.keys(THREAT_COLORS);

export const ACCENT = "#14B8C4";

export function threatColor(score: number): string {
  if (score >= 65) return "#EF4444";
  if (score >= 45) return "#F59E0B";
  if (score >= 25) return "#A855F7";
  return "#10B981";
}
