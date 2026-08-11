import { ChevronRight, MapPin, Repeat2, ThumbsUp } from "lucide-react";
import type { Post } from "../services/api";
import { BotChip, LanguageChip, PlatformIcon, SentimentBadge } from "./Badges";
import { PostMediaGrid } from "./PostMedia";

export function timeAgo(iso: string): string {
  const s = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
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
  const critical = post.concern_score >= 65;
  const isHigh = post.concern_score >= 45 && post.concern_score < 65;

  return (
    <button
      onClick={() => onOpen?.(post)}
      className={`reveal-item glass glass-hover group block w-full cursor-pointer rounded-2xl border p-3.5 text-left transition-all duration-200 hover:-translate-y-0.5 ${
        critical
          ? "border-threat-critical/40 bg-threat-critical/[0.04] shadow-[0_0_24px_-8px_rgba(220,38,38,0.3)]"
          : isHigh
          ? "border-threat-inflammatory/30 bg-threat-inflammatory/[0.02]"
          : "border-white/[0.08]"
      }`}
    >
      <div className="flex items-start gap-3">
        <PlatformIcon platform={post.platform} size={26} />
        <div className="min-w-0 flex-1">
          {/* Header Row */}
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="truncate text-xs font-bold text-slate-100">
              {post.author_name || post.author_handle}
            </span>
            <span className="truncate font-mono text-[11px] text-slate-400">
              @{post.author_handle}
            </span>
            <span className="font-mono text-[10.5px] text-slate-400">
              · {timeAgo(post.created_at)}
            </span>
            <div className="ml-auto flex items-center gap-1.5">
              {post.is_amplified && <BotChip />}
              <SentimentBadge label={post.sentiment_label} score={post.concern_score} />
            </div>
          </div>

          {/* Post Text */}
          <p className={`mt-1.5 text-xs leading-relaxed text-slate-200 ${compact ? "line-clamp-2" : ""}`}>
            {post.text}
          </p>

          {/* AI Translation Callout */}
          {post.translation && post.translation !== post.text && (
            <div className="mt-2 rounded-xl border border-accent/20 bg-accent/[0.05] px-2.5 py-1.5 text-[11.5px] text-slate-200">
              <span className="mr-1.5 font-bold uppercase tracking-wider text-accent text-[9.5px]">
                AI Translation:
              </span>
              <span className="italic">{post.translation}</span>
            </div>
          )}

          {/* Attachments — relayed through /api/media, never loaded from the
              platform CDN, so opening the feed does not tell those platforms
              which accounts this console watches. */}
          {!compact && (post.media_urls?.length ?? 0) > 0 && (
            <div className="mt-2">
              <PostMediaGrid urls={post.media_urls!} maxHeight={120} />
            </div>
          )}

          {/* Metadata & Tag Row */}
          <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2 border-t border-white/[0.06] pt-2 text-[11px] text-slate-300">
            <div className="flex flex-wrap items-center gap-1.5">
              <LanguageChip language={post.language} mixed={post.code_mixed} />
              {post.location && (
                <span className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/[0.04] px-1.5 py-0.2 text-[10.5px] text-slate-300">
                  <MapPin size={10} className="text-threat-inflammatory" /> {post.location}
                </span>
              )}
            </div>

            <div className="flex items-center gap-2.5 font-mono text-[10.5px] text-slate-300">
              <span className="inline-flex items-center gap-1" title="Likes">
                <ThumbsUp size={10} className="text-slate-400" /> {post.engagement.likes?.toLocaleString() ?? 0}
              </span>
              <span className="inline-flex items-center gap-1" title="Shares / Reposts">
                <Repeat2 size={10} className="text-slate-400" /> {post.engagement.shares?.toLocaleString() ?? 0}
              </span>
              {post.hashtags.length > 0 && (
                <div className="hidden items-center gap-1 sm:flex">
                  {post.hashtags.slice(0, 2).map((h) => (
                    <span key={h} className="text-accent font-medium">
                      #{h}
                    </span>
                  ))}
                </div>
              )}
              <span className="flex items-center gap-0.5 text-xs font-semibold text-accent group-hover:translate-x-0.5 transition-transform">
                Inspect <ChevronRight size={12} />
              </span>
            </div>
          </div>
        </div>
      </div>
    </button>
  );
}

