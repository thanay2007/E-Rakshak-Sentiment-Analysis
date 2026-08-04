import {
  AlertTriangle, CheckCircle2, Clock, KeyRound, Loader2, Lock, Plus,
  RefreshCcw, ScrollText, ShieldCheck, UserMinus, Users,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import GlassCard, { SectionTitle } from "../components/GlassCard";
import { useAuth } from "../hooks/useAuth";
import { api } from "../services/api";
import type {
  AuditEntry, NewOfficer, Officer, PostureCheck, SecurityPosture,
} from "../services/api";

type Tab = "officers" | "audit" | "posture";

const TABS: { id: Tab; label: string; icon: typeof Users }[] = [
  { id: "officers", label: "Officers", icon: Users },
  { id: "audit", label: "Audit Trail", icon: ScrollText },
  { id: "posture", label: "Security Posture", icon: ShieldCheck },
];

const ROLE_NOTE: Record<string, string> = {
  analyst: "Read the feed, investigate, generate reports",
  supervisor: "Analyst, plus escalation, bulk export and registry deletion",
  admin: "Everything, plus officer accounts and the operations toolkit",
};

const SEVERITY_STYLE: Record<string, string> = {
  critical: "border-red-500/30 bg-red-500/10 text-red-300",
  high: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  medium: "border-sky-500/30 bg-sky-500/10 text-sky-300",
  info: "border-white/10 bg-white/[0.04] text-slate-400",
};

function when(iso: string | null): string {
  if (!iso) return "never";
  const d = new Date(iso.endsWith("Z") ? iso : `${iso}Z`);
  return d.toLocaleString("en-IN", { hour12: false });
}

const inputCls =
  "w-full rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-xs " +
  "text-slate-100 placeholder-slate-600 outline-none focus:border-accent/50";

export default function AdminPanel() {
  const { user } = useAuth();
  const [tab, setTab] = useState<Tab>("officers");

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-bold tracking-wide text-slate-100">Admin Panel</h1>
        <p className="mt-1 text-xs text-slate-500">
          Signed in as{" "}
          <span className="font-mono text-slate-400">{user?.username}</span> ·{" "}
          {user?.role}. Every action on this page is written to the audit trail
          against your badge.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`flex items-center gap-2 rounded-xl border px-4 py-2 text-xs font-semibold transition-colors ${
              tab === id
                ? "border-accent/40 bg-accent/10 text-accent"
                : "border-white/[0.08] text-slate-400 hover:bg-white/[0.05] hover:text-slate-200"
            }`}
          >
            <Icon size={14} />
            {label}
          </button>
        ))}
      </div>

      {tab === "officers" && <OfficersTab />}
      {tab === "audit" && <AuditTab />}
      {tab === "posture" && <PostureTab />}
    </div>
  );
}

// ── Officers ────────────────────────────────────────────────────────────────

function OfficersTab() {
  const { user } = useAuth();
  const [rows, setRows] = useState<Officer[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);

  const load = useCallback(async () => {
    try {
      setRows(await api.officers());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (id: string, label: string, fn: () => Promise<unknown>) => {
    setBusy(id);
    setError(null);
    setNotice(null);
    try {
      await fn();
      setNotice(label);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-4">
      {error && <Banner tone="error">{error}</Banner>}
      {notice && <Banner tone="ok">{notice}</Banner>}

      <GlassCard className="p-5">
        <SectionTitle
          title="Officer accounts"
          sub="Rank decides what the server will allow, not what the UI shows."
          right={
            <button
              onClick={() => setShowCreate((s) => !s)}
              className="flex items-center gap-1.5 rounded-xl border border-accent/40 bg-accent/10 px-3 py-1.5 text-[11px] font-semibold text-accent hover:bg-accent/20"
            >
              <Plus size={13} />
              New officer
            </button>
          }
        />

        {showCreate && (
          <CreateOfficer
            onDone={async (msg) => {
              setShowCreate(false);
              setNotice(msg);
              await load();
            }}
            onError={setError}
          />
        )}

        {loading ? (
          <p className="py-6 text-center text-xs text-slate-500">Loading…</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-xs">
              <thead>
                <tr className="border-b border-white/[0.06] text-[10px] uppercase tracking-wider text-slate-500">
                  <th className="py-2 pr-3">Officer</th>
                  <th className="py-2 pr-3">Rank</th>
                  <th className="py-2 pr-3">Unit / badge</th>
                  <th className="py-2 pr-3">Last sign-in</th>
                  <th className="py-2 pr-3">Status</th>
                  <th className="py-2 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((o) => {
                  const isSelf = o.id === user?.id;
                  return (
                    <tr key={o.id} className="border-b border-white/[0.04] align-middle">
                      <td className="py-2.5 pr-3">
                        <div className="font-medium text-slate-200">
                          {o.full_name || o.username}
                        </div>
                        <div className="font-mono text-[10px] text-slate-600">
                          {o.username}
                          {isSelf && " · you"}
                        </div>
                      </td>
                      <td className="py-2.5 pr-3">
                        <select
                          value={o.role}
                          disabled={isSelf || busy === o.id}
                          title={isSelf ? "You cannot change your own rank" : ROLE_NOTE[o.role]}
                          onChange={(e) =>
                            act(o.id, `${o.username} is now ${e.target.value}.`, () =>
                              api.updateOfficer(o.id, { role: e.target.value as Officer["role"] })
                            )
                          }
                          className="rounded-lg border border-white/[0.08] bg-base-800 px-2 py-1 text-[11px] text-slate-300 disabled:opacity-40"
                        >
                          {Object.keys(ROLE_NOTE).map((r) => (
                            <option key={r} value={r}>
                              {r}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="py-2.5 pr-3 text-slate-400">
                        {[o.unit, o.badge_number].filter(Boolean).join(" · ") || "—"}
                      </td>
                      <td className="py-2.5 pr-3 font-mono text-[10px] text-slate-500">
                        {when(o.last_login_at)}
                      </td>
                      <td className="py-2.5 pr-3">
                        {!o.active ? (
                          <Pill tone="off">deactivated</Pill>
                        ) : o.must_change_password ? (
                          <Pill tone="warn">password change due</Pill>
                        ) : (
                          <Pill tone="ok">active</Pill>
                        )}
                      </td>
                      <td className="py-2.5">
                        <div className="flex items-center justify-end gap-1.5">
                          <ResetPassword
                            officer={o}
                            onDone={(msg) => act(o.id, msg, async () => {})}
                            onError={setError}
                          />
                          <button
                            disabled={isSelf || !o.active || busy === o.id}
                            onClick={() => {
                              if (
                                !window.confirm(
                                  `Deactivate ${o.username}? Their sessions end immediately. ` +
                                    `The account is kept, not deleted, so the audit trail still ` +
                                    `resolves their past actions.`
                                )
                              )
                                return;
                              void act(o.id, `${o.username} deactivated.`, () =>
                                api.deactivateOfficer(o.id)
                              );
                            }}
                            title={isSelf ? "You cannot deactivate yourself" : "Deactivate"}
                            className="rounded-lg border border-white/[0.08] p-1.5 text-slate-500 hover:border-red-500/30 hover:text-red-300 disabled:opacity-30 disabled:hover:border-white/[0.08] disabled:hover:text-slate-500"
                          >
                            {busy === o.id ? (
                              <Loader2 size={13} className="animate-spin" />
                            ) : (
                              <UserMinus size={13} />
                            )}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>
    </div>
  );
}

function CreateOfficer({
  onDone,
  onError,
}: {
  onDone: (msg: string) => void | Promise<void>;
  onError: (msg: string) => void;
}) {
  const [form, setForm] = useState<NewOfficer>({
    username: "",
    password: "",
    full_name: "",
    badge_number: "",
    unit: "",
    role: "analyst",
  });
  const [busy, setBusy] = useState(false);

  const set = (k: keyof NewOfficer) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    onError("");
    try {
      const created = await api.createOfficer(form);
      await onDone(
        `Created ${created.username}. They must set their own password at first sign-in.`
      );
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      onSubmit={submit}
      className="mb-4 grid gap-2.5 rounded-xl border border-white/[0.08] bg-white/[0.02] p-4 sm:grid-cols-2 lg:grid-cols-3"
    >
      <input className={inputCls} placeholder="Username" required value={form.username} onChange={set("username")} />
      <input className={inputCls} placeholder="Full name" value={form.full_name} onChange={set("full_name")} />
      <input className={inputCls} placeholder="Badge number" value={form.badge_number} onChange={set("badge_number")} />
      <input className={inputCls} placeholder="Unit / station" value={form.unit} onChange={set("unit")} />
      <select className={inputCls} value={form.role} onChange={set("role")}>
        {Object.entries(ROLE_NOTE).map(([r, note]) => (
          <option key={r} value={r} title={note}>
            {r}
          </option>
        ))}
      </select>
      <input
        className={inputCls}
        type="password"
        placeholder="Temporary password (12+ chars)"
        autoComplete="new-password"
        required
        value={form.password}
        onChange={set("password")}
      />
      <div className="sm:col-span-2 lg:col-span-3 flex items-center gap-3">
        <button
          type="submit"
          disabled={busy}
          className="flex items-center gap-1.5 rounded-xl border border-accent/40 bg-accent/10 px-4 py-2 text-[11px] font-semibold text-accent hover:bg-accent/20 disabled:opacity-50"
        >
          {busy && <Loader2 size={13} className="animate-spin" />}
          Create officer
        </button>
        <p className="text-[10px] leading-relaxed text-slate-600">
          The password you set here is temporary — the officer is forced to
          replace it before they can use anything, so you never know their
          working credential.
        </p>
      </div>
    </form>
  );
}

function ResetPassword({
  officer,
  onDone,
  onError,
}: {
  officer: Officer;
  onDone: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.resetOfficerPassword(officer.id, pw);
      setOpen(false);
      setPw("");
      onDone(
        `Password reset for ${officer.username}. Their sessions ended and they must set a new one.`
      );
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        title="Reset password"
        className="rounded-lg border border-white/[0.08] p-1.5 text-slate-500 hover:border-accent/30 hover:text-accent"
      >
        <KeyRound size={13} />
      </button>
    );
  }
  return (
    <form onSubmit={submit} className="flex items-center gap-1.5">
      <input
        className="w-44 rounded-lg border border-white/[0.08] bg-white/[0.04] px-2 py-1 text-[11px] text-slate-100 outline-none focus:border-accent/50"
        type="password"
        autoFocus
        required
        placeholder="Temporary password"
        autoComplete="new-password"
        value={pw}
        onChange={(e) => setPw(e.target.value)}
      />
      <button
        type="submit"
        disabled={busy}
        className="rounded-lg border border-accent/40 bg-accent/10 px-2 py-1 text-[10px] font-semibold text-accent disabled:opacity-50"
      >
        {busy ? "…" : "Set"}
      </button>
      <button
        type="button"
        onClick={() => {
          setOpen(false);
          setPw("");
        }}
        className="rounded-lg border border-white/[0.08] px-2 py-1 text-[10px] text-slate-500"
      >
        Cancel
      </button>
    </form>
  );
}

// ── Audit trail ─────────────────────────────────────────────────────────────

function AuditTab() {
  const [rows, setRows] = useState<AuditEntry[]>([]);
  const [action, setAction] = useState("");
  const [actor, setActor] = useState("");
  const [limit, setLimit] = useState(100);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await api.auditLog({ limit, action: action.trim(), actor: actor.trim() }));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [action, actor, limit]);

  useEffect(() => {
    void load();
  }, [load]);

  // Offered as a datalist rather than a fixed dropdown: the action vocabulary
  // grows whenever a new call site logs something, and a hardcoded list would
  // quietly stop matching.
  const actions = useMemo(
    () => Array.from(new Set(rows.map((r) => r.action))).sort(),
    [rows]
  );

  return (
    <div className="space-y-4">
      {error && <Banner tone="error">{error}</Banner>}
      <GlassCard className="p-5">
        <SectionTitle
          title="Chain of custody"
          sub="Append-only — the database refuses UPDATE and DELETE on this table."
          right={
            <button
              onClick={() => void load()}
              className="flex items-center gap-1.5 rounded-xl border border-white/[0.08] px-3 py-1.5 text-[11px] text-slate-400 hover:bg-white/[0.05]"
            >
              <RefreshCcw size={13} className={loading ? "animate-spin" : ""} />
              Refresh
            </button>
          }
        />

        <div className="mb-4 flex flex-wrap gap-2">
          <input
            list="audit-actions"
            className={`${inputCls} max-w-[220px]`}
            placeholder="Filter by action"
            value={action}
            onChange={(e) => setAction(e.target.value)}
          />
          <datalist id="audit-actions">
            {actions.map((a) => (
              <option key={a} value={a} />
            ))}
          </datalist>
          <input
            className={`${inputCls} max-w-[200px]`}
            placeholder="Filter by officer username"
            value={actor}
            onChange={(e) => setActor(e.target.value)}
          />
          <select
            className={`${inputCls} max-w-[130px]`}
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
          >
            {[50, 100, 250, 500].map((n) => (
              <option key={n} value={n}>
                last {n}
              </option>
            ))}
          </select>
        </div>

        {rows.length === 0 && !loading ? (
          <p className="py-6 text-center text-xs text-slate-500">
            No entries match that filter.
          </p>
        ) : (
          <div className="max-h-[560px] overflow-auto">
            <table className="w-full min-w-[820px] text-left text-xs">
              <thead className="sticky top-0 bg-base-900/90 backdrop-blur">
                <tr className="border-b border-white/[0.06] text-[10px] uppercase tracking-wider text-slate-500">
                  <th className="py-2 pr-3">When</th>
                  <th className="py-2 pr-3">Action</th>
                  <th className="py-2 pr-3">Officer</th>
                  <th className="py-2 pr-3">From</th>
                  <th className="py-2">Detail</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="border-b border-white/[0.04] align-top">
                    <td className="whitespace-nowrap py-2 pr-3 font-mono text-[10px] text-slate-500">
                      {when(r.created_at)}
                    </td>
                    <td className="py-2 pr-3">
                      <span
                        className={`rounded-md border px-1.5 py-0.5 font-mono text-[10px] ${
                          r.action.includes("failed") || r.action.includes("refused")
                            ? "border-amber-500/25 bg-amber-500/10 text-amber-300"
                            : "border-white/10 bg-white/[0.04] text-slate-400"
                        }`}
                      >
                        {r.action}
                      </span>
                    </td>
                    <td className="py-2 pr-3 text-slate-300">
                      {r.actor_username || <span className="text-slate-600">unauthenticated</span>}
                      {r.actor_role && (
                        <span className="ml-1 text-[10px] text-slate-600">({r.actor_role})</span>
                      )}
                    </td>
                    <td className="py-2 pr-3 font-mono text-[10px] text-slate-500">
                      {r.ip || "—"}
                    </td>
                    <td className="py-2 font-mono text-[10px] leading-relaxed text-slate-500">
                      {Object.keys(r.details || {}).length
                        ? JSON.stringify(r.details)
                        : r.target_id || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>
    </div>
  );
}

// ── Security posture ────────────────────────────────────────────────────────

function PostureTab() {
  const [data, setData] = useState<SecurityPosture | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .securityPosture()
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  if (error) return <Banner tone="error">{error}</Banner>;
  if (!data) return <p className="py-6 text-center text-xs text-slate-500">Loading…</p>;

  const order = { critical: 0, high: 1, medium: 2, info: 3 };
  const checks = [...data.checks].sort(
    (a, b) =>
      Number(a.ok) - Number(b.ok) ||
      order[a.severity] - order[b.severity]
  );

  return (
    <div className="space-y-4">
      <GlassCard className="p-5">
        <SectionTitle
          title="Security posture"
          sub={
            data.failing === 0
              ? "Every check passes on this instance."
              : `${data.failing} check${data.failing === 1 ? "" : "s"} need attention before this holds real case data.`
          }
        />
        <div className="grid gap-2.5">
          {checks.map((c) => (
            <PostureRow key={c.key} check={c} />
          ))}
        </div>
      </GlassCard>

      <GlassCard className="p-5">
        <SectionTitle title="Accounts" />
        <div className="grid gap-3 sm:grid-cols-3">
          <Stat label="Active officers" value={data.accounts.active} />
          <Stat label="Administrators" value={data.accounts.admins} />
          <Stat label="Total on record" value={data.accounts.total} />
        </div>
        {data.accounts.pending_password_change.length > 0 && (
          <p className="mt-4 flex items-start gap-2 rounded-xl border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-300">
            <Clock size={13} className="mt-px shrink-0" />
            <span>
              Password change outstanding:{" "}
              {data.accounts.pending_password_change.join(", ")}. These accounts
              cannot reach anything but the change-password screen.
            </span>
          </p>
        )}
        {data.accounts.locked_out.length > 0 && (
          <p className="mt-2 flex items-start gap-2 rounded-xl border border-red-500/25 bg-red-500/10 px-3 py-2 text-[11px] text-red-300">
            <Lock size={13} className="mt-px shrink-0" />
            <span>
              Locked out after repeated failed sign-ins:{" "}
              {data.accounts.locked_out.join(", ")}. Locks clear themselves; a
              reset here clears one immediately.
            </span>
          </p>
        )}
      </GlassCard>
    </div>
  );
}

function PostureRow({ check }: { check: PostureCheck }) {
  return (
    <div
      className={`flex items-start gap-3 rounded-xl border px-4 py-3 ${
        check.ok ? "border-white/[0.06] bg-white/[0.02]" : SEVERITY_STYLE[check.severity]
      }`}
    >
      {check.ok ? (
        <CheckCircle2 size={15} className="mt-px shrink-0 text-threat-neutral" />
      ) : (
        <AlertTriangle size={15} className="mt-px shrink-0" />
      )}
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-slate-200">{check.title}</span>
          {!check.ok && (
            <span className="rounded-md border border-current px-1.5 py-px font-mono text-[9px] uppercase tracking-wider">
              {check.severity}
            </span>
          )}
        </div>
        <p
          className={`mt-1 text-[11px] leading-relaxed ${
            check.ok ? "text-slate-500" : "opacity-90"
          }`}
        >
          {check.detail}
        </p>
      </div>
    </div>
  );
}

// ── shared bits ─────────────────────────────────────────────────────────────

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] px-4 py-3">
      <div className="font-mono text-xl font-bold text-slate-100">{value}</div>
      <div className="mt-0.5 text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
    </div>
  );
}

function Pill({ tone, children }: { tone: "ok" | "warn" | "off"; children: React.ReactNode }) {
  const cls = {
    ok: "border-threat-neutral/30 bg-threat-neutral/10 text-threat-neutral",
    warn: "border-amber-500/30 bg-amber-500/10 text-amber-300",
    off: "border-white/10 bg-white/[0.04] text-slate-500",
  }[tone];
  return (
    <span className={`rounded-md border px-1.5 py-0.5 text-[10px] ${cls}`}>{children}</span>
  );
}

function Banner({ tone, children }: { tone: "error" | "ok"; children: React.ReactNode }) {
  if (!children) return null;
  const cls =
    tone === "error"
      ? "border-red-500/30 bg-red-500/10 text-red-300"
      : "border-threat-neutral/30 bg-threat-neutral/10 text-threat-neutral";
  return (
    <p className={`rounded-xl border px-3 py-2 text-[11px] ${cls}`}>{children}</p>
  );
}
