import { describe, expect, it } from "vitest";

import { parseClientAction } from "./clientActions";

describe("parseClientAction", () => {
  it("accepts the console's own export routes", () => {
    expect(
      parseClientAction({
        type: "download",
        path: "/api/reports/3f2a9c1e-1111-2222-3333-444455556666/download.xlsx",
        filename: "SENTINEL_incident_3f2a.xlsx",
      })
    ).toEqual({
      type: "download",
      path: "/api/reports/3f2a9c1e-1111-2222-3333-444455556666/download.xlsx",
      filename: "SENTINEL_incident_3f2a.xlsx",
    });
    expect(
      parseClientAction({ type: "download", path: "/api/admin/export/posts.csv?hours=24", filename: "p.csv" })
    ).not.toBeNull();
  });

  it("refuses any other download target", () => {
    for (const path of [
      "https://evil.example/x.pdf",
      "//evil.example/x.pdf",
      "/api/admin/purge?days=1",
      "/api/reports/../admin/export/posts.csv",
      "javascript:alert(1)",
    ]) {
      expect(parseClientAction({ type: "download", path, filename: "x" })).toBeNull();
    }
  });

  it("sanitises filenames and validates ids", () => {
    const d = parseClientAction({
      type: "download",
      path: "/api/reports/3f2a9c1e/download",
      filename: "../../etc/passwd",
    });
    expect(d).toEqual({ type: "download", path: "/api/reports/3f2a9c1e/download", filename: "download" });
    expect(parseClientAction({ type: "open_post", post_id: "<img src=x>" })).toBeNull();
    expect(parseClientAction({ type: "confirm", action_id: "abc123def0", summary: "Do it", expires_in: 120 }))
      .toMatchObject({ type: "confirm", action_id: "abc123def0" });
    expect(parseClientAction({ type: "navigate_anywhere", path: "/x" })).toBeNull();
  });
});
