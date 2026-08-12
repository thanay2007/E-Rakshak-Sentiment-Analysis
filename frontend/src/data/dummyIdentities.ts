/**
 * Display helpers for the "Identified Individuals" panel in the Image & Video
 * Forensics tool. Detection and 1:N matching both run server-side and for
 * real (osint/face_db.py) — this file only shapes a matched `Suspect` record
 * into what the panel renders. It never invents an identity: a face with no
 * confident registry match is shown as unresolved (see PersonIdentification's
 * `FaceOutcome`), not attached to a made-up name.
 */
import type { Suspect } from "../services/api";

export type IdentityCategory =
  | "wanted" | "criminal" | "missing" | "person_of_interest" | "public_figure" | "no_record";

export interface DisplayIdentity {
  id: string;
  name: string;
  category: IdentityCategory;
  age: number;
  heightCm: number;
  gender: string;
  occupation: string;
  riskLevel?: "critical" | "high" | "medium" | "low";
  /** What they did (wanted/POI) or who they are (public figure/no record). */
  detail: string;
  aliases?: string[];
  caseRef?: string;
  lastSeen?: string;
}

export const CATEGORY_LABEL: Record<IdentityCategory, string> = {
  wanted: "Wanted",
  criminal: "Criminal Record",
  missing: "Missing Person",
  person_of_interest: "Person of Interest",
  public_figure: "Public Figure",
  no_record: "No Criminal Record",
};

export const CATEGORY_COLOR: Record<IdentityCategory, string> = {
  wanted: "#EF4444",
  criminal: "#EF4444",
  missing: "#8B5CF6",
  person_of_interest: "#F59E0B",
  public_figure: "#14B8C4",
  no_record: "#10B981",
};

const RECORD_TYPE_TO_CATEGORY: Record<string, IdentityCategory> = {
  wanted: "wanted",
  criminal: "criminal",
  missing: "missing",
  person_of_interest: "person_of_interest",
  cleared: "no_record",
};

export function categoryForRecordType(recordType: string): IdentityCategory {
  return RECORD_TYPE_TO_CATEGORY[recordType] ?? "person_of_interest";
}

/** Converts a real, enrolled suspect-registry record into the panel's card shape. */
export function fromSuspect(s: Suspect): DisplayIdentity {
  return {
    id: s.id,
    name: s.full_name,
    category: categoryForRecordType(s.record_type),
    age: s.age,
    heightCm: s.height_cm,
    gender: s.gender || "Unknown",
    occupation: s.occupation || "Unknown",
    riskLevel: (["critical", "high", "medium", "low"] as const).includes(s.risk_level as never)
      ? (s.risk_level as DisplayIdentity["riskLevel"]) : undefined,
    detail: s.notes || s.identifying_marks || "No further details on file.",
    aliases: s.aliases?.length ? s.aliases : undefined,
    caseRef: s.case_ids?.[0],
    lastSeen: s.last_known_location || undefined,
  };
}

function hashString(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h;
}

const AVATAR_PALETTE = ["#14B8C4", "#8B5CF6", "#F59E0B", "#10B981", "#EF4444", "#3B82F6"];

export function avatarColor(name: string): string {
  return AVATAR_PALETTE[hashString(name) % AVATAR_PALETTE.length];
}

export function initials(name: string): string {
  const parts = name.replace(/["]/g, "").split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] || "") + (parts[parts.length - 1]?.[0] || "")).toUpperCase();
}
