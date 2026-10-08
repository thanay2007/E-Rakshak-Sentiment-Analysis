import { useEffect, useRef } from "react";
import type { RefObject } from "react";

// Only the top window handles keyboard input when a report opens post details.
const dialogs: symbol[] = [];
let originalOverflow = "";

export function useModalDialog(open: boolean, onClose: () => void, ref: RefObject<HTMLElement>) {
  const closeRef = useRef(onClose);
  useEffect(() => { closeRef.current = onClose; }, [onClose]);

  useEffect(() => {
    if (!open) return;
    const id = Symbol("dialog");
    const restoreTo = document.activeElement as HTMLElement | null;
    if (dialogs.length === 0) {
      originalOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
    }
    dialogs.push(id);
    const isTop = () => dialogs[dialogs.length - 1] === id;
    const onKeyDown = (event: KeyboardEvent) => {
      if (!isTop()) return;
      if (event.key === "Escape") {
        event.preventDefault();
        closeRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const panel = ref.current;
      const elements = panel?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );
      const focusables = Array.from(elements ?? []).filter(element => !element.closest('[hidden], [inert], [aria-hidden="true"]'));
      if (!focusables.length) {
        event.preventDefault();
        panel?.focus();
        return;
      }
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const active = document.activeElement;
      if (active === panel || !panel?.contains(active)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    const raf = window.requestAnimationFrame(() => { if (isTop()) ref.current?.focus(); });
    return () => {
      const wasTop = isTop();
      dialogs.splice(dialogs.indexOf(id), 1);
      document.removeEventListener("keydown", onKeyDown);
      window.cancelAnimationFrame(raf);
      if (!dialogs.length) document.body.style.overflow = originalOverflow;
      if (wasTop && restoreTo?.isConnected) restoreTo.focus();
    };
  }, [open, ref]);
}
