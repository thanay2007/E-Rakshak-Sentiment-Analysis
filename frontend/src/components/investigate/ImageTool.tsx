import { useEffect, useMemo, useRef, useState } from "react";
import {
  Camera, ExternalLink, Fingerprint, ImageUp, Link2, MapPin, Radar, ScanSearch,
  ShieldCheck, Upload, Users,
} from "lucide-react";
import GlassCard, { SectionTitle } from "../GlassCard";
import { api } from "../../services/api";
import type { Appearance, ImageAnalysis, ImageSource, Identification, MediaPost, PersonFind, ReverseImage } from "../../services/api";
import PostMedia from "../PostMedia";
import { AccountChip, EmptyHint, FindingRow, KV, Meter, Pill, RunButton, Spinner, TextInput } from "./shared";
import { safeHref } from "../../lib/safeUrl";
import IdentifiedPersonsPanel, { buildFaceOutcomes } from "./PersonIdentification";
import PersonDatabase from "./PersonDatabase";

type Mode = "upload" | "url" | "feed";
/** A post link or a post ID, as opposed to search words. */
const LOOKS_LIKE_REF = /^https?:\/\/|^[0-9a-f-]{20,}$/i;
interface Result {
  analysis: ImageAnalysis; reverse_image: ReverseImage; person: PersonFind;
  source?: ImageSource; preview?: string | null; thumbnail?: ImageAnalysis | null;
  identification?: Identification;
}

function fmtDuration(s?: number | null): string {
  if (!s && s !== 0) return "?";
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.round(s % 60)).padStart(2, "0")} min`;
}

function Bucket({ title, icon, accounts, tone }: {
  title: string; icon: React.ReactNode; accounts: Appearance[]; tone: string;
}) {
  if (!accounts.length) return null;
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-[12px] font-semibold uppercase tracking-wide" style={{ color: tone }}>
        {icon} {title} <span className="text-slate-500">({accounts.length})</span>
      </div>
      <div className="grid gap-1.5 sm:grid-cols-2">
        {accounts.map((a) => (
          <AccountChip key={a.platform + a.handle} handle={a.handle} name={`${a.platform} · ${a.name}`}
            followers={a.followers} verified={a.verified} botScore={a.bot_score} botVerdict={a.bot_verdict} url={a.url} />
        ))}
      </div>
    </div>
  );
}

export default function ImageTool() {
  const [mode, setMode] = useState<Mode>("upload");
  const [url, setUrl] = useState("");
  const [postId, setPostId] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [picker, setPicker] = useState<MediaPost[] | null>(null);
  const [pickerErr, setPickerErr] = useState<string | null>(null);

  function reset() { setErr(null); setResult(null); }

  /** Recent feed posts with real media, filtered by the search box. */
  async function loadPicker(q = "") {
    setPickerErr(null);
    try { setPicker(await api.mediaPosts(q)); }
    catch (e) { setPickerErr((e as Error).message); setPicker([]); }
  }
  useEffect(() => { if (mode === "feed" && picker === null) void loadPicker(); }, [mode]); // eslint-disable-line react-hooks/exhaustive-deps

  /** The platform image, fetched through /api/media so the CDN never sees
   *  the officer's browser (same rule as the feed's own media). */
  async function proxiedPreview(src?: ImageSource, a?: ImageAnalysis): Promise<string | null> {
    if (!src?.image_url || a?.media_type === "video") return null;
    try { return URL.createObjectURL(await api.media(src.image_url)); }
    catch { return null; }
  }

  async function fromFile(file: File) {
    reset(); setLoading(true);
    const preview = URL.createObjectURL(file);
    try {
      const r = await api.investigateImage(file);
      setResult({ ...r, preview });
    } catch (e) { setErr((e as Error).message); }
    finally { setLoading(false); }
  }

  async function fromUrl() {
    if (!url.trim()) return;
    reset(); setLoading(true);
    try {
      const r = await api.investigateImageFromUrl(url.trim());
      if (!r.ok || !r.analysis) { setErr(r.error || "Could not resolve media from that URL."); }
      else setResult({ analysis: r.analysis, reverse_image: r.reverse_image!, person: r.person!, source: r.source, preview: await proxiedPreview(r.source, r.analysis), thumbnail: r.thumbnail, identification: r.identification });
    } catch (e) { setErr((e as Error).message); }
    finally { setLoading(false); }
  }

  /** `ref` is a post ID or post URL; blank takes the most concerning recent
   *  post that has media. */
  async function fromFeed(ref?: string) {
    reset(); setLoading(true);
    try {
      const r = await api.investigatePostMedia((ref ?? postId).trim() || "top");
      if (!r.ok || !r.analysis) { setErr(r.error || "That post has no attached media."); }
      else setResult({ analysis: r.analysis, reverse_image: r.reverse_image!, person: r.person!, source: r.source, preview: await proxiedPreview(r.source, r.analysis), thumbnail: r.thumbnail, identification: r.identification });
    } catch (e) { setErr((e as Error).message); }
    finally { setLoading(false); }
  }

  const a = result?.analysis;
  const rev = result?.reverse_image;
  const person = result?.person;
  const src = result?.source;
  const faceMatches = a?.forensics?.face_matches;
  const identification = result?.identification;
  // Every face gets exactly what the real registry search found for it — a
  // confirmed match, a below-threshold lead, or an honest "not identified".
  // Nothing here is invented: a blurry or unenrolled face must never render
  // as a specific named person.
  const faceOutcomes = useMemo(() => buildFaceOutcomes(faceMatches, identification), [faceMatches, identification]);

  const MODES: { id: Mode; label: string; icon: typeof Upload }[] = [
    { id: "upload", label: "Upload", icon: Upload },
    { id: "url", label: "From post URL", icon: Link2 },
    { id: "feed", label: "From live feed", icon: Radar },
  ];

  return (
    <div className="space-y-4">
      <GlassCard className="p-4">
        <SectionTitle title="Image & Video Check"
          sub="Upload an image or video, pull it straight from a post URL, or grab a flagged post from the live feed — then trace where else it appears." />

        <div className="mb-3 flex gap-1.5">
          {MODES.map(({ id, label, icon: Icon }) => (
            <button key={id} onClick={() => { setMode(id); reset(); }}
              className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[12px] font-medium transition-all ${
                mode === id ? "border-accent/30 bg-accent/10 text-accent" : "border-white/[0.07] text-slate-400 hover:text-slate-200"}`}>
              <Icon size={13} /> {label}
            </button>
          ))}
        </div>

        {mode === "upload" && (
          <div
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files?.[0]; if (f) fromFile(f); }}
            className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-white/[0.1] bg-white/[0.02] py-8 text-center transition-colors hover:border-accent/40"
          >
            <ImageUp size={26} className="text-slate-500" />
            <div className="text-sm text-slate-400">Drop an image or video here or <span className="text-accent">browse</span></div>
            <div className="text-[13px] text-slate-600">JPG / PNG / WEBP · MP4 / MOV — Check file details, editing, and image sources · max 25 MB</div>
            <input ref={inputRef} type="file" accept="image/*,video/*" className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) fromFile(f); }} />
          </div>
        )}

        {mode === "url" && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <div className="flex-1"><TextInput value={url} onChange={setUrl} onEnter={fromUrl}
                placeholder="Paste a post, image or video URL (X / Reddit / news / direct .jpg / .mp4 / v.redd.it)" mono /></div>
              <RunButton onClick={fromUrl} disabled={loading || !url.trim()}><ScanSearch size={15} /> Fetch & analyze</RunButton>
            </div>
            <p className="text-[13px] text-slate-600">The system reads the post's media — og:image preview, og:video stream, direct image/video links, or v.redd.it renditions. Login-gated posts can't be fetched.</p>
          </div>
        )}

        {mode === "feed" && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <div className="min-w-[220px] flex-1"><TextInput value={postId} onChange={setPostId}
                onEnter={() => (LOOKS_LIKE_REF.test(postId.trim()) ? fromFeed() : loadPicker(postId.trim()))}
                placeholder="Search by handle, words or city — or paste a post link / ID" /></div>
              <RunButton onClick={() => (LOOKS_LIKE_REF.test(postId.trim()) ? fromFeed() : loadPicker(postId.trim()))} disabled={loading}><ScanSearch size={15} /> Search</RunButton>
              <RunButton onClick={() => fromFeed("top")} disabled={loading}><Radar size={15} /> Most concerning</RunButton>
            </div>
            {pickerErr && <p className="text-[13px] text-red-400">{pickerErr}</p>}
            {picker === null ? <Spinner label="Loading recent posts with media…" /> : picker.length === 0 ? (
              <EmptyHint>No recent feed posts with media{postId.trim() ? " match that search" : ""}.</EmptyHint>
            ) : (
              <div className="grid max-h-[420px] gap-2 overflow-y-auto pr-1 sm:grid-cols-2 xl:grid-cols-3">
                {picker.map((p) => (
                  <button key={p.post_id} onClick={() => fromFeed(p.post_id)} disabled={loading}
                    className="flex gap-3 rounded-xl border border-white/[0.07] bg-white/[0.02] p-2 text-left transition-colors hover:border-accent/40 disabled:opacity-50">
                    <PostMedia url={p.media_url} maxHeight={72} className="w-[72px] shrink-0 overflow-hidden" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5 text-[12px]">
                        <span className="font-semibold text-slate-300">{p.platform}</span>
                        <span className="truncate font-mono text-slate-500">@{p.author_handle}</span>
                      </div>
                      <div className="mt-0.5 line-clamp-2 text-[12px] leading-snug text-slate-400">{p.text || "(no caption)"}</div>
                      <div className="mt-1 text-[11px] text-slate-600">
                        concern {p.concern_score}{p.location ? ` · ${p.location}` : ""}{p.media_count > 1 ? ` · ${p.media_count} media` : ""}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}
            <p className="text-[13px] text-slate-600">Pick a monitored post — its attached image or video is downloaded and analyzed. Only real attachments are used.</p>
          </div>
        )}

        {result?.preview && (
          <div className="mt-3 flex items-center gap-3">
            <img src={result.preview} alt="post media" className="h-16 w-16 rounded-lg border border-white/10 object-cover" />
            <span className="truncate text-xs text-slate-500">{a?.filename}</span>
          </div>
        )}
      </GlassCard>

      <PersonDatabase />

      {src && (
        <GlassCard className="flex flex-wrap items-center gap-2 p-3 text-[12px] text-slate-400">
          <Radar size={14} className="text-accent" />
          {src.post ? (
            <span>Pulled from <b className="text-slate-200">{src.post.platform}</b> post by <span className="font-mono">@{src.post.author_handle}</span> · {src.post.sentiment_label}</span>
          ) : (
            <span>Fetched from post URL</span>
          )}
          <span className="rounded bg-white/[0.06] px-1.5 py-0.5 text-xs uppercase tracking-wide text-slate-500">via {src.via}</span>
          {src.image_url && <a href={safeHref(src.image_url)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">source image <ExternalLink size={11} /></a>}
        </GlassCard>
      )}

      {loading && <GlassCard className="p-2"><Spinner label="Extracting metadata & matching sources…" /></GlassCard>}
      {err && <GlassCard className="p-4 text-sm text-red-400">Error: {err}</GlassCard>}

      {a && !loading && (
        <>
        <div className="grid gap-4 lg:grid-cols-2">
          {/* ── forensics ─────────────────────────────────── */}
          <GlassCard className="space-y-3 p-4">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-200"><Fingerprint size={15} className="text-accent" /> Metadata & Fingerprint</div>
            {a.resolved_from_index ? (
              <>
                <KV k="Subject" v={a.subject} />
                <KV k="pHash" v={a.perceptual_hash} />
                <div className="space-y-1.5">
                  {a.manipulation.findings.map((f, i) => <FindingRow key={i} level={f.level} text={f.text} />)}
                </div>
              </>
            ) : a.media_type === "video" ? (
              <>
                <div>
                  <KV k="Format" v={`${a.format} · ${a.codec || "?"}`} />
                  {a.width && a.height && <KV k="Resolution" v={`${a.width}×${a.height}`} />}
                  <KV k="Duration" v={fmtDuration(a.duration_s)} />
                  {a.bitrate_kbps && <KV k="Bitrate" v={`${a.bitrate_kbps} kbps`} />}
                  <KV k="Size" v={`${(a.size_bytes / (1024 * 1024)).toFixed(2)} MB`} />
                  {a.captured_at && <KV k="Captured" v={a.captured_at} />}
                  {a.modified_at && <KV k="Modified" v={a.modified_at} />}
                  <KV k="SHA-256" v={<span title={a.sha256}>{a.sha256?.slice(0, 16)}…</span>} />
                </div>
                {a.manipulation.integrity_score !== null && (
                  <Meter value={a.manipulation.integrity_score}
                    color={a.manipulation.integrity_score >= 70 ? "#10B981" : a.manipulation.integrity_score >= 40 ? "#F59E0B" : "#EF4444"}
                    label="Metadata integrity" />
                )}
                <div className="space-y-1.5">
                  {a.manipulation.findings.map((f, i) => <FindingRow key={i} level={f.level} text={f.text} />)}
                </div>
              </>
            ) : a.media_type !== "image" ? (
              <EmptyHint>{a.note || a.error || "Non-image media."}</EmptyHint>
            ) : (
              <>
                <div>
                  <KV k="Dimensions" v={`${a.width}×${a.height} (${a.megapixels} MP)`} />
                  <KV k="Format" v={`${a.format} · ${a.mode}`} />
                  <KV k="Size" v={`${(a.size_bytes / 1024).toFixed(1)} KB`} />
                  {a.camera && <KV k="Camera" v={<span className="inline-flex items-center gap-1"><Camera size={12} />{a.camera}</span>} />}
                  {a.captured_at && <KV k="Captured" v={a.captured_at} />}
                  {a.software && <KV k="Software" v={a.software} />}
                  <KV k="pHash" v={a.perceptual_hash} />
                  <KV k="SHA-256" v={<span title={a.sha256}>{a.sha256?.slice(0, 16)}…</span>} />
                </div>
                {a.forensics && a.forensics.faces_detected > 0 && (
                  <div className="mt-4 space-y-2 rounded-lg border border-accent/20 bg-accent/[0.02] p-3">
                    <div className="flex items-center gap-2 text-[13px] font-semibold text-slate-200">
                      <ScanSearch size={14} className="text-accent" /> Facial Recognition
                    </div>
                    <div className="text-[12px] text-slate-400">
                      Detected {a.forensics.faces_detected} face{a.forensics.faces_detected > 1 ? 's' : ''}.
                    </div>
                    {result?.preview && a.width && a.height && (
                      <div className="relative mt-2 overflow-hidden rounded border border-white/10" style={{ maxWidth: '300px' }}>
                        <img src={result.preview} alt="analyzed" className="w-full h-auto block" />
                        {a.forensics.face_matches.map((f, i) => {
                          const topPct = (f.bounding_box.top / a.height!) * 100;
                          const leftPct = (f.bounding_box.left / a.width!) * 100;
                          const widthPct = ((f.bounding_box.right - f.bounding_box.left) / a.width!) * 100;
                          const heightPct = ((f.bounding_box.bottom - f.bounding_box.top) / a.height!) * 100;
                          const outcome = faceOutcomes[i];
                          const label = outcome?.kind === "confirmed" ? outcome.identity.name
                            : outcome?.kind === "lead" ? `${outcome.name}?`
                            : "Not identified";
                          const color = outcome?.kind === "confirmed" ? "#14B8C4"
                            : outcome?.kind === "lead" ? "#F59E0B" : "#64748B";
                          return (
                            <div key={i} className="absolute border-2" style={{ borderColor: color, backgroundColor: `${color}33`, top: `${topPct}%`, left: `${leftPct}%`, width: `${widthPct}%`, height: `${heightPct}%` }}>
                              <div className="absolute -top-5 left-[-2px] whitespace-nowrap px-1 text-[13px] font-bold text-[#0F1420]" style={{ backgroundColor: color }}>
                                {label}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}
                {a.gps && (
                  <a href={safeHref(a.gps.maps_url)} target="_blank" rel="noreferrer"
                    className="flex items-center gap-2 rounded-lg border border-accent/20 bg-accent/[0.06] px-3 py-2 text-[13px] text-accent hover:bg-accent/10">
                    <MapPin size={14} /> GPS: {a.gps.latitude}, {a.gps.longitude} <ExternalLink size={12} className="ml-auto" />
                  </a>
                )}
                {a.manipulation.integrity_score !== null && (
                  <Meter value={a.manipulation.integrity_score}
                    color={a.manipulation.integrity_score >= 70 ? "#10B981" : a.manipulation.integrity_score >= 40 ? "#F59E0B" : "#EF4444"}
                    label="Metadata integrity" />
                )}
                <div className="space-y-1.5">
                  {a.manipulation.findings.map((f, i) => <FindingRow key={i} level={f.level} text={f.text} />)}
                </div>
              </>
            )}
          </GlassCard>

          {/* ── reverse image / person ────────────────────── */}
          <GlassCard className="space-y-3 p-4">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-200"><ScanSearch size={15} className="text-accent" /> Reverse-Source Trace</div>
            {a.media_type === "video" && (
              <p className="rounded-lg border border-white/[0.07] bg-white/[0.02] px-3 py-2 text-[13px] text-slate-500">
                Video traced by its poster frame (thumbnail). The frame is fingerprinted and matched
                the same way as an image — the strongest signal for recycled/miscaptioned clips.
              </p>
            )}
            {rev?.matched && rev.match ? (
              <>
                <div className="rounded-lg border border-white/[0.07] bg-white/[0.02] p-3">
                  <div className="text-[13px] font-medium text-slate-200">{rev.match.subject}</div>
                  <div className="mt-1 text-[12px] text-slate-400">{rev.match.context}</div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <Pill color="#14B8C4">{(rev.confidence! * 100).toFixed(0)}% match</Pill>
                    <Pill color="#64748B">{rev.match.total_appearances} appearances</Pill>
                    <Pill color="#64748B">{rev.match.platform_count} platforms</Pill>
                    <Pill color="#64748B">first seen {rev.match.first_seen_hours_ago}h ago</Pill>
                  </div>
                </div>

                {person?.identified && (
                  <div className="rounded-lg border border-white/[0.07] p-3 text-[13px] text-slate-300">
                    <div className="flex items-center gap-2 font-semibold text-slate-200">
                      <Users size={14} className="text-accent" /> People finder
                    </div>
                    <p className="mt-1 text-slate-400">{person.summary}</p>
                  </div>
                )}

                <Bucket title="Verified / public figures" tone="#10B981"
                  icon={<ShieldCheck size={13} />} accounts={rev.match.public_figures} />
                <Bucket title="⚠ Suspected impersonators" tone="#EF4444"
                  icon={<Users size={13} />} accounts={rev.match.impersonators} />
                <Bucket title="Re-posters / amplifiers" tone="#F59E0B"
                  icon={<Users size={13} />} accounts={rev.match.other_accounts} />
              </>
            ) : (
              <div className="space-y-3">
                <EmptyHint>{rev?.note || "No confident match in the monitored index."}</EmptyHint>
                {rev?.nearest_reference && (
                  <div className="text-[12px] text-slate-500">Nearest reference: {rev.nearest_reference.subject} (distance {rev.nearest_reference.hamming_distance})</div>
                )}
                <div>
                  <div className="mb-1.5 text-[13px] uppercase tracking-wide text-slate-500">Continue on external engines</div>
                  <div className="flex flex-wrap gap-2">
                    {rev?.external_engines.map((e) => (
                      <a key={e.name} href={safeHref(e.url)} target="_blank" rel="noreferrer"
                        className="inline-flex items-center gap-1 rounded-lg border border-white/10 px-2.5 py-1.5 text-[12px] text-slate-300 hover:border-accent/40 hover:text-accent">
                        {e.name} <ExternalLink size={11} />
                      </a>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </GlassCard>
        </div>

        {faceOutcomes.length > 0 && (
          <IdentifiedPersonsPanel
            outcomes={faceOutcomes}
            boxes={a.forensics?.face_matches.map((f) => f.bounding_box)}
            mediaW={a.width}
            mediaH={a.height}
            previewSrc={a.media_type === "image" ? result?.preview : null}
          />
        )}
        </>
      )}
    </div>
  );
}
