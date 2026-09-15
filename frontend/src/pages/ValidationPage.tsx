import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { asDecision } from "../api/types";
import { Empty, ErrorBanner, JsonCollapse, Panel } from "../components/Chrome";
import { DiffTable } from "../components/DiffTable";
import { VerdictChip } from "../components/VerdictChip";
import { lastTool, readLastTraceId, rememberTrace, stepsOf } from "../lib/trace";

export function ValidationPage() {
  const { traceId } = useParams();
  const navigate = useNavigate();
  const traces = useQuery({ queryKey: ["traces"], queryFn: api.traces });
  const resolved = traceId || readLastTraceId() || traces.data?.[0]?.id;

  useEffect(() => {
    if (!traceId && resolved) navigate(`/validation/${resolved}`, { replace: true });
  }, [navigate, resolved, traceId]);

  const trace = useQuery({
    queryKey: ["trace", resolved],
    queryFn: () => api.trace(resolved!),
    enabled: !!resolved,
  });

  useEffect(() => {
    if (trace.data?.id) rememberTrace(trace.data.id);
  }, [trace.data?.id]);

  const data = trace.data;
  const decision = asDecision(data?.decision);
  const validates = (data?.steps ?? []).filter((s) => s.tool === "validate_action");
  const lastValidate = lastTool(data?.steps, "validate_action");
  const act = stepsOf(data?.steps, "ACT");
  const recon = stepsOf(data?.steps, "RECONCILE");
  const post = stepsOf(data?.steps, "POST-VERIFY");
  const diffs = data?.verification?.diffs ?? [];
  const mismatch = data?.verification?.matched === false || diffs.length > 0;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex shrink-0 items-center gap-3 border-b border-zinc-800 px-3 py-1.5">
        <h2 className="text-[13px] font-medium text-zinc-100">Validation & Feedback</h2>
        <select
          className="max-w-xs rounded border border-zinc-700 bg-zinc-950 px-2 py-0.5 font-mono text-[11px] text-zinc-200"
          value={resolved ?? ""}
          onChange={(e) => e.target.value && navigate(`/validation/${e.target.value}`)}
        >
          <option value="">select trace</option>
          {(traces.data ?? []).map((row) => (
            <option key={row.id} value={row.id}>
              {row.id.slice(0, 8)} · {row.matched === false ? "DIFF" : row.matched ? "ok" : row.status}
            </option>
          ))}
        </select>
        {data && (
          <Link to={`/run/${data.id}`} className="font-mono text-[11px] text-teal-400">
            open run
          </Link>
        )}
      </header>

      <div className="min-h-0 flex-1 overflow-auto p-3">
        {trace.isError && <ErrorBanner error={trace.error} />}
        {!resolved && <Empty>Run a situation. Pre-validate, the write, and post-verify diffs land here from the API.</Empty>}
        {data && (
          <div className="space-y-3">
            {mismatch && (
              <div className="rounded border-2 border-rose-500 bg-rose-950/60 px-3 py-2">
                <p className="font-mono text-[12px] font-medium uppercase tracking-widest text-rose-200">
                  Source-of-truth mismatch
                </p>
                <p className="mt-1 text-[12px] text-rose-100">
                  Expected outcome did not match the database after the write. Reviewer: this is the contract break.
                </p>
              </div>
            )}
            <div className="flex items-center gap-2">
              <VerdictChip decision={decision?.decision} />
              <span className="font-mono text-[11px] text-zinc-500">{data.status}</span>
            </div>

            <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
              <Panel title={`pre-validation · ${validates.length} pass(es)`} className="rounded border border-zinc-800">
                {validates.length === 0 && <Empty>No validate_action calls on this trace.</Empty>}
                {validates.map((step, i) => (
                  <div key={i} className="mb-2 border-b border-zinc-800 pb-2 last:border-0">
                    <p className="font-mono text-[10px] uppercase text-zinc-500">
                      revision {i + 1}
                      {i === validates.length - 1 ? " · last" : ""}
                    </p>
                    <JsonCollapse label="args" value={step.arguments} />
                    <JsonCollapse label="result" value={step.result} defaultOpen={i === validates.length - 1} />
                  </div>
                ))}
                {lastValidate && (
                  <p className="font-mono text-[11px] text-zinc-400">
                    last passed: {String((lastValidate.result as { passed?: boolean } | null)?.passed ?? "—")}
                  </p>
                )}
              </Panel>

              <Panel title="executed action" className="rounded border border-zinc-800">
                {act.length === 0 && <Empty>No ACT stage — reject / escalate / investigate leave the world unchanged.</Empty>}
                {act.map((step, i) => (
                  <div key={i} className="mb-2">
                    <p className="font-mono text-[11px] text-zinc-200">{step.tool ?? "action"}</p>
                    <JsonCollapse label="args" value={step.arguments} defaultOpen />
                    <JsonCollapse label="tool return" value={step.result} />
                  </div>
                ))}
                {!!data.actions?.length && (
                  <ul className="mt-2 space-y-1 font-mono text-[11px] text-zinc-500">
                    {data.actions.map((a) => (
                      <li key={a.id}>
                        {a.tool_name} {a.latency_ms != null ? `${a.latency_ms}ms` : ""}
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>
            </div>

            <DiffTable diffs={diffs} matched={data.verification?.matched} />

            {post.length > 0 && (
              <Panel title="post-verify re-read" className="rounded border border-zinc-800">
                {post.map((step, i) => (
                  <div key={i} className="mb-2">
                    {step.note && <p className="text-[12px] text-zinc-400">{step.note}</p>}
                    <JsonCollapse label="source of truth" value={step.result} defaultOpen={mismatch} />
                  </div>
                ))}
              </Panel>
            )}

            <Panel title="reconciliation" className="rounded border border-zinc-800">
              {recon.length === 0 && <Empty>No reconciliation rounds.</Empty>}
              {recon.map((step, i) => (
                <div key={i} className="mb-2">
                  {step.note && <p className="text-[12px] text-zinc-300">{step.note}</p>}
                  <JsonCollapse label="result" value={step.result} defaultOpen={mismatch} />
                </div>
              ))}
            </Panel>
          </div>
        )}
      </div>
    </div>
  );
}
