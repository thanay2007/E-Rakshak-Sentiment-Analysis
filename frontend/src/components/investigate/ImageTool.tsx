import { useRef, useState } from "react";
import {
  Camera, ExternalLink, Fingerprint, ImageUp, Link2, MapPin, Radar, ScanSearch,
  ShieldCheck, Upload, Users,
} from "lucide-react";
import GlassCard, { SectionTitle } from "../GlassCard";
import { api } from "../../services/api";
import type { Appearance, ImageAnalysis, ImageSource, PersonFind, ReverseImage } from "../../services/api";
import { AccountChip, EmptyHint, FindingRow, KV, Meter, Pill, RunButton, Spinner, TextInput } from "./shared";

type Mode = "upload" | "url" | "feed";
interface Result {
  analysis: ImageAnalysis; reverse_image: ReverseImage; person: PersonFind;
  source?: ImageSource; preview?: string | null; thumbnail?: ImageAnalysis | null;
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

  function reset() { setErr(null); setResult(null); }

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
      else setResult({ analysis: r.analysis, reverse_image: r.reverse_image!, person: r.person!, source: r.source, preview: r.analysis.media_type === "video" ? null : r.source?.image_url, thumbnail: r.thumbnail });
    } catch (e) { setErr((e as Error).message); }
    finally { setLoading(false); }
  }

  async function fromFeed() {
    reset(); setLoading(true);
    try {
      const r = await api.investigatePostMedia(postId.trim() || "top");
      if (!r.ok || !r.analysis) { setErr(r.error || "That post has no attached media."); }
      else setResult({ analysis: r.analysis, reverse_image: r.reverse_image!, person: r.person!, source: r.source, preview: r.analysis.media_type === "video" ? null : r.source?.image_url, thumbnail: r.thumbnail });
    } catch (e) { setErr((e as Error).message); }
    finally { setLoading(false); }
  }

  const a = result?.analysis;
  const rev = result?.reverse_image;
  const person = result?.person;
  const src = result?.source;

  const MODES: { id: Mode; label: string; icon: typeof Upload }[] = [
    { id: "upload", label: "Upload", icon: Upload },
    { id: "url", label: "From post URL", icon: Link2 },
    { id: "feed", label: "From live feed", icon: Radar },
  ];

  return (
    <div className="space-y-4">
      <GlassCard className="p-4">
        <SectionTitle title="Image & Video Forensics"
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
            <div className="text-[11px] text-slate-600">JPG / PNG / WEBP · MP4 / MOV — EXIF & container forensics + reverse-source tracing · max 25 MB</div>
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
            <p className="text-[11px] text-slate-600">The system reads the post's media — og:image preview, og:video stream, direct image/video links, or v.redd.it renditions. Login-gated posts can't be fetched.</p>
          </div>
        )}

        {mode === "feed" && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <div className="flex-1"><TextInput value={postId} onChange={setPostId} onEnter={fromFeed}
                placeholder="Post ID (blank = latest flagged post carrying media)" mono /></div>
              <RunButton onClick={fromFeed} disabled={loading}><Radar size={15} /> Pull from feed</RunButton>
            </div>
            <p className="text-[11px] text-slate-600">Takes the image attached to a monitored post automatically and traces its sources.</p>
          </div>
        )}

        {result?.preview && (
          <div className="mt-3 flex items-center gap-3">
            <img src={result.preview} alt="post media" className="h-16 w-16 rounded-lg border border-white/10 object-cover" />
            <span className="truncate text-xs text-slate-500">{a?.filename}</span>
          </div>
        )}
      </GlassCard>

      {src && (
        <GlassCard className="flex flex-wrap items-center gap-2 p-3 text-[12px] text-slate-400">
          <Radar size={14} className="text-accent" />
          {src.post ? (
            <span>Pulled from <b className="text-slate-200">{src.post.platform}</b> post by <span className="font-mono">@{src.post.author_handle}</span> · {src.post.threat_label}</span>
          ) : (
            <span>Fetched from post URL</span>
          )}
          <span className="rounded bg-white/[0.06] px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-slate-500">via {src.via}</span>
          {src.image_url && <a href={src.image_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">source image <ExternalLink size={11} /></a>}
        </GlassCard>
      )}

      {loading && <GlassCard className="p-2"><Spinner label="Extracting metadata & matching sources…" /></GlassCard>}
      {err && <GlassCard className="p-4 text-sm text-red-400">Error: {err}</GlassCard>}

      {a && !loading && (
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
                          return (
                            <div key={i} className="absolute border-2 border-[#14B8C4] bg-[#14B8C4]/20"
                              style={{ top: `${topPct}%`, left: `${leftPct}%`, width: `${widthPct}%`, height: `${heightPct}%` }}>
                              <div className="absolute -top-5 left-[-2px] whitespace-nowrap bg-[#14B8C4] px-1 text-[9px] font-bold text-[#0F1420]">
                                {f.matched_suspect || `Unknown #${i+1}`}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}
                {a.gps && (
                  <a href={a.gps.maps_url} target="_blank" rel="noreferrer"
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
              <p className="rounded-lg border border-white/[0.07] bg-white/[0.02] px-3 py-2 text-[11px] text-slate-500">
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
                  <div className="mb-1.5 text-[11px] uppercase tracking-wide text-slate-500">Continue on external engines</div>
                  <div className="flex flex-wrap gap-2">
                    {rev?.external_engines.map((e) => (
                      <a key={e.name} href={e.url} target="_blank" rel="noreferrer"
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
      )}
    </div>
  );
}
