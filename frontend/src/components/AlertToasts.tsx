import { gsap } from "gsap";
import { ShieldAlert, X } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { SEVERITY_COLORS } from "../data/constants";
import type { Alert } from "../services/api";
import { liveSocket } from "../services/ws";

interface Toast extends Alert {
  key: number;
}

function ToastCard({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const color = SEVERITY_COLORS[toast.severity] ?? "#14B8C4";

  useLayoutEffect(() => {
    if (!ref.current) return;
    gsap.fromTo(
      ref.current,
      { x: 110, opacity: 0, scale: 0.94 },
      { x: 0, opacity: 1, scale: 1, duration: 0.6, ease: "back.out(1.6)" }
    );
  }, []);

  useEffect(() => {
    const id = window.setTimeout(onDismiss, 8000);
    return () => window.clearTimeout(id);
  }, [onDismiss]);

  return (
    <div
      ref={ref}
      className="glass pointer-events-auto w-80 cursor-pointer border-l-2 p-3"
      style={{ borderLeftColor: color, boxShadow: `0 0 26px -8px ${color}88` }}
      onClick={() => navigate("/app/alerts")}
      role="alert"
    >
      <div className="flex items-start gap-2.5">
        <span className="mt-0.5 shrink-0" style={{ color }}>
          <ShieldAlert size={16} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span
              className="text-[10px] font-bold uppercase tracking-widest"
              style={{ color }}
            >
              {toast.severity} alert
            </span>
            <span className="font-mono text-[10px] text-slate-500">
              score {Math.round(toast.threat_score)}
            </span>
          </div>
          <p className="mt-0.5 truncate text-[12.5px] font-semibold text-slate-200">{toast.title}</p>
          <p className="mt-0.5 line-clamp-2 text-[11px] text-slate-400">{toast.summary}</p>
        </div>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDismiss();
          }}
          className="rounded p-1 text-slate-500 hover:bg-white/10"
          aria-label="Dismiss"
        >
          <X size={12} />
        </button>
      </div>
    </div>
  );
}

/** Global GSAP toast stack for incoming critical/high alerts via WebSocket. */
export default function AlertToasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const counter = useRef(0);

  useEffect(() => {
    liveSocket.start();
    return liveSocket.subscribe((msg) => {
      if (msg.type === "alert" && (msg.data.severity === "critical" || msg.data.severity === "high")) {
        const t: Toast = { ...msg.data, key: counter.current++ };
        setToasts((prev) => [t, ...prev].slice(0, 4));
      }
    });
  }, []);

  return (
    <div className="pointer-events-none fixed right-4 top-16 z-[60] flex flex-col gap-2">
      {toasts.map((t) => (
        <ToastCard
          key={t.key}
          toast={t}
          onDismiss={() => setToasts((prev) => prev.filter((x) => x.key !== t.key))}
        />
      ))}
    </div>
  );
}
