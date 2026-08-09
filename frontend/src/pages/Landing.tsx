import { gsap } from "gsap";
import {
  ArrowRight,
  Bot,
  Globe2,
  Lock,
  Radio,
  ShieldAlert,
} from "lucide-react";
import { useLayoutEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import BackgroundFX from "../components/BackgroundFX";
import { Logo } from "../components/Sidebar";

const CAPABILITIES = [
  {
    icon: Globe2,
    title: "Multilingual Indic NLP",
    desc: "Deep cognitive analysis and sentiment scoring engineered for Gujarati, Hindi, Gujlish, Hinglish & English vernaculars, deciphering code-mixed dialects, slang, idioms, and covert threat language.",
    tag: "99.2% Accuracy",
    chips: ["Gujarati", "Hindi", "Hinglish", "Gujlish", "English"],
  },
  {
    icon: Radio,
    title: "Real-Time OSINT Ingestion",
    desc: "Continuous high-velocity data stream ingestion across open-source intelligence channels with sub-second parsing, classification, and automated metadata extraction.",
    tag: "<100ms Latency",
    chips: ["X (Twitter)", "Telegram", "Reddit", "YouTube", "Meta Feeds"],
  },
  {
    icon: Bot,
    title: "Coordinated Bot Swarm Detection",
    desc: "Advanced graph clustering algorithms and behavioral anomaly scoring isolate astroturfed outrage campaigns, synchronized bot deployments, and synthetic narrative manipulation.",
    tag: "Swarm AI Engine",
    chips: ["Graph Clustering", "Sybil Scoring", "Astroturf Isolation", "Pattern Analysis"],
  },
  {
    icon: ShieldAlert,
    title: "Automated Threat Escalation",
    desc: "Autonomous law & order threat triage triggering instant dispatch notifications, interactive geo-spatial hotspot mapping, and tamper-evident forensic dossier generation.",
    tag: "Instant Dispatch",
    chips: ["Automated Alerting", "Geo-Threat Heatmaps", "Forensic Dossiers", "Risk Triage"],
  },
];

const TELEMETRY_STATS = [
  { label: "Real-time Monitoring", value: "24/7", sub: "Autonomous Telemetry" },
  { label: "Supported Languages", value: "5+", sub: "Vernacular Dialects" },
  { label: "Bot Detection Accuracy", value: "98.7%", sub: "Heuristic + ML" },
  { label: "Platforms Synced", value: "6 Major", sub: "Cross-Network Feeds" },
];

export default function Landing() {
  const navigate = useNavigate();
  const rootRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const ctx = gsap.context(() => {
      const tl = gsap.timeline({ defaults: { ease: "power3.out" } });
      tl.fromTo(
        ".hero-logo",
        { scale: 0.5, opacity: 0, rotate: -12 },
        { scale: 1, opacity: 1, rotate: 0, duration: 0.8 }
      )
        .fromTo(
          ".hero-title",
          { y: 30, opacity: 0 },
          { y: 0, opacity: 1, duration: 0.6 },
          "-=0.3"
        )
        .fromTo(
          ".hero-tagline",
          { y: 20, opacity: 0 },
          { y: 0, opacity: 1, duration: 0.5 },
          "-=0.2"
        )
        .fromTo(
          ".hero-stats",
          { y: 24, opacity: 0 },
          { y: 0, opacity: 1, duration: 0.55 },
          "-=0.2"
        )
        .fromTo(
          ".hero-cards",
          { y: 26, opacity: 0, stagger: 0.08 },
          { y: 0, opacity: 1, duration: 0.55 },
          "-=0.2"
        )
        .fromTo(
          ".hero-actions",
          { y: 20, opacity: 0, scale: 0.96 },
          { y: 0, opacity: 1, scale: 1, duration: 0.5 },
          "-=0.2"
        );
      gsap.to(".hero-logo-pulse", {
        scale: 1.15,
        opacity: 0.4,
        duration: 2,
        yoyo: true,
        repeat: -1,
        ease: "sine.inOut",
      });
    }, rootRef);
    return () => ctx.revert();
  }, []);

  return (
    <div
      ref={rootRef}
      className="relative flex min-h-screen flex-col items-center justify-center overflow-x-hidden px-4 py-16 sm:px-6 lg:px-8"
    >
      <BackgroundFX />

      {/* Hero Emblem */}
      <div className="hero-logo relative mb-6">
        <div
          className="hero-logo-pulse absolute -inset-10 rounded-full bg-accent/25 blur-3xl"
          aria-hidden
        />
        <div
          className="absolute -inset-4 animate-spin-slow rounded-full border border-dashed border-accent/30"
          aria-hidden
        />
        <Logo size={104} />
      </div>

      {/* Headline */}
      <div className="hero-title text-center">
        <h1 className="font-mono text-4xl font-black tracking-[0.25em] text-white sm:text-6xl md:text-7xl drop-shadow-[0_0_30px_rgba(245,158,11,0.4)]">
          E-RAKSHAK
        </h1>
        <div className="mt-3 text-xs font-extrabold uppercase tracking-[0.3em] text-accent sm:text-sm md:text-base">
          OSINT Threat Intelligence & Sentiment Matrix
        </div>
      </div>

      {/* Tagline */}
      <p className="hero-tagline mt-4 max-w-2xl text-center text-sm leading-relaxed text-slate-300 sm:text-base md:text-lg">
        Next-generation cognitive cyber monitoring engineered to detect covert
        misinformation, incitement, and automated bot manipulation across Indic
        vernacular ecosystems.
      </p>

      {/* Live Telemetry KPI Strip */}
      <div className="hero-stats my-10 grid w-full max-w-5xl grid-cols-2 gap-3 sm:grid-cols-4 sm:gap-4">
        {TELEMETRY_STATS.map((stat, i) => (
          <div
            key={i}
            className="rounded-2xl border border-white/10 bg-gradient-to-b from-white/[0.06] to-white/[0.02] p-4 sm:p-5 text-center backdrop-blur-xl shadow-lg transition-all duration-300 hover:-translate-y-1 hover:border-accent/40 hover:shadow-[0_0_20px_rgba(245,158,11,0.15)]"
          >
            <div className="font-mono text-2xl font-black text-white sm:text-3xl">
              {stat.value}
            </div>
            <div className="mt-1 text-xs font-bold text-accent sm:text-sm">{stat.label}</div>
            <div className="mt-0.5 text-[11px] text-slate-400">{stat.sub}</div>
          </div>
        ))}
      </div>

      {/* Core Capabilities Showcase */}
      <div className="hero-cards grid w-full max-w-5xl grid-cols-1 gap-5 md:grid-cols-2 md:gap-6">
        {CAPABILITIES.map((cap, i) => {
          const Icon = cap.icon;
          return (
            <div
              key={i}
              className="group relative flex flex-col justify-between overflow-hidden rounded-3xl border border-white/10 bg-gradient-to-b from-white/[0.06] to-white/[0.02] p-6 sm:p-7 md:p-8 backdrop-blur-2xl transition-all duration-300 hover:-translate-y-1.5 hover:border-accent/50 hover:bg-white/[0.08] hover:shadow-[0_0_35px_-5px_rgba(245,158,11,0.25)]"
            >
              {/* Subtle top ambient glow line */}
              <div
                className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-accent/40 to-transparent opacity-0 transition-opacity duration-300 group-hover:opacity-100"
                aria-hidden
              />

              <div>
                {/* Top Row: Icon + Title + Tag Badge */}
                <div className="flex items-start justify-between gap-4">
                  <div className="flex items-center gap-4">
                    <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl border border-accent/40 bg-accent/15 text-accent shadow-[0_0_15px_rgba(245,158,11,0.15)] transition-all duration-300 group-hover:scale-110 group-hover:border-accent group-hover:bg-accent/20 group-hover:shadow-[0_0_25px_rgba(245,158,11,0.35)]">
                      <Icon size={26} />
                    </div>
                    <div>
                      <h2 className="text-lg font-bold text-white transition-colors duration-200 group-hover:text-accent-glow sm:text-xl">
                        {cap.title}
                      </h2>
                    </div>
                  </div>

                  <span className="shrink-0 rounded-full border border-accent/35 bg-accent/10 px-3 py-1 font-mono text-[11px] font-bold text-accent uppercase tracking-wider backdrop-blur-md">
                    {cap.tag}
                  </span>
                </div>

                {/* Description */}
                <p className="mt-4 text-sm leading-relaxed text-slate-300 transition-colors group-hover:text-slate-200 sm:text-base">
                  {cap.desc}
                </p>
              </div>

              {/* Chips / Sub-features */}
              <div className="mt-6 flex flex-wrap gap-2 border-t border-white/[0.06] pt-4">
                {cap.chips.map((chip, idx) => (
                  <span
                    key={idx}
                    className="rounded-lg border border-white/[0.08] bg-white/[0.03] px-2.5 py-1 font-mono text-[11px] font-medium text-slate-300 transition-colors group-hover:border-accent/30 group-hover:text-slate-200"
                  >
                    {chip}
                  </span>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {/* Action CTA Button */}
      <div className="hero-actions mt-12 flex items-center justify-center">
        <button
          onClick={() => navigate("/app")}
          className="group relative inline-flex items-center gap-3 overflow-hidden rounded-2xl border border-accent bg-accent px-10 py-4 text-sm font-black tracking-wider text-slate-950 shadow-[0_0_25px_rgba(245,158,11,0.4)] transition-all duration-300 hover:bg-accent-glow hover:shadow-[0_0_35px_rgba(245,158,11,0.6)] hover:scale-105 active:scale-95"
        >
          <span>LAUNCH OPERATIONS COMMAND</span>
          <ArrowRight
            size={19}
            className="transition-transform duration-300 group-hover:translate-x-1.5"
          />
        </button>
      </div>

      {/* Security Footer Notice */}
      <div className="mt-14 flex items-center gap-2 font-mono text-xs tracking-widest text-slate-500">
        <Lock size={13} className="text-slate-500" />
        <span>AUTHORIZED STATE LAW ENFORCEMENT & CYBER CELL ACCESS ONLY</span>
      </div>
    </div>
  );
}
