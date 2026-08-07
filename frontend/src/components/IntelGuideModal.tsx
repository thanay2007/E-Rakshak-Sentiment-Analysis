import { AnimatePresence, motion } from "framer-motion";
import {
  Activity,
  AlertTriangle,
  Bot,
  CheckCircle2,
  Cpu,
  Flame,
  HelpCircle,
  Keyboard,
  Layers,
  Network,
  Radio,
  Search,
  ShieldAlert,
  Sparkles,
  TrendingUp,
  X,
} from "lucide-react";
import { useState } from "react";
import { createPortal } from "react-dom";
import { THREAT_COLORS, THREAT_SHORT } from "../data/constants";

interface Props {
  open: boolean;
  onClose: () => void;
}

type Tab = "overview" | "threats" | "spikes" | "nlp" | "osint" | "shortcuts";

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
          aria-label="Intelligence & Operations Guide"
        >
          {/* Header */}
          <div className="flex items-center justify-between border-b border-white/[0.08] px-6 py-4">
            <div className="flex items-center gap-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl border border-accent/40 bg-accent/10 text-accent">
                <HelpCircle size={18} />
              </span>
              <div>
                <h2 className="text-base font-bold tracking-wide text-slate-100">
                  E-RAKSHAK · Intelligence & Operational Guide
                </h2>
                <p className="text-xs text-slate-400">
                  Threat metrics, statistical definitions, NLP scoring, and OSINT investigation reference
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
              { id: "threats", label: "Threat Classifications", icon: ShieldAlert },
              { id: "spikes", label: "Spikes & Z-Scores (σ)", icon: Flame },
              { id: "nlp", label: "Multilingual NLP", icon: Cpu },
              { id: "osint", label: "OSINT & Link Analysis", icon: Network },
              { id: "shortcuts", label: "Shortcuts & Workflow", icon: Keyboard },
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
                  <div className="font-bold text-accent">What is E-Rakshak?</div>
                  E-Rakshak is a real-time OSINT threat intelligence platform designed for state cyber command centers. It monitors social media platforms (X, Reddit, Facebook, Instagram, Telegram, YouTube) to detect communal incitement, viral disinformation, coordinated bot campaigns, and regional tension in native scripts (Gujarati, Hindi, English) as well as code-mixed vernaculars (Hinglish, Gujlish).
                </div>

                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-4">
                    <div className="flex items-center gap-2 font-semibold text-slate-200">
                      <Radio size={16} className="text-threat-neutral" /> 1. Real-time Ingestion
                    </div>
                    <p className="mt-2 text-xs leading-relaxed text-slate-400">
                      Posts flow from live social streams via WebSockets. Each post undergoes immediate multilingual preprocessing, translation, and 3-model NLP ensemble scoring.
                    </p>
                  </div>

                  <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-4">
                    <div className="flex items-center gap-2 font-semibold text-slate-200">
                      <ShieldAlert size={16} className="text-threat-critical" /> 2. Threat Triage
                    </div>
                    <p className="mt-2 text-xs leading-relaxed text-slate-400">
                      High-threat posts (score ≥ 65) automatically raise Critical Incidents with auto-generated escalation packets and suggested police countermeasures.
                    </p>
                  </div>

                  <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-4">
                    <div className="flex items-center gap-2 font-semibold text-slate-200">
                      <Network size={16} className="text-purple-400" /> 3. Coordination Detection
                    </div>
                    <p className="mt-2 text-xs leading-relaxed text-slate-400">
                      Link analysis clusters accounts posting near-identical text bursts or sharing common propaganda hashtags within tight time windows.
                    </p>
                  </div>

                  <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-4">
                    <div className="flex items-center gap-2 font-semibold text-slate-200">
                      <Sparkles size={16} className="text-amber-400" /> 4. AI Forensics & Dossiers
                    </div>
                    <p className="mt-2 text-xs leading-relaxed text-slate-400">
                      Deepfake image analysis, reverse image lookup, handle profiling, and one-click court-ready evidence dossier export.
                    </p>
                  </div>
                </div>
              </div>
            )}

            {tab === "threats" && (
              <div className="space-y-5">
                <p className="text-xs text-slate-400">
                  Every post receives a normalized threat score from 0 to 100 calculated by ensemble classification:
                </p>

                <div className="space-y-3">
                  <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="h-3 w-3 rounded-full bg-threat-critical" />
                        <span className="font-bold text-red-300">Critical Threat (Score 65 – 100)</span>
                      </div>
                      <span className="rounded-md border border-red-500/40 bg-red-500/20 px-2 py-0.5 font-mono text-[11px] font-bold text-red-200">
                        EMERGENCY ACTION
                      </span>
                    </div>
                    <p className="mt-2 text-xs text-slate-300">
                      Explicit calls for mob violence, riot orchestration, weapon acquisition, VIP threats, or urgent public safety emergencies. Immediately raises a Critical Alert.
                    </p>
                  </div>

                  <div className="rounded-xl border border-orange-500/30 bg-orange-500/10 p-4">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="h-3 w-3 rounded-full bg-threat-inflammatory" />
                        <span className="font-bold text-orange-300">Inflammatory Content (Score 40 – 64)</span>
                      </div>
                      <span className="rounded-md border border-orange-500/40 bg-orange-500/20 px-2 py-0.5 font-mono text-[11px] font-bold text-orange-200">
                        HIGH MONITORING
                      </span>
                    </div>
                    <p className="mt-2 text-xs text-slate-300">
                      Communal slurs, hate speech, targeted harassment, sectarian tension, or provocative statements designed to polarize communities.
                    </p>
                  </div>

                  <div className="rounded-xl border border-purple-500/30 bg-purple-500/10 p-4">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="h-3 w-3 rounded-full bg-threat-fake" />
                        <span className="font-bold text-purple-300">Fake News & Misinformation (Score 40 – 75)</span>
                      </div>
                      <span className="rounded-md border border-purple-500/40 bg-purple-500/20 px-2 py-0.5 font-mono text-[11px] font-bold text-purple-200">
                        FACT-CHECK ACTIVE
                      </span>
                    </div>
                    <p className="mt-2 text-xs text-slate-300">
                      Fabricated news articles, out-of-context historical photos, synthetic AI images, morphed video clips, or false government notices.
                    </p>
                  </div>

                  <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="h-3 w-3 rounded-full bg-threat-neutral" />
                        <span className="font-bold text-emerald-300">Neutral / Benign (Score 0 – 39)</span>
                      </div>
                      <span className="rounded-md border border-emerald-500/40 bg-emerald-500/20 px-2 py-0.5 font-mono text-[11px] font-bold text-emerald-200">
                        CLEAN
                      </span>
                    </div>
                    <p className="mt-2 text-xs text-slate-300">
                      Normal public discourse, news reporting, cultural discussions, or non-threatening commentary.
                    </p>
                  </div>
                </div>
              </div>
            )}

            {tab === "spikes" && (
              <div className="space-y-5">
                <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] p-4">
                  <h3 className="flex items-center gap-2 font-bold text-slate-200">
                    <Flame size={16} className="text-threat-critical" /> What does the Spike Z-Score (e.g. 3.2σ) mean?
                  </h3>
                  <p className="mt-2 text-xs leading-relaxed text-slate-300">
                    A <strong>Z-Score (standard score)</strong> measures how many standard deviations a term's current hourly mention velocity deviates from its 24-hour baseline rolling average:
                  </p>
                  <div className="my-3 rounded-lg bg-black/30 p-3 font-mono text-xs text-accent">
                    Z = (Current Hourly Velocity - 24h Mean) / Standard Deviation
                  </div>
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                    <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-3 text-xs">
                      <div className="font-bold text-slate-300">&lt; 1.5σ (Normal)</div>
                      <div className="mt-1 text-slate-400">Regular organic fluctuations within baseline variance.</div>
                    </div>
                    <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs">
                      <div className="font-bold text-amber-300">1.5σ – 2.5σ (Elevated)</div>
                      <div className="mt-1 text-slate-300">Notable acceleration. Potential emerging viral topic.</div>
                    </div>
                    <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-xs">
                      <div className="font-bold text-red-300">&gt; 2.5σ (Viral Spike)</div>
                      <div className="mt-1 text-slate-300">Statistically abnormal surge (p &lt; 0.01). Possible orchestrated blitz.</div>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {tab === "nlp" && (
              <div className="space-y-4">
                <p className="text-xs text-slate-400">
                  E-Rakshak utilizes a multi-stage Indic NLP pipeline specifically tuned for Western and Northern Indian languages and dialects:
                </p>

                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div className="rounded-xl border border-white/[0.07] bg-white/[0.03] p-4 text-xs">
                    <div className="font-bold text-slate-200">Gujarati & Gujlish</div>
                    <div className="mt-1 text-slate-400">
                      Handles native Gujarati script (ગુજરાતી) as well as Romanized Gujlish phonetic writing (e.g. "aa loko ne sabak shikhavo").
                    </div>
                  </div>
                  <div className="rounded-xl border border-white/[0.07] bg-white/[0.03] p-4 text-xs">
                    <div className="font-bold text-slate-200">Hindi & Hinglish</div>
                    <div className="mt-1 text-slate-400">
                      Full Devnagari parsing combined with phonetic Hinglish tokenizers to classify colloquial slang, abusive idioms, and dogwhistles.
                    </div>
                  </div>
                  <div className="rounded-xl border border-white/[0.07] bg-white/[0.03] p-4 text-xs">
                    <div className="font-bold text-slate-200">3-Model Consensus</div>
                    <div className="mt-1 text-slate-400">
                      Combines RoBERTa/mBERT Indic transformer embeddings, keyword-density heuristics, and LLM verification for high precision and low false-positive rate.
                    </div>
                  </div>
                  <div className="rounded-xl border border-white/[0.07] bg-white/[0.03] p-4 text-xs">
                    <div className="font-bold text-slate-200">Sentiment Score (-1.0 to +1.0)</div>
                    <div className="mt-1 text-slate-400">
                      Polarity index: -1.0 (extremely hostile/negative), 0.0 (neutral factual), +1.0 (positive/supportive).
                    </div>
                  </div>
                </div>
              </div>
            )}

            {tab === "osint" && (
              <div className="space-y-4">
                <div className="rounded-xl border border-white/[0.07] bg-white/[0.03] p-4 text-xs">
                  <h3 className="font-bold text-slate-200">Investigation Hub OSINT Capabilities</h3>
                  <div className="mt-3 space-y-3">
                    <div className="flex items-start gap-2">
                      <span className="font-mono text-accent">1. Image & Reverse Forensics:</span>
                      <span>Analyzes metadata, EXIF traces, deepfake manipulation probability, and queries Google/Yandex/TinEye databases for cross-web appearances.</span>
                    </div>
                    <div className="flex items-start gap-2">
                      <span className="font-mono text-accent">2. Username Lookup:</span>
                      <span>Scans 30+ platforms for account presence, bio consistency, account age, and known malicious aliases.</span>
                    </div>
                    <div className="flex items-start gap-2">
                      <span className="font-mono text-accent">3. Link & URL Scanner:</span>
                      <span>Unshortens redirected links (bit.ly, t.co), checks Google Safe Browsing and VirusTotal reputation, and parses destination meta tags.</span>
                    </div>
                    <div className="flex items-start gap-2">
                      <span className="font-mono text-accent">4. Bot & Comments Swarm:</span>
                      <span>Analyzes reply velocity, repetitive syntactic patterns, and temporal bursts to score account authenticity.</span>
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
                      <span className="text-slate-300">Global Search & Feed Filter</span>
                      <kbd className="rounded border border-white/20 bg-base-800 px-2 py-0.5 font-mono text-[11px] text-accent">/</kbd>
                    </div>
                    <div className="flex items-center justify-between border-b border-white/[0.05] pb-2">
                      <span className="text-slate-300">Close Modals & Drawers</span>
                      <kbd className="rounded border border-white/20 bg-base-800 px-2 py-0.5 font-mono text-[11px] text-slate-300">Esc</kbd>
                    </div>
                    <div className="flex items-center justify-between border-b border-white/[0.05] pb-2">
                      <span className="text-slate-300">Open Sentinel Voice AI Assistant</span>
                      <span className="text-slate-400">Click Sentinel button at bottom right or speak query</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-slate-300">Inspect Full Post Dossier</span>
                      <span className="text-slate-400">Click on any post card in Dashboard or Feed</span>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between border-t border-white/[0.08] bg-base-950/60 px-6 py-3.5">
            <span className="font-mono text-[11px] text-slate-400">
              E-RAKSHAK OSINT THREAT INTELLIGENCE SYSTEM · CONFIDENTIAL
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
