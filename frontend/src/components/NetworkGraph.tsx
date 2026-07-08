import {
  forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation,
} from "d3-force";
import type { Simulation } from "d3-force";
import { gsap } from "gsap";
import { useEffect, useRef, useState } from "react";
import { threatColor } from "../data/constants";
import type { NetLink, NetNode } from "../services/api";

interface SimNode extends NetNode {
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
  fx?: number | null;
  fy?: number | null;
  r: number;
}

interface SimLink {
  source: SimNode;
  target: SimNode;
  weight: number;
  kind: string;
}

/** Force-directed account graph on canvas: nodes sized by influence, colored
 *  by threat contribution, dashed red rings on suspected bot/coordinated
 *  accounts. GSAP fade-in intro; hover tooltip; click to focus edges; wheel zoom. */
export default function NetworkGraph({
  nodes,
  links,
  height = 560,
  onSelect,
}: {
  nodes: NetNode[];
  links: NetLink[];
  height?: number;
  onSelect?: (n: NetNode | null) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ n: SimNode; px: number; py: number } | null>(null);
  const stateRef = useRef<{
    sim?: Simulation<SimNode, undefined>;
    nodes: SimNode[];
    links: SimLink[];
    focus: SimNode | null;
    scale: number;
    tx: number;
    ty: number;
    alpha: number;
  }>({ nodes: [], links: [], focus: null, scale: 1, tx: 0, ty: 0, alpha: 0 });

  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap || !nodes.length) return;

    const dpr = window.devicePixelRatio || 1;
    const width = wrap.clientWidth;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    const ctx = canvas.getContext("2d")!;

    const st = stateRef.current;
    st.scale = 1;
    st.tx = 0;
    st.ty = 0;
    st.focus = null;

    const maxInf = Math.max(...nodes.map((n) => n.influence), 0.001);
    st.nodes = nodes.map((n) => ({
      ...n,
      r: 5 + Math.sqrt(n.influence / maxInf) * 16,
      x: width / 2 + (Math.random() - 0.5) * 220,
      y: height / 2 + (Math.random() - 0.5) * 220,
    }));
    const byId = new Map(st.nodes.map((n) => [n.id, n]));
    st.links = links
      .filter((l) => byId.has(l.source) && byId.has(l.target))
      .map((l) => ({
        source: byId.get(l.source)!,
        target: byId.get(l.target)!,
        weight: l.weight,
        kind: l.kind,
      }));

    st.sim?.stop();
    st.sim = forceSimulation(st.nodes)
      .force(
        "link",
        forceLink<SimNode, any>(st.links as any)
          .id((d: SimNode) => d.id)
          .distance((l: any) => (l.kind === "coordination" ? 55 : 110))
          .strength((l: any) => (l.kind === "coordination" ? 0.5 : 0.05))
      )
      .force("charge", forceManyBody().strength(-120))
      .force("center", forceCenter(width / 2, height / 2))
      .force("collide", forceCollide<SimNode>().radius((d) => d.r + 3));

    // GSAP intro: the whole graph fades/blooms in
    st.alpha = 0;
    gsap.to(st, { alpha: 1, duration: 1.4, ease: "power2.out" });

    let raf = 0;
    const draw = () => {
      ctx.save();
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);
      ctx.globalAlpha = st.alpha;
      ctx.translate(st.tx, st.ty);
      ctx.scale(st.scale, st.scale);

      const focus = st.focus;
      const neighbors = new Set<string>();
      if (focus) {
        neighbors.add(focus.id);
        for (const l of st.links) {
          if (l.source.id === focus.id) neighbors.add(l.target.id);
          if (l.target.id === focus.id) neighbors.add(l.source.id);
        }
      }

      // edges
      for (const l of st.links) {
        const inFocus = !focus || l.source.id === focus.id || l.target.id === focus.id;
        const base = l.kind === "coordination" ? "239,68,68" : "148,163,184";
        const a = inFocus ? (l.kind === "coordination" ? 0.34 : 0.1) : 0.03;
        ctx.strokeStyle = `rgba(${base},${a})`;
        ctx.lineWidth = l.kind === "coordination" ? Math.min(2.5, 0.7 + l.weight * 0.3) : 0.7;
        ctx.beginPath();
        ctx.moveTo(l.source.x!, l.source.y!);
        ctx.lineTo(l.target.x!, l.target.y!);
        ctx.stroke();
      }

      // nodes
      for (const n of st.nodes) {
        const dimmed = focus ? !neighbors.has(n.id) : false;
        const color = threatColor(n.threat);
        ctx.globalAlpha = st.alpha * (dimmed ? 0.15 : 1);

        if (n.threat >= 65 && !dimmed) {
          ctx.shadowColor = color;
          ctx.shadowBlur = 14;
        }
        ctx.beginPath();
        ctx.arc(n.x!, n.y!, n.r, 0, Math.PI * 2);
        ctx.fillStyle = `${color}cc`;
        ctx.fill();
        ctx.shadowBlur = 0;
        ctx.lineWidth = 1;
        ctx.strokeStyle = "rgba(10,14,26,0.9)";
        ctx.stroke();

        if (n.is_bot) {
          ctx.setLineDash([4, 3]);
          ctx.strokeStyle = "rgba(239,68,68,0.85)";
          ctx.lineWidth = 1.4;
          ctx.beginPath();
          ctx.arc(n.x!, n.y!, n.r + 4, 0, Math.PI * 2);
          ctx.stroke();
          ctx.setLineDash([]);
        }

        if ((n.r > 13 || focus?.id === n.id) && !dimmed) {
          ctx.font = "10px 'JetBrains Mono', monospace";
          ctx.fillStyle = "rgba(226,232,240,0.75)";
          ctx.textAlign = "center";
          ctx.fillText(`@${n.id}`, n.x!, n.y! + n.r + 12);
        }
      }
      ctx.restore();
      raf = requestAnimationFrame(draw);
    };
    draw();

    // interaction helpers
    const toWorld = (px: number, py: number) => ({
      x: (px - st.tx) / st.scale,
      y: (py - st.ty) / st.scale,
    });
    const hit = (px: number, py: number): SimNode | null => {
      const { x, y } = toWorld(px, py);
      for (let i = st.nodes.length - 1; i >= 0; i--) {
        const n = st.nodes[i];
        const dx = n.x! - x;
        const dy = n.y! - y;
        if (dx * dx + dy * dy <= (n.r + 4) * (n.r + 4)) return n;
      }
      return null;
    };

    let dragging: SimNode | null = null;
    let panning = false;
    let last = { x: 0, y: 0 };

    const pos = (e: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      return { x: e.clientX - rect.left, y: e.clientY - rect.top };
    };

    const onDown = (e: PointerEvent) => {
      const p = pos(e);
      const n = hit(p.x, p.y);
      if (n) {
        dragging = n;
        st.sim?.alphaTarget(0.25).restart();
      } else {
        panning = true;
      }
      last = p;
      canvas.setPointerCapture(e.pointerId);
    };
    const onMove = (e: PointerEvent) => {
      const p = pos(e);
      if (dragging) {
        const w = toWorld(p.x, p.y);
        dragging.fx = w.x;
        dragging.fy = w.y;
      } else if (panning) {
        st.tx += p.x - last.x;
        st.ty += p.y - last.y;
      } else {
        const n = hit(p.x, p.y);
        setHover(n ? { n, px: p.x, py: p.y } : null);
        canvas.style.cursor = n ? "pointer" : "grab";
      }
      last = p;
    };
    const onUp = (e: PointerEvent) => {
      const p = pos(e);
      const moved = Math.hypot(p.x - last.x, p.y - last.y);
      if (dragging) {
        dragging.fx = null;
        dragging.fy = null;
        st.sim?.alphaTarget(0);
        if (moved < 3) {
          st.focus = st.focus?.id === dragging.id ? null : dragging;
          onSelect?.(st.focus);
        }
        dragging = null;
      } else if (panning) {
        panning = false;
        if (moved < 3) {
          st.focus = null;
          onSelect?.(null);
        }
      }
    };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const px = e.clientX - rect.left;
      const py = e.clientY - rect.top;
      const factor = e.deltaY < 0 ? 1.12 : 0.89;
      const ns = Math.min(3.5, Math.max(0.4, st.scale * factor));
      // zoom around cursor
      st.tx = px - ((px - st.tx) / st.scale) * ns;
      st.ty = py - ((py - st.ty) / st.scale) * ns;
      st.scale = ns;
    };

    canvas.addEventListener("pointerdown", onDown);
    canvas.addEventListener("pointermove", onMove);
    canvas.addEventListener("pointerup", onUp);
    canvas.addEventListener("wheel", onWheel, { passive: false });

    return () => {
      cancelAnimationFrame(raf);
      st.sim?.stop();
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("pointermove", onMove);
      canvas.removeEventListener("pointerup", onUp);
      canvas.removeEventListener("wheel", onWheel);
    };
  }, [nodes, links, height, onSelect]);

  return (
    <div ref={wrapRef} className="relative w-full" style={{ height }}>
      <canvas ref={canvasRef} className="rounded-2xl" aria-label="Account interaction network" />
      {hover && (
        <div
          className="pointer-events-none absolute z-10 min-w-[180px] rounded-xl border border-white/10 bg-base-800/95 p-2.5 text-[11px] shadow-xl backdrop-blur-xl"
          style={{ left: Math.min(hover.px + 14, (wrapRef.current?.clientWidth ?? 300) - 200), top: hover.py + 10 }}
        >
          <div className="font-semibold text-slate-200">{hover.n.label}</div>
          <div className="font-mono text-slate-500">@{hover.n.id} · {hover.n.platform}</div>
          <div className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 font-mono text-slate-400">
            <span>threat {Math.round(hover.n.threat)}</span>
            <span>posts {hover.n.posts}</span>
            <span>infl {(hover.n.influence * 100).toFixed(1)}</span>
            <span>{hover.n.followers.toLocaleString()} fol</span>
          </div>
          {hover.n.is_bot && (
            <div className="mt-1 font-bold text-threat-critical">⚠ suspected coordinated account</div>
          )}
        </div>
      )}
      <div className="absolute bottom-3 left-3 flex flex-wrap gap-3 rounded-xl border border-white/[0.06] bg-base-900/70 px-3 py-1.5 text-[10px] text-slate-500 backdrop-blur">
        <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-threat-critical" />high threat</span>
        <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-threat-inflammatory" />elevated</span>
        <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-threat-neutral" />benign</span>
        <span className="text-threat-critical">◌ dashed = bot-like</span>
        <span>size = influence · drag / scroll / click</span>
      </div>
    </div>
  );
}
