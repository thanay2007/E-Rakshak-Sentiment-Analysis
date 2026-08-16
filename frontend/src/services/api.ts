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
  /** The post's only tag: "positive" | "negative" | "neutral". */
  sentiment_label: string;
  /** -1 (most negative) .. +1 (most positive). */
  sentiment_score: number;
  sentiment_confidence: number;
  sentiment_consensus?: SentimentConsensus;
  /** 0-100 — how much analyst attention the post warrants (ml/score.py). */
  concern_score: number;
  hashtags: string[];
  location: string;
  engagement: Engagement;
  is_amplified: boolean;
  cluster_id: string;
  llm_verification?: {
    model?: string;
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
    sources?: string[];
    attempted?: string[];
    matches?: { title: string; source: string; link: string; api?: string; description?: string; published?: string }[];
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

export interface EmergingItem {
  post_id: string;
  platform: string;
  author_handle: string;
  author_name: string;
  author_followers: number;
  author_verified: boolean;
  text: string;
  sentiment_label: string;
  concern_score: number;
  /** Triage rank, 0-100. How alarming the claim is, whether it carries rumour
   *  phrasing, and how much it is being passed on — NOT a spread measure. */
  priority_score: number;
  /** informational | opinion | call_to_action | rumor */
  intent: string;
  source_count: number;
  url: string;
  location: string;
  language: string;
  fact_check_verdict: string;
  reasons: string[];
  created_at: string;
}
export interface EmergingData {
  window_hours: number;
  /** Items on this page. */
  count: number;
  /** Items matching the filters across the whole window — what paging walks. */
  total: number;
  /** Posts the detector actually read, so an empty list is not ambiguous. */
  scanned: number;
  /** Why the rest were filtered out — makes a short queue legible. */
  dropped: Partial<Record<"established" | "not_a_claim" | "low_concern" | "corroborated", number>>;
  platforms: string[];
  locations: string[];
  items: EmergingItem[];
}
export interface EmergingFilters {
  hours?: number; limit?: number; offset?: number;
  platform?: string; location?: string; sentiment?: string; min_priority?: number;
}

export interface ModelVote {
  model: string;
  label: string;
  confidence: number;
  probs?: Record<string, number>;
  /** Lexicon model only: the matched terms and the rules that modified each. */
  evidence?: { term: string; polarity: string; valence: number; rules?: string[] }[];
}

/** A bounded, reasoned adjustment to the ensemble's confidence — never the label. */
export interface ContextAdjustment {
  factor: string;
  delta: number;
  reason: string;
}

/** One contribution to the 0-100 concern score. */
export interface ScorePart {
  factor: string;
  weight: number;
  input: number;
  points: number;
  detail: string;
}

/** One named source behind the verdict: a model, the account metadata, a news API. */
export interface EvidenceSource {
  source: string;
  kind: "model" | "llm" | "context" | "metadata" | "score" | "news" | string;
  detail?: string;
  verdict?: string;
  items?: string[];
  links?: { title: string; link: string; source: string }[];
}

export interface GroqCheck {
  label?: string;
  confidence?: number;
  agrees?: boolean;
  reason?: string;
  quotes?: string[];
  model?: string;
  overrode?: boolean;
}

export interface SentimentConsensus {
  label?: string;
  score?: number;
  confidence?: number;
  chosen_by?: string;
  agreement?: string;
  votes?: ModelVote[];
  context_adjustments?: ContextAdjustment[];
  score_breakdown?: ScorePart[];
  evidence?: EvidenceSource[];
  groq_check?: GroqCheck;
  groq_sentiment?: string;
  groq_agrees?: boolean;
}

export interface ModelCard {
  id: string;
  name: string;
  family: string;
  base_model?: string;
  approach: string;
  training_data?: { train_rows?: number; test_rows?: number; sources?: string };
  accuracy?: { accuracy?: number; macro_f1?: number };
  per_language?: Record<string, { n: number; accuracy: number; macro_f1: number }>;
  epochs?: number;
  live?: boolean;
  strength?: string;
  context_version?: string;
  context_aware?: boolean;
}
export interface ModelsInfo {
  ensemble: {
    task: string;
    labels: string[];
    decision_rule: string;
    context?: { version: string; textual: string; metadata: string };
    models: ModelCard[];
  };
  final_check: { layer: string; role: string; enabled: boolean };
  pipeline_eval?: {
    accuracy?: number; macro_f1?: number; samples?: number;
    per_class?: Record<string, { precision: number; recall: number; f1: number; support: number }>;
  };
  scoring: { name: string; range: string; formula: string; note: string };
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
  /** Alerts raised in the last 24h. */
  alert_posts: number;
  alert_posts_delta: number;
  /** Critical alerts still sitting in "new" — the subset nobody has touched. */
  critical_alerts_open: number;
  /** Coordinated inauthentic messaging clusters in the last 48h. */
  fake_pr_campaigns: number;
  /** Single-source, uncorroborated claims in the 24h triage queue. */
  unverified_rumours: number;
  platforms_online: number;
  platforms_total: number;
}

export interface Stats {
  kpis: Kpis;
  sparklines: { posts: number[]; threats: number[]; alerts: number[] };
  sentiment_distribution: Record<string, number>;
  sentiment_24h: { hour: string; positive: number; neutral: number; negative: number }[];
  platform_activity: { platform: string; posts: number; threats: number }[];
  // `adapter` names the route actually in use for that platform — e.g. "X" for
  // the official API vs "X (twikit)" for the session-cookie fallback.
  // `detail` is why an offline platform is offline, in words an operator can
  // act on ("session cookie rejected …"). Empty for a platform that was simply
  // never configured — that one needs credentials, not troubleshooting.
  platforms: { name: string; online: boolean; adapter?: string; detail?: string }[];
  accuracy: { overall: number | null; per_class: Record<string, number>; sample: number };
  last_updated: string;
}

export interface TermStat {
  term: string;
  kind: "hashtag" | "keyword";
  count: number;
  series: number[];
  change_pct: number;
  spike_z: number;
  spiking: boolean;
  top_label: string;
  sentiment_mix: Record<string, number>;
  negative_share: number;
}

export interface SentimentBucket {
  label: string; positive: number; neutral: number; negative: number;
  total: number; avg_concern: number;
}

export interface Trends {
  window_hours: number;
  total_posts: number;
  avg_concern: number;
  hashtags: TermStat[];
  keywords: TermStat[];
  languages: { name: string; count: number; pct: number }[];
  regions: { name: string; count: number; avg_concern: number; threats: number; lat: number; lon: number }[];
  platforms: { name: string; count: number; negative: number; positive: number; avg_concern: number }[];
  sentiment_series: SentimentBucket[];
  sentiment_totals: { positive: number; neutral: number; negative: number };
}

/** A spiking negative term not yet watched — offered to the analyst, never auto-added. */
export interface WatchSuggestion {
  kind: "keyword" | "hashtag";
  value: string; count: number; spike_z: number;
  change_pct: number; negative_share: number; reason: string;
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
  /** The post `sample_text` was taken from — opens the full record. */
  sample_post_id?: string;
  avg_concern: number;
}

export interface NetworkData {
  window_hours: number;
  platform?: string;
  platform_counts?: Record<string, number>;
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
  concern_score: number;
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
  has_xlsx: boolean;
  payload?: any;
}

export interface WatchItem {
  id: string;
  kind: "keyword" | "hashtag" | "account" | "location";
  value: string;
  note: string;
  priority: "low" | "medium" | "high" | "critical";
  category: string;
  active: boolean;
  created_at: string;
  hits_7d: number;
  last_hit: string | null;
  top_threat: number;
}

export interface WatchPreset { slug: string; title: string; description: string; count: number }

export interface SystemStatus {
  uptime_seconds: number;
  nlp_mode: string;
  simulation: boolean;
  ingest_interval_seconds: number;
  scheduler_running: boolean;
  database: {
    url: string; size_mb: number | null;
    counts: { posts: number; alerts: number; reports: number; watchlist: number };
    oldest_post: string | null; newest_post: string | null; untranslated_posts: number;
  };
  llm: {
    enabled: boolean;
    models: { model: string; role: string; state: string; cooldown_seconds_left: number; last_ok: string | null; last_error: string | null }[];
  };
  news?: {
    sources: {
      name: string;
      configured: boolean;
      keyless: boolean;
      used_today: number | null;
      daily_budget: number | null;
      note: string;
    }[];
  };
}

export interface FeedFilters {
  platform?: string;
  language?: string;
  sentiment?: string;
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

// ── Facial identification ──────────────────────────────────────────────

export interface FaceQuality {
  score: number; band: "good" | "fair" | "poor"; face_px: number;
  sharpness: number; brightness: number; yaw: number | null; roll: number | null;
  issues: string[]; usable_for_matching: boolean;
}
export interface SuspectCandidate {
  suspect_id: string; full_name: string; record_type: string; risk_level: string;
  status: string; photo_thumb: string; distance: number; confidence: number;
  band: "confirmed" | "probable" | "possible" | "no_match";
  matched_template?: string; template_source?: string;
}
export interface FaceIdentity {
  identified: boolean; searched?: boolean; ambiguous?: boolean;
  match?: SuspectCandidate | null; candidates: SuspectCandidate[];
  registry_size?: number; templates_searched?: number; reason?: string;
  /** The reference-gallery search for the same face, run alongside the
   *  registry one and kept separate: a name is not a record. */
  known_person?: KnownPerson;
}
/** A hit in the reference gallery (the `pics/` folder, stored in the database).
 *  This says who is in the photo — nothing about records, charges or risk. */
export interface KnownPersonCandidate {
  name: string; distance: number; confidence: number; band: string;
  matched_photo: string; thumb: string; reference_photos: number;
}
export interface KnownPerson {
  identified: boolean; searched: boolean; ambiguous?: boolean;
  match?: KnownPersonCandidate | null; candidates: KnownPersonCandidate[];
  people?: number; photos?: number; reason?: string;
}
export interface FaceMatch {
  index: number;
  bounding_box: { top: number; right: number; bottom: number; left: number };
  area_ratio: number;
  quality: FaceQuality;
  matched_suspect: string | null;
  /** Name from the reference gallery, when it recognised this face. */
  known_person?: string | null;
  confidence: number | null;
  identity?: FaceIdentity;
}
export interface FaceForensics {
  available: boolean; engine?: string; reason?: string | null; note?: string | null;
  faces_detected: number; truncated?: boolean;
  detection_passes?: { pass: string; found: number; scale?: number; error?: string }[];
  face_matches: FaceMatch[];
}

export interface Charge { section: string; description: string; status: string; date: string }
export interface SocialHandle { platform: string; handle: string; url: string; note: string }
export interface FaceTemplate {
  id: string; quality: FaceQuality; source: string; thumb: string; added_at: string;
}
export interface Suspect {
  id: string; full_name: string; aliases: string[];
  record_type: string; risk_level: string; status: string;
  case_ids: string[]; charges: Charge[]; convictions: number;
  jurisdiction: string; last_known_location: string; wanted_since: string;
  gender: string; age: number; height_cm: number; occupation: string;
  nationality: string; identifying_marks: string;
  notes: string; social_handles: SocialHandle[];
  photo_thumb: string; source: string; active: boolean;
  enrolled_faces: number; face_templates: FaceTemplate[];
  created_at: string; updated_at: string;
}
export interface DossierAccount extends SocialHandle {
  in_corpus?: boolean; not_expanded?: boolean; error?: string;
  profile?: { author_name?: string; followers?: number; verified?: boolean; platforms?: string[]; languages?: string[]; locations?: string[] };
  activity?: { posts_tracked?: number; posts_per_day?: number; first_seen?: string; last_seen?: string; duplicate_ratio?: number };
  threat_profile?: { avg_concern_score?: number; max_concern_score?: number; label_breakdown?: Record<string, number>; negative_posts?: number };
  authenticity?: { score?: number; verdict?: string; signals?: { text: string; level?: string }[] };
  coordination?: { in_cluster?: boolean; cluster_ids?: string[]; amplified_posts?: number };
  notable_posts?: { id?: string; platform: string; sentiment_label: string; concern_score: number; text: string; url: string; created_at: string }[];
  cross_platform?: UsernameReport;
}
export interface DossierPost {
  id: string; platform: string; author_handle: string; text: string;
  original_text: string; language: string; sentiment_label: string;
  concern_score: number; location: string; engagement: Record<string, number>;
  media_urls: string[]; is_amplified: boolean; cluster_id: string; url: string;
  created_at: string;
}
export interface IdentityDossier {
  suspect: Suspect; summary: string; error?: string;
  social_footprint: { handles_known: number; handles_expanded: number; deep_lookup: boolean; accounts: DossierAccount[] };
  monitored_posts: { total: number; returned: number; items: DossierPost[] };
  threat_summary: {
    posts: number; avg_concern_score?: number; max_concern_score?: number;
    label_breakdown?: Record<string, number>; sentiment_breakdown?: Record<string, number>;
    negative_posts?: number; platforms?: string[]; locations?: string[];
    amplified_posts?: number; clusters?: string[]; first_seen?: string; last_seen?: string;
  };
  linked_alerts: { id: string; post_id: string; severity: string; status: string; title: string; summary: string; category: string; location: string; platform: string; concern_score: number; created_at: string }[];
  timeline: { kind: "charge" | "post" | "alert"; at: string; title: string; detail: string; status: string; ref?: string }[];
}
export interface GalleryStats {
  directory: string; exists: boolean; people: number; photos: number;
  stored_in?: string;
  last_scan?: { scanned: number; enrolled: number };
  skipped?: { file: string; person?: string; reason: string }[];
  error?: string;
}
export interface Identification {
  faces_detected: number; identified: number; candidates: number;
  /** People the reference gallery could name, whether or not they are on record. */
  known_people?: number; known_names?: string[];
  identities: Record<string, IdentityDossier>;
  registry: { active_records: number; enrolled_records: number; templates: number };
  gallery?: GalleryStats;
  summary: string; from_video_frame?: boolean;
}
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
  forensics?: FaceForensics;
  note?: string; error?: string;
  resolved_from_index?: boolean; subject?: string;
}
export interface ImageSource {
  kind: string; via: string; post_url?: string; image_url?: string; note?: string;
  post?: { post_id: string; platform: string; author_handle: string; text: string; sentiment_label: string; url: string };
}
export interface PostImageReport {
  ok: boolean; error?: string; source?: ImageSource;
  analysis?: ImageAnalysis; thumbnail?: ImageAnalysis | null;
  reverse_image?: ReverseImage; person?: PersonFind;
  identification?: Identification;
  post?: { post_id: string; platform: string; author_handle: string; text: string; sentiment_label: string; url: string };
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
export interface ImageReport {
  analysis: ImageAnalysis; reverse_image: ReverseImage; person: PersonFind;
  identification?: Identification;
}

/** What Google Lens actually returned, rather than a link to go and ask it.
 *  `ok: false` is a normal outcome (Chrome missing, or Google serving its
 *  anti-automation check) and `reason` says which — the manual engine links
 *  stay on screen either way. */
export interface LensMatch { title: string; url: string; domain: string }
export interface LensSearch {
  ok: boolean;
  engine?: string;
  matches?: LensMatch[];
  match_count?: number;
  domains?: string[];
  results_url?: string;
  took_seconds?: number;
  cached?: boolean;
  challenged?: boolean;
  reason?: string;
}

/** One platform's answer. `source` says whether the profile was *read* from an
 *  API or merely inferred from a URL probe — the two are not equally trustworthy
 *  and the UI labels them differently. */
export interface UsernameHit {
  site: string; category: string; url: string; status: string; http: number | null;
  /** How the finding was obtained, weakest claim last:
   *  "api"      — the platform's own profile endpoint answered
   *  "preview"  — Meta's public link-preview card (Instagram / Threads / Facebook)
   *  "mirror"   — X's profile data relayed by a third party
   *  "sherlock" — the ~480-site sweep, using that site's own "no such user"
   *               signature and re-tested against a handle nobody owns
   *  "probe"    — a plain page fetch, the weakest of the five */
  source: "api" | "preview" | "mirror" | "sherlock" | "probe";
  handle: string; display_name: string; bio: string; avatar: string;
  followers: number | null; created_at: string; verified: boolean;
  location: string; link: string;
  extra: Record<string, unknown>;
  match?: { confidence: number; why: string[] };
}
/** An account under a different handle that the evidence ties to the same person. */
export interface RelatedAccount {
  site: string; handle: string; url: string; display_name: string; bio: string;
  avatar: string; followers: number | null;
  confidence: number; verdict: "strong_link" | "possible_link" | "weak"; why: string[];
  discovered_by: "variant" | "search";
}
export interface UsernameReport {
  username: string; valid: boolean; error?: string; results: UsernameHit[];
  summary: {
    found: number; not_found: number; blocked: number; unknown: number;
    checked: number; via_api: number; via_sweep?: number;
    /** The site sweep's own tally. `unreliable` is sites that answered the same
     *  for an invented handle, so their hit was discarded rather than shown. */
    sherlock?: { checked: number; found: number; manifest: number; skipped: number; timed_out: number; unreliable: number; excluded?: number };
  };
  related?: RelatedAccount[];
  identity?: {
    display_name: string; display_names: string[]; locations: string[]; links: string[];
    verified_on: string[]; total_reach: number; avatar: string; bio: string;
  };
  coverage?: Record<string, string>;
}

export interface PrCampaign {
  id: string; type: string; type_label: string; confidence: number;
  law_order_category: string; accounts: string[];
  /** Independent actors — one organisation's several handles count once. */
  account_count: number;
  handle_count?: number;
  /** Accounts in the cluster that ARE established public voices, listed so the
   *  officer can see who was discounted from the roster and why. */
  established_accounts?: string[];
  posts: number;
  bot_ratio: number; suspicious_ratio?: number;
  sentiment_lean: string; sentiment_uniformity: number;
  reach_estimate: number; top_hashtags: string[]; why: string[]; sample_text: string;
  locations: string[]; first_seen: string;
  last_seen: string; spread_minutes: number; avg_concern: number; platforms: string[];
  sample_posts: { id: string; platform: string; author_handle: string; text: string; concern_score: number; created_at: string }[];
}
/** LLM commentary on a report. `available: false` is normal — no key, rate
 *  limits, or a report shape with no explainer — and `reason` says which. */
export interface ExplainResult {
  available: boolean;
  explanation?: string;
  model?: string;
  reason?: string;
}

/** A duplicate-copy cluster that is NOT a campaign — official desks or verified
 *  accounts carrying the same notice. Shown so the officer can see the detector
 *  considered it and why it was set aside, rather than wondering what happened
 *  to a cluster they can see in the feed. */
export interface PrSyndication {
  id: string; accounts: string[]; actors: number; posts: number;
  platforms: string[]; sentiment_lean: string; sample_text: string;
  first_seen: string; why: string;
}
export interface PrReport {
  window_hours: number; campaigns_found: number; campaigns: PrCampaign[]; note: string;
  posts_scanned: number; clusters_found: number; neutral_clusters_ignored: number; min_accounts: number;
  syndication_ignored?: number; syndication?: PrSyndication[];
  weak_clusters_ignored?: number; min_confidence?: number;
}

// ── Administration ─────────────────────────────────────────────────────

/** An officer account as the server is willing to describe it. Note what is
 *  absent: password_hash and token_version never leave the backend. */
export interface Officer {
  id: string;
  username: string;
  full_name: string;
  badge_number: string;
  unit: string;
  role: "analyst" | "supervisor" | "admin";
  active: boolean;
  must_change_password: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface AuditEntry {
  id: string;
  action: string;
  target_id: string;
  actor_id: string;
  actor_username: string;
  actor_role: string;
  actor_badge: string;
  ip: string;
  user_agent: string;
  details: Record<string, unknown>;
  created_at: string;
}

export interface PostureCheck {
  key: string;
  ok: boolean;
  severity: "critical" | "high" | "medium" | "info";
  title: string;
  detail: string;
}

export interface SecurityPosture {
  checks: PostureCheck[];
  failing: number;
  accounts: {
    total: number;
    active: number;
    admins: number;
    pending_password_change: string[];
    locked_out: string[];
  };
}

export interface NewOfficer {
  username: string;
  password: string;
  full_name?: string;
  badge_number?: string;
  unit?: string;
  role?: string;
}

// ── Sentinel voice assistant ───────────────────────────────────────────

/** One tool the assistant ran to build its answer. Names and arguments only —
 *  results arrive separately in `data`, keyed by the same tool name. */
export interface AssistantStep {
  tool: string;
  arguments: Record<string, unknown>;
}

export interface AssistantAnswer {
  intent: string;
  /** Shown in the panel. */
  reply: string;
  /** Read aloud — deliberately separate from `reply`, which may carry detail
   *  that is fine on screen but tedious in audio. */
  speech: string;
  /** In-app path the answer wants to open. Only ever set by the backend's
   *  `navigate` tool resolving a fixed label against a fixed table — never
   *  parsed out of model prose. See services/assistant/agent.py. */
  navigate: string | null;
  /** Per-tool results for the panel to render. Richer than what the model was
   *  shown: post wording lives here, and is displayed rather than spoken. */
  data: Record<string, unknown>;
  source: "rules" | "agent" | "refusal" | "unknown";
  trace: AssistantStep[];
  model: string | null;
}

export interface AssistantCapabilities {
  enabled: boolean;
  name: string;
  wake_words: string[];
  read_only: boolean;
  /** The caller's rank. The tool list below is already filtered by it. */
  role: string;
  agent_enabled: boolean;
  sql_enabled: boolean;
  capabilities: { intent: string; description: string }[];
  tools: { name: string; description: string }[];
  knowledge_topics: { id: string; title: string }[];
  refuses: string[];
  cities: string[];
  examples: string[];
}

/** The read-only views the SQL window exposes, served so the limits are
 *  inspectable without reading the source. */
export interface AssistantSchema {
  enabled: boolean;
  available: boolean;
  views: string[];
  schema: string;
  limits: Record<string, string | number>;
}

/** Shape of a `run_sql` result inside `AssistantAnswer.data`. */
/** Shape of a `top_posts` result inside `AssistantAnswer.data`. */
// ── HTTP helpers ───────────────────────────────────────────────────────

/** Raised on 401 so callers can distinguish "signed out" from a real failure. */
export class UnauthorizedError extends Error {
  constructor(message = "Your session has ended. Please sign in again.") {
    super(message);
    this.name = "UnauthorizedError";
  }
}

/** Called when the server rejects our token — wired up in AuthProvider to
 *  clear the session and bounce to the sign-in screen. Kept as a hook rather
 *  than importing the router here, so this module stays free of React. */
let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

function authHeaders(extra?: HeadersInit): HeadersInit {
  const token = sessionStorage.getItem("sentinel.token");
  return { ...(extra || {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) };
}

async function describeError(res: Response, path: string): Promise<string> {
  // FastAPI returns {"detail": "..."} — surface that instead of a bare status,
  // so the analyst sees "Rate limit reached for this tool" rather than "429".
  try {
    const body = await res.json();
    if (body?.detail) return String(body.detail);
  } catch {
    /* non-JSON body */
  }
  return `${res.status} ${res.statusText} — ${path}`;
}

/** How long any single call may hang before it is called a failure.
 *
 *  `fetch` has no timeout of its own, and the gap that matters is not a dead
 *  server — a refused connection fails in milliseconds. It is a server that has
 *  *bound the port but is not serving yet*: this API loads ~2.5 GB of models
 *  during startup, so for a minute after launch every request connects
 *  successfully and then waits forever. The UI has no way to tell that from a
 *  slow answer, so it sits on "checking…" indefinitely and looks broken.
 *
 *  Generous, because the assistant legitimately takes several seconds when the
 *  model has tools to call — this is a backstop against hanging, not a latency
 *  budget. */
const REQUEST_TIMEOUT_MS = 90_000;

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const timeout = AbortSignal.timeout(REQUEST_TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: timeout,
      headers: authHeaders({ "Content-Type": "application/json", ...(init?.headers || {}) }),
    });
  } catch (err) {
    // A timeout and an unreachable server are the same thing to the officer —
    // nothing came back — but only one of them says so on its own.
    if (err instanceof DOMException && err.name === "TimeoutError") {
      throw new Error("The server didn't answer in time. It may still be starting up.");
    }
    throw err;
  }
  if (res.status === 401) {
    onUnauthorized();
    throw new UnauthorizedError(await describeError(res, path));
  }
  if (!res.ok) throw new Error(await describeError(res, path));
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

/** Upload helper for multipart bodies.
 *  Content-Type is deliberately NOT set — the browser has to generate it
 *  itself to include the multipart boundary. */
async function upload<T>(path: string, fd: FormData): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    body: fd,
    headers: authHeaders(),
  });
  if (res.status === 401) {
    onUnauthorized();
    throw new UnauthorizedError(await describeError(res, path));
  }
  if (!res.ok) throw new Error(await describeError(res, path));
  return res.json() as Promise<T>;
}

/** Authenticated file download.
 *
 *  A plain <a href> cannot carry an Authorization header, so protected exports
 *  and PDFs are fetched with the token, turned into a blob and handed to a
 *  synthetic link. The alternative — putting a token in the query string —
 *  would write the credential into server logs and browser history.
 */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, { headers: authHeaders() });
  if (res.status === 401) {
    onUnauthorized();
    throw new UnauthorizedError();
  }
  if (!res.ok) throw new Error(await describeError(res, path));
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
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
  // Public liveness probe. nlp_mode/simulation moved to /api/admin/system —
  // an unauthenticated endpoint should not describe the deployment.
  health: () => http<{ status: string }>("/api/health"),
  stats: () => http<Stats>("/api/stats"),
  models: () => http<ModelsInfo>("/api/models"),
  emerging: (f: EmergingFilters = {}) =>
    http<EmergingData>(`/api/emerging${qs({ hours: 24, ...f } as Record<string, unknown>)}`),
  feed: (f: FeedFilters = {}) => http<FeedPage>(`/api/feed${qs(f as Record<string, unknown>)}`),
  post: (id: string) => http<Post>(`/api/feed/${id}`),
  factCheckPost: (id: string) =>
    http<NonNullable<Post["fact_check"]>>(`/api/feed/${id}/fact-check`, { method: "POST" }),
  translatePost: (id: string) =>
    http<{ translation: string; cached: boolean }>(`/api/feed/${id}/translate`, { method: "POST" }),
  evidenceReport: (id: string) =>
    http<EvidenceReport>(`/api/feed/${id}/evidence-report`, { method: "POST" }),
  trends: (hours = 24) => http<Trends>(`/api/trends?hours=${hours}`),
  network: (hours = 24, platform = "") =>
    http<NetworkData>(`/api/network?hours=${hours}${platform ? `&platform=${encodeURIComponent(platform)}` : ""}`),
  alerts: (params: { status?: string; severity?: string; limit?: number } = {}) =>
    http<Alert[]>(`/api/alerts${qs(params)}`),
  acknowledgeAlert: (id: string) => http<Alert>(`/api/alerts/${id}/acknowledge`, { method: "POST" }),
  escalateAlert: (id: string) => http<Alert>(`/api/alerts/${id}/escalate`, { method: "POST" }),
  reports: () => http<Report[]>("/api/reports"),
  report: (id: string) => http<Report>(`/api/reports/${id}`),
  generateReport: (body: { title?: string; period_hours?: number; kind?: string }) =>
    http<Report>("/api/reports/generate", { method: "POST", body: JSON.stringify(body) }),
  downloadReport: (id: string) =>
    downloadFile(`/api/reports/${id}/download`, `SENTINEL_report_${id}.pdf`),
  downloadReportXlsx: (id: string) =>
    downloadFile(`/api/reports/${id}/download.xlsx`, `SENTINEL_report_${id}.xlsx`),
  watchlist: () => http<WatchItem[]>("/api/watchlist"),
  addWatch: (body: { kind: string; value: string; note?: string; priority?: string; category?: string }) =>
    http<WatchItem>("/api/watchlist", { method: "POST", body: JSON.stringify(body) }),
  bulkAddWatch: (items: { kind: string; value: string; note?: string; priority?: string }[]) =>
    http<{ added: number; skipped: number }>("/api/watchlist/bulk", { method: "POST", body: JSON.stringify({ items }) }),
  watchPresets: () => http<WatchPreset[]>("/api/watchlist/presets"),
  watchSuggestions: (hours = 24) =>
    http<WatchSuggestion[]>(`/api/watchlist/suggestions?hours=${hours}`),
  applyWatchPreset: (slug: string) =>
    http<{ pack: string; added: number; skipped: number }>(`/api/watchlist/presets/${slug}`, { method: "POST" }),
  downloadWatchlist: () => downloadFile("/api/watchlist/export", "watchlist.csv"),
  updateWatch: (id: string, body: Partial<Pick<WatchItem, "value" | "note" | "active" | "priority" | "category">>) =>
    http<WatchItem>(`/api/watchlist/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteWatch: (id: string) => http<void>(`/api/watchlist/${id}`, { method: "DELETE" }),

  // ── admin / operations toolkit ─────────────────────────────────────────
  systemStatus: () => http<SystemStatus>("/api/admin/system"),
  testLlm: () => http<{ ok: boolean; model?: string; latency_ms?: number; error?: string }>("/api/admin/test-llm", { method: "POST" }),
  crawlNow: () => http<{ ok: boolean; new_posts: number }>("/api/admin/crawl-now", { method: "POST" }),
  translateMissing: (limit = 40) =>
    http<{ translated: number; remaining_candidates: number }>(`/api/admin/translate-missing?limit=${limit}`, { method: "POST" }),
  relabelLanguages: () => http<{ relabeled: number }>("/api/admin/relabel-languages", { method: "POST" }),
  purgePosts: (days: number) => http<{ deleted: number }>(`/api/admin/purge?days=${days}`, { method: "POST" }),
  downloadPostsCsv: (hours: number) =>
    downloadFile(`/api/admin/export/posts.csv?hours=${hours}`, `posts_last_${hours}h.csv`),
  retrainBaseline: () => http<{ started: boolean }>("/api/admin/retrain-baseline", { method: "POST" }),
  retrainStatus: () =>
    http<{ state: "idle" | "running" | "done" | "failed"; elapsed_seconds?: number; exit_code?: number }>("/api/admin/retrain-baseline/status"),
  /** Post media, relayed by the backend so no platform CDN sees the analyst.
   *  Returns the raw Blob — the caller turns it into an object URL. */
  media: async (url: string): Promise<Blob> => {
    const res = await fetch(`${API_BASE}/api/media?url=${encodeURIComponent(url)}`, {
      headers: authHeaders(),
    });
    if (res.status === 401) {
      onUnauthorized();
      throw new UnauthorizedError("Session expired");
    }
    if (!res.ok) throw new Error(await describeError(res, "/api/media"));
    return res.blob();
  },
  reanalysePosts: () => http<{ started: boolean }>("/api/admin/reanalyse", { method: "POST" }),
  reanalyseStatus: () =>
    http<{
      state: "idle" | "running" | "done" | "failed";
      elapsed_seconds: number | null;
      remaining: number;
      total: number;
      done: number;
    }>("/api/admin/reanalyse/status"),

  // ── officer administration (admin only, enforced server-side) ──────────
  officers: () => http<Officer[]>("/api/auth/users"),
  createOfficer: (body: NewOfficer) =>
    http<Officer>("/api/auth/users", { method: "POST", body: JSON.stringify(body) }),
  updateOfficer: (id: string, body: Partial<Pick<Officer, "full_name" | "badge_number" | "unit" | "role" | "active">>) =>
    http<Officer>(`/api/auth/users/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  resetOfficerPassword: (id: string, newPassword: string) =>
    http<{ ok: boolean }>(`/api/auth/users/${id}/reset-password`, {
      method: "POST",
      body: JSON.stringify({ new_password: newPassword }),
    }),
  deactivateOfficer: (id: string) => http<void>(`/api/auth/users/${id}`, { method: "DELETE" }),
  auditLog: (params: { limit?: number; action?: string; actor?: string } = {}) =>
    http<AuditEntry[]>(`/api/auth/audit${qs(params)}`),
  securityPosture: () => http<SecurityPosture>("/api/auth/security-posture"),

  // ── Sentinel voice assistant ───────────────────────────────────────────
  assistantCapabilities: () => http<AssistantCapabilities>("/api/assistant/capabilities"),
  assistantSchema: () => http<AssistantSchema>("/api/assistant/schema"),
  ask: (query: string, page = "") =>
    http<AssistantAnswer>("/api/assistant/ask", {
      method: "POST",
      body: JSON.stringify({ query, page }),
    }),

  // ── investigation / OSINT toolkit ──────────────────────────────────────
  investigateImage: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return upload<ImageReport>("/api/investigate/image", fd);
  },
  investigateImageFromUrl: (url: string) =>
    http<PostImageReport>("/api/investigate/image-from-url", { method: "POST", body: JSON.stringify({ url }) }),
  /** Runs Google Lens server-side and returns the pages it found. Slow by
   *  nature (a real browser drives a real search, ~15s), so the tool fires it
   *  alongside the forensics rather than waiting for it. */
  reverseImageSearch: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return upload<LensSearch>("/api/investigate/reverse-image", fd);
  },
  reverseImageSearchUrl: (url: string) =>
    http<LensSearch>("/api/investigate/reverse-image-url", { method: "POST", body: JSON.stringify({ url }) }),
  investigatePostMedia: (postId: string) =>
    http<PostImageReport>(`/api/investigate/post-media/${encodeURIComponent(postId)}`),
  /** `deep` runs the ~480-site sweep as well as the platform APIs. It is the
   *  slower half of the lookup (roughly 20s), which is why it is switchable. */
  investigateUsername: (u: string, similar = true, deep = true) =>
    http<UsernameReport>(`/api/investigate/username?u=${encodeURIComponent(u)}&similar=${similar}&deep=${deep}`),
  /** Model commentary on a report already on screen. The report is posted back
   *  rather than recomputed, so the explanation describes what the officer is
   *  actually looking at. */
  investigateExplain: (tool: "image" | "username" | "pr", report: unknown) =>
    http<ExplainResult>("/api/investigate/explain", {
      method: "POST", body: JSON.stringify({ tool, report }),
    }),
  investigatePrCampaigns: (hours = 72, minAccounts = 3) =>
    http<PrReport>(`/api/investigate/pr-campaigns?hours=${hours}&min_accounts=${minAccounts}`),
};
