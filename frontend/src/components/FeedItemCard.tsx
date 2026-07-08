import { MapPin, Radio, Repeat2, ThumbsUp } from "lucide-react";
import type { Post } from "../services/api";
import { SENTIMENT_COLORS } from "../data/constants";
import { BotChip, LanguageChip, PlatformIcon, ThreatBadge } from "./Badges";

export function timeAgo(iso: string): string {
  const s = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

export default function FeedItemCard({
  post,
  onOpen,
  compact = false,
}: {
  post: Post;
  onOpen?: (p: Post) => void;
  compact?: boolean;
}) {
  const critical = post.threat_score >= 65;
  return (
    <button
      onClick={() => onOpen?.(post)}
      className={`reveal-item glass glass-hover block w-full cursor-pointer p-3.5 text-left transition-transform duration-200 hover:-translate-y-0.5 ${
        critical ? "border-threat-critical/30 glow-critical" : ""
      }`}
    >
      <div className="flex items-start gap-3">
        <PlatformIcon platform={post.platform} size={26} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="truncate text-[13px] font-semibold text-slate-200">
              {post.author_name || post.author_handle}
            </span>
            <span className="truncate font-mono text-[11px] text-slate-500">
              @{post.author_handle}
            </span>
            <span className="font-mono text-[10px] text-slate-600">{timeAgo(post.created_at)}</span>
            <span className="ml-auto flex items-center gap-1.5">
              {post.is_amplified && <BotChip />}
              <ThreatBadge label={post.threat_label} score={post.threat_score} />
            </span>
          </div>

          <p className={`mt-1.5 text-[13px] leading-relaxed text-slate-300 ${compact ? "line-clamp-2" : ""}`}>
            {post.text}
          </p>
          {post.translation && post.translation !== post.text && (
            <p className="mt-1 line-clamp-1 text-[11.5px] italic text-slate-500">
              ⇢ {post.translation}
            </p>
          )}

          <div className="mt-2 flex flex-wrap items-center gap-2 text-[10.5px] text-slate-500">
            <LanguageChip language={post.language} mixed={post.code_mixed} />
            <span
              className="inline-flex items-center gap-1 font-mono"
              style={{ color: SENTIMENT_COLORS[post.sentiment_label] }}
            >
              <Radio size={10} />
              {post.sentiment_label} {post.sentiment_score > 0 ? "+" : ""}
              {post.sentiment_score.toFixed(2)}
            </span>
            {post.location && (
              <span className="inline-flex items-center gap-1">
                <MapPin size={10} /> {post.location}
              </span>
            )}
            <span className="inline-flex items-center gap-1 font-mono">
              <ThumbsUp size={10} /> {post.engagement.likes ?? 0}
            </span>
            <span className="inline-flex items-center gap-1 font-mono">
              <Repeat2 size={10} /> {post.engagement.shares ?? 0}
            </span>
            {post.hashtags.slice(0, 3).map((h) => (
              <span key={h} className="text-accent/80">
                #{h}
              </span>
            ))}
          </div>
        </div>
      </div>
    </button>
  );
}
