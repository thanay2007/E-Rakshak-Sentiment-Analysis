import { gsap } from "gsap";
import { ArrowRight, Globe2, Radar, ShieldCheck, Zap } from "lucide-react";
import { useLayoutEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import BackgroundFX from "../components/BackgroundFX";
import { Logo } from "../components/Sidebar";

const FEATURES = [
  { icon: Globe2, label: "Gujarati · Hindi · Hinglish · Gujlish · English NLP" },
  { icon: Radar, label: "Real-time multi-platform OSINT ingestion" },
  { icon: Zap, label: "Coordinated-campaign & bot detection" },
  { icon: ShieldCheck, label: "Automated threat scoring & escalation" },
];

export default function Landing() {
  const navigate = useNavigate();
  const rootRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const ctx = gsap.context(() => {
      const tl = gsap.timeline({ defaults: { ease: "power3.out" } });
      tl.fromTo(".hero-logo", { scale: 0.4, opacity: 0, rotate: -18 }, { scale: 1, opacity: 1, rotate: 0, duration: 1 })
        .fromTo(".hero-letter", { y: 46, opacity: 0 }, { y: 0, opacity: 1, duration: 0.6, stagger: 0.055 }, "-=0.45")
        .fromTo(".hero-tagline", { y: 18, opacity: 0 }, { y: 0, opacity: 1, duration: 0.6 }, "-=0.2")
        .fromTo(".hero-feature", { y: 22, opacity: 0 }, { y: 0, opacity: 1, duration: 0.5, stagger: 0.09 }, "-=0.25")
        .fromTo(".hero-cta", { y: 20, opacity: 0, scale: 0.94 }, { y: 0, opacity: 1, scale: 1, duration: 0.55, ease: "back.out(1.7)" }, "-=0.2")
        .fromTo(".hero-foot", { opacity: 0 }, { opacity: 1, duration: 0.8 }, "-=0.2");
      gsap.to(".hero-logo", { y: -8, duration: 2.6, yoyo: true, repeat: -1, ease: "sine.inOut", delay: 1.2 });
    }, rootRef);
    return () => ctx.revert();
  }, []);

  return (
    <div ref={rootRef} className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden px-4">
      <BackgroundFX />

      <div className="hero-logo relative mb-8">
        <div className="absolute -inset-12 rounded-full bg-accent/20 blur-3xl" aria-hidden />
        <div className="absolute -inset-6 animate-pulse-slow rounded-full border border-accent/15" aria-hidden />
        <Logo size={92} />
      </div>

      <h1 className="flex font-mono text-5xl font-bold tracking-[0.3em] text-slate-200 sm:text-6xl" aria-label="E-RAKSHAK">
        {"E-RAKSHAK".split("").map((ch, i) => (
          <span key={i} className="hero-letter text-glow">
            {ch}
          </span>
        ))}
      </h1>

      <p className="hero-tagline mt-5 max-w-xl text-center text-sm leading-relaxed text-slate-400 sm:text-base">
        Real-Time OSINT Threat Intelligence — monitoring coordinated misinformation,
        incitement and organized abuse across social platforms, in the languages
        generic moderation misses.
      </p>

      <div className="mt-9 grid grid-cols-1 gap-3 sm:grid-cols-2">
        {FEATURES.map(({ icon: Icon, label }) => (
          <div key={label} className="hero-feature glass flex items-center gap-3 px-4 py-3">
            <span className="text-accent">
              <Icon size={16} />
            </span>
            <span className="text-xs text-slate-300">{label}</span>
          </div>
        ))}
      </div>

      <button
        onClick={() => navigate("/app")}
        className="hero-cta glow-accent group mt-10 inline-flex items-center gap-2 rounded-2xl border border-accent/50 bg-accent/15 px-8 py-3.5 text-sm font-bold tracking-wider text-accent transition-all duration-300 hover:bg-accent hover:text-base-900"
      >
        ENTER DASHBOARD
        <ArrowRight size={16} className="transition-transform duration-300 group-hover:translate-x-1" />
      </button>

      <p className="hero-foot mt-10 font-mono text-[10px] tracking-widest text-slate-600">
        E-RAKSHAK · STATE CYBER CELL HQ · AUTHORIZED PERSONNEL ONLY
      </p>
    </div>
  );
}
