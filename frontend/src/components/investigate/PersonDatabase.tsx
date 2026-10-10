import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronUp, ExternalLink, ImagePlus, Loader2, Trash2, UserPlus, X } from "lucide-react";
import GlassCard from "../GlassCard";
import { api } from "../../services/api";
import type { FaceEngine, IdentityDossier, PersonEnrolFields, Suspect } from "../../services/api";
import { safeHref } from "../../lib/safeUrl";
import { usePostDetail } from "../PostDetailProvider";
import { categoryForRecordType, CATEGORY_COLOR, CATEGORY_LABEL } from "../../data/dummyIdentities";
import { Pill, RunButton } from "./shared";

const inputCls =
  "w-full rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-[13px] " +
  "text-slate-100 placeholder-slate-600 outline-none focus:border-accent/50";

const RECORD_TYPES: [string, string][] = [
  ["person_of_interest", "Person of interest"],
  ["wanted", "Wanted"],
  ["criminal", "Criminal record"],
  ["missing", "Missing person"],
  ["cleared", "No record / cleared"],
];
const RISK_LEVELS = ["low", "medium", "high", "critical"];
const STATUSES: [string, string][] = [
  ["under_investigation", "Under investigation"],
  ["at_large", "At large"],
  ["in_custody", "In custody"],
  ["on_bail", "On bail"],
  ["convicted", "Convicted"],
  ["acquitted", "Acquitted"],
  ["cleared", "Cleared"],
];

const EMPTY: PersonEnrolFields = {
  full_name: "", notes: "", record_type: "person_of_interest", risk_level: "medium",
  status: "under_investigation", aliases: "", last_known_location: "",
  social_handles: "", gender: "", occupation: "", identifying_marks: "",
};

type Duplicate = { suspect_id: string; full_name: string; message: string };

const label = (v: string) => v.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

function Row({ k, v }: { k: string; v?: React.ReactNode }) {
  if (v === undefined || v === null || v === "" || v === 0) return null;
  return (
    <div className="flex gap-3 border-b border-white/[0.05] py-1.5 last:border-0">
      <span className="w-36 shrink-0 text-[12px] uppercase tracking-wide text-slate-500">{k}</span>
      <span className="min-w-0 text-[13px] text-slate-200">{v}</span>
    </div>
  );
}

/** The full record for one enrolled person: every reference photo, every
 *  description field, their handles, and what they have posted in the feed. */
function PersonProfile({ person, onClose, onChanged }: {
  person: Suspect; onClose: () => void; onChanged: () => void;
}) {
  const { openPostId } = usePostDetail();
  const [dossier, setDossier] = useState<IdentityDossier | null>(null);
  const [dossierErr, setDossierErr] = useState<string | null>(null);
  const [photoErr, setPhotoErr] = useState<string | null>(null);
  const [handleText, setHandleText] = useState("");
  const [handleBusy, setHandleBusy] = useState(false);
  const cat = categoryForRecordType(person.record_type);

  /** "Instagram:ramesh_p, X:rp_surat" → appended to the record's handles. */
  async function addHandles() {
    const added = handleText.split(",").map((raw) => raw.trim()).filter(Boolean).map((raw) => {
      const i = raw.lastIndexOf(":");
      return { platform: i > 0 ? raw.slice(0, i).trim() : "", handle: raw.slice(i + 1).trim().replace(/^@/, ""),
               url: "", note: "" };
    }).filter((h) => h.handle);
    if (!added.length) return;
    setHandleBusy(true); setPhotoErr(null);
    try {
      await api.updatePerson(person.id, { social_handles: [...person.social_handles, ...added] });
      setHandleText("");
      onChanged();
    } catch (e) { setPhotoErr((e as Error).message); }
    finally { setHandleBusy(false); }
  }

  useEffect(() => {
    let alive = true;
    setDossier(null); setDossierErr(null);
    api.personDossier(person.id)
      .then((d) => { if (alive) setDossier(d); })
      .catch((e) => { if (alive) setDossierErr((e as Error).message); });
    return () => { alive = false; };
  }, [person.id, person.enrolled_faces, person.social_handles.length]);

  async function removePhoto(templateId: string) {
    if (person.face_templates.length <= 1) {
      setPhotoErr("This is the only reference photo — add another before removing it, or delete the person.");
      return;
    }
    if (!window.confirm("Remove this reference photo?")) return;
    setPhotoErr(null);
    try { await api.deletePersonPhoto(person.id, templateId); onChanged(); }
    catch (e) { setPhotoErr((e as Error).message); }
  }

  const posts = dossier?.monitored_posts;
  const alerts = dossier?.linked_alerts ?? [];

  return (
    <div className="col-span-full rounded-xl border border-accent/25 bg-accent/[0.03] p-4">
      <div className="flex items-start gap-4">
        {person.photo_thumb
          ? <img src={person.photo_thumb} alt="" className="h-24 w-24 shrink-0 rounded-xl object-cover" />
          : <div className="h-24 w-24 shrink-0 rounded-xl bg-white/[0.05]" />}
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <div>
              <div className="text-base font-bold text-slate-100">{person.full_name}</div>
              {person.aliases.length > 0 && (
                <div className="text-[13px] text-slate-400">also known as {person.aliases.join(", ")}</div>
              )}
            </div>
            <button onClick={onClose} aria-label="Close profile"
              className="rounded-lg p-1.5 text-slate-400 hover:bg-white/[0.06] hover:text-slate-200">
              <X size={16} />
            </button>
          </div>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            <Pill color={CATEGORY_COLOR[cat]}>{CATEGORY_LABEL[cat]}</Pill>
            <Pill color="#F59E0B">{label(person.risk_level)} risk</Pill>
            <Pill color="#64748B">{label(person.status)}</Pill>
          </div>
          {person.notes && <p className="mt-2 whitespace-pre-wrap text-[13px] leading-relaxed text-slate-300">{person.notes}</p>}
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div>
          <div className="mb-1 text-[12px] font-semibold uppercase tracking-wide text-slate-400">Details</div>
          <Row k="Last known location" v={person.last_known_location} />
          <Row k="Gender" v={person.gender} />
          <Row k="Age" v={person.age || undefined} />
          <Row k="Height" v={person.height_cm ? `${person.height_cm} cm` : undefined} />
          <Row k="Occupation" v={person.occupation} />
          <Row k="Nationality" v={person.nationality} />
          <Row k="Identifying marks" v={person.identifying_marks} />
          <Row k="Jurisdiction" v={person.jurisdiction} />
          <Row k="Case IDs" v={person.case_ids.join(", ")} />
          <Row k="Wanted since" v={person.wanted_since} />
          <Row k="Charges" v={person.charges.length ? person.charges.map((c) => `${c.section}${c.description ? ` — ${c.description}` : ""}`).join("; ") : undefined} />
          <Row k="Added" v={new Date(person.created_at).toLocaleString()} />
          <div className="mt-3">
            <div className="mb-1 text-[12px] font-semibold uppercase tracking-wide text-slate-400">Social accounts</div>
            <div className="mb-2 flex gap-2">
              <input value={handleText} onChange={(e) => setHandleText(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") void addHandles(); }}
                placeholder="Add: Instagram:ramesh_p, X:rp_surat"
                className="min-w-0 flex-1 rounded-lg border border-white/[0.08] bg-white/[0.04] px-2.5 py-1.5 font-mono text-[12px] text-slate-200 placeholder-slate-600 outline-none focus:border-accent/50" />
              <button onClick={() => void addHandles()} disabled={handleBusy || !handleText.trim()}
                className="rounded-lg border border-accent/30 bg-accent/10 px-2.5 text-[12px] font-semibold text-accent disabled:opacity-40">
                {handleBusy ? "…" : "Add"}
              </button>
            </div>
          </div>
          {person.social_handles.length > 0 && (
            <div>
              <div className="flex flex-wrap gap-1.5">
                {person.social_handles.map((h) => {
                  const chip = (
                    <span className="inline-flex items-center gap-1 rounded-lg border border-white/[0.08] px-2 py-1 font-mono text-[12px] text-slate-300">
                      {h.platform && <span className="text-slate-500">{h.platform}</span>} @{h.handle}
                      {h.url && <ExternalLink size={11} />}
                    </span>
                  );
                  return h.url
                    ? <a key={h.platform + h.handle} href={safeHref(h.url)} target="_blank" rel="noreferrer">{chip}</a>
                    : <span key={h.platform + h.handle}>{chip}</span>;
                })}
              </div>
            </div>
          )}
        </div>

        <div>
          <div className="mb-1.5 text-[12px] font-semibold uppercase tracking-wide text-slate-400">
            Reference photos ({person.face_templates.length})
          </div>
          <div className="flex flex-wrap gap-2">
            {person.face_templates.map((t) => (
              <div key={t.id} className="group relative">
                {t.thumb
                  ? <img src={t.thumb} alt={t.source} title={t.source} className="h-20 w-20 rounded-lg border border-white/10 object-cover" />
                  : <div className="h-20 w-20 rounded-lg bg-white/[0.05]" />}
                <span className="absolute bottom-1 left-1 rounded bg-black/70 px-1 font-mono text-[10px] text-slate-200"
                  title="Face quality score (0-100)">
                  q{t.quality?.score ?? "?"}
                </span>
                <button onClick={() => removePhoto(t.id)} aria-label="Remove this photo"
                  className="absolute -right-1.5 -top-1.5 hidden rounded-full bg-slate-900 p-0.5 text-slate-300 hover:text-red-400 group-hover:block">
                  <X size={12} />
                </button>
              </div>
            ))}
          </div>
          {photoErr && <p className="mt-1.5 text-[12px] text-red-400">{photoErr}</p>}
        </div>
      </div>

      <div className="mt-4 border-t border-white/[0.06] pt-3">
        <div className="mb-1.5 text-[12px] font-semibold uppercase tracking-wide text-slate-400">Activity in the monitored feed</div>
        {dossierErr ? <p className="text-[13px] text-red-400">{dossierErr}</p>
          : !dossier ? <p className="inline-flex items-center gap-2 text-[13px] text-slate-500"><Loader2 size={13} className="animate-spin" /> Loading…</p>
          : !person.social_handles.length ? (
            <p className="text-[13px] text-slate-500">No social accounts on this record yet, so no posts can be linked to it. Add their handles under Social accounts above.</p>
          ) : !posts?.total ? (
            <p className="text-[13px] text-slate-500">None of their accounts has posted in the monitored feed.</p>
          ) : (
            <>
              <p className="mb-2 text-[13px] text-slate-400">
                {posts.total} post{posts.total === 1 ? "" : "s"} · {alerts.length} alert{alerts.length === 1 ? "" : "s"} raised
              </p>
              <div className="max-h-72 space-y-1.5 overflow-y-auto pr-1">
                {posts.items.map((p) => (
                  <button key={p.id} onClick={() => openPostId(p.id)}
                    className="block w-full rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2 text-left hover:border-accent/40">
                    <div className="flex items-center gap-2 text-[12px] text-slate-500">
                      <span className="font-semibold text-slate-300">{p.platform}</span>
                      <span className="font-mono">@{p.author_handle}</span>
                      <span>· {p.sentiment_label} · concern {Math.round(p.concern_score)}</span>
                      <span className="ml-auto">{new Date(p.created_at).toLocaleDateString()}</span>
                    </div>
                    <div className="mt-0.5 line-clamp-2 text-[13px] text-slate-300">{p.text}</div>
                  </button>
                ))}
              </div>
            </>
          )}
      </div>
    </div>
  );
}

function Field({ label, children, wide }: { label: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <label className={`block space-y-1 ${wide ? "sm:col-span-2" : ""}`}>
      <span className="text-[12px] uppercase tracking-wide text-slate-500">{label}</span>
      {children}
    </label>
  );
}

/** Adds people to the face registry from the console — photo plus description —
 *  so an officer never has to seed the database from code. Every upload in the
 *  Image & Video Check is matched against whoever is enrolled here. */
export default function PersonDatabase() {
  const [open, setOpen] = useState(false);
  const [showList, setShowList] = useState(false);
  const [people, setPeople] = useState<Suspect[]>([]);
  const [engine, setEngine] = useState<FaceEngine | null>(null);
  const [form, setForm] = useState<PersonEnrolFields>(EMPTY);
  const [age, setAge] = useState("");
  const [photos, setPhotos] = useState<File[]>([]);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ tone: "ok" | "err"; text: string } | null>(null);
  const [duplicate, setDuplicate] = useState<Duplicate | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const photoInput = useRef<HTMLInputElement>(null);
  const addInput = useRef<HTMLInputElement>(null);
  const addTarget = useRef<string | null>(null);
  const previews = useMemo(() => photos.map((f) => URL.createObjectURL(f)), [photos]);
  useEffect(() => () => previews.forEach((u) => URL.revokeObjectURL(u)), [previews]);

  async function refresh() {
    try {
      const [list, eng] = await Promise.all([api.listPeople(), api.faceEngine()]);
      setPeople(list);
      setEngine(eng);
    } catch { /* the panel still works for adding */ }
  }
  useEffect(() => { void refresh(); }, []);

  const set = (k: keyof PersonEnrolFields) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
      setForm((f) => ({ ...f, [k]: e.target.value }));

  function addPhotos(files: FileList | null) {
    // Copied out NOW: the input's onChange clears it right after this call so
    // the same file can be picked again, and clearing empties the live
    // FileList — read inside the state updater, it was always empty.
    const picked = Array.from(files ?? []).filter(
      (f) => f.type.startsWith("image/") || /\.(jpe?g|png|webp|bmp|gif|jfif|tiff?)$/i.test(f.name));
    if (!picked.length) {
      if (files?.length) setMsg({ tone: "err", text: "Those files are not images (JPG, PNG, WEBP, BMP or GIF)." });
      return;
    }
    setMsg(null);
    setPhotos((p) => [...p, ...picked].slice(0, 6));
  }

  /** Adds photos to an existing record; returns per-photo problems. */
  async function attach(suspectId: string, files: File[]): Promise<string[]> {
    const problems: string[] = [];
    for (const f of files) {
      try { await api.addPersonPhoto(suspectId, f); }
      catch (e) { problems.push(`${f.name}: ${(e as Error).message}`); }
    }
    return problems;
  }

  function finish(name: string, added: number, problems: string[]) {
    setMsg({
      tone: problems.length && !added ? "err" : "ok",
      text: added
        ? `${name} saved with ${added} photo${added === 1 ? "" : "s"}. Uploads of this person will now be identified.`
          + (problems.length ? ` Skipped: ${problems.join("; ")}` : "")
        : `Nothing was added. ${problems.join("; ")}`,
    });
    setForm(EMPTY); setAge(""); setPhotos([]); setDuplicate(null);
    void refresh();
  }

  async function submit(allowDuplicate = false) {
    if (!form.full_name.trim() || !photos.length) return;
    setSaving(true); setMsg(null); setDuplicate(null);
    try {
      const r = await api.enrolPerson(photos[0], {
        ...form, age: Number(age) || undefined, allow_duplicate: allowDuplicate || undefined,
      });
      if (!r.ok) { setDuplicate(r.duplicate); return; }
      const problems = await attach(r.suspect.id, photos.slice(1));
      finish(r.suspect.full_name, photos.length - problems.length, problems);
    } catch (e) {
      setMsg({ tone: "err", text: (e as Error).message });
    } finally { setSaving(false); }
  }

  async function addToExisting(d: Duplicate) {
    setSaving(true); setMsg(null);
    try {
      const problems = await attach(d.suspect_id, photos);
      finish(d.full_name, photos.length - problems.length, problems);
    } finally { setSaving(false); }
  }

  async function addMore(fileList: FileList | null) {
    const files = Array.from(fileList ?? []);   // before the input is cleared
    const id = addTarget.current;
    if (!id || !files.length) return;
    setBusyId(id); setMsg(null);
    const name = people.find((p) => p.id === id)?.full_name ?? "Record";
    const list = files;
    const problems = await attach(id, list);
    setBusyId(null);
    setMsg({
      tone: problems.length === list.length ? "err" : "ok",
      text: problems.length === list.length
        ? problems.join("; ")
        : `Added ${list.length - problems.length} photo(s) to ${name}.`
          + (problems.length ? ` Skipped: ${problems.join("; ")}` : ""),
    });
    void refresh();
  }

  async function remove(p: Suspect) {
    if (!window.confirm(`Delete ${p.full_name} and all their reference photos? This cannot be undone.`)) return;
    setBusyId(p.id);
    try { await api.deletePerson(p.id); await refresh(); }
    catch (e) { setMsg({ tone: "err", text: (e as Error).message }); }
    finally { setBusyId(null); }
  }

  const matcher = engine?.arcface
    ? { color: "#10B981", text: "ArcFace matcher active" }
    : engine?.arcface_downloading
      ? { color: "#F59E0B", text: "ArcFace model downloading — basic matcher until it finishes" }
      : engine ? { color: "#F59E0B", text: "Basic matcher (ArcFace unavailable)" } : null;

  return (
    <GlassCard className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">Person Database</h2>
          <p className="mt-0.5 text-xs text-slate-500">
            {people.length} {people.length === 1 ? "person" : "people"} enrolled · uploaded photos are matched against them
            {matcher && <span className="ml-2" style={{ color: matcher.color }}>● {matcher.text}</span>}
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => setShowList((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-xl border border-white/[0.08] px-3 py-2 text-[13px] text-slate-300 hover:text-slate-100">
            {showList ? <ChevronUp size={14} /> : <ChevronDown size={14} />} View enrolled
          </button>
          <RunButton onClick={() => { setOpen((v) => !v); setMsg(null); }}>
            {open ? <X size={15} /> : <UserPlus size={15} />} {open ? "Close" : "Add person"}
          </RunButton>
        </div>
      </div>

      {msg && (
        <div className={`mt-3 rounded-lg border px-3 py-2 text-[13px] ${msg.tone === "ok"
          ? "border-emerald-500/30 bg-emerald-500/[0.06] text-emerald-300"
          : "border-red-500/30 bg-red-500/[0.06] text-red-300"}`}>
          {msg.text}
        </div>
      )}

      {open && (
        <div className="mt-4 space-y-4 border-t border-white/[0.06] pt-4">
          <div>
            <div className="mb-2 text-[12px] uppercase tracking-wide text-slate-500">
              Photos <span className="normal-case text-slate-600">— one clear face per photo. 2–3 photos from different angles or days make matching much more reliable.</span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {photos.map((f, i) => (
                <div key={i} className="relative">
                  <img src={previews[i]} alt={f.name}
                    className="h-20 w-20 rounded-lg border border-white/10 object-cover" />
                  <button onClick={() => setPhotos((p) => p.filter((_, j) => j !== i))}
                    className="absolute -right-1.5 -top-1.5 rounded-full bg-slate-900 p-0.5 text-slate-300 hover:text-red-400"
                    aria-label={`Remove ${f.name}`}>
                    <X size={12} />
                  </button>
                </div>
              ))}
              {photos.length < 6 && (
                <button onClick={() => photoInput.current?.click()}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => { e.preventDefault(); addPhotos(e.dataTransfer.files); }}
                  className="flex h-20 w-20 flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed border-white/[0.1] text-[11px] text-slate-500 hover:border-accent/40 hover:text-accent">
                  <ImagePlus size={18} /> Add
                </button>
              )}
              <input ref={photoInput} type="file" accept="image/*" multiple className="hidden"
                onChange={(e) => { addPhotos(e.target.files); e.target.value = ""; }} />
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Full name *">
              <input className={inputCls} value={form.full_name} onChange={set("full_name")} placeholder="e.g. Ramesh Patel" />
            </Field>
            <Field label="Aliases (comma-separated)">
              <input className={inputCls} value={form.aliases} onChange={set("aliases")} placeholder="Ramu, RP" />
            </Field>
            <Field label="Description" wide>
              <textarea className={`${inputCls} min-h-[80px]`} value={form.notes} onChange={set("notes")}
                placeholder="Who this person is, why they are of interest, case context…" />
            </Field>
            <Field label="Category">
              <select className={inputCls} value={form.record_type} onChange={set("record_type")}>
                {RECORD_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </Field>
            <Field label="Risk level">
              <select className={inputCls} value={form.risk_level} onChange={set("risk_level")}>
                {RISK_LEVELS.map((v) => <option key={v} value={v}>{v[0].toUpperCase() + v.slice(1)}</option>)}
              </select>
            </Field>
            <Field label="Status">
              <select className={inputCls} value={form.status} onChange={set("status")}>
                {STATUSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </Field>
            <Field label="Last known location">
              <input className={inputCls} value={form.last_known_location} onChange={set("last_known_location")} placeholder="Surat, Adajan" />
            </Field>
            <Field label="Gender">
              <select className={inputCls} value={form.gender} onChange={set("gender")}>
                <option value="">—</option><option>Male</option><option>Female</option><option>Other</option>
              </select>
            </Field>
            <Field label="Age">
              <input className={inputCls} value={age} onChange={(e) => setAge(e.target.value.replace(/\D/g, "").slice(0, 3))} placeholder="32" inputMode="numeric" />
            </Field>
            <Field label="Occupation">
              <input className={inputCls} value={form.occupation} onChange={set("occupation")} />
            </Field>
            <Field label="Identifying marks">
              <input className={inputCls} value={form.identifying_marks} onChange={set("identifying_marks")} placeholder="Scar on left cheek" />
            </Field>
            <Field label="Social handles (platform:handle, comma-separated)" wide>
              <input className={`${inputCls} font-mono`} value={form.social_handles} onChange={set("social_handles")} placeholder="Instagram:ramesh_p, X:rp_surat" />
            </Field>
          </div>

          {duplicate && (
            <div className="space-y-2 rounded-lg border border-amber-500/30 bg-amber-500/[0.06] px-3 py-2.5 text-[13px] text-amber-200">
              <div>{duplicate.message}</div>
              <div className="flex flex-wrap gap-2">
                <RunButton onClick={() => addToExisting(duplicate)} disabled={saving}>
                  <ImagePlus size={14} /> Add {photos.length > 1 ? "these photos" : "this photo"} to {duplicate.full_name}
                </RunButton>
                <button onClick={() => submit(true)} disabled={saving}
                  className="rounded-xl border border-white/[0.1] px-3 py-2 text-[13px] text-slate-300 hover:text-slate-100 disabled:opacity-40">
                  It's a different person — create anyway
                </button>
              </div>
            </div>
          )}

          <div className="flex items-center justify-end gap-3">
            {!photos.length && <span className="text-[12px] text-slate-500">Add at least one photo</span>}
            <RunButton onClick={() => submit()} disabled={saving || !form.full_name.trim() || !photos.length}>
              {saving ? <Loader2 size={15} className="animate-spin" /> : <UserPlus size={15} />} Save to database
            </RunButton>
          </div>
        </div>
      )}

      {showList && (
        <div className="mt-4 border-t border-white/[0.06] pt-4">
          {!people.length ? (
            <div className="py-4 text-center text-[13px] text-slate-500">Nobody enrolled yet — use “Add person”.</div>
          ) : (
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
              {people.map((p) => {
                const cat = categoryForRecordType(p.record_type);
                if (expanded === p.id) {
                  return <PersonProfile key={p.id} person={p} onClose={() => setExpanded(null)} onChanged={() => void refresh()} />;
                }
                return (
                  <div key={p.id} className="flex items-center gap-3 rounded-lg border border-white/[0.07] bg-white/[0.02] p-2.5 transition-colors hover:border-accent/30">
                    <button onClick={() => setExpanded(p.id)} aria-label={`Open ${p.full_name}'s profile`}
                      className="flex min-w-0 flex-1 items-center gap-3 text-left">
                    {p.photo_thumb
                      ? <img src={p.photo_thumb} alt="" className="h-12 w-12 shrink-0 rounded-lg object-cover" />
                      : <div className="h-12 w-12 shrink-0 rounded-lg bg-white/[0.05]" />}
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[13px] font-semibold text-slate-200">{p.full_name}</div>
                      <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
                        <Pill color={CATEGORY_COLOR[cat]}>{CATEGORY_LABEL[cat]}</Pill>
                        <span className="text-[12px] text-slate-500">{p.enrolled_faces} photo{p.enrolled_faces === 1 ? "" : "s"}</span>
                      </div>
                      {p.notes && <div className="mt-0.5 truncate text-[12px] text-slate-500" title={p.notes}>{p.notes}</div>}
                    </div>
                    </button>
                    {busyId === p.id ? <Loader2 size={15} className="animate-spin text-slate-400" /> : (
                      <div className="flex shrink-0 gap-1">
                        <button title="Add more photos" aria-label={`Add photos to ${p.full_name}`}
                          onClick={() => { addTarget.current = p.id; addInput.current?.click(); }}
                          className="rounded-lg p-1.5 text-slate-400 hover:bg-white/[0.06] hover:text-accent">
                          <ImagePlus size={15} />
                        </button>
                        <button title="Delete" aria-label={`Delete ${p.full_name}`} onClick={() => remove(p)}
                          className="rounded-lg p-1.5 text-slate-400 hover:bg-white/[0.06] hover:text-red-400">
                          <Trash2 size={15} />
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
          <input ref={addInput} type="file" accept="image/*" multiple className="hidden"
            onChange={(e) => { void addMore(e.target.files); e.target.value = ""; }} />
        </div>
      )}
    </GlassCard>
  );
}
