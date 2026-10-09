import { AnimatePresence, motion } from "framer-motion";
import {
  Activity,
  Cpu,
  Flame,
  HelpCircle,
  Keyboard,
  Network,
  Radio,
  ShieldAlert,
  Sparkles,
  X,
} from "lucide-react";
import { useState } from "react";
import { createPortal } from "react-dom";

interface Props {
  open: boolean;
  onClose: () => void;
}

type Tab = "overview" | "sentiment" | "spikes" | "nlp" | "osint" | "shortcuts";

export default function IntelGuideModal({ open, onClose }: Props) {
  const [tab, setTab] = useState<Tab>("overview");

  if (!open) return null;

  return createPortal(
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        {/* Backdrop */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
          className="fixed inset-0 bg-black/70 backdrop-blur-md"
        />

        {/* Modal Window */}
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: 16 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 16 }}
          transition={{ type: "spring", damping: 25, stiffness: 300 }}
          className="relative z-10 flex h-[85vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-white/10 bg-base-900/95 shadow-2xl backdrop-blur-2xl"
          role="dialog"
          aria-label="User Guide"
        >
          {/* Header */}
          <div className="flex items-center justify-between border-b border-white/[0.08] px-6 py-4">
            <div className="flex items-center gap-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl border border-accent/40 bg-accent/10 text-accent">
                <HelpCircle size={18} />
              </span>
              <div>
                <h2 className="text-base font-bold tracking-wide text-slate-100">
                  SENTINEL · User Guide
                </h2>
                <p className="text-xs text-slate-400">
                  How to review posts, understand scores, and use investigation tools
                </p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="rounded-xl border border-white/10 p-2 text-slate-400 hover:bg-white/[0.06] hover:text-slate-200"
              aria-label="Close guide"
            >
              <X size={18} />
            </button>
          </div>

          {/* Navigation Tabs */}
          <div className="flex flex-wrap gap-1 border-b border-white/[0.06] bg-base-800/50 px-6 py-2.5">
            {[
              { id: "overview", label: "Quick Start", icon: Activity },
              { id: "sentiment", label: "Post Tone & Concern Score", icon: ShieldAlert },
              { id: "spikes", label: "Sudden Increases", icon: Flame },
              { id: "nlp", label: "Language Support", icon: Cpu },
              { id: "osint", label: "Investigation Tools", icon: Network },
              { id: "shortcuts", label: "Shortcuts & Tips", icon: Keyboard },
            ].map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                onClick={() => setTab(id as Tab)}
                className={`inline-flex items-center gap-2 rounded-xl border px-3.5 py-1.5 text-xs font-semibold transition-all ${
                  tab === id
                    ? "border-accent/40 bg-accent/15 text-accent shadow-sm"
                    : "border-transparent text-slate-400 hover:bg-white/[0.05] hover:text-slate-200"
                }`}
              >
                <Icon size={14} />
                {label}
              </button>
            ))}
          </div>

          {/* Content Body */}
          <div className="flex-1 overflow-y-auto p-6 text-slate-300">
            {tab === "overview" && (
              <div className="space-y-6">
                <div className="rounded-xl border border-accent/20 bg-accent/[0.06] p-4 text-xs leading-relaxed text-slate-200">
                  <div className="font-bold text-accent">What is Sentinel?</div>
                  Sentinel helps police review public social media posts on X, Reddit, Facebook, Instagram, Telegram, and YouTube. It shows the tone of posts, concern scores, and signs of accounts posting together. It supports Gujarati, Hindi, English, Hinglish, and Gujlish. Officers must check the evidence before taking action.
                </div>

                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-4">
                    <div className="flex items-center gap-2 font-semibold text-slate-200">
                      <Radio size={16} className="text-threat-neutral" /> 1. Collect New Posts
                    </div>
                    <p className="mt-2 text-xs leading-relaxed text-slate-400">
                      New social media posts appear as they are collected. The system checks their language, translates them when needed, and uses three models to assess their tone.
                    </p>
                  </div>

                  <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-4">
                    <div className="flex items-center gap-2 font-semibold text-slate-200">
                      <ShieldAlert size={16} className="text-threat-critical" /> 2. Review Alerts
                    </div>
                    <p className="mt-2 text-xs leading-relaxed text-slate-400">
                      Posts with a concern score of 65 or more raise alerts. Review the post and its evidence, then decide whether to send it to the police unit for action.
                    </p>
                  </div>

                  <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-4">
                    <div className="flex items-center gap-2 font-semibold text-slate-200">
                      <Network size={16} className="text-purple-400" /> 3. Find Accounts Posting Together
                    </div>
                    <p className="mt-2 text-xs leading-relaxed text-slate-400">
                      The system groups accounts that post very similar messages or use the same hashtags at nearly the same time.
                    </p>
                  </div>

                  <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-4">
                    <div className="flex items-center gap-2 font-semibold text-slate-200">
                      <Sparkles size={16} className="text-amber-400" /> 4. Check Images & Create Reports
                    </div>
                    <p className="mt-2 text-xs leading-relaxed text-slate-400">
                      Check images for possible editing or AI fakes, find where they appear online, review account details, and create evidence reports.
                    </p>
                  </div>
                </div>
              </div>
            )}

            {tab === "sentiment" && (
              <div className="space-y-5">
                <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] p-4">
                  <h3 className="font-bold text-slate-200">What the Results Mean</h3>
                  <p className="mt-2 text-xs leading-relaxed text-slate-300">
                    Every post gets exactly one tag — <b>positive</b>, <b>negative</b> or <b>neutral</b> —
                    plus a <b>concern score</b> from 0 to 100. These are the three possible tags.
                  </p>
                  <p className="mt-2 text-xs leading-relaxed text-slate-400">
                    A negative tag does <b>not</b> prove that a post is false or will cause violence.
                    Officers must check the facts and evidence. Open the post to see related news
                    from named sources (Google News, GNews, NewsAPI.org) and compare their reports.
                  </p>
                </div>

                <div>
                  <h3 className="mb-2 font-bold text-slate-200">The three tags</h3>
                  <div className="grid gap-2 sm:grid-cols-3">
                    {[
                      { t: "Negative", c: "red", d: "Angry, abusive, upset, or unhappy language." },
                      { t: "Neutral", c: "slate", d: "Information without a clear positive or negative tone." },
                      { t: "Positive", c: "emerald", d: "Support, praise, happiness, or approval." },
                    ].map((x) => (
                      <div key={x.t} className={`rounded-xl border border-${x.c}-500/30 bg-${x.c}-500/10 p-3`}>
                        <div className={`font-bold text-${x.c}-300`}>{x.t}</div>
                        <p className="mt-1 text-[13px] leading-relaxed text-slate-300">{x.d}</p>
                      </div>
                    ))}
                  </div>
                </div>

                <div>
                  <h3 className="mb-2 font-bold text-slate-200">Concern Score Levels</h3>
                  <p className="mb-2 text-xs text-slate-400">
                    The score uses the post's negative tone and confidence in that result (50%),
                    abusive language (22%), how widely it has spread (18%), and concerning words (10%).
                    An alert needs a combination of factors. Positive posts do not raise alerts,
                    even if they spread widely.
                  </p>
                  <div className="space-y-2">
                    {[
                      { t: "Critical", r: "74 – 100", c: "red", d: "Strongly negative, abusive, and spreading widely. Raises a critical alert with an automatic action report." },
                      { t: "High", r: "65 – 73", c: "orange", d: "Raises a high-priority alert for an officer to review." },
                      { t: "Elevated", r: "50 – 64", c: "amber", d: "Shown on the dashboard for review. No alert is raised." },
                      { t: "Routine", r: "0 – 49", c: "emerald", d: "Collected posts that you can search. No alert is raised." },
                    ].map((b) => (
                      <div key={b.t} className={`rounded-xl border border-${b.c}-500/30 bg-${b.c}-500/10 p-3`}>
                        <div className="flex items-center justify-between">
                          <span className={`font-bold text-${b.c}-300`}>{b.t}</span>
                          <span className={`rounded-md border border-${b.c}-500/40 bg-${b.c}-500/20 px-2 py-0.5 font-mono text-[13px] font-bold text-${b.c}-200`}>
                            {b.r}
                          </span>
                        </div>
                        <p className="mt-1.5 text-xs text-slate-300">{b.d}</p>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] p-4">
                  <h3 className="font-bold text-slate-200">How a tag is decided</h3>
                  <p className="mt-2 text-xs leading-relaxed text-slate-300">
                    Three models check the post's words and context, such as questions, quotations,
                    and sarcasm. If two models agree, their tag is used. If all three disagree,
                    the result with the highest confidence is used. Account details and reach can
                    change the confidence score, but not the tag. A final AI check can change the
                    result; any change is recorded. Open a post to see the results and reasons.
                  </p>
                </div>
              </div>
            )}

            {tab === "spikes" && (
              <div className="space-y-5">
                <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] p-4">
                  <h3 className="flex items-center gap-2 font-bold text-slate-200">
                    <Flame size={16} className="text-threat-critical" /> How Unusual Is This Increase?
                  </h3>
                  <p className="mt-2 text-xs leading-relaxed text-slate-300">
                    The <strong>increase score (Z-score)</strong> compares mentions of a topic in the current hour with its usual level over the last 24 hours. A higher score means a more unusual increase:
                  </p>
                  <div className="my-3 rounded-lg bg-black/30 p-3 font-mono text-xs text-accent">
                    Z-score = (mentions this hour - usual hourly mentions) / usual variation
                  </div>
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                    <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-3 text-xs">
                      <div className="font-bold text-slate-300">&lt; 1.5σ (Normal)</div>
                      <div className="mt-1 text-slate-400">Small changes within the usual range.</div>
                    </div>
                    <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs">
                      <div className="font-bold text-amber-300">1.5σ – 2.5σ (Elevated)</div>
                      <div className="mt-1 text-slate-300">Mentions are increasing. The topic may be spreading quickly.</div>
                    </div>
                    <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-xs">
                      <div className="font-bold text-red-300">&gt; 2.5σ (Viral Spike)</div>
                      <div className="mt-1 text-slate-300">A large, unusual increase. Check whether accounts are posting together.</div>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {tab === "nlp" && (
              <div className="space-y-4">
                <p className="text-xs text-slate-400">
                  Sentinel checks posts in local languages, including Hindi and Gujarati written in English letters:
                </p>

                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div className="rounded-xl border border-white/[0.07] bg-white/[0.03] p-4 text-xs">
                    <div className="font-bold text-slate-200">Gujarati & Gujlish</div>
                    <div className="mt-1 text-slate-400">
                      Reads Gujarati script (ગુજરાતી) and Gujarati written in English letters (Gujlish).
                    </div>
                  </div>
                  <div className="rounded-xl border border-white/[0.07] bg-white/[0.03] p-4 text-xs">
                    <div className="font-bold text-slate-200">Hindi & Hinglish</div>
                    <div className="mt-1 text-slate-400">
                      Reads Hindi script and Hindi written in English letters (Hinglish), including slang and abusive phrases.
                    </div>
                  </div>
                  <div className="rounded-xl border border-white/[0.07] bg-white/[0.03] p-4 text-xs">
                    <div className="font-bold text-slate-200">Three Models Check Each Post</div>
                    <div className="mt-1 text-slate-400">
                      Three models assess each post, followed by a final AI check when available. Review the results and reasons in the post details.
                    </div>
                  </div>
                  <div className="rounded-xl border border-white/[0.07] bg-white/[0.03] p-4 text-xs">
                    <div className="font-bold text-slate-200">Post Tone Score (-1.0 to +1.0)</div>
                    <div className="mt-1 text-slate-400">
                      -1.0 means strongly negative, 0.0 means neutral, and +1.0 means strongly positive.
                    </div>
                  </div>
                </div>
              </div>
            )}

            {tab === "osint" && (
              <div className="space-y-4">
                <div className="rounded-xl border border-white/[0.07] bg-white/[0.03] p-4 text-xs">
                  <h3 className="font-bold text-slate-200">Investigation Tools</h3>
                  <div className="mt-3 space-y-3">
                    <div className="flex items-start gap-2">
                      <span className="font-mono text-accent">1. Image & Video Check:</span>
                      <span>Checks file details and possible editing or AI fakes. Searches for the image on other websites.</span>
                    </div>
                    <div className="flex items-start gap-2">
                      <span className="font-mono text-accent">2. Username Lookup:</span>
                      <span>Searches public sites for a username and compares the profiles found.</span>
                    </div>
                    <div className="flex items-start gap-2">
                      <span className="font-mono text-accent">3. Suspicious Link Check:</span>
                      <span>Finds where a shortened link leads and checks the destination for signs of fraud or harmful content.</span>
                    </div>
                    <div className="flex items-start gap-2">
                      <span className="font-mono text-accent">4. Organized Online Campaigns:</span>
                      <span>Looks for accounts posting together to influence public opinion on law-and-order issues.</span>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {tab === "shortcuts" && (
              <div className="space-y-4">
                <div className="rounded-xl border border-white/[0.07] bg-white/[0.03] p-4 text-xs">
                  <h3 className="font-bold text-slate-200">Keyboard Shortcuts & Navigation Tips</h3>
                  <div className="mt-3 space-y-2">
                    <div className="flex items-center justify-between border-b border-white/[0.05] pb-2">
                      <span className="text-slate-300">Search Posts & Apply Filters</span>
                      <kbd className="rounded border border-white/20 bg-base-800 px-2 py-0.5 font-mono text-[13px] text-accent">/</kbd>
                    </div>
                    <div className="flex items-center justify-between border-b border-white/[0.05] pb-2">
                      <span className="text-slate-300">Close Pop-Up Windows</span>
                      <kbd className="rounded border border-white/20 bg-base-800 px-2 py-0.5 font-mono text-[13px] text-slate-300">Esc</kbd>
                    </div>
                    <div className="flex items-center justify-between border-b border-white/[0.05] pb-2">
                      <span className="text-slate-300">Open Voice Assistant</span>
                      <span className="text-slate-400">Click the Sentinel button at the bottom right or ask a question aloud</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-slate-300">View Full Post Details</span>
                      <span className="text-slate-400">Click on any post card in Dashboard or Feed</span>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between border-t border-white/[0.08] bg-base-950/60 px-6 py-3.5">
            <span className="font-mono text-[13px] text-slate-400">
              SENTINEL SOCIAL MEDIA MONITORING · CONFIDENTIAL
            </span>
            <button
              onClick={onClose}
              className="rounded-xl border border-accent/40 bg-accent/15 px-4 py-1.5 text-xs font-bold text-accent hover:bg-accent hover:text-base-900"
            >
              Got it
            </button>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>,
    document.body
  );
}
