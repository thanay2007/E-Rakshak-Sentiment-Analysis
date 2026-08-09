import { gsap } from "gsap";
import { Clock } from "lucide-react";
import { useCallback, useLayoutEffect, useRef, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import AlertToasts from "./AlertToasts";
import BackgroundFX from "./BackgroundFX";
import ErrorBoundary from "./ErrorBoundary";
import Sentinel from "./Sentinel";
import Sidebar from "./Sidebar";
import TopBar from "./TopBar";
import { useAuth } from "../hooks/useAuth";
import { useIdleLogout } from "../hooks/useIdleLogout";

/** App shell: sidebar + topbar + GSAP route transitions + global toasts. */
export default function Layout() {
  const [collapsed, setCollapsed] = useState(false);
  const mainRef = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const navigate = useNavigate();
  const { signOut } = useAuth();

  const endSession = useCallback(async () => {
    await signOut();
    navigate("/login", { replace: true });
  }, [navigate, signOut]);

  const { secondsLeft, staySignedIn } = useIdleLogout({ onTimeout: endSession });

  useLayoutEffect(() => {
    if (!mainRef.current) return;
    const tween = gsap.fromTo(
      mainRef.current,
      { opacity: 0, y: 16, filter: "blur(4px)" },
      { opacity: 1, y: 0, filter: "blur(0px)", duration: 0.55, ease: "power3.out" }
    );
    return () => {
      tween.kill();
    };
  }, [location.pathname]);

  return (
    <div className="min-h-screen">
      <BackgroundFX />
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} />
      <div
        className={`transition-[margin] duration-300 ${collapsed ? "ml-[68px]" : "ml-[240px]"}`}
      >
        <TopBar />
        <main ref={mainRef} className="mx-auto max-w-[1500px] p-4 lg:p-6">
          {/* keyed on the route so navigating away clears a crashed view */}
          <ErrorBoundary resetKey={location.pathname}>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
      <AlertToasts />
      <Sentinel />

      {secondsLeft !== null && (
        <div
          role="alertdialog"
          aria-live="assertive"
          className="fixed left-1/2 top-4 z-50 flex -translate-x-1/2 items-center gap-3 rounded-xl border border-amber-500/40 bg-base-900/95 px-4 py-2.5 backdrop-blur-xl"
        >
          <Clock size={14} className="text-amber-400" />
          <span className="text-[11px] text-amber-200">
            Signing out in {secondsLeft}s — this terminal has been idle.
          </span>
          <button
            onClick={staySignedIn}
            className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-2.5 py-1 text-[10px] font-semibold text-amber-200 hover:bg-amber-500/20"
          >
            I'm still here
          </button>
        </div>
      )}
    </div>
  );
}
