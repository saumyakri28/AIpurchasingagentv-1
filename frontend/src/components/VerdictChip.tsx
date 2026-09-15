import { verdictTone, toneClass } from "../lib/status";

export function VerdictChip({ decision }: { decision?: string | null }) {
  const tone = verdictTone(decision);
  const label = (decision || "—").replaceAll("_", " ").toUpperCase();
  return (
    <span
      className={`inline-flex items-center rounded border px-2 py-0.5 font-mono text-[11px] font-medium tracking-wide ${toneClass[tone]}`}
    >
      {label}
    </span>
  );
}

export function ConfidenceBar({ value }: { value?: number | null }) {
  const pct = Math.round(Math.max(0, Math.min(1, value ?? 0)) * 100);
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-zinc-800">
        <div className="h-full bg-teal-600" style={{ width: `${pct}%` }} />
      </div>
      <span className="font-mono text-[11px] text-zinc-400">{pct}%</span>
    </div>
  );
}
