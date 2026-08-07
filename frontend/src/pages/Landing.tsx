import { gsap } from "gsap";
import {
  ArrowRight,
  Bot,
  Flame,
  Globe2,
  Lock,
  Radio,
  ScanSearch,
  Shield,
  ShieldAlert,
  Sparkles,
  Zap,
} from "lucide-react";
import { useLayoutEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import BackgroundFX from "../components/BackgroundFX";
import { Logo } from "../components/Sidebar";

const CAPABILITIES = [
  {
    icon: Globe2,
    title: "Multilingual Indic NLP",
    desc: "Deep analysis for Gujarati, Hindi, Gujlish, Hinglish & English slang, idioms, and covert code-words.",
    tag: "99.2% Accuracy",
  },
  {
    icon: Radio,
    title: "Real-Time OSINT Ingestion",
    desc: "Continuous cross-platform monitoring spanning X, Telegram, Reddit, Facebook, Instagram & YouTube.",
    tag: "<100ms Latency",
  },
  {
    icon: Bot,
    title: "Coordinated Bot Swarm Detection",
    desc: "Graph clustering algorithms isolate astroturfed outrage and automated narrative manipulation campaigns.",
    tag: "Swarm AI",
  },
  {
    icon: ShieldAlert,
    title: "Automated Threat Escalation",
    desc: "Law & order classification with automated police alerting, geo-threat mapping & forensic dossiers.",
    tag: "State Cyber Cell",
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
        ".hero-badge",
        { y: -20, opacity: 0 },
        { y: 0, opacity: 1, duration: 0.6 }
      )
        .fromTo(
          ".hero-logo",
          { scale: 0.5, opacity: 0, rotate: -12 },
          { scale: 1, opacity: 1, rotate: 0, duration: 0.8 },
          "-=0.3"
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
      className="relative flex min-h-screen flex-col items-center justify-center overflow-x-hidden px-4 py-12"
    >
      <BackgroundFX />

      {/* Cyber Security Cell Badge Header */}
      <div className="hero-badge mb-6 inline-flex items-center gap-2 rounded-full border border-accent/40 bg-accent/10 px-4 py-1.5 shadow-[0_0_20px_rgba(245,158,11,0.2)] backdrop-blur-md">
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
        </span>
        <span className="font-mono text-xs font-bold tracking-widest text-accent uppercase">
          E-RAKSHAK · STATE CYBER DEFENSE HQ
        </span>
      </div>

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
        <Logo size={100} />
      </div>

      {/* Headline */}
      <div className="hero-title text-center">
        <h1 className="font-mono text-4xl font-black tracking-[0.25em] text-white sm:text-6xl drop-shadow-[0_0_30px_rgba(245,158,11,0.4)]">
          E-RAKSHAK
        </h1>
        <div className="mt-2 text-xs font-extrabold uppercase tracking-[0.3em] text-accent">
          OSINT Threat Intelligence & Sentiment Matrix
        </div>
      </div>

      {/* Tagline */}
      <p className="hero-tagline mt-4 max-w-2xl text-center text-sm leading-relaxed text-slate-300 sm:text-base">
        Next-generation cognitive cyber monitoring engineered to detect covert
        misinformation, incitement, and automated bot manipulation across Indic
        vernacular ecosystems.
      </p>

      {/* Live Telemetry KPI Strip */}
      <div className="hero-stats my-8 grid w-full max-w-4xl grid-cols-2 gap-3 sm:grid-cols-4">
        {TELEMETRY_STATS.map((stat, i) => (
          <div
            key={i}
            className="rounded-2xl border border-white/[0.08] bg-white/[0.03] p-4 text-center backdrop-blur-xl shadow-lg transition-transform hover:-translate-y-0.5 hover:border-accent/30"
          >
            <div className="font-mono text-2xl font-black text-white">
              {stat.value}
            </div>
            <div className="text-xs font-bold text-accent">{stat.label}</div>
            <div className="mt-0.5 text-[10px] text-slate-400">{stat.sub}</div>
          </div>
        ))}
      </div>

      {/* Core Capabilities Showcase */}
      <div className="hero-cards grid w-full max-w-4xl grid-cols-1 gap-3.5 sm:grid-cols-2">
        {CAPABILITIES.map((cap, i) => {
          const Icon = cap.icon;
          return (
            <div
              key={i}
              className="group relative overflow-hidden rounded-2xl border border-white/[0.08] bg-base-950/70 p-4.5 backdrop-blur-xl transition-all duration-300 hover:border-accent/40 hover:bg-white/[0.06] hover:shadow-[0_0_25px_-5px_rgba(245,158,11,0.2)]"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <div className="rounded-xl border border-accent/40 bg-accent/15 p-2.5 text-accent group-hover:scale-105 transition-transform">
                    <Icon size={20} />
                  </div>
                  <h2 className="text-sm font-bold text-slate-100 group-hover:text-white">
                    {cap.title}
                  </h2>
                </div>
                <span className="rounded-md border border-accent/30 bg-accent/10 px-2 py-0.5 font-mono text-[9px] font-bold text-accent">
                  {cap.tag}
                </span>
              </div>
              <p className="mt-2.5 text-xs leading-relaxed text-slate-400 group-hover:text-slate-300">
                {cap.desc}
              </p>
            </div>
          );
        })}
      </div>

      {/* Action CTA Buttons */}
      <div className="hero-actions mt-10 flex flex-wrap items-center justify-center gap-4">
        <button
          onClick={() => navigate("/app")}
          className="group relative inline-flex items-center gap-2.5 overflow-hidden rounded-2xl border border-accent bg-accent px-8 py-3.5 text-sm font-black tracking-wider text-slate-950 shadow-[0_0_25px_rgba(245,158,11,0.4)] transition-all duration-300 hover:bg-accent-glow hover:shadow-[0_0_35px_rgba(245,158,11,0.6)] hover:scale-105 active:scale-95"
        >
          <span>LAUNCH OPERATIONS COMMAND</span>
          <ArrowRight
            size={18}
            className="transition-transform duration-300 group-hover:translate-x-1"
          />
        </button>

        <button
          onClick={() => navigate("/app/investigate")}
          className="inline-flex items-center gap-2 rounded-2xl border border-white/20 bg-white/[0.04] px-6 py-3.5 text-sm font-bold tracking-wider text-slate-200 backdrop-blur-xl transition-all duration-300 hover:border-accent/50 hover:bg-white/[0.08] hover:text-white hover:scale-105 active:scale-95"
        >
          <ScanSearch size={17} className="text-accent" />
          <span>CYBER FORENSICS SUITE</span>
        </button>
      </div>

      {/* Security Footer Notice */}
      <div className="mt-12 flex items-center gap-2 font-mono text-[11px] tracking-widest text-slate-500">
        <Lock size={12} className="text-slate-500" />
        <span>AUTHORIZED STATE LAW ENFORCEMENT & CYBER CELL ACCESS ONLY</span>
      </div>
    </div>
  );
}

