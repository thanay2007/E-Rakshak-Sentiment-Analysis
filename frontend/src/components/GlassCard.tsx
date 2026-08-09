import type { HTMLAttributes, ReactNode } from "react";

interface Props extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  hover?: boolean;
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
}: {
  title: string;
  sub?: string;
  right?: ReactNode;
}) {
  return (
    <div className="mb-4 flex items-start justify-between gap-3 shrink-0">
      <div className="min-w-0">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300 whitespace-nowrap">{title}</h2>
        {sub && <p className="mt-0.5 text-xs text-slate-500 truncate">{sub}</p>}
      </div>
      {right && <div className="shrink-0">{right}</div>}
    </div>
  );
}
