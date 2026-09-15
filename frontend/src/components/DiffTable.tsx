import type { VerificationDiff } from "../api/types";

export function DiffTable({ diffs, matched }: { diffs: VerificationDiff[]; matched?: boolean | null }) {
  const mismatch = matched === false || diffs.length > 0;
  return (
    <div className={mismatch ? "rounded border-2 border-rose-600 bg-rose-950/40 p-2" : "rounded border border-zinc-800 p-2"}>
      <p className={`mb-2 font-mono text-[11px] uppercase tracking-widest ${mismatch ? "text-rose-300" : "text-emerald-400"}`}>
        {mismatch ? "post-verify mismatch" : "post-verify matched"}
      </p>
      {diffs.length === 0 ? (
        <p className="text-[12px] text-zinc-500">No field diffs.</p>
      ) : (
        <table className="w-full text-left font-mono text-[11px]">
          <thead className="text-[10px] uppercase tracking-widest text-zinc-500">
            <tr>
              <th className="py-1 font-medium">field</th>
              <th className="py-1 font-medium">expected</th>
              <th className="py-1 font-medium">actual</th>
            </tr>
          </thead>
          <tbody>
            {diffs.map((diff) => (
              <tr key={diff.field} className="border-t border-rose-900/60">
                <td className="py-1.5 pr-2 text-rose-200">{diff.field}</td>
                <td className="py-1.5 pr-2 text-zinc-400 line-through">{String(diff.expected)}</td>
                <td className="py-1.5 font-medium text-rose-100">{String(diff.actual)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
