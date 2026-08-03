import { AlertTriangle, RefreshCcw } from "lucide-react";
import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

interface Props {
  children: ReactNode;
  /** Remounts the subtree when this changes — used to clear the error on navigation. */
  resetKey?: unknown;
}
interface State {
  error: Error | null;
}

/** Catches render/lifecycle throws so one bad payload degrades a single view
 *  instead of blanking the whole command center. */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidUpdate(prev: Props) {
    if (this.state.error && prev.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="flex min-h-[60vh] items-center justify-center p-6">
        <div className="glass max-w-lg p-6 text-center">
          <AlertTriangle size={26} className="mx-auto text-threat-critical" />
          <h2 className="mt-3 text-sm font-bold uppercase tracking-wider text-slate-200">
            This view failed to render
          </h2>
          <p className="mt-1.5 text-xs leading-relaxed text-slate-500">
            The rest of the console is still live — switch views from the sidebar, or retry below.
          </p>
          <pre className="mt-3 overflow-x-auto rounded-xl bg-black/30 p-3 text-left font-mono text-[11px] leading-relaxed text-threat-critical">
            {error.message}
          </pre>
          <div className="mt-4 flex items-center justify-center gap-2">
            <button
              onClick={() => this.setState({ error: null })}
              className="inline-flex items-center gap-1.5 rounded-xl border border-accent/50 bg-accent/15 px-3.5 py-2 text-xs font-bold text-accent hover:bg-accent hover:text-base-900"
            >
              <RefreshCcw size={13} /> Retry
            </button>
            <button
              onClick={() => window.location.reload()}
              className="rounded-xl border border-white/[0.1] bg-white/[0.05] px-3.5 py-2 text-xs font-semibold text-slate-300 hover:border-accent/40 hover:text-accent"
            >
              Reload console
            </button>
          </div>
        </div>
      </div>
    );
  }
}
