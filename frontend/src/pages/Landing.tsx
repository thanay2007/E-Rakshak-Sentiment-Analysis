import { gsap } from "gsap";
import { ArrowRight, Lock } from "lucide-react";
import { useLayoutEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import BackgroundFX from "../components/BackgroundFX";
import { Logo } from "../components/Sidebar";

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
          SENTINEL
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

      {/* Action CTA Button */}
      <div className="hero-actions mt-2 flex items-center justify-center">
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
