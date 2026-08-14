import { HelpCircle } from "lucide-react";
import type { HTMLAttributes, ReactNode } from "react";

interface Props extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  hover?: boolean;
}

/** A "what am I looking at" marker for a panel heading.
 *
 *  Styled rather than a native `title=` attribute, for two reasons that matter
 *  in a control room: the native tooltip waits about a second before it
 *  appears, which is long enough that an officer scanning the screen never
 *  discovers it exists; and it renders in the OS theme, which on a dark
 *  console reads as a rendering fault rather than help.
 *
 *  `normal-case` and `tracking-normal` are set explicitly because these sit
 *  inside uppercase, letter-spaced headings, and a paragraph of explanation
 *  inherited into all-caps is harder to read than no explanation at all.
 */
export function InfoHint({ text, label }: { text: string; label?: string }) {
  return (
    <span className="group/hint relative inline-flex shrink-0 items-center">
      <HelpCircle
        size={12}
        className="cursor-help text-slate-500 transition-colors group-hover/hint:text-accent"
        aria-hidden="true"
      />
      {/* The accessible copy of the same text: the icon is decorative, so a
          screen reader gets the explanation rather than the word "help". */}
      <span className="sr-only">{label ?? text}</span>
      <span
        role="tooltip"
        className="pointer-events-none absolute left-0 top-full z-30 mt-2 w-60 rounded-xl border border-white/10
                   bg-base-900/95 p-2.5 text-[11px] font-normal normal-case leading-relaxed tracking-normal
                   text-slate-300 opacity-0 shadow-xl shadow-black/40 backdrop-blur-md transition-opacity
                   duration-150 group-hover/hint:opacity-100"
      >
        {text}
      </span>
    </span>
  );
}

export default function GlassCard({ children, hover = false, className = "", ...rest }: Props) {
  return (
    <div className={`glass ${hover ? "glass-hover" : ""} ${className}`} {...rest}>
      {children}
    </div>
  );
}

export function SectionTitle({
  title,
  sub,
  right,
  hint,
}: {
  title: string;
  sub?: string;
  right?: ReactNode;
  /** One or two sentences on what this panel is showing and what to do with
   *  it. Rendered as a hover marker beside the heading. */
  hint?: string;
}) {
  return (
    <div className="mb-4 flex items-start justify-between gap-3 shrink-0">
      <div className="min-w-0">
        <div className="flex items-center gap-1.5">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300 whitespace-nowrap">{title}</h2>
          {hint && <InfoHint text={hint} label={`About ${title}`} />}
        </div>
        {sub && <p className="mt-0.5 text-xs text-slate-500 truncate">{sub}</p>}
      </div>
      {right && <div className="shrink-0">{right}</div>}
    </div>
  );
}
