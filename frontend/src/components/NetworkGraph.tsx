import {
  forceCenter, forceCollide, forceLink, forceManyBody, forceRadial, forceSimulation,
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
  isolated: boolean;
}

interface SimLink {
  source: SimNode;
  target: SimNode;
  weight: number;
  kind: string;
}

const PLATFORM_RING: Record<string, string> = {
  X: "#E7E9EA",
  Reddit: "#FF4500",
  Facebook: "#1877F2",
  Instagram: "#E1306C",
  Telegram: "#229ED9",
};

/** Andrew monotone-chain convex hull for cluster envelopes. */
function hull(points: [number, number][]): [number, number][] {
  if (points.length < 3) return points;
  const pts = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const cross = (o: number[], a: number[], b: number[]) =>
    (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lower: [number, number][] = [];
  for (const p of pts) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop();
    lower.push(p);
  }
  const upper: [number, number][] = [];
  for (const p of [...pts].reverse()) {
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop();
    upper.push(p);
  }
  return lower.slice(0, -1).concat(upper.slice(0, -1));
}

/** Link-analysis board: force-directed graph on canvas in the style of an
 *  intel console — dotted grid backdrop, red envelopes around coordinated
 *  clusters, every account labeled, platform ring + threat fill, dashed rings
 *  on bot-like accounts, zoom toolbar. Isolated accounts are parked on an
 *  outer orbit so the connected core stays readable. */
export default function NetworkGraph({
  nodes,
  links,
  height = 620,
  focusId,
  onSelect,
}: {
  nodes: NetNode[];
  links: NetLink[];
  height?: number;
  focusId?: string | null;
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
    width: number;
  }>({ nodes: [], links: [], focus: null, scale: 1, tx: 0, ty: 0, alpha: 0, width: 0 });

  // external focus (e.g. clicking a row in the influencer table)
  useEffect(() => {
    const st = stateRef.current;
    st.focus = focusId ? st.nodes.find((n) => n.id === focusId) ?? null : null;
  }, [focusId]);

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
    st.width = width;

    const connected = new Set<string>();
    for (const l of links) {
      connected.add(l.source);
      connected.add(l.target);
    }

    const maxInf = Math.max(...nodes.map((n) => n.influence), 0.001);
    st.nodes = nodes.map((n, i) => {
      const isolated = !connected.has(n.id);
      // isolated accounts start on an outer ring, connected core in the middle
      const angle = (i / nodes.length) * Math.PI * 2;
      const dist = isolated ? Math.min(width, height) * 0.42 : 90 + Math.random() * 120;
      return {
        ...n,
        isolated,
        r: 6 + Math.sqrt(n.influence / maxInf) * 15,
        x: width / 2 + Math.cos(angle) * dist,
        y: height / 2 + Math.sin(angle) * dist,
      };
    });
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
          .distance((l: any) => (l.kind === "coordination" ? 60 : 120))
          .strength((l: any) => (l.kind === "coordination" ? 0.55 : 0.06))
      )
      .force("charge", forceManyBody().strength((d: any) => (d.isolated ? -30 : -140)))
      .force("center", forceCenter(width / 2, height / 2))
      .force(
        "orbit",
        forceRadial<SimNode>(
          Math.min(width, height) * 0.42,
          width / 2,
          height / 2
        ).strength((d) => (d.isolated ? 0.55 : 0))
      )
      .force("collide", forceCollide<SimNode>().radius((d) => d.r + 14));

    st.alpha = 0;
    gsap.to(st, { alpha: 1, duration: 1.2, ease: "power2.out" });

    let raf = 0;
    const draw = () => {
      ctx.save();
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);

      // dotted grid backdrop (screen space)
      ctx.fillStyle = "rgba(148,163,184,0.07)";
      for (let gx = 20; gx < width; gx += 34) {
        for (let gy = 20; gy < height; gy += 34) {
          ctx.fillRect(gx, gy, 1.2, 1.2);
        }
      }

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

      // cluster envelopes (under everything)
      const byCluster = new Map<string, SimNode[]>();
      for (const n of st.nodes) {
        if (n.cluster) {
          if (!byCluster.has(n.cluster)) byCluster.set(n.cluster, []);
          byCluster.get(n.cluster)!.push(n);
        }
      }
      for (const [cid, members] of byCluster) {
        if (members.length < 2) continue;
        const pts = hull(members.map((m) => [m.x!, m.y!] as [number, number]));
        if (pts.length < 2) continue;
        ctx.beginPath();
        ctx.moveTo(pts[0][0], pts[0][1]);
        for (const [px, py] of pts.slice(1)) ctx.lineTo(px, py);
        ctx.closePath();
        ctx.fillStyle = "rgba(239,68,68,0.06)";
        ctx.strokeStyle = "rgba(239,68,68,0.35)";
        ctx.lineWidth = 1.2;
        ctx.setLineDash([6, 4]);
        // expand visually via fat line join
        ctx.lineJoin = "round";
        ctx.fill();
        ctx.stroke();
        ctx.setLineDash([]);
        const cy = Math.min(...members.map((m) => m.y! - m.r));
        const cx = members.reduce((s, m) => s + m.x!, 0) / members.length;
        ctx.font = "bold 11px 'JetBrains Mono', monospace";
        ctx.fillStyle = "rgba(239,68,68,0.9)";
        ctx.textAlign = "center";
        ctx.fillText(`⚠ CLUSTER ${cid}`, cx, cy - 14);
      }

      // edges
      for (const l of st.links) {
        const inFocus = !focus || l.source.id === focus.id || l.target.id === focus.id;
        const base = l.kind === "coordination" ? "239,68,68" : "100,140,180";
        const a = inFocus ? (l.kind === "coordination" ? 0.45 : 0.16) : 0.03;
        ctx.strokeStyle = `rgba(${base},${a})`;
        ctx.lineWidth = l.kind === "coordination" ? Math.min(3, 0.9 + l.weight * 0.3) : 0.8;
        ctx.beginPath();
        ctx.moveTo(l.source.x!, l.source.y!);
        ctx.lineTo(l.target.x!, l.target.y!);
        ctx.stroke();
      }

      // nodes
      for (const n of st.nodes) {
        const dimmed = focus ? !neighbors.has(n.id) : false;
        const color = threatColor(n.threat);
        ctx.globalAlpha = st.alpha * (dimmed ? 0.13 : 1);

        if (n.threat >= 65 && !dimmed) {
          ctx.shadowColor = color;
          ctx.shadowBlur = 16;
        }
        ctx.beginPath();
        ctx.arc(n.x!, n.y!, n.r, 0, Math.PI * 2);
        ctx.fillStyle = `${color}d9`;
        ctx.fill();
        ctx.shadowBlur = 0;

        // platform ring
        ctx.lineWidth = 1.6;
        ctx.strokeStyle = `${PLATFORM_RING[n.platform] ?? "#64748B"}b8`;
        ctx.stroke();

        if (n.is_bot) {
          ctx.setLineDash([4, 3]);
          ctx.strokeStyle = "rgba(239,68,68,0.9)";
          ctx.lineWidth = 1.5;
          ctx.beginPath();
          ctx.arc(n.x!, n.y!, n.r + 4.5, 0, Math.PI * 2);
          ctx.stroke();
          ctx.setLineDash([]);
        }

        if (focus?.id === n.id) {
          ctx.strokeStyle = "rgba(20,184,196,0.95)";
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.arc(n.x!, n.y!, n.r + 8, 0, Math.PI * 2);
          ctx.stroke();
        }

        // label every account — dark halo so it stays readable on any color
        if (!dimmed && (st.scale >= 0.75 || n.r >= 12 || focus?.id === n.id)) {
          const label = `@${n.id.length > 18 ? n.id.slice(0, 17) + "…" : n.id}`;
          ctx.font = `${focus?.id === n.id ? "bold " : ""}10px 'JetBrains Mono', monospace`;
          ctx.textAlign = "center";
          ctx.lineWidth = 3;
          ctx.strokeStyle = "rgba(7,11,22,0.9)";
          ctx.strokeText(label, n.x!, n.y! + n.r + 13);
          ctx.fillStyle = focus?.id === n.id ? "#5EEAD4" : "rgba(226,232,240,0.85)";
          ctx.fillText(label, n.x!, n.y! + n.r + 13);
        }
      }
      ctx.restore();
      raf = requestAnimationFrame(draw);
    };
    draw();

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
      const ns = Math.min(3.5, Math.max(0.35, st.scale * factor));
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

  const zoom = (factor: number) => {
    const st = stateRef.current;
    const cx = st.width / 2;
    const cy = height / 2;
    const ns = factor === 0 ? 1 : Math.min(3.5, Math.max(0.35, st.scale * factor));
    if (factor === 0) {
      st.tx = 0;
      st.ty = 0;
      st.scale = 1;
      return;
    }
    st.tx = cx - ((cx - st.tx) / st.scale) * ns;
    st.ty = cy - ((cy - st.ty) / st.scale) * ns;
    st.scale = ns;
  };

  const clusterCount = new Set(nodes.filter((n) => n.cluster).map((n) => n.cluster)).size;

  return (
    <div ref={wrapRef} className="relative w-full" style={{ height }}>
      <canvas ref={canvasRef} className="rounded-2xl" aria-label="Account interaction network" />

      {/* board header chip */}
      <div className="absolute left-3 top-3 flex items-center gap-2 rounded-xl border border-white/[0.07] bg-base-900/80 px-3 py-1.5 font-mono text-[10px] text-slate-400 backdrop-blur">
        <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
        LINK ANALYSIS · {nodes.length} accounts · {links.length} links ·{" "}
        <span className={clusterCount ? "font-bold text-threat-critical" : ""}>
          {clusterCount} cluster{clusterCount === 1 ? "" : "s"}
        </span>
      </div>

      {/* zoom toolbar */}
      <div className="absolute right-3 top-3 flex flex-col overflow-hidden rounded-xl border border-white/[0.08] bg-base-900/80 backdrop-blur">
        {[
          ["+", () => zoom(1.3)],
          ["−", () => zoom(0.77)],
          ["⌂", () => zoom(0)],
        ].map(([label, fn]) => (
          <button
            key={label as string}
            onClick={fn as () => void}
            className="px-2.5 py-1.5 font-mono text-sm text-slate-400 transition-colors hover:bg-white/[0.07] hover:text-slate-200"
            aria-label={label === "⌂" ? "reset view" : label === "+" ? "zoom in" : "zoom out"}
          >
            {label as string}
          </button>
        ))}
      </div>

      {hover && (
        <div
          className="pointer-events-none absolute z-10 min-w-[190px] rounded-xl border border-white/10 bg-base-800/95 p-2.5 text-[11px] shadow-xl backdrop-blur-xl"
          style={{ left: Math.min(hover.px + 14, (wrapRef.current?.clientWidth ?? 300) - 210), top: hover.py + 10 }}
        >
          <div className="font-semibold text-slate-200">{hover.n.label}</div>
          <div className="font-mono text-slate-500">@{hover.n.id} · {hover.n.platform}</div>
          <div className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 font-mono text-slate-400">
            <span>threat {Math.round(hover.n.threat)}</span>
            <span>posts {hover.n.posts}</span>
            <span>infl {(hover.n.influence * 100).toFixed(1)}</span>
            <span>{hover.n.followers.toLocaleString()} fol</span>
          </div>
          {hover.n.cluster && (
            <div className="mt-1 font-mono text-[10px] text-threat-critical">cluster {hover.n.cluster}</div>
          )}
          {hover.n.is_bot && (
            <div className="mt-1 font-bold text-threat-critical">⚠ suspected coordinated account</div>
          )}
        </div>
      )}

      {/* legend */}
      <div className="absolute bottom-3 left-3 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-white/[0.06] bg-base-900/80 px-3 py-1.5 text-[10px] text-slate-500 backdrop-blur">
        <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-threat-critical" />high threat</span>
        <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-threat-inflammatory" />elevated</span>
        <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-threat-neutral" />benign</span>
        <span className="text-threat-critical">◌ bot-like</span>
        <span className="text-threat-critical/80">▨ red envelope = coordinated cluster</span>
        <span>ring = platform · size = influence</span>
      </div>
    </div>
  );
}
