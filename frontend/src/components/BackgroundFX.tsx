/** Ambient command-center backdrop: subtle static gradient mesh. */
export default function BackgroundFX() {
  return (
    <div aria-hidden className="fixed inset-0 -z-10 pointer-events-none overflow-hidden">
      <div className="absolute inset-0 bg-base-900 transition-colors duration-300" />
      <div className="absolute inset-0 gradient-mesh opacity-60" />
    </div>
  );
}
