import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { EvalRun } from "../api/types";
import { Empty, ErrorBanner } from "../components/Chrome";
import { TraceTimeline } from "../components/TraceTimeline";
import { VerdictChip } from "../components/VerdictChip";
import { toneClass } from "../lib/status";

const HARNESS_DIMS = [
  "decision_correctness",
  "information_sufficiency",
  "constraint_respect",
  "action_correctness",
  "validation_performed",
  "recovery",
  "explanation_quality",
] as const;

const TRACE_DIMS = ["plan", "replenishment", "decision", "constraints", "verification"] as const;

const SHORT: Record<string, string> = {
  decision_correctness: "Decision",
  information_sufficiency: "Info",
  constraint_respect: "Constraint",
  action_correctness: "Action",
  validation_performed: "Validation",
  recovery: "Recovery",
  explanation_quality: "Explain",
};

export function EvalsPage() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["evals"], queryFn: api.evals });
  const detail = useQuery({
    queryKey: ["eval", runId],
    queryFn: () => api.evalRun(runId!),
    enabled: !!runId,
  });
  const run = useMutation({
    mutationFn: () => api.runEvals({ suite: "all", repeat: 1, llm: "fake" }),
    onSuccess: (report) => {
      void qc.invalidateQueries({ queryKey: ["evals"] });
      navigate(`/evals/${report.id}`);
    },
  });

  const rows = list.data ?? [];
  const selected = detail.data;
  const isHarness = Boolean(selected?.cases?.length || selected?.kind === "harness");
  const dims = isHarness ? HARNESS_DIMS : TRACE_DIMS;

  return (
    <div className="flex h-full min-h-0">
      <section className="min-h-0 flex-1 overflow-auto p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <h2 className="text-sm font-medium text-zinc-100">Evaluation</h2>
            <p className="mt-0.5 text-[12px] text-zinc-500">
              Seven grader dimensions, reported separately. Sample report lives in{" "}
              <span className="font-mono">evals/report.md</span>.
            </p>
          </div>
          <button
            type="button"
            disabled={run.isPending}
            onClick={() => run.mutate()}
            className="rounded border border-teal-800 bg-teal-950/70 px-2.5 py-1 font-mono text-[11px] text-teal-100 disabled:opacity-50"
          >
            {run.isPending ? "Running suite…" : "Run suite (fake, ×1)"}
          </button>
        </div>
        {list.isError && (
          <div className="mt-3">
            <ErrorBanner error={list.error} />
          </div>
        )}
        {run.isError && (
          <div className="mt-3">
            <ErrorBanner error={run.error} />
          </div>
        )}
        <table className="mt-3 w-full text-left font-mono text-[11px]">
          <thead className="text-[10px] uppercase tracking-widest text-zinc-600">
            <tr>
              <th className="py-1">run</th>
              <th>kind</th>
              <th>llm</th>
              {HARNESS_DIMS.map((c) => (
                <th key={c}>{SHORT[c]}</th>
              ))}
              <th>all</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const byCat = Object.fromEntries((row.assertions ?? []).map((a) => [a.category, a.passed]));
              const harnessish = row.kind === "harness" || Boolean(row.cases_total);
              return (
                <tr
                  key={row.id}
                  className={`cursor-pointer border-t border-zinc-800 hover:bg-zinc-900/60 ${runId === row.id ? "bg-zinc-900" : ""}`}
                  onClick={() => navigate(`/evals/${row.id}`)}
                >
                  <td className="py-1.5 pr-2 text-zinc-400">{row.id.slice(0, 12)}</td>
                  <td className="pr-2">{harnessish ? "harness" : "trace"}</td>
                  <td className="pr-2">{row.llm ?? "—"}</td>
                  {HARNESS_DIMS.map((c) => (
                    <td key={c} className="pr-2">
                      <PassFail ok={byCat[c]} />
                    </td>
                  ))}
                  <td>
                    <PassFail ok={row.passed} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {rows.length === 0 && (
          <div className="mt-3">
            <Empty>No eval runs yet. Run the suite or execute a situation.</Empty>
          </div>
        )}
      </section>
      {runId && selected && (
        <aside className="w-[32rem] shrink-0 overflow-auto border-l border-zinc-800 p-3">
          {detail.isError && <ErrorBanner error={detail.error} />}
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <VerdictChip decision={selected.decision ?? (selected.passed ? "accept" : "reject")} />
              <PassFail ok={selected.passed} />
              {selected.stability_mean != null && (
                <span className="font-mono text-[11px] text-zinc-500">stability {selected.stability_mean}</span>
              )}
              {selected.kind !== "harness" && (
                <>
                  <Link to={`/run/${selected.id}`} className="font-mono text-[11px] text-teal-400">
                    open run
                  </Link>
                  <Link to={`/validation/${selected.id}`} className="font-mono text-[11px] text-zinc-400">
                    validation
                  </Link>
                </>
              )}
            </div>
            {isHarness ? <HarnessDetail report={selected} /> : <TraceDetail report={selected} dims={[...dims]} />}
          </div>
        </aside>
      )}
    </div>
  );
}

function HarnessDetail({ report }: { report: EvalRun }) {
  return (
    <div className="space-y-3">
      <p className="font-mono text-[11px] text-zinc-500">
        {report.cases_passed}/{report.cases_total} cases · repeat {report.repeat} · {report.llm}
      </p>
      <table className="w-full text-left font-mono text-[10px]">
        <thead className="uppercase tracking-widest text-zinc-600">
          <tr>
            <th className="py-1">case</th>
            {HARNESS_DIMS.map((c) => (
              <th key={c}>{SHORT[c]}</th>
            ))}
            <th>stab</th>
          </tr>
        </thead>
        <tbody>
          {(report.cases ?? []).map((row) => {
            const byCat = Object.fromEntries((row.assertions ?? []).map((a) => [a.category, a.passed]));
            return (
              <tr key={row.id} className="border-t border-zinc-800">
                <td className="py-1 pr-1 text-zinc-300">{row.id}</td>
                {HARNESS_DIMS.map((c) => (
                  <td key={c}>
                    <PassFail ok={byCat[c]} />
                  </td>
                ))}
                <td>{row.stability ?? "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {report.markdown && (
        <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded border border-zinc-800 bg-zinc-950 p-2 font-mono text-[10px] text-zinc-500">
          {report.markdown}
        </pre>
      )}
    </div>
  );
}

function TraceDetail({ report, dims }: { report: EvalRun; dims: readonly string[] }) {
  return (
    <>
      <ul className="space-y-1">
        {report.assertions.map((a) => (
          <li key={a.category} className="flex items-center justify-between font-mono text-[11px]">
            <span className="text-zinc-400">{a.category}</span>
            <PassFail ok={a.passed} />
          </li>
        ))}
      </ul>
      {report.trace?.steps && <TraceTimeline steps={report.trace.steps} />}
      {dims.length === 0 ? null : null}
    </>
  );
}

function PassFail({ ok }: { ok?: boolean }) {
  if (ok == null) return <span className="text-zinc-600">—</span>;
  return (
    <span className={`rounded border px-1 text-[10px] uppercase ${toneClass[ok ? "pass" : "fail"]}`}>
      {ok ? "pass" : "fail"}
    </span>
  );
}
