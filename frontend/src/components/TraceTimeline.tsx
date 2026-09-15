import type { TraceStep } from "../api/types";
import { JsonCollapse } from "./Chrome";

const STAGE_TONE: Record<string, string> = {
  PLAN: "text-teal-400",
  INVESTIGATE: "text-zinc-300",
  PREVALIDATE: "text-amber-300",
  "PRE-VALIDATE": "text-amber-300",
  DECIDE: "text-zinc-100",
  ACT: "text-emerald-300",
  "POST-VERIFY": "text-sky-300",
  RECONCILE: "text-rose-300",
  REPORT: "text-zinc-500",
};

export function TraceTimeline({ steps }: { steps: TraceStep[] }) {
  const visible = steps.filter((s) => s.stage !== "LLM" && s.stage !== "INTAKE");
  return (
    <ol className="space-y-2">
      {visible.map((step, i) => (
        <li key={`${step.stage}-${step.tool ?? i}-${i}`} className="border-l border-zinc-800 pl-3">
          <div className="flex flex-wrap items-baseline gap-2">
            <span className={`font-mono text-[10px] uppercase tracking-widest ${STAGE_TONE[step.stage] ?? "text-zinc-400"}`}>
              {step.stage}
            </span>
            {step.tool && <span className="font-mono text-[11px] text-zinc-200">{step.tool}</span>}
            {step.tool === "compute_replenishment_plan" && (
              <span className="font-mono text-[9px] uppercase tracking-widest text-teal-600">deterministic</span>
            )}
            {step.tool === "validate_action" && (
              <span className="font-mono text-[9px] uppercase tracking-widest text-amber-500">constraints</span>
            )}
            {step.latency_ms != null && (
              <span className="font-mono text-[10px] text-zinc-600">{step.latency_ms}ms</span>
            )}
          </div>
          {step.note && <p className="mt-0.5 text-[11px] text-zinc-500">{step.note}</p>}
          {step.arguments && Object.keys(step.arguments).length > 0 && (
            <JsonCollapse label="args" value={step.arguments} />
          )}
          {step.result != null && <JsonCollapse label="result" value={step.result} />}
        </li>
      ))}
      {visible.length === 0 && <li className="text-[12px] text-zinc-500">No steps yet.</li>}
    </ol>
  );
}
