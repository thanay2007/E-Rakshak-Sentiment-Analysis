import { useCallback, useEffect, useRef, useState } from "react";
import {
  AtSign, BadgeCheck, CheckCircle2, ChevronDown, ExternalLink, Globe, HelpCircle,
  Link as LinkIcon, MapPin, Search, ShieldAlert, Sparkles, Users, XCircle,
} from "lucide-react";
import GlassCard, { SectionTitle } from "../GlassCard";
import { api } from "../../services/api";
import type { RelatedAccount, UsernameHit, UsernameReport } from "../../services/api";
import { AiExplanation, EmptyHint, Meter, Pill, RunButton, Spinner } from "./shared";
import { useUrlFilters } from "../../hooks/useUrlFilters";
import { safeHref } from "../../lib/safeUrl";

const STATUS_META: Record<string, { color: string; icon: React.ReactNode; label: string }> = {
  found: { color: "#10B981", icon: <CheckCircle2 size={14} />, label: "Found" },
  not_found: { color: "#64748B", icon: <XCircle size={14} />, label: "Not found" },
  blocked: { color: "#F59E0B", icon: <ShieldAlert size={14} />, label: "Blocked" },
  unknown: { color: "#A855F7", icon: <HelpCircle size={14} />, label: "Unknown" },
};

// "Link", not "identity": the same photo and name is equally consistent with
// the person and with someone impersonating them. The reasons decide, not the badge.
const VERDICT_META: Record<string, { color: string; label: string }> = {
  strong_link: { color: "#10B981", label: "Strong link" },
  possible_link: { color: "#F59E0B", label: "Possible link" },
  weak: { color: "#64748B", label: "Weak signal" },
};

const compact = (n: number) => Intl.NumberFormat(undefined, { notation: "compact" }).format(n);

/**
 * Profile photo, relayed through `/api/media`.
 *
 * The same rule as post attachments (backend/app/routers/media.py): the browser
 * never fetches from Instagram's or X's CDN directly, because that would tell
 * the platform hosting a suspect's avatar which officer looked at it and from
 * where. Falls back to the handle's initial rather than a broken-image icon.
 */
function Avatar({ url, name, size = 40 }: { url: string; name: string; size?: number }) {
  const [src, setSrc] = useState<string | null>(null);

  useEffect(() => {
    if (!url) return;
    let live = true;
    let created: string | null = null;
    api.media(url)
      .then((blob) => {
        if (!live) return;
        created = URL.createObjectURL(blob);
        setSrc(created);
      })
      .catch(() => { /* initials fallback is the designed failure mode */ });
    return () => { live = false; if (created) URL.revokeObjectURL(created); };
  }, [url]);

  if (src) {
    return (
      <img src={src} alt="" width={size} height={size} loading="lazy"
        className="shrink-0 rounded-full border border-white/10 object-cover"
        style={{ width: size, height: size }} />
    );
  }
  return (
    <div className="grid shrink-0 place-items-center rounded-full border border-white/10 bg-white/[0.05] font-semibold uppercase text-slate-400"
      style={{ width: size, height: size, fontSize: size * 0.38 }}>
      {(name || "?").replace(/^@/, "").charAt(0)}
    </div>
  );
}

/** Confidence + the evidence behind it. A number with no reasons is unusable in a case file. */
function MatchEvidence({ confidence, why, verdict }: { confidence: number; why: string[]; verdict?: string }) {
  const meta = VERDICT_META[verdict ?? ""] ?? { color: confidence >= 70 ? "#10B981" : confidence >= 45 ? "#F59E0B" : "#64748B", label: "" };
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] uppercase tracking-wide text-slate-500">
          {meta.label || "Corroborated by other profiles"}
        </span>
        <span className="font-mono text-[12px] font-semibold" style={{ color: meta.color }}>{confidence}%</span>
      </div>
      <Meter value={confidence} color={meta.color} />
      {why.length > 0 && (
        <ul className="space-y-0.5 pt-0.5">
          {why.map((w) => (
            <li key={w} className="flex gap-1.5 text-[11px] leading-snug text-slate-400">
              <span className="mt-[5px] h-1 w-1 shrink-0 rounded-full bg-slate-600" />{w}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ProfileCard({ hit }: { hit: UsernameHit }) {
  const meta = STATUS_META[hit.status] ?? STATUS_META.unknown;
  return (
    <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-3 transition-colors hover:border-white/[0.16]">
      <div className="flex items-start gap-3">
        <Avatar url={hit.avatar} name={hit.display_name || hit.handle} size={44} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-[13px] font-semibold text-slate-100">
              {hit.display_name || hit.handle || "—"}
            </span>
            {hit.verified && <BadgeCheck size={14} className="shrink-0 text-accent" />}
          </div>
          <div className="truncate font-mono text-[11px] text-slate-500">@{hit.handle || "—"}</div>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-[12px] font-medium text-slate-300">{hit.site}</div>
          <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wide"
            style={{ color: hit.source === "api" ? "#14B8C4" : "#64748B" }}>
            {hit.source === "api" ? "read via API" : "URL probe"}
          </span>
        </div>
      </div>

      {hit.bio && <p className="mt-2 line-clamp-2 text-[12px] leading-snug text-slate-400">{hit.bio}</p>}

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-500">
        {hit.followers != null && (
          <span className="inline-flex items-center gap-1"><Users size={11} />{compact(hit.followers)} followers</span>
        )}
        {hit.created_at && <span>joined {hit.created_at}</span>}
        {hit.location && <span className="inline-flex items-center gap-1"><MapPin size={11} />{hit.location}</span>}
        {hit.link && (
          <a href={safeHref(hit.link)} target="_blank" rel="noreferrer"
            className="inline-flex items-center gap-1 text-sky-400 hover:underline">
            <LinkIcon size={11} />{hit.link.replace(/^https?:\/\//, "").slice(0, 28)}
          </a>
        )}
      </div>

      {hit.match && hit.match.why.length > 0 && (
        <div className="mt-3 border-t border-white/[0.06] pt-2.5">
          <MatchEvidence confidence={hit.match.confidence} why={hit.match.why} />
        </div>
      )}

      <a href={safeHref(hit.url)} target="_blank" rel="noreferrer"
        className="mt-2.5 inline-flex items-center gap-1 text-[11px] font-medium hover:underline"
        style={{ color: meta.color }}>
        {meta.icon} Open profile <ExternalLink size={10} />
      </a>
    </div>
  );
}

function RelatedCard({ acct }: { acct: RelatedAccount }) {
  const meta = VERDICT_META[acct.verdict] ?? VERDICT_META.weak;
  return (
    <div className="rounded-xl border p-3" style={{ borderColor: `${meta.color}33`, backgroundColor: `${meta.color}0A` }}>
      <div className="flex items-start gap-3">
        <Avatar url={acct.avatar} name={acct.display_name || acct.handle} size={40} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-semibold text-slate-100">
            {acct.display_name || acct.handle}
          </div>
          <div className="truncate font-mono text-[11px] text-slate-500">
            @{acct.handle} · {acct.site}
          </div>
        </div>
        <Pill color={meta.color}>{meta.label}</Pill>
      </div>

      {acct.bio && <p className="mt-2 line-clamp-2 text-[12px] leading-snug text-slate-400">{acct.bio}</p>}

      <div className="mt-2.5">
        <MatchEvidence confidence={acct.confidence} why={acct.why} verdict={acct.verdict} />
      </div>

      <div className="mt-2 flex items-center justify-between gap-2 text-[11px]">
        <span className="text-slate-600">
          found by {acct.discovered_by === "variant" ? "handle variant" : "platform user search"}
          {acct.followers != null && ` · ${compact(acct.followers)} followers`}
        </span>
        <a href={safeHref(acct.url)} target="_blank" rel="noreferrer"
          className="inline-flex items-center gap-1 text-sky-400 hover:underline">
          open <ExternalLink size={10} />
        </a>
      </div>
    </div>
  );
}

export default function UsernameTool() {
  // A handle can arrive in the URL — the network graph's "Trace" pivot and the
  // assistant both do that. Without this the link lands on an empty box and
  // the officer has to retype what they just clicked.
  const { get } = useUrlFilters();
  const urlHandle = get("u", "");
  const [u, setU] = useState(urlHandle);
  const [similar, setSimilar] = useState(true);
  const [data, setData] = useState<UsernameReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showMisses, setShowMisses] = useState(false);

  const run = useCallback(async (override?: string) => {
    const handle = (override ?? u).trim().replace(/^@+/, "");
    if (!handle) return;
    setErr(null); setLoading(true); setData(null); setShowMisses(false);
    try {
      setData(await api.investigateUsername(handle, similar));
    } catch (e) { setErr((e as Error).message); }
    finally { setLoading(false); }
  }, [u, similar]);

  // Auto-run for a handle that arrived in the URL, once per handle — arriving
  // from a pivot means the officer has already asked for this lookup.
  const ranFor = useRef("");
  useEffect(() => {
    const handle = urlHandle.trim().replace(/^@+/, "");
    if (!handle || ranFor.current === handle) return;
    ranFor.current = handle;
    setU(handle);
    void run(handle);
  }, [urlHandle, run]);

  const found = data?.results.filter((r) => r.status === "found") ?? [];
  const misses = data?.results.filter((r) => r.status !== "found") ?? [];
  const identity = data?.identity;
  const related = data?.related ?? [];
  // Platforms whose API could not be used at all — said out loud, because an
  // empty result there means "not checked", not "no account".
  const gaps = Object.entries(data?.coverage ?? {})
    .filter(([, v]) => v === "missing")
    .map(([k]) => k);

  return (
    <div className="space-y-4">
      <GlassCard className="p-4">
        <SectionTitle
          title="Username Lookup"
          sub="Read the handle's real profile on every platform that publishes one, then correlate them into a single identity."
        />

        {/* One control: the @ sits inside the field's border, not floating over it. */}
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <div className="flex flex-1 items-center gap-2 rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 transition-colors focus-within:border-accent/50 focus-within:bg-white/[0.06]">
            <AtSign size={15} className="shrink-0 text-slate-500" />
            <input
              value={u}
              onChange={(e) => setU(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") run(); }}
              placeholder="handle e.g. desh_sachai_4471"
              spellCheck={false}
              autoComplete="off"
              aria-label="Username to look up"
              className="w-full bg-transparent py-2.5 font-mono text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none"
            />
            {u && (
              <button onClick={() => setU("")} aria-label="Clear"
                className="shrink-0 text-slate-600 transition-colors hover:text-slate-300">
                <XCircle size={14} />
              </button>
            )}
          </div>
          {/* Wrapped, not passed directly: the button hands its click event to
              the handler, and `run` now takes an optional handle override. */}
          <RunButton onClick={() => void run()} disabled={loading || !u.trim()}>
            <Search size={15} /> Search
          </RunButton>
        </div>

        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <label className="inline-flex cursor-pointer items-center gap-2 text-[12px] text-slate-400">
            <input type="checkbox" checked={similar} onChange={(e) => setSimilar(e.target.checked)}
              className="h-3.5 w-3.5 cursor-pointer accent-[#14B8C4]" />
            <Sparkles size={13} className="text-accent" />
            Also hunt for related accounts (handle variants + platform user search)
          </label>
          <p className="text-[11px] text-slate-600">
            Official APIs where they exist · public profile URLs elsewhere · no login, no scraping
          </p>
        </div>

        {gaps.length > 0 && (
          <p className="mt-2 rounded-lg border border-amber-500/20 bg-amber-500/[0.06] px-3 py-1.5 text-[11px] text-amber-300/90">
            No API credentials for {gaps.join(", ")} — those platforms are reported as “unknown”, which is not the same as “no account”.
          </p>
        )}
      </GlassCard>

      {loading && (
        <GlassCard className="p-2">
          <Spinner label={`Reading profiles for “${u.trim().replace(/^@+/, "")}”${similar ? " and hunting related handles" : ""}…`} />
        </GlassCard>
      )}
      {err && <GlassCard className="p-4 text-sm text-red-400">Error: {err}</GlassCard>}
      {data && !data.valid && <GlassCard className="p-4 text-sm text-amber-400">{data.error}</GlassCard>}

      {data?.valid && !loading && (
        <>
          {/* Who the platforms agree this is */}
          {(identity?.display_name || identity?.avatar || identity?.bio) && (
            <GlassCard className="p-4">
              <div className="flex items-start gap-4">
                <Avatar url={identity.avatar} name={identity.display_name || data.username} size={64} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-base font-semibold text-slate-100">
                      {identity.display_name || `@${data.username}`}
                    </h3>
                    <span className="font-mono text-[12px] text-slate-500">@{data.username}</span>
                    {identity.verified_on.length > 0 && (
                      <Pill color="#14B8C4"><BadgeCheck size={11} /> verified on {identity.verified_on.join(", ")}</Pill>
                    )}
                  </div>
                  {identity.bio && <p className="mt-1 text-[12px] leading-snug text-slate-400">{identity.bio}</p>}
                  <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-500">
                    <span className="inline-flex items-center gap-1">
                      <Users size={11} />{compact(identity.total_reach)} combined reach
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <Globe size={11} />{found.length} live {found.length === 1 ? "profile" : "profiles"}
                    </span>
                    {identity.locations.map((l) => (
                      <span key={l} className="inline-flex items-center gap-1"><MapPin size={11} />{l}</span>
                    ))}
                    {identity.display_names.length > 1 && (
                      <span>also posts as {identity.display_names.slice(1).join(", ")}</span>
                    )}
                  </div>
                </div>
              </div>
            </GlassCard>
          )}

          <AiExplanation tool="username" report={data} deps={[data.username, data.summary.found, related.length]} />

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              { label: "Accounts found", value: data.summary.found, color: "#10B981" },
              { label: "Read via API", value: data.summary.via_api, color: "#14B8C4" },
              { label: "Related accounts", value: related.length, color: "#A855F7" },
              { label: "Platforms checked", value: data.summary.checked, color: "#64748B" },
            ].map((t) => (
              <GlassCard key={t.label} className="p-3 text-center">
                <div className="font-mono text-2xl font-semibold" style={{ color: t.color }}>{t.value}</div>
                <div className="mt-0.5 text-[11px] uppercase tracking-wide text-slate-500">{t.label}</div>
              </GlassCard>
            ))}
          </div>

          {found.length > 0 && (
            <GlassCard className="p-4">
              <SectionTitle title="Confirmed profiles"
                sub={`${found.length} platform${found.length === 1 ? "" : "s"} carry this handle`} />
              <div className="grid gap-2.5 lg:grid-cols-2">
                {found.map((r) => <ProfileCard key={r.site} hit={r} />)}
              </div>
            </GlassCard>
          )}

          {related.length > 0 && (
            <GlassCard className="p-4">
              <SectionTitle title="Related accounts"
                sub="Different handles the evidence ties to the same person — photo, name, bio and links, not spelling alone" />
              <div className="grid gap-2.5 lg:grid-cols-2">
                {related.map((a) => <RelatedCard key={`${a.site}:${a.handle}`} acct={a} />)}
              </div>
            </GlassCard>
          )}

          {similar && related.length === 0 && found.length > 0 && (
            <GlassCard className="p-3 text-center text-[12px] text-slate-500">
              No related accounts cleared the evidence threshold — nearby handles existed but nothing tied them to this person.
            </GlassCard>
          )}

          {misses.length > 0 && (
            <GlassCard className="p-4">
              <button onClick={() => setShowMisses((s) => !s)}
                className="flex w-full items-center justify-between gap-2 text-left">
                <span className="text-sm font-semibold uppercase tracking-wider text-slate-400">
                  No presence · {misses.length} platforms
                </span>
                <ChevronDown size={16} className={`text-slate-500 transition-transform ${showMisses ? "rotate-180" : ""}`} />
              </button>
              {showMisses && (
                <div className="mt-3 grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
                  {misses.map((r) => {
                    const m = STATUS_META[r.status] ?? STATUS_META.unknown;
                    const note = typeof r.extra?.note === "string" ? r.extra.note : "";
                    return (
                      <a key={r.site} href={safeHref(r.url)} target="_blank" rel="noreferrer" title={note}
                        className="flex items-center justify-between gap-2 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2 hover:border-white/[0.15]">
                        <div className="min-w-0">
                          <div className="truncate text-[12px] text-slate-300">{r.site}</div>
                          <div className="truncate text-[10px] text-slate-600">{note || r.category}</div>
                        </div>
                        <span className="inline-flex shrink-0 items-center gap-1 text-[11px]" style={{ color: m.color }}>
                          {m.icon} {m.label}
                        </span>
                      </a>
                    );
                  })}
                </div>
              )}
            </GlassCard>
          )}
        </>
      )}

      {!data && !loading && !err && (
        <EmptyHint>Enter a username to map its cross-platform presence.</EmptyHint>
      )}
    </div>
  );
}
