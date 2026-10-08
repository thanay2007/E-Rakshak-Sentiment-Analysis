import { describe, expect, it } from "vitest";
import { readableReportText, reportPeriod } from "./reportPeriod";

describe("report period wording", () => {
  it.each([[1, "1 hour"], [6, "6 hours"], [24, "24 hours"], [72, "72 hours"], [168, "7 days"]])("formats %s hours as %s", (hours, label) => {
    expect(reportPeriod(Number(hours))).toBe(label);
  });
  it("makes saved seven-day reports readable without changing unrelated numbers", () => {
    expect(readableReportText("Last 168h: 168 posts checked over 168 hours.", 168)).toBe("Last 7 days: 168 posts checked over 7 days.");
    expect(readableReportText("Past 6 hours: 168 posts.", 6)).toBe("Past 6 hours: 168 posts.");
  });
});
