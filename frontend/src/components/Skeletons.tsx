/** Shimmer loading states. */
export function SkeletonTile() {
  return <div className="shimmer h-[110px]" />;
}

export function SkeletonRow({ n = 6 }: { n?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: n }, (_, i) => (
        <div key={i} className="shimmer h-[84px]" />
      ))}
    </div>
  );
}

export function SkeletonChart({ h = 260 }: { h?: number }) {
  return <div className="shimmer" style={{ height: h }} />;
}
