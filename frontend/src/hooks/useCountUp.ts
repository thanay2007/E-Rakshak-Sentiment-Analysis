import { gsap } from "gsap";
import { useEffect, useRef } from "react";

/** GSAP number count-up: animates the element's text to the target value
 *  every time it changes. */
export function useCountUp(value: number, duration = 1.1) {
  const ref = useRef<HTMLSpanElement>(null);
  const state = useRef({ v: 0 });

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const tween = gsap.to(state.current, {
      v: value,
      duration,
      ease: "power2.out",
      onUpdate: () => {
        el.textContent = Math.round(state.current.v).toLocaleString();
      },
    });
    return () => {
      tween.kill();
    };
  }, [value, duration]);

  return ref;
}
