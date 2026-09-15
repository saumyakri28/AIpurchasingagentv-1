import { asDecision, type Trace } from "../api/types";
import { recommendedQty } from "../lib/trace";
import { ConfidenceBar, VerdictChip } from "./VerdictChip";

export function DecisionPanel({ trace }: { trace: Trace }) {
  const decision = asDecision(trace.decision);
  const rec = recommendedQty(trace);
  const final = decision?.final_quantity ?? null;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <VerdictChip decision={decision?.decision ?? (typeof trace.decision === "string" ? trace.decision : trace.status)} />
        {decision?.requires_human_approval && (
          <span className="rounded border border-amber-800 bg-amber-950/40 px-1.5 py-0.5 font-mono text-[10px] uppercase text-amber-300">
            approval
          </span>
        )}
      </div>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-[11px]">
        <div>
          <dt className="text-zinc-600">recommended</dt>
          <dd className="text-zinc-200">{rec ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-zinc-600">final qty</dt>
          <dd className="text-zinc-100">{final ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-zinc-600">supplier</dt>
          <dd className="text-zinc-200">{decision?.supplier_id ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-zinc-600">node</dt>
          <dd className="text-zinc-200">{decision?.node ?? String(trace.intake?.node ?? "—")}</dd>
        </div>
      </dl>
      <div>
        <p className="mb-1 font-mono text-[10px] uppercase tracking-widest text-zinc-500">confidence</p>
        <ConfidenceBar value={decision?.confidence} />
      </div>
      {decision?.reasoning_summary && (
        <p className="text-[12px] leading-snug text-zinc-300">{decision.reasoning_summary}</p>
      )}
      {decision?.approval_reason && (
        <p className="text-[11px] text-amber-300">{decision.approval_reason}</p>
      )}
      {!!decision?.key_factors?.length && (
        <table className="w-full text-left font-mono text-[11px]">
          <thead className="text-[10px] uppercase tracking-widest text-zinc-600">
            <tr>
              <th className="py-1 font-medium">factor</th>
              <th className="py-1 font-medium">evidence</th>
              <th className="py-1 font-medium">src</th>
            </tr>
          </thead>
          <tbody>
            {decision.key_factors.map((factor, i) => (
              <tr key={`${factor.factor}-${i}`} className="border-t border-zinc-800 align-top">
                <td className="py-1 pr-2 text-zinc-300">{factor.factor}</td>
                <td className="py-1 pr-2 text-zinc-100">{factor.evidence_value}</td>
                <td className="py-1">
                  <span className="rounded border border-teal-900 bg-teal-950/50 px-1 text-[10px] text-teal-400">
                    {factor.source_tool}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {!!decision?.alternatives_considered?.length && (
        <ul className="space-y-1 text-[11px] text-zinc-400">
          {decision.alternatives_considered.map((alt, i) => (
            <li key={`${alt.option}-${i}`}>
              <span className="text-zinc-200">{alt.option}</span>
              <span className="text-zinc-600"> — {alt.why_not}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
