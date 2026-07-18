/** The ONLY place the frontend talks to the backend. Every page goes through
 *  these typed calls; swap VITE_API_BASE_URL to point anywhere. */

export const API_BASE =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ??
  "http://localhost:8000";

export const WS_URL = API_BASE.replace(/^http/, "ws") + "/ws/live";

// ── Types (mirror backend serializers exactly) ─────────────────────────

export interface Engagement {
  likes?: number;
  shares?: number;
  comments?: number;
  views?: number;
}

export interface Post {
  id: string;
  platform: string;
  author_handle: string;
  author_name: string;
  author_followers: number;
  author_verified: boolean;
  text: string;
  translation: string;
  language: string;
  code_mixed: boolean;
  sentiment_label: string;
  sentiment_score: number;
  threat_label: string;
  threat_confidence: number;
  threat_score: number;
  hashtags: string[];
  location: string;
  engagement: Engagement;
  is_amplified: boolean;
  cluster_id: string;
  llm_verification?: {
    model?: string;
    llm_threat_label?: string;
    llm_sentiment?: string;
    llm_confidence?: number;
    evidence?: string[];
    reason?: string;
    verdict?: "agrees" | "disagrees";
    overridden?: boolean;
  };
  evidence_report?: EvidenceReport;
  fact_check?: {
    checked?: boolean;
    query?: string;
    verdict?: "corroborated" | "partially corroborated" | "uncorroborated";
    note?: string;
    matches?: { title: string; source: string; link: string }[];
    checked_at?: string;
  };
  media_urls?: string[];
  url?: string;
  created_at: string;
  // full detail
  author_account_age_days?: number;
  intent?: string;
  class_probs?: Record<string, number>;
  hate_flags?: string[];
  toxicity_score?: number;
  keywords?: string[];
  latitude?: number;
  longitude?: number;
  true_label?: string;
  ingested_at?: string;
}

export interface EvidenceReport {
  generated_at?: string;
  model?: string;
  summary?: string;
  claims?: { claim: string; type: string; assessment: string; basis: string }[];
  evidence_phrases?: { quote: string; significance: string }[];
  corroboration?: {
    verdict?: string;
    explanation?: string;
    citations?: { source: string; title: string; link: string }[];
  };
  account_assessment?: string;
  risk_assessment?: string;
  recommended_action?: string;
  limitations?: string;
  confidence?: number;
}

export interface FeedPage {
  items: Post[];
  total: number;
  page: number;
  page_size: number;
}

export interface Kpis {
  posts_monitored: number;
  posts_monitored_delta: number;
  active_threats: number;
  active_threats_delta: number;
  critical_alerts: number;
  critical_alerts_delta: number;
  platforms_online: number;
  platforms_total: number;
  campaigns: number;
}

export interface Stats {
  kpis: Kpis;
  sparklines: { posts: number[]; threats: number[]; alerts: number[] };
  threat_distribution: Record<string, number>;
  sentiment_24h: { hour: string; positive: number; neutral: number; negative: number }[];
  platform_activity: { platform: string; posts: number; threats: number }[];
  platforms: { name: string; online: boolean }[];
  accuracy: { overall: number | null; per_class: Record<string, number>; sample: number };
  last_updated: string;
}

export interface TermStat {
  term: string;
  count: number;
  series: number[];
  change_pct: number;
  spike_z: number;
  spiking: boolean;
  top_label: string;
}

export interface Trends {
  window_hours: number;
  total_posts: number;
  hashtags: TermStat[];
  keywords: TermStat[];
  languages: { name: string; count: number; pct: number }[];
  regions: { name: string; count: number; avg_threat: number; threats: number; lat: number; lon: number }[];
}

export interface NetNode {
  id: string;
  label: string;
  influence: number;
  followers: number;
  threat: number;
  posts: number;
  platform: string;
  is_bot: boolean;
  cluster: string | null;
}

export interface NetLink {
  source: string;
  target: string;
  weight: number;
  kind: "coordination" | "hashtag";
}

export interface NetCluster {
  id: string;
  label: string;
  confidence: number;
  accounts: string[];
  posts: number;
  why: string[];
  sample_text: string;
  avg_threat: number;
}

export interface NetworkData {
  window_hours: number;
  nodes: NetNode[];
  links: NetLink[];
  clusters: NetCluster[];
}

export interface Alert {
  id: string;
  post_id: string;
  severity: "critical" | "high" | "medium";
  status: "new" | "acknowledged" | "escalated";
  title: string;
  summary: string;
  category: string;
  location: string;
  platform: string;
  threat_score: number;
  escalation: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  escalation_report_id?: string;
}

export interface Report {
  id: string;
  title: string;
  kind: string;
  period_hours: number;
  created_at: string;
  has_pdf: boolean;
  payload?: any;
}

export interface WatchItem {
  id: string;
  kind: "keyword" | "hashtag" | "account" | "location";
  value: string;
  note: string;
  active: boolean;
  created_at: string;
}

export interface FeedFilters {
  platform?: string;
  language?: string;
  threat_level?: string;
  location?: string;
  q?: string;
  min_score?: number;
  date_from?: string;
  date_to?: string;
  sort?: "recent" | "score" | "engagement";
  page?: number;
  page_size?: number;
}

// ── Investigation / OSINT toolkit ──────────────────────────────────────

export interface ImageFinding { level: string; text: string }
export interface ImageAnalysis {
  filename: string; size_bytes: number; sha256: string; media_type: string;
  format?: string; width?: number; height?: number; megapixels?: number; mode?: string;
  perceptual_hash?: string | null; average_hash?: string | null;
  camera?: string | null; captured_at?: string | null; software?: string | null;
  // video-specific (MP4 container forensics)
  codec?: string | null; duration_s?: number | null; bitrate_kbps?: number | null;
  modified_at?: string | null;
  exif?: Record<string, unknown>;
  gps?: { latitude: number; longitude: number; maps_url: string; altitude_m?: number } | null;
  manipulation: { integrity_score: number | null; findings: ImageFinding[] };
  forensics?: {
    faces_detected: number;
    face_matches: {
      bounding_box: { top: number; right: number; bottom: number; left: number };
      matched_suspect: string | null;
      confidence: number | null;
    }[];
  };
  note?: string; error?: string;
  resolved_from_index?: boolean; subject?: string;
}
export interface ImageSource {
  kind: string; via: string; post_url?: string; image_url?: string; note?: string;
  post?: { post_id: string; platform: string; author_handle: string; text: string; threat_label: string; url: string };
}
export interface PostImageReport {
  ok: boolean; error?: string; source?: ImageSource;
  analysis?: ImageAnalysis; thumbnail?: ImageAnalysis | null;
  reverse_image?: ReverseImage; person?: PersonFind;
  post?: { post_id: string; platform: string; author_handle: string; text: string; threat_label: string; url: string };
}
export interface Appearance {
  platform: string; handle: string; name: string; followers: number;
  verified: boolean; account_age_days: number; posted_at: string; kind: string;
  url: string; bot_score?: number; bot_verdict?: string;
}
export interface ReverseImage {
  matched: boolean; confidence?: number; hamming_distance?: number; query_hash?: string;
  match?: {
    id: string; subject: string; context: string; first_seen_hours_ago: number;
    total_appearances: number; platforms: string[]; platform_count: number;
    public_figures: Appearance[]; impersonators: Appearance[]; other_accounts: Appearance[];
  } | null;
  nearest_reference?: { subject: string; hamming_distance: number } | null;
  external_engines: { name: string; url: string }[];
  note?: string; reason?: string;
}
export interface PersonFind {
  identified: boolean; confidence?: number; subject?: string; is_public_figure?: boolean;
  public_figures?: Appearance[]; impersonators?: Appearance[]; other_accounts?: Appearance[];
  summary?: string; reason?: string; external_engines?: { name: string; url: string }[];
}
export interface ImageReport { analysis: ImageAnalysis; reverse_image: ReverseImage; person: PersonFind }

export interface UsernameHit { site: string; category: string; url: string; status: string; http: number | null }
export interface UsernameReport {
  username: string; valid: boolean; error?: string; results: UsernameHit[];
  summary: { found: number; not_found: number; blocked: number; unknown: number; checked: number };
}

export interface UrlFinding { level: string; text: string; on?: string }
export interface UrlReport {
  url: string; valid: boolean; error?: string; risk_score?: number; risk_level?: string;
  meta?: Record<string, unknown>;
  redirect?: { resolved: boolean; hops?: number; chain: { url: string; status: number }[]; final_url: string | null; reason?: string };
  findings?: UrlFinding[];
}

export interface AnalyzedComment {
  author_handle: string; author_name: string; text: string;
  sentiment_label: string; sentiment_score: number; duplicate_ratio: number;
  bot_score: number; bot_verdict: string; bot_signals: string[];
}
export interface CommentReport {
  source: string; synthetic?: boolean;
  post?: { post_id: string; platform: string; author_handle: string; text: string; threat_label: string };
  total_comments: number;
  sentiment_breakdown: { positive: number; neutral: number; negative: number; positive_pct: number; neutral_pct: number; negative_pct: number };
  bot_analysis: { likely_bots: number; suspicious: number; suspected_pct: number; bot_pct: number; coordinated: boolean };
  assessment: string[]; comments: AnalyzedComment[]; error?: string;
}

export interface PrCampaign {
  id: string; type: string; type_label: string; confidence: number;
  law_order_category: string; accounts: string[]; account_count: number; posts: number;
  bot_ratio: number; sentiment_lean: string; sentiment_uniformity: number;
  reach_estimate: number; top_hashtags: string[]; why: string[]; sample_text: string;
  locations: string[]; first_seen: string;
}
export interface PrReport { window_hours: number; campaigns_found: number; campaigns: PrCampaign[]; note: string }

export interface Dossier {
  handle: string; found: boolean; note?: string; error?: string;
  profile?: { author_name: string; followers: number; verified: boolean; account_age_days: number; primary_platform: string; platforms: string[]; languages: string[]; locations: string[] };
  activity?: { posts_tracked: number; posts_per_day: number; first_seen: string; last_seen: string; duplicate_ratio: number };
  threat_profile?: { avg_threat_score: number; max_threat_score: number; label_breakdown: Record<string, number>; non_neutral_posts: number };
  sentiment_lean?: Record<string, number>;
  authenticity: { score: number; verdict: string; signals: string[]; verified: boolean };
  coordination?: { in_cluster: boolean; cluster_ids: string[]; amplified_posts: number };
  notable_posts?: { platform: string; threat_label: string; threat_score: number; text: string; url: string; created_at: string }[];
  cross_platform?: UsernameReport;
}

// ── HTTP helpers ───────────────────────────────────────────────────────

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${path}`);
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

function qs(params: Record<string, unknown>): string {
  const entries = Object.entries(params).filter(
    ([, v]) => v !== undefined && v !== null && v !== "" && v !== 0
  );
  if (!entries.length) return "";
  return "?" + entries.map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join("&");
}

// ── API surface ────────────────────────────────────────────────────────

export const api = {
  health: () => http<{ status: string; nlp_mode: string; simulation: boolean }>("/api/health"),
  stats: () => http<Stats>("/api/stats"),
  feed: (f: FeedFilters = {}) => http<FeedPage>(`/api/feed${qs(f as Record<string, unknown>)}`),
  post: (id: string) => http<Post>(`/api/feed/${id}`),
  factCheckPost: (id: string) =>
    http<NonNullable<Post["fact_check"]>>(`/api/feed/${id}/fact-check`, { method: "POST" }),
  evidenceReport: (id: string) =>
    http<EvidenceReport>(`/api/feed/${id}/evidence-report`, { method: "POST" }),
  trends: (hours = 24) => http<Trends>(`/api/trends?hours=${hours}`),
  network: (hours = 24) => http<NetworkData>(`/api/network?hours=${hours}`),
  alerts: (params: { status?: string; severity?: string; limit?: number } = {}) =>
    http<Alert[]>(`/api/alerts${qs(params)}`),
  acknowledgeAlert: (id: string) => http<Alert>(`/api/alerts/${id}/acknowledge`, { method: "POST" }),
  escalateAlert: (id: string) => http<Alert>(`/api/alerts/${id}/escalate`, { method: "POST" }),
  reports: () => http<Report[]>("/api/reports"),
  report: (id: string) => http<Report>(`/api/reports/${id}`),
  generateReport: (body: { title?: string; period_hours?: number; kind?: string }) =>
    http<Report>("/api/reports/generate", { method: "POST", body: JSON.stringify(body) }),
  reportDownloadUrl: (id: string) => `${API_BASE}/api/reports/${id}/download`,
  watchlist: () => http<WatchItem[]>("/api/watchlist"),
  addWatch: (body: { kind: string; value: string; note?: string }) =>
    http<WatchItem>("/api/watchlist", { method: "POST", body: JSON.stringify(body) }),
  updateWatch: (id: string, body: Partial<Pick<WatchItem, "value" | "note" | "active">>) =>
    http<WatchItem>(`/api/watchlist/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteWatch: (id: string) => http<void>(`/api/watchlist/${id}`, { method: "DELETE" }),

  // ── investigation / OSINT toolkit ──────────────────────────────────────
  investigateImage: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch(`${API_BASE}/api/investigate/image`, { method: "POST", body: fd })
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json() as Promise<ImageReport>;
      });
  },
  investigateImageFromUrl: (url: string) =>
    http<PostImageReport>("/api/investigate/image-from-url", { method: "POST", body: JSON.stringify({ url }) }),
  investigatePostMedia: (postId: string) =>
    http<PostImageReport>(`/api/investigate/post-media/${encodeURIComponent(postId)}`),
  investigateUsername: (u: string) =>
    http<UsernameReport>(`/api/investigate/username?u=${encodeURIComponent(u)}`),
  investigateUrl: (url: string, resolve = true) =>
    http<UrlReport>("/api/investigate/url", { method: "POST", body: JSON.stringify({ url, resolve }) }),
  investigatePostComments: (postId: string) =>
    http<CommentReport>(`/api/investigate/comments/${encodeURIComponent(postId)}`),
  investigateComments: (comments: { author_handle: string; text: string; followers?: number; account_age_days?: number }[]) =>
    http<CommentReport>("/api/investigate/comments", { method: "POST", body: JSON.stringify({ comments }) }),
  investigatePrCampaigns: (hours = 72) => http<PrReport>(`/api/investigate/pr-campaigns?hours=${hours}`),
  investigateSleuth: (handle: string, lookup = true) =>
    http<Dossier>(`/api/investigate/sleuth?handle=${encodeURIComponent(handle)}&lookup=${lookup}`),
};
