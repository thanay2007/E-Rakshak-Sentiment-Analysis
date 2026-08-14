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
                  SENTINEL · Intelligence & Operational Guide
                </h2>
                <p className="text-xs text-slate-400">
                  Sentiment tagging, concern scoring, spike statistics and OSINT investigation reference
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
              { id: "sentiment", label: "Sentiment & Concern Score", icon: ShieldAlert },
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
                  <div className="font-bold text-accent">What is SENTINEL?</div>
                  SENTINEL is a real-time OSINT threat intelligence platform designed for state cyber command centers. It monitors social media platforms (X, Reddit, Facebook, Instagram, Telegram, YouTube) to detect communal incitement, viral disinformation, coordinated bot campaigns, and regional tension in native scripts (Gujarati, Hindi, English) as well as code-mixed vernaculars (Hinglish, Gujlish).
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
                      Posts scoring ≥ 65 on the concern score automatically raise Critical Incidents with auto-generated escalation packets and suggested police countermeasures.
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

            {tab === "sentiment" && (
              <div className="space-y-5">
                <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] p-4">
                  <h3 className="font-bold text-slate-200">What the system claims — and what it does not</h3>
                  <p className="mt-2 text-xs leading-relaxed text-slate-300">
                    Every post gets exactly one tag — <b>positive</b>, <b>negative</b> or <b>neutral</b> —
                    plus a <b>concern score</b> from 0 to 100. That is the whole taxonomy.
                  </p>
                  <p className="mt-2 text-xs leading-relaxed text-slate-400">
                    The system does <b>not</b> classify posts as incitement, propaganda or
                    misinformation. Whether a post will cause violence, or whether a claim inside it
                    is false, are investigative conclusions about the world — a model reading one
                    post's words cannot establish either, and a console that printed them as model
                    output would invite an analyst to treat a guess as a finding. Where an external
                    fact matters, the post detail shows news corroboration from named sources
                    (Google News, GNews, NewsAPI.org) and lets you judge it yourself.
                  </p>
                </div>

                <div>
                  <h3 className="mb-2 font-bold text-slate-200">The three tags</h3>
                  <div className="grid gap-2 sm:grid-cols-3">
                    {[
                      { t: "Negative", c: "red", d: "Anger, grievance, hostility, abuse or distress." },
                      { t: "Neutral", c: "slate", d: "Factual, logistical or informational — no clear lean." },
                      { t: "Positive", c: "emerald", d: "Approval, praise, celebration or satisfaction." },
                    ].map((x) => (
                      <div key={x.t} className={`rounded-xl border border-${x.c}-500/30 bg-${x.c}-500/10 p-3`}>
                        <div className={`font-bold text-${x.c}-300`}>{x.t}</div>
                        <p className="mt-1 text-[11px] leading-relaxed text-slate-300">{x.d}</p>
                      </div>
                    ))}
                  </div>
                </div>

                <div>
                  <h3 className="mb-2 font-bold text-slate-200">Concern score bands</h3>
                  <p className="mb-2 text-xs text-slate-400">
                    The score combines how negative the post is (weighted by model confidence, 50%),
                    how toxic its language is (22%), how far it travelled (18%) and the severity of
                    the strongest matched term (10%). The weights are shaped so no single dimension
                    reaches an alert band alone — an alert always means <b>negative and travelling</b>.
                    A positive post never raises one, however viral.
                  </p>
                  <div className="space-y-2">
                    {[
                      { t: "Critical", r: "74 – 100", c: "red", d: "Strongly negative, abusive and spreading. Raises a critical alert with an auto-generated escalation packet." },
                      { t: "High", r: "65 – 73", c: "orange", d: "Raises a high alert for analyst triage." },
                      { t: "Elevated", r: "50 – 64", c: "amber", d: "Surfaced on the dashboard as worth a look; no alert." },
                      { t: "Routine", r: "0 – 49", c: "emerald", d: "Ordinary traffic — collected and searchable, nothing raised." },
                    ].map((b) => (
                      <div key={b.t} className={`rounded-xl border border-${b.c}-500/30 bg-${b.c}-500/10 p-3`}>
                        <div className="flex items-center justify-between">
                          <span className={`font-bold text-${b.c}-300`}>{b.t}</span>
                          <span className={`rounded-md border border-${b.c}-500/40 bg-${b.c}-500/20 px-2 py-0.5 font-mono text-[11px] font-bold text-${b.c}-200`}>
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
                    Three independent models read the post — a fine-tuned MuRIL transformer, a
                    TF-IDF + LinearSVC classical model, and a multilingual valence lexicon. All
                    three see the post together with its discourse tags (is it a question, reported
                    speech, conditional, ironic, contrastive). If two or more agree, that tag wins;
                    if all three disagree, the most confident model's answer is chosen. Account
                    standing and reach then adjust the <i>confidence only</i>, never the tag, and
                    every adjustment is shown with its reason. Finally Groq reads the post and can
                    overturn the result when it is confident — recorded as an override, never
                    silent. Open any post to see all of it.
                  </p>
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
                  SENTINEL utilizes a multi-stage Indic NLP pipeline specifically tuned for Western and Northern Indian languages and dialects:
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
                      <span className="text-slate-300">Sentinel Voice AI Assistant</span>
                      <span className="text-slate-400">Mic button at bottom right — on, it listens until muted</span>
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
              SENTINEL OSINT THREAT INTELLIGENCE SYSTEM · CONFIDENTIAL
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
