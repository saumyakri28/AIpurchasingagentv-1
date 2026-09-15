import type { Meter } from "../lib/constraints";
import { toneClass, toneDot } from "../lib/status";

export function ConstraintMeters({ meters }: { meters: Meter[] }) {
  return (
    <div className="space-y-1">
      {meters.map((row) => (
        <div
          key={row.name}
          className={`rounded border px-2 py-1 ${row.binding ? "border-rose-600 bg-rose-950/40" : "border-zinc-800"}`}
        >
          <div className="flex items-center gap-2">
            <span className={`h-1.5 w-1.5 rounded-full ${toneDot[row.tone]}`} />
            <span className="w-8 font-mono text-[10px] text-zinc-500">{row.code}</span>
            <span className="flex-1 truncate font-mono text-[11px] text-zinc-200">{row.name}</span>
            <span className={`rounded border px-1 font-mono text-[10px] uppercase ${toneClass[row.tone]}`}>
              {row.status === "idle" ? "—" : row.status}
            </span>
          </div>
          <div className="mt-0.5 grid grid-cols-3 gap-1 font-mono text-[10px] text-zinc-500">
            <span>act {row.actual}</span>
            <span>lim {row.limit}</span>
            <span>slack {row.slack}</span>
          </div>
          {row.binding && row.message && (
            <p className="mt-0.5 text-[11px] text-rose-300">{row.message}</p>
          )}
        </div>
      ))}
    </div>
  );
}
