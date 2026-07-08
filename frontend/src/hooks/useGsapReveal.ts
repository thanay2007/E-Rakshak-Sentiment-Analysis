import { gsap } from "gsap";
import { useLayoutEffect, useRef } from "react";

/** Staggered fade-in-up entrance for everything inside the container that
 *  carries the `.reveal-item` class. Re-runs when `dep` changes. */
export function useGsapReveal<T extends HTMLElement = HTMLDivElement>(dep?: unknown) {
  const ref = useRef<T>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const items = el.querySelectorAll(".reveal-item");
    if (!items.length) return;
    const ctx = gsap.context(() => {
      gsap.fromTo(
        items,
        { opacity: 0, y: 22 },
        { opacity: 1, y: 0, duration: 0.65, stagger: 0.07, ease: "power3.out", clearProps: "transform" }
      );
    }, el);
    return () => ctx.revert();
  }, [dep]);

  return ref;
}
