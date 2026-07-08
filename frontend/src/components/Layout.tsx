import { gsap } from "gsap";
import { useLayoutEffect, useRef, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import AlertToasts from "./AlertToasts";
import BackgroundFX from "./BackgroundFX";
import Sidebar from "./Sidebar";
import TopBar from "./TopBar";

/** App shell: sidebar + topbar + GSAP route transitions + global toasts. */
export default function Layout() {
  const [collapsed, setCollapsed] = useState(false);
  const mainRef = useRef<HTMLDivElement>(null);
  const location = useLocation();

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
        className={`transition-[margin] duration-300 ${collapsed ? "ml-[64px]" : "ml-[220px]"}`}
      >
        <TopBar />
        <main ref={mainRef} className="mx-auto max-w-[1500px] p-4 lg:p-6">
          <Outlet />
        </main>
      </div>
      <AlertToasts />
    </div>
  );
}
