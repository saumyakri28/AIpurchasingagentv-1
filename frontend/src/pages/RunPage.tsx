import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { asDecision } from "../api/types";
import { ConstraintMeters } from "../components/ConstraintMeters";
import { CoverChart } from "../components/CoverChart";
import { DecisionPanel } from "../components/DecisionPanel";
import { Empty, ErrorBanner, Panel } from "../components/Chrome";
import { TraceTimeline } from "../components/TraceTimeline";
import { metersFromTrace } from "../lib/constraints";
import { readLastTraceId, rememberTrace, skuNode } from "../lib/trace";

export function RunPage() {
  const { traceId } = useParams();
  const navigate = useNavigate();
  const traces = useQuery({ queryKey: ["traces"], queryFn: api.traces });
  const resolved = traceId || readLastTraceId() || traces.data?.[0]?.id;

  useEffect(() => {
    if (!traceId && resolved) navigate(`/run/${resolved}`, { replace: true });
  }, [navigate, resolved, traceId]);

  const trace = useQuery({
    queryKey: ["trace", resolved],
    queryFn: () => api.trace(resolved!),
    enabled: !!resolved,
    refetchInterval: (query) => (query.state.data?.status === "running" ? 800 : false),
  });

  useEffect(() => {
    if (trace.data?.id) rememberTrace(trace.data.id);
  }, [trace.data?.id]);

  const coverKey = skuNode(trace.data);
  const cover = useQuery({
    queryKey: ["cover", coverKey?.sku, coverKey?.node],
    queryFn: () => api.stockCover(coverKey!.sku, coverKey!.node),
    enabled: !!coverKey,
  });

  const meters = metersFromTrace(trace.data?.steps);
  const decision = asDecision(trace.data?.decision);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex shrink-0 items-center gap-3 border-b border-zinc-800 px-3 py-1.5">
        <h2 className="text-[13px] font-medium text-zinc-100">Run</h2>
        <select
          className="max-w-xs rounded border border-zinc-700 bg-zinc-950 px-2 py-0.5 font-mono text-[11px] text-zinc-200"
          value={resolved ?? ""}
          onChange={(e) => e.target.value && navigate(`/run/${e.target.value}`)}
        >
          <option value="">select trace</option>
          {(traces.data ?? []).map((row) => (
            <option key={row.id} value={row.id}>
              {row.id.slice(0, 8)} · {row.scenario_type ?? "?"} · {row.decision ?? row.status}
            </option>
          ))}
        </select>
        {trace.data && (
          <>
            <span className="font-mono text-[11px] text-zinc-500">{trace.data.status}</span>
            {trace.data.po_id && (
              <Link to={`/pos/${trace.data.po_id}`} className="font-mono text-[11px] text-teal-400">
                {trace.data.po_id}
              </Link>
            )}
            <Link to={`/validation/${trace.data.id}`} className="font-mono text-[11px] text-zinc-400 hover:text-zinc-200">
              validation
            </Link>
          </>
        )}
      </header>
      {trace.isError && (
        <div className="p-3">
          <ErrorBanner error={trace.error} />
        </div>
      )}
      {!resolved && <div className="p-4"><Empty>Run a situation first. Traces appear here from the API.</Empty></div>}
      {resolved && trace.isLoading && <p className="p-3 font-mono text-[11px] text-zinc-500">Loading trace…</p>}
      {trace.data && (
        <div className="grid min-h-0 flex-1 grid-cols-1 divide-y divide-zinc-800 lg:grid-cols-3 lg:divide-x lg:divide-y-0">
          <Panel title="live trace" className="min-h-0">
            {trace.data.plan && (
              <p className="mb-3 text-[12px] leading-snug text-zinc-400">
                <span className="mr-2 font-mono text-[10px] uppercase tracking-widest text-teal-500">plan</span>
                {trace.data.plan}
              </p>
            )}
            <TraceTimeline steps={trace.data.steps ?? []} />
          </Panel>
          <Panel title="decision" className="min-h-0">
            <DecisionPanel trace={trace.data} />
            {decision?.expected_outcome && (
              <dl className="mt-3 grid grid-cols-2 gap-1 font-mono text-[10px] text-zinc-500">
                {Object.entries(decision.expected_outcome).map(([k, v]) =>
                  v == null ? null : (
                    <div key={k}>
                      <dt className="text-zinc-600">{k}</dt>
                      <dd className="text-zinc-300">{String(v)}</dd>
                    </div>
                  ),
                )}
              </dl>
            )}
          </Panel>
          <Panel title="constraints C1–C12" className="min-h-0">
            <ConstraintMeters meters={meters} />
            <div className="mt-3 border-t border-zinc-800 pt-3">
              <p className="mb-1 font-mono text-[10px] uppercase tracking-widest text-zinc-500">projected stock cover</p>
              {cover.isError && <ErrorBanner error={cover.error} />}
              {cover.data ? <CoverChart data={cover.data} /> : (
                <Empty>Cover chart needs sku + node on the intake.</Empty>
              )}
            </div>
          </Panel>
        </div>
      )}
    </div>
  );
}
