import { useState } from "react";
import { Bot, Image, Link2, Megaphone, UserSearch, AtSign } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import ImageTool from "../components/investigate/ImageTool";
import UsernameTool from "../components/investigate/UsernameTool";
import UrlTool from "../components/investigate/UrlTool";
import CommentsTool from "../components/investigate/CommentsTool";
import PrTool from "../components/investigate/PrTool";
import SleuthTool from "../components/investigate/SleuthTool";

interface Tool { id: string; label: string; icon: LucideIcon; el: React.ReactNode }

const TOOLS: Tool[] = [
  { id: "image", label: "Image & Reverse", icon: Image, el: <ImageTool /> },
  { id: "username", label: "Username Lookup", icon: AtSign, el: <UsernameTool /> },
  { id: "url", label: "Link / URL", icon: Link2, el: <UrlTool /> },
  { id: "comments", label: "Comments & Bots", icon: Bot, el: <CommentsTool /> },
  { id: "pr", label: "Fake PR", icon: Megaphone, el: <PrTool /> },
  { id: "sleuth", label: "Social Sleuth", icon: UserSearch, el: <SleuthTool /> },
];

export default function Investigate() {
  const [active, setActive] = useState("image");
  const tool = TOOLS.find((t) => t.id === active) ?? TOOLS[0];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-1.5">
        {TOOLS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setActive(id)}
            className={`inline-flex items-center gap-2 rounded-xl border px-3.5 py-2 text-[13px] font-medium transition-all ${
              active === id
                ? "border-accent/30 bg-accent/10 text-accent"
                : "border-white/[0.07] text-slate-400 hover:border-white/[0.15] hover:text-slate-200"
            }`}
          >
            <Icon size={15} /> {label}
          </button>
        ))}
      </div>
      {tool.el}
    </div>
  );
}
