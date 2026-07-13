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
    reason?: string;
    verdict?: "agrees" | "disagrees";
    overridden?: boolean;
  };
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
  url?: string;
  true_label?: string;
  ingested_at?: string;
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
};
