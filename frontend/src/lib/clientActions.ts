/** Browser effects the assistant's tools can ask for, and the check each one
 *  passes before this console acts on it.
 *
 *  They are built server-side from typed tool results (never from model
 *  prose), but this is the last place before an effect touches the officer's
 *  machine, so every field is validated again here: a download may only fetch
 *  one of the console's own export routes, and a post or action id must look
 *  like an id. Anything else is dropped.
 */

export type ClientAction =
  | { type: "download"; path: string; filename: string }
  | { type: "open_post"; post_id: string }
  | { type: "confirm"; action_id: string; summary: string; expires_in: number }
  | { type: "confirm_clear" };

/** The only files the assistant may download: report PDFs and workbooks, and
 *  the admin posts export. Each route enforces its own rank and audits the
 *  download server-side. */
const DOWNLOAD_PATH =
  /^\/api\/(reports\/[0-9a-fA-F-]{8,40}\/download(\.xlsx)?|admin\/export\/posts\.csv\?hours=\d{1,4})$/;
const RECORD_ID = /^[0-9a-fA-F-]{8,40}$/;
const ACTION_ID = /^[0-9a-f]{6,32}$/;
const FILENAME = /^[\w.-]{1,120}$/;

export function parseClientAction(raw: unknown): ClientAction | null {
  if (!raw || typeof raw !== "object") return null;
  const a = raw as Record<string, unknown>;
  switch (a.type) {
    case "download": {
      const path = String(a.path ?? "");
      const filename = String(a.filename ?? "");
      if (!DOWNLOAD_PATH.test(path)) return null;
      return { type: "download", path, filename: FILENAME.test(filename) ? filename : "download" };
    }
    case "open_post": {
      const id = String(a.post_id ?? "");
      return RECORD_ID.test(id) ? { type: "open_post", post_id: id } : null;
    }
    case "confirm": {
      const id = String(a.action_id ?? "");
      if (!ACTION_ID.test(id)) return null;
      return {
        type: "confirm",
        action_id: id,
        summary: String(a.summary ?? "").slice(0, 240),
        expires_in: Math.max(0, Math.min(Number(a.expires_in) || 0, 600)),
      };
    }
    case "confirm_clear":
      return { type: "confirm_clear" };
    default:
      return null;
  }
}
