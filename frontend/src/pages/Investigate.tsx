import { useState } from "react";
import { Bot, Image, Link2, Megaphone, UserSearch, AtSign, ShieldCheck } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import ImageTool from "../components/investigate/ImageTool";
import UsernameTool from "../components/investigate/UsernameTool";
import UrlTool from "../components/investigate/UrlTool";
import CommentsTool from "../components/investigate/CommentsTool";
import PrTool from "../components/investigate/PrTool";
import SleuthTool from "../components/investigate/SleuthTool";

interface Tool {
  id: string;
  label: string;
  desc: string;
  icon: LucideIcon;
  el: React.ReactNode;
}

const TOOLS: Tool[] = [
  {
    id: "image",
    label: "Image & Reverse Forensics",
    desc: "EXIF metadata, tampering heatmaps, deepfake probability & web reverse search",
    icon: Image,
    el: <ImageTool />,
  },
  {
    id: "username",
    label: "Cross-Platform Username",
    desc: "Enumerate social & messaging footprint across 100+ public platforms",
    icon: AtSign,
    el: <UsernameTool />,
  },
  {
    id: "url",
    label: "Phishing & URL Unroller",
    desc: "Unwrap shortened redirect chains and scan for phishing & obfuscation heuristics",
    icon: Link2,
    el: <UrlTool />,
  },
  {
    id: "comments",
    label: "Comment Bot Swarms",
    desc: "Analyze comment threads for bot coordinated amplification and sentiment skew",
    icon: Bot,
    el: <CommentsTool />,
  },
  {
    id: "pr",
    label: "Coordinated Narrative PR",
    desc: "Detect astroturfed law-and-order narratives and manufactured outrage",
    icon: Megaphone,
    el: <PrTool />,
  },
  {
    id: "sleuth",
    label: "Actor Sleuth & Dossier",
    desc: "Synthesize corpus footprint, bot scores, and network clusters into a case dossier",
    icon: UserSearch,
    el: <SleuthTool />,
  },
];

export default function Investigate() {
  const [active, setActive] = useState("image");
  const tool = TOOLS.find((t) => t.id === active) ?? TOOLS[0];

  return (
    <div className="space-y-4">
      {/* Tool Selector Tabs */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {TOOLS.map(({ id, label, icon: Icon }) => {
          const isActive = active === id;
          return (
            <button
              key={id}
              onClick={() => setActive(id)}
              className={`group flex flex-col items-center justify-center gap-2 rounded-2xl border p-3 text-center transition-all duration-150 ${
                isActive
                  ? "border-accent/60 bg-accent/15 text-accent shadow-[0_0_20px_-5px_rgba(20,184,196,0.3)] ring-1 ring-accent/30"
                  : "border-white/[0.08] bg-white/[0.02] text-slate-400 hover:border-white/20 hover:bg-white/[0.05] hover:text-slate-200"
              }`}
            >
              <div
                className={`rounded-xl p-2 transition-colors ${
                  isActive ? "bg-accent/20 text-accent" : "bg-white/[0.04] text-slate-400 group-hover:text-slate-200"
                }`}
              >
                <Icon size={18} />
              </div>
              <span className="text-xs font-semibold leading-tight">{label}</span>
            </button>
          );
        })}
      </div>

      {/* Active Tool Subtitle Banner */}
      <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] px-4 py-2 text-xs text-slate-300 flex items-center justify-between">
        <span className="text-slate-400">
          <strong className="text-slate-200">{tool.label}</strong>: {tool.desc}
        </span>
        <span className="hidden md:inline-flex items-center gap-1 font-mono text-[11px] text-accent">
          <ShieldCheck size={13} /> Active Cyber Forensic Module
        </span>
      </div>

      {tool.el}
    </div>
  );
}

