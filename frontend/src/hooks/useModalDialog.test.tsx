import { useRef } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useModalDialog } from "./useModalDialog";

function Dialog({ name, onClose }: { name: string; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useModalDialog(true, onClose, ref);
  return <div ref={ref} role="dialog" aria-label={name} tabIndex={-1}>
    <button>{name} first</button><button>{name} last</button>
  </div>;
}

afterEach(() => { cleanup(); document.body.style.overflow = ""; });

describe("modal keyboard and scroll behavior", () => {
  it("keeps Tab inside the window, closes on Escape, and restores focus", async () => {
    const close = vi.fn();
    const opener = document.createElement("button");
    document.body.append(opener);
    opener.focus();
    const { unmount } = render(<Dialog name="Post" onClose={close} />);
    await waitFor(() => expect(screen.getByRole("dialog")).toHaveFocus());
    expect(document.body.style.overflow).toBe("hidden");
    fireEvent.keyDown(document, { key: "Tab" });
    expect(screen.getByText("Post first")).toHaveFocus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(screen.getByText("Post last")).toHaveFocus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(screen.getByText("Post first")).toHaveFocus();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(close).toHaveBeenCalledOnce();
    unmount();
    expect(document.body.style.overflow).toBe("");
    expect(opener).toHaveFocus();
    opener.remove();
  });

  it("only closes the top window and keeps scrolling locked until both close", async () => {
    const closeReport = vi.fn();
    const closePost = vi.fn();
    const { rerender, unmount } = render(<><Dialog name="Report" onClose={closeReport} /></>);
    await waitFor(() => expect(screen.getByRole("dialog", { name: "Report" })).toHaveFocus());
    screen.getByText("Report last").focus();
    rerender(<><Dialog name="Report" onClose={closeReport} /><Dialog name="Post" onClose={closePost} /></>);
    await waitFor(() => expect(screen.getByRole("dialog", { name: "Post" })).toHaveFocus());
    fireEvent.keyDown(document, { key: "Escape" });
    expect(closePost).toHaveBeenCalledOnce();
    expect(closeReport).not.toHaveBeenCalled();
    rerender(<><Dialog name="Report" onClose={closeReport} /></>);
    expect(document.body.style.overflow).toBe("hidden");
    expect(screen.getByText("Report last")).toHaveFocus();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(closeReport).toHaveBeenCalledOnce();
    unmount();
    expect(document.body.style.overflow).toBe("");
  });
});
