import type { CSSProperties } from "react";
import { AlertTriangle, BookUser, Briefcase, Cake, CircleHelp, Eye, Fingerprint, Ruler, ShieldCheck, Siren, UserRoundX, UserX, VenetianMask } from "lucide-react";
import type { DisplayIdentity, IdentityCategory } from "../../data/dummyIdentities";
import { avatarColor, categoryForRecordType, CATEGORY_COLOR, CATEGORY_LABEL, fromSuspect, initials } from "../../data/dummyIdentities";
import type { FaceMatch, Identification } from "../../services/api";
import { Pill } from "./shared";

type BoundingBox = { top: number; right: number; bottom: number; left: number };

/** What the real searches actually determined for one detected face —
 * never a stand-in for "we don't know", which is its own honest state below. */
export type FaceOutcome =
  | { kind: "confirmed"; identity: DisplayIdentity; confidencePct: number; knownAs?: string }
  /** Named by the reference gallery, with no criminal record attached. This is
   * a separate outcome from `confirmed` on purpose: knowing who someone is and
   * holding a record on them are different claims, and merging them would put
   * every recognised face inside a police-record card. */
  | { kind: "known"; name: string; confidencePct: number; referencePhotos: number; thumb?: string; reason: string; registryReason?: string }
  | { kind: "lead"; name: string; category: IdentityCategory; confidencePct: number; reason: string; photoThumb?: string }
  | { kind: "unresolved"; reason: string; knownReason?: string };

/**
 * Turns raw detection + search results into the honest per-face outcomes above.
 * Shared by every place that shows identification (the Forensics tool's manual
 * upload and automatic per-post verification) so they can never drift into
 * inconsistent — or invented — results.
 */
export function buildFaceOutcomes(faceMatches: FaceMatch[] | undefined, identification: Identification | undefined): FaceOutcome[] {
  return (faceMatches ?? []).map((face): FaceOutcome => {
    const fi = face.identity;
    const known = fi?.known_person;
    const knownMatch = known?.identified ? known.match : null;
    const suspectId = fi?.match?.suspect_id;
    const dossier = suspectId ? identification?.identities?.[suspectId] : undefined;

    // A record beats a name: if this person is on file, that is the headline
    // and the gallery name rides along as an alias.
    if (face.matched_suspect && fi?.match && dossier?.suspect) {
      return {
        kind: "confirmed",
        identity: fromSuspect(dossier.suspect),
        confidencePct: Math.round((face.confidence ?? fi.match.confidence ?? 0) * 100),
        knownAs: knownMatch?.name,
      };
    }
    if (knownMatch) {
      return {
        kind: "known",
        name: knownMatch.name,
        confidencePct: Math.round(knownMatch.confidence * 100),
        referencePhotos: knownMatch.reference_photos,
        thumb: knownMatch.thumb,
        reason: known?.reason || "",
        registryReason: fi?.reason,
      };
    }
    if (fi?.match && fi.match.band === "possible") {
      return {
        kind: "lead",
        name: fi.match.full_name,
        category: categoryForRecordType(fi.match.record_type),
        confidencePct: Math.round(fi.match.confidence * 100),
        reason: fi.reason || "Below the identification threshold.",
        photoThumb: fi.match.photo_thumb,
      };
    }
    const reason = fi?.reason
      || (fi?.searched === false
        ? `Face quality too low to search: ${face.quality.issues.join("; ")}`
        : "No faces detected.");
    return { kind: "unresolved", reason, knownReason: known?.reason };
  });
}

const CATEGORY_ICON: Record<IdentityCategory, typeof AlertTriangle> = {
  wanted: AlertTriangle,
  criminal: Siren,
  missing: UserX,
  person_of_interest: Eye,
  public_figure: ShieldCheck,
  no_record: UserRoundX,
};

/** Crops a thumbnail out of the full-resolution preview around a face box, via background-position math — no canvas needed. */
function faceCropStyle(box: BoundingBox, mediaW: number, mediaH: number, previewSrc: string, size = 88): CSSProperties {
  const faceW = box.right - box.left;
  const faceH = box.bottom - box.top;
  const cropSide = Math.max(faceW, faceH, 1) * 1.7; // pad around the face for context
  const cx = box.left + faceW / 2;
  const cy = box.top + faceH / 2;
  const scale = size / cropSide;
  return {
    backgroundImage: `url(${previewSrc})`,
    backgroundSize: `${mediaW * scale}px ${mediaH * scale}px`,
    backgroundPosition: `${-(cx * scale - size / 2)}px ${-(cy * scale - size / 2)}px`,
    backgroundRepeat: "no-repeat",
  };
}

function MiniStat({ icon: Icon, label, value }: { icon: typeof Cake; label: string; value: string }) {
  return (
    <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-2.5 py-1.5">
      <div className="flex items-center gap-1 text-[10px] uppercase tracking-wide text-slate-500"><Icon size={11} /> {label}</div>
      <div className="mt-0.5 text-[13px] font-medium leading-snug text-slate-200">{value}</div>
    </div>
  );
}

function Avatar({ box, mediaW, mediaH, previewSrc, photoThumb, fallbackLabel, fallbackName }: {
  box?: BoundingBox; mediaW?: number; mediaH?: number; previewSrc?: string | null;
  photoThumb?: string; fallbackLabel?: string; fallbackName?: string;
}) {
  const canCrop = box && mediaW && mediaH && previewSrc;
  if (canCrop) {
    return <div className="h-[88px] w-[88px] shrink-0 overflow-hidden rounded-lg border border-white/10" style={faceCropStyle(box, mediaW, mediaH, previewSrc)} />;
  }
  if (photoThumb) {
    return <img src={photoThumb} alt="" className="h-[88px] w-[88px] shrink-0 rounded-lg border border-white/10 object-cover" />;
  }
  const color = fallbackName ? avatarColor(fallbackName) : "#64748B";
  return (
    <div className="flex h-[88px] w-[88px] shrink-0 items-center justify-center rounded-lg border border-white/10" style={{ backgroundColor: `${color}22` }}>
      {fallbackName ? (
        <span className="text-lg font-bold" style={{ color }}>{initials(fallbackName)}</span>
      ) : (
        <CircleHelp size={28} className="text-slate-600" />
      )}
      {fallbackLabel && <span className="sr-only">{fallbackLabel}</span>}
    </div>
  );
}

function ConfirmedCard({ identity, confidencePct, knownAs, box, mediaW, mediaH, previewSrc }: {
  identity: DisplayIdentity; confidencePct: number; knownAs?: string;
  box?: BoundingBox; mediaW?: number; mediaH?: number; previewSrc?: string | null;
}) {
  const color = CATEGORY_COLOR[identity.category];
  const CatIcon = CATEGORY_ICON[identity.category];
  return (
    <div className="space-y-3 rounded-xl border border-white/[0.07] bg-white/[0.02] p-3.5">
      <div className="flex items-start gap-3">
        <Avatar box={box} mediaW={mediaW} mediaH={mediaH} previewSrc={previewSrc} fallbackName={identity.name} />
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="truncate text-[14px] font-semibold text-slate-100">{identity.name}</span>
            <Pill color={color}><CatIcon size={11} /> {CATEGORY_LABEL[identity.category]}</Pill>
            {identity.riskLevel && <Pill color={color}>{identity.riskLevel} risk</Pill>}
          </div>
          <div className="text-[12px] text-slate-500">{identity.occupation}</div>
          <div className="text-[11px] text-slate-600">
            {confidencePct}% match confidence — confirmed against the suspect registry
            {knownAs && knownAs !== identity.name && (
              <> · reference gallery names this face <span className="text-slate-400">{knownAs}</span></>
            )}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-1.5">
        <MiniStat icon={Cake} label="Age" value={`${identity.age} yrs`} />
        <MiniStat icon={Ruler} label="Height" value={`${identity.heightCm} cm`} />
        <MiniStat icon={VenetianMask} label="Gender" value={identity.gender} />
      </div>
      <MiniStat icon={Briefcase} label="Occupation" value={identity.occupation} />

      <div className="rounded-lg border border-white/[0.06] bg-white/[0.015] px-3 py-2 text-[12.5px] leading-snug text-slate-300">
        {identity.detail}
      </div>

      {(identity.caseRef || identity.aliases?.length || identity.lastSeen) && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-500">
          {identity.caseRef && <span>Case ref: <span className="font-mono text-slate-400">{identity.caseRef}</span></span>}
          {identity.aliases?.length ? <span>Aliases: <span className="text-slate-400">{identity.aliases.join(", ")}</span></span> : null}
          {identity.lastSeen && <span>Last seen: <span className="text-slate-400">{identity.lastSeen}</span></span>}
        </div>
      )}
    </div>
  );
}

function KnownCard({ outcome, box, mediaW, mediaH, previewSrc }: {
  outcome: Extract<FaceOutcome, { kind: "known" }>;
  box?: BoundingBox; mediaW?: number; mediaH?: number; previewSrc?: string | null;
}) {
  const color = CATEGORY_COLOR.public_figure;
  return (
    <div className="space-y-2.5 rounded-xl border border-white/[0.07] bg-white/[0.02] p-3.5">
      <div className="flex items-start gap-3">
        <Avatar box={box} mediaW={mediaW} mediaH={mediaH} previewSrc={previewSrc} fallbackName={outcome.name} />
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="truncate text-[14px] font-semibold text-slate-100">{outcome.name}</span>
            <Pill color={color}><BookUser size={11} /> Known person</Pill>
            <Pill color={CATEGORY_COLOR.no_record}><ShieldCheck size={11} /> No criminal record</Pill>
          </div>
          <div className="text-[11px] text-slate-500">
            {outcome.confidencePct}% match against {outcome.referencePhotos} reference
            photo{outcome.referencePhotos === 1 ? "" : "s"} in the gallery
          </div>
        </div>
        {outcome.thumb && (
          <img src={outcome.thumb} alt="" title="Reference photo this matched"
            className="h-[52px] w-[52px] shrink-0 rounded-lg border border-white/10 object-cover opacity-90" />
        )}
      </div>
      <div className="rounded-lg border border-white/[0.06] bg-white/[0.015] px-3 py-2 text-[12px] leading-snug text-slate-400">
        Recognised from the reference gallery, which names people — it is not the
        suspect registry. {outcome.registryReason || "No registry record matched this face."}
      </div>
    </div>
  );
}

function LeadCard({ outcome, box, mediaW, mediaH, previewSrc }: {
  outcome: Extract<FaceOutcome, { kind: "lead" }>;
  box?: BoundingBox; mediaW?: number; mediaH?: number; previewSrc?: string | null;
}) {
  const color = CATEGORY_COLOR[outcome.category];
  return (
    <div className="space-y-2.5 rounded-xl border border-dashed border-white/[0.1] bg-white/[0.015] p-3.5">
      <div className="flex items-start gap-3">
        <Avatar box={box} mediaW={mediaW} mediaH={mediaH} previewSrc={previewSrc} photoThumb={outcome.photoThumb} fallbackName={outcome.name} />
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="truncate text-[14px] font-semibold text-slate-200">{outcome.name}</span>
            <Pill color={color}>possible lead</Pill>
          </div>
          <div className="text-[11px] text-amber-400/90">{outcome.confidencePct}% resemblance — below the confirmation threshold</div>
        </div>
      </div>
      <div className="rounded-lg border border-white/[0.06] bg-white/[0.015] px-3 py-2 text-[12px] leading-snug text-slate-400">
        {outcome.reason} Not shown as an identification — an analyst should confirm manually before acting on it.
      </div>
    </div>
  );
}

function UnresolvedCard({ outcome }: { outcome: Extract<FaceOutcome, { kind: "unresolved" }> }) {
  return (
    <div className="space-y-2.5 rounded-xl border border-dashed border-white/[0.08] bg-white/[0.01] p-3.5">
      <div className="flex items-start gap-3">
        <Avatar />
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="text-[14px] font-medium text-slate-400">Not identified</div>
          <div className="text-[11px] text-slate-600">No confident match in the registry or the reference gallery</div>
        </div>
      </div>
      <div className="space-y-1.5 rounded-lg border border-white/[0.06] bg-white/[0.015] px-3 py-2 text-[12px] leading-snug text-slate-500">
        <div>{outcome.reason}</div>
        {/* Both searches reported separately: "not on record" and "we don't know
            who this is" are different answers, and an officer needs to see
            which one they got — especially when the gallery is simply empty. */}
        {outcome.knownReason && <div className="text-slate-600">{outcome.knownReason}</div>}
      </div>
    </div>
  );
}

export default function IdentifiedPersonsPanel({ outcomes, boxes, mediaW, mediaH, previewSrc, singleColumn = false }: {
  outcomes: FaceOutcome[];
  boxes?: (BoundingBox | undefined)[];
  mediaW?: number; mediaH?: number; previewSrc?: string | null;
  /** Tailwind's `lg:` breakpoint tracks the viewport, not this panel's own
   * container — inside a narrow host (a drawer, a sidebar) two columns
   * force-fit into too little width and cards start truncating. Pass true
   * there to stay single-column regardless of viewport size. */
  singleColumn?: boolean;
}) {
  if (!outcomes.length) return null;
  const confirmedCount = outcomes.filter((o) => o.kind === "confirmed").length;
  const namedCount = outcomes.filter((o) => o.kind === "known").length;
  return (
    <div className="space-y-3 rounded-2xl border border-white/[0.07] bg-white/[0.02] p-4">
      <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
        <Fingerprint size={15} className="text-accent" /> Identified Individuals
        <span className="text-slate-500">
          ({confirmedCount}/{outcomes.length} on record
          {namedCount > 0 && `, ${namedCount} named`})
        </span>
      </div>
      <p className="text-[11px] text-slate-600">
        Each detected face is searched twice by real biometric matching: against the suspect registry, and against the
        reference gallery of known people. A registry hit means this person is on record; a gallery hit only puts a name
        to the face. Anything below the confirmation threshold is reported exactly as the search found it, never as an
        identification.
      </p>
      <div className={`grid gap-3 ${singleColumn ? "" : "lg:grid-cols-2"}`}>
        {outcomes.map((o, i) => {
          const box = boxes?.[i];
          if (o.kind === "confirmed") {
            return <ConfirmedCard key={i} identity={o.identity} confidencePct={o.confidencePct} knownAs={o.knownAs} box={box} mediaW={mediaW} mediaH={mediaH} previewSrc={previewSrc} />;
          }
          if (o.kind === "known") {
            return <KnownCard key={i} outcome={o} box={box} mediaW={mediaW} mediaH={mediaH} previewSrc={previewSrc} />;
          }
          if (o.kind === "lead") {
            return <LeadCard key={i} outcome={o} box={box} mediaW={mediaW} mediaH={mediaH} previewSrc={previewSrc} />;
          }
          return <UnresolvedCard key={i} outcome={o} />;
        })}
      </div>
    </div>
  );
}
