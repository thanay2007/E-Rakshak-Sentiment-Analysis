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

// Where a finding came from, in words an officer can act on. The first three
// are the account's own details as the platform publishes them; the last two
// only confirm that a page with this name exists.
const SOURCE_LABEL: Record<string, string> = {
  api: "read from the platform",
  preview: "public profile card",
  mirror: "via an X mirror",
  sherlock: "site check",
  probe: "checked the page",
};

// Sources that hand back the account holder's own name, photo and counts.
const FIRST_HAND = new Set(["api", "preview", "mirror"]);

const COVERAGE_LABEL: Record<string, string> = {
  x: "X (Twitter)", github: "GitHub", youtube: "YouTube",
  reddit: "Reddit", instagram: "Instagram",
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
          {meta.label || "Backed up by the other accounts"}
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
            style={{ color: FIRST_HAND.has(hit.source) ? "#14B8C4" : "#64748B" }}>
            {SOURCE_LABEL[hit.source] ?? "checked the page"}
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
          found by {acct.discovered_by === "variant" ? "trying similar names" : "searching the site"}
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
  const [deep, setDeep] = useState(true);
  const [data, setData] = useState<UsernameReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showMisses, setShowMisses] = useState(false);

  const run = useCallback(async (override?: string) => {
    const handle = (override ?? u).trim().replace(/^@+/, "");
    if (!handle) return;
    setErr(null); setLoading(true); setData(null); setShowMisses(false);
    try {
      setData(await api.investigateUsername(handle, similar, deep));
    } catch (e) { setErr((e as Error).message); }
    finally { setLoading(false); }
  }, [u, similar, deep]);

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
  // A hit with a name, photo or bio behind it gets a full card; a site that
  // only confirmed "this handle exists here" gets a one-line link. Eighty
  // identical empty cards would bury the four that carry evidence.
  const profiles = found.filter((r) => r.display_name || r.bio || r.avatar || r.followers != null);
  const bareHits = found.filter((r) => !profiles.includes(r));
  const misses = data?.results.filter((r) => r.status !== "found") ?? [];
  // Blocked, or checked-but-unreadable: the honest "we don't know" bucket.
  // Limited to the named platforms — a few dozen forums that answered with a
  // bot wall are noise here, and they stay in the collapsed list below.
  const unreadable = misses.filter(
    (r) => (r.status === "blocked" || r.status === "unknown") && r.source !== "sherlock");
  const otherMisses = misses.filter((r) => !unreadable.includes(r));
  const identity = data?.identity;
  const related = data?.related ?? [];
  const sweep = data?.summary.sherlock;
  // Platforms whose API could not be used at all — said out loud, because an
  // empty result there means "not checked", not "no account". `sherlock` is in
  // the same map but is not a credential, so it is reported separately below.
  const gaps = Object.entries(data?.coverage ?? {})
    .filter(([k, v]) => v === "missing" && k !== "sherlock")
    // The coverage map is keyed by lowercase route names; "no access key for x"
    // reads like a typo on screen.
    .map(([k]) => COVERAGE_LABEL[k] ?? k);
  const sweepMissing = data?.coverage?.sherlock === "missing";

  return (
    <div className="space-y-4">
      <GlassCard className="p-4">
        <SectionTitle
          title="Username Search"
          sub="Type a username. We check the big platforms and around 480 other websites for that name, open the profiles we can read, and show which accounts look like the same person."
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
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
            <label className="inline-flex cursor-pointer items-center gap-2 text-[12px] text-slate-400">
              <input type="checkbox" checked={similar} onChange={(e) => setSimilar(e.target.checked)}
                className="h-3.5 w-3.5 cursor-pointer accent-[#14B8C4]" />
              <Sparkles size={13} className="text-accent" />
              Also look for the same person under a slightly different name
            </label>
            <label className="inline-flex cursor-pointer items-center gap-2 text-[12px] text-slate-400">
              <input type="checkbox" checked={deep} onChange={(e) => setDeep(e.target.checked)}
                className="h-3.5 w-3.5 cursor-pointer accent-[#14B8C4]" />
              <Globe size={13} className="text-accent" />
              Search ~480 more websites — forums, gaming, shopping (slower)
            </label>
          </div>
          <p className="text-[11px] text-slate-600">
            Public pages only · no login, nothing hacked
          </p>
        </div>

        {gaps.length > 0 && (
          <p className="mt-2 rounded-lg border border-amber-500/20 bg-amber-500/[0.06] px-3 py-1.5 text-[11px] text-amber-300/90">
            We have no access key for {gaps.join(", ")}, so those were not checked. That is not the same as “no account there”.
          </p>
        )}
        {sweepMissing && deep && (
          <p className="mt-2 rounded-lg border border-amber-500/20 bg-amber-500/[0.06] px-3 py-1.5 text-[11px] text-amber-300/90">
            The list of extra websites could not be loaded on the server, so only the main platforms were searched.
          </p>
        )}
      </GlassCard>

      {loading && (
        <GlassCard className="p-2">
          <Spinner label={`Searching for “${u.trim().replace(/^@+/, "")}”${deep ? " across ~480 websites — this takes about half a minute" : ""}…`} />
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
                      <Users size={11} />{compact(identity.total_reach)} followers in total
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <Globe size={11} />{found.length} {found.length === 1 ? "account" : "accounts"} found
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
              { label: "Full profiles read", value: profiles.length, color: "#14B8C4" },
              { label: "Same person, other name", value: related.length, color: "#A855F7" },
              { label: "Websites checked", value: data.summary.checked, color: "#64748B" },
            ].map((t) => (
              <GlassCard key={t.label} className="p-3 text-center">
                <div className="font-mono text-2xl font-semibold" style={{ color: t.color }}>{t.value}</div>
                <div className="mt-0.5 text-[11px] uppercase tracking-wide text-slate-500">{t.label}</div>
              </GlassCard>
            ))}
          </div>

          {/* Said plainly, because "480 sites checked" is only trustworthy if
              the discarded ones are admitted to as well. */}
          {sweep && (
            <p className="px-1 text-[11px] text-slate-500">
              Site sweep: {sweep.checked} of {sweep.manifest} websites checked · {sweep.found} had this name
              {(sweep.excluded ?? 0) > 0 && <> · {sweep.excluded} skipped as unreliable</>}
              {sweep.unreliable > 0 && <> · {sweep.unreliable} dropped because that site says “yes” to any name</>}
              {sweep.timed_out > 0 && <> · {sweep.timed_out} did not reply in time</>}
            </p>
          )}

          {/* The platforms nobody could read. Previously these were folded into
              the collapsed "no account here" list, where "we were blocked" was
              indistinguishable from "there is no account" — the reason an
              officer concluded their own Instagram did not exist. */}
          {unreadable.length > 0 && (
            <GlassCard className="p-4">
              <SectionTitle title="Could not be checked"
                sub="These sites refused the check. It does NOT mean there is no account — open them to see for yourself." />
              <div className="grid gap-1.5 sm:grid-cols-2">
                {unreadable.map((r) => (
                  <a key={r.site} href={safeHref(r.url)} target="_blank" rel="noreferrer"
                    className="flex items-start justify-between gap-2 rounded-lg border border-amber-500/20 bg-amber-500/[0.05] px-3 py-2 hover:border-amber-500/40">
                    <div className="min-w-0">
                      <div className="text-[12px] font-medium text-slate-200">{r.site}</div>
                      <div className="text-[11px] leading-snug text-slate-400">
                        {typeof r.extra?.note === "string" && r.extra.note
                          ? r.extra.note
                          : "the site did not answer the check"}
                      </div>
                    </div>
                    <ExternalLink size={11} className="mt-0.5 shrink-0 text-amber-400" />
                  </a>
                ))}
              </div>
            </GlassCard>
          )}

          {profiles.length > 0 && (
            <GlassCard className="p-4">
              <SectionTitle title="Accounts we could open"
                sub={`${profiles.length} account${profiles.length === 1 ? "" : "s"} with a name, photo or bio we could read`} />
              <div className="grid gap-2.5 lg:grid-cols-2">
                {profiles.map((r) => <ProfileCard key={r.site} hit={r} />)}
              </div>
            </GlassCard>
          )}

          {bareHits.length > 0 && (
            <GlassCard className="p-4">
              <SectionTitle title="Other websites using this name"
                sub="The name is taken on these sites, but the page shows nothing about the person — open one to check it yourself" />
              <div className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
                {bareHits.map((r) => (
                  <a key={r.site} href={safeHref(r.url)} target="_blank" rel="noreferrer"
                    className="flex items-center justify-between gap-2 rounded-lg border border-emerald-500/20 bg-emerald-500/[0.05] px-3 py-2 hover:border-emerald-500/40">
                    <span className="truncate text-[12px] text-slate-200">{r.site}</span>
                    <ExternalLink size={11} className="shrink-0 text-emerald-400" />
                  </a>
                ))}
              </div>
            </GlassCard>
          )}

          {related.length > 0 && (
            <GlassCard className="p-4">
              <SectionTitle title="Looks like the same person"
                sub="Accounts under a different name that share this person's photo, name, bio or links — not just a similar spelling" />
              <div className="grid gap-2.5 lg:grid-cols-2">
                {related.map((a) => <RelatedCard key={`${a.site}:${a.handle}`} acct={a} />)}
              </div>
            </GlassCard>
          )}

          {similar && related.length === 0 && found.length > 0 && (
            <GlassCard className="p-3 text-center text-[12px] text-slate-500">
              Nothing found under a different name. Similar handles exist, but no photo, bio or link ties them to this person.
            </GlassCard>
          )}

          {otherMisses.length > 0 && (
            <GlassCard className="p-4">
              <button onClick={() => setShowMisses((s) => !s)}
                className="flex w-full items-center justify-between gap-2 text-left">
                <span className="text-sm font-semibold uppercase tracking-wider text-slate-400">
                  No account here · {otherMisses.length} sites
                </span>
                <ChevronDown size={16} className={`text-slate-500 transition-transform ${showMisses ? "rotate-180" : ""}`} />
              </button>
              {showMisses && (
                <div className="mt-3 grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
                  {otherMisses.map((r) => {
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
        <EmptyHint>Type a username above to find every account using that name.</EmptyHint>
      )}
    </div>
  );
}
