import { describe, expect, it } from "vitest";
import { newsStatusLabel } from "./newsStatus";

describe("plain English news status", () => {
  it.each([
    ["corroborated", "Supported by news reports"],
    ["partially corroborated", "Some support in news reports"],
    ["uncorroborated", "No support found in news reports"],
    ["PARTIALLY_CORROBORATED", "Some support in news reports"],
  ])("preserves the meaning of %s without claiming proof", (status, label) => {
    expect(newsStatusLabel(status)).toBe(label);
  });
  it("preserves other evidence verdicts", () => {
    expect(newsStatusLabel("negative")).toBe("negative");
    expect(newsStatusLabel()).toBe("");
  });
});
