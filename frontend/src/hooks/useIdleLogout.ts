/** Sign an idle session out.
 *
 *  These are shared station terminals. The realistic compromise here is not a
 *  remote attacker — it is an unlocked dashboard left open while the officer
 *  handles something else, in a room with other people in it. sessionStorage
 *  already ends the session when the browser closes; this covers the much more
 *  common case where nobody closes anything.
 *
 *  The warning window matters: an analyst reading a long dossier is idle by
 *  every measure this hook can see, and dumping them to the sign-in screen
 *  mid-read would train them to keep a second tab open just to stay alive.
 */
import { useEffect, useRef, useState } from "react";

/** Events that count as "someone is still here". `scroll` and `keydown` cover
 *  reading and typing; pointer events cover everything else. */
const ACTIVITY = ["mousedown", "keydown", "scroll", "touchstart", "pointermove"] as const;

export interface IdleOptions {
  /** Minutes of inactivity before the session ends. */
  timeoutMinutes?: number;
  /** Minutes before that at which to warn. */
  warnMinutes?: number;
  onTimeout: () => void;
  enabled?: boolean;
}

export function useIdleLogout({
  timeoutMinutes = 20,
  warnMinutes = 2,
  onTimeout,
  enabled = true,
}: IdleOptions) {
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);
  const deadline = useRef(0);
  const onTimeoutRef = useRef(onTimeout);
  onTimeoutRef.current = onTimeout;

  useEffect(() => {
    if (!enabled) {
      setSecondsLeft(null);
      return;
    }

    const total = timeoutMinutes * 60_000;
    const warnAt = warnMinutes * 60_000;
    const reset = () => {
      deadline.current = Date.now() + total;
      setSecondsLeft(null);
    };
    reset();

    // `passive` so a pointermove listener on every page cannot make scrolling
    // janky — this hook must never be the reason the dashboard feels slow.
    ACTIVITY.forEach((event) =>
      window.addEventListener(event, reset, { passive: true })
    );

    // Wall-clock deadline rather than a decrementing counter: a laptop that
    // sleeps for an hour freezes timers, and a counter would resume as though
    // no time had passed at all.
    const tick = window.setInterval(() => {
      const remaining = deadline.current - Date.now();
      if (remaining <= 0) {
        setSecondsLeft(null);
        onTimeoutRef.current();
        return;
      }
      setSecondsLeft(remaining <= warnAt ? Math.ceil(remaining / 1000) : null);
    }, 1000);

    return () => {
      ACTIVITY.forEach((event) => window.removeEventListener(event, reset));
      window.clearInterval(tick);
    };
  }, [enabled, timeoutMinutes, warnMinutes]);

  return {
    /** Seconds remaining, but only inside the warning window. */
    secondsLeft,
    staySignedIn: () => {
      deadline.current = Date.now() + timeoutMinutes * 60_000;
      setSecondsLeft(null);
    },
  };
}
