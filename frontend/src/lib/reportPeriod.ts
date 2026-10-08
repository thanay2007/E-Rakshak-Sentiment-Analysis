/** Match the report filter's labels while keeping API durations in hours. */
export function reportPeriod(hours: number): string {
  if (hours === 168) return "7 days";
  return `${hours} ${hours === 1 ? "hour" : "hours"}`;
}

/** Older reports may already contain the numeric duration in saved copy. */
export function readableReportText(text: string, hours: number): string {
  if (hours !== 168) return text;
  return text.replace(/\b168\s*(?:hours?\b|h\b)/gi, reportPeriod(hours));
}
