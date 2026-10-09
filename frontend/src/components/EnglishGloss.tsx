import { useEnglish } from "../hooks/useEnglish";

interface Props {
  id?: string;
  text?: string;
  translation?: string | null;
  language?: string;
  className?: string;
}

/** The "AI Translation" callout shown under a non-English post. Uses the
 *  stored translation, or fetches one automatically when there is none. */
export default function EnglishGloss({ id, text, translation, language, className = "" }: Props) {
  const { english, pending } = useEnglish(id, text, translation, language);
  if (!english && !pending) return null;
  return (
    <div className={`rounded-xl border border-accent/20 bg-accent/[0.05] px-2.5 py-1.5 text-[11.5px] text-slate-200 ${className}`}>
      <span className="mr-1.5 text-[13px] font-bold uppercase tracking-wider text-accent">AI Translation:</span>
      {english ? <span className="italic">{english}</span> : <span className="italic text-slate-500">Translating…</span>}
    </div>
  );
}
