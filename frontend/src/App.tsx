import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import {
  api,
  type InsightDef,
  type Scenario,
  type ScenarioVariant,
  type Trace,
} from "./api/client";

const NAV = [
  { id: "situations", label: "Situations" },
  { id: "insights", label: "Insights" },
  { id: "validation", label: "Validation" },
  { id: "approvals", label: "Approvals" },
  { id: "pos", label: "Purchase Orders" },
  { id: "evals", label: "Evaluation" },
] as const;

type NavId = (typeof NAV)[number]["id"];

function decisionTone(decision?: string) {
  if (decision === "reject") return "text-amber-300";
  if (decision === "escalate") return "text-rose-300";
  if (decision === "modify" || decision === "accept") return "text-emerald-300";
  return "text-sky-300";
}

export default function App() {
  const [page, setPage] = useState<NavId>("situations");
  const [lastTrace, setLastTrace] = useState<Trace | null>(null);
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const healthy = health.data?.status === "ok";

  return (
    <div className="min-h-screen">
      <header className="flex items-center justify-between border-b border-zinc-800 px-6 py-3">
        <div className="flex items-baseline gap-3">
          <h1 className="text-sm font-semibold tracking-wide text-zinc-100">
            Purchasing Agent
          </h1>
          <span className="font-mono text-[11px] uppercase tracking-widest text-zinc-500">
            Operator console
          </span>
        </div>
        <div className="flex items-center gap-2 font-mono text-xs">
          <span
            className={`h-1.5 w-1.5 rounded-full ${healthy ? "bg-emerald-400" : "bg-amber-400"}`}
          />
          <span className="text-zinc-400">
            {health.isLoading
              ? "checking api"
              : healthy
                ? "api ok"
                : "api unreachable — start the backend"}
          </span>
        </div>
      </header>

      <div className="flex">
        <nav className="w-52 shrink-0 border-r border-zinc-800 px-3 py-4">
          <ul className="space-y-1">
            {NAV.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => setPage(item.id)}
                  className={`w-full rounded px-2 py-1.5 text-left text-sm ${
                    item.id === page
                      ? "bg-zinc-800 text-zinc-100"
                      : "text-zinc-500 hover:text-zinc-300"
                  }`}
                >
                  {item.label}
                </button>
              </li>
            ))}
          </ul>
        </nav>

        <main className="flex-1 px-6 py-5">
          {page === "situations" && (
            <SituationsPage lastTrace={lastTrace} onTrace={setLastTrace} />
          )}
          {page === "insights" && <InsightsPage />}
          {page === "validation" && <ValidationPage trace={lastTrace} />}
          {page === "approvals" && <ApprovalsPage />}
          {page === "pos" && <PosPage />}
          {page === "evals" && (
            <section>
              <h2 className="text-lg font-medium text-zinc-100">Evaluation</h2>
              <p className="mt-2 text-sm text-zinc-500">
                Scenario eval harness (E1–E13) lands in Prompt 7. Until then, each
                Situations card runs the same agent against a FakeLLM fixture.
              </p>
            </section>
          )}
        </main>
      </div>
    </div>
  );
}

function SituationsPage({
  lastTrace,
  onTrace,
}: {
  lastTrace: Trace | null;
  onTrace: (trace: Trace) => void;
}) {
  const scenarios = useQuery({ queryKey: ["scenarios"], queryFn: api.scenarios });
  const queryClient = useQueryClient();
  const [picked, setPicked] = useState<Record<string, string>>({});
  const [runningId, setRunningId] = useState<string | null>(null);

  const run = useMutation({
    mutationFn: ({ scenario, variant }: { scenario: Scenario; variant: ScenarioVariant }) =>
      api.runScenario(scenario.id, { variant: variant.id, seed: true }),
    onMutate: ({ scenario }) => setRunningId(scenario.id),
    onSettled: () => setRunningId(null),
    onSuccess: (trace) => {
      onTrace(trace);
      void queryClient.invalidateQueries({ queryKey: ["pos"] });
      void queryClient.invalidateQueries({ queryKey: ["approvals"] });
      void queryClient.invalidateQueries({ queryKey: ["insights"] });
    },
  });

  return (
    <div>
      <div className="mb-4">
        <h2 className="text-lg font-medium text-zinc-100">Situations</h2>
        <p className="mt-1 max-w-3xl text-sm text-zinc-500">
          Four assignment entry points. Same agent and tools; each card loads its
          fixture world and a different intake. FakeLLM scripts keep the demo
          deterministic without an API key.
        </p>
      </div>

      {scenarios.isError && (
        <p className="mb-4 rounded border border-amber-900/60 bg-amber-950/40 px-3 py-2 text-sm text-amber-200">
          Could not load scenarios. Run <code className="font-mono">make dev</code>{" "}
          so the FastAPI server is on :8000.
        </p>
      )}

      {run.isError && (
        <p className="mb-4 rounded border border-rose-900/60 bg-rose-950/40 px-3 py-2 text-sm text-rose-200">
          {(run.error as Error).message}
        </p>
      )}

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {(scenarios.data ?? []).map((scenario) => {
          const variantId = picked[scenario.id] ?? scenario.default_variant;
          const variant =
            scenario.variants.find((row) => row.id === variantId) ?? scenario.variants[0];
          return (
            <article
              key={scenario.id}
              className="rounded-md border border-zinc-800 bg-zinc-900/40 p-4"
            >
              <p className="font-mono text-[11px] uppercase tracking-widest text-teal-500">
                {scenario.id}
              </p>
              <h3 className="mt-1 text-sm font-medium text-zinc-100">{scenario.title}</h3>
              <p className="mt-2 text-sm text-zinc-400">{scenario.summary}</p>
              <label className="mt-3 block text-[11px] uppercase tracking-widest text-zinc-500">
                Variant
                <select
                  className="mt-1 w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-200"
                  value={variant.id}
                  onChange={(e) =>
                    setPicked((prev) => ({ ...prev, [scenario.id]: e.target.value }))
                  }
                >
                  {scenario.variants.map((row) => (
                    <option key={row.id} value={row.id}>
                      {row.label}
                    </option>
                  ))}
                </select>
              </label>
              {variant?.note && (
                <p className="mt-2 text-xs text-zinc-500">{variant.note}</p>
              )}
              <button
                type="button"
                disabled={run.isPending}
                onClick={() => variant && run.mutate({ scenario, variant })}
                className="mt-3 rounded border border-teal-800 bg-teal-950/60 px-3 py-1.5 text-xs text-teal-200 hover:border-teal-600 disabled:opacity-50"
              >
                {runningId === scenario.id ? "Running…" : "Run agent"}
              </button>
            </article>
          );
        })}
      </div>

      {lastTrace && <TracePanel trace={lastTrace} />}
    </div>
  );
}

function TracePanel({ trace }: { trace: Trace }) {
  const decision = trace.decision?.decision;
  const tools = useMemo(
    () =>
      (trace.steps ?? [])
        .filter((step) => step.tool)
        .map((step) => step.tool as string),
    [trace.steps],
  );
  return (
    <section className="mt-6 rounded-md border border-zinc-800 bg-zinc-900/40 p-4">
      <div className="flex flex-wrap items-baseline gap-3">
        <h3 className="text-sm font-medium text-zinc-100">Last run</h3>
        <span className={`font-mono text-xs uppercase ${decisionTone(decision)}`}>
          {decision ?? trace.status}
        </span>
        <span className="font-mono text-[11px] text-zinc-500">{trace.id}</span>
      </div>
      {trace.decision?.reasoning_summary && (
        <p className="mt-3 text-sm text-zinc-300">{trace.decision.reasoning_summary}</p>
      )}
      <dl className="mt-3 grid grid-cols-2 gap-2 text-xs text-zinc-400 md:grid-cols-4">
        <div>
          <dt className="text-zinc-600">qty</dt>
          <dd className="font-mono text-zinc-200">
            {trace.decision?.final_quantity ?? "—"}
          </dd>
        </div>
        <div>
          <dt className="text-zinc-600">supplier</dt>
          <dd className="font-mono text-zinc-200">{trace.decision?.supplier_id ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-zinc-600">verified</dt>
          <dd className="font-mono text-zinc-200">
            {trace.verification == null
              ? "—"
              : trace.verification.matched
                ? "matched"
                : "diff"}
          </dd>
        </div>
        <div>
          <dt className="text-zinc-600">approval</dt>
          <dd className="font-mono text-zinc-200">
            {trace.decision?.requires_human_approval ? "required" : "no"}
          </dd>
        </div>
      </dl>
      {!!trace.decision?.key_factors?.length && (
        <ul className="mt-3 space-y-1 text-xs text-zinc-500">
          {trace.decision.key_factors.map((factor, i) => (
            <li key={`${factor.factor}-${i}`}>
              <span className="text-zinc-400">{factor.factor}</span>{" "}
              <span className="font-mono text-zinc-300">{factor.evidence_value}</span>{" "}
              <span className="text-zinc-600">via {factor.source_tool}</span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 font-mono text-[11px] text-zinc-600">
        tools: {Array.from(new Set(tools)).join(" → ") || "none"}
      </p>
    </section>
  );
}

function InsightsPage() {
  const catalogue = useQuery({ queryKey: ["insight-defs"], queryFn: api.insightCatalogue });
  const [active, setActive] = useState<string | null>(null);
  const [sku, setSku] = useState("SKU-ALT");
  const payload = useQuery({
    queryKey: ["insight", active, sku],
    queryFn: () => api.insight(active!, active === "alternate-suppliers" ? { sku } : undefined),
    enabled: !!active,
  });

  return (
    <div>
      <h2 className="text-lg font-medium text-zinc-100">Insights</h2>
      <p className="mt-1 max-w-3xl text-sm text-zinc-500">
        Cheap extras on the current world: overdue/ghost POs, supplier reliability,
        alternate sources, and safety stock. One click, no agent loop.
      </p>
      <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
        {(catalogue.data ?? []).map((insight: InsightDef) => (
          <article key={insight.id} className="rounded-md border border-zinc-800 bg-zinc-900/40 p-4">
            <h3 className="text-sm font-medium text-zinc-100">{insight.title}</h3>
            <p className="mt-2 text-sm text-zinc-400">{insight.summary}</p>
            {insight.id === "alternate-suppliers" && (
              <input
                className="mt-2 w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1 font-mono text-xs text-zinc-200"
                value={sku}
                onChange={(e) => setSku(e.target.value)}
              />
            )}
            <button
              type="button"
              onClick={() => setActive(insight.id)}
              className="mt-3 rounded border border-zinc-700 px-3 py-1.5 text-xs text-zinc-200 hover:border-teal-700"
            >
              {active === insight.id && payload.isFetching ? "Loading…" : "Open"}
            </button>
          </article>
        ))}
      </div>
      {payload.data != null && (
        <pre className="mt-4 max-h-96 overflow-auto rounded-md border border-zinc-800 bg-zinc-950 p-3 font-mono text-[11px] text-zinc-400">
          {JSON.stringify(payload.data, null, 2)}
        </pre>
      )}
      {payload.isError && (
        <p className="mt-4 text-sm text-rose-300">{(payload.error as Error).message}</p>
      )}
    </div>
  );
}

function ValidationPage({ trace }: { trace: Trace | null }) {
  if (!trace) {
    return (
      <section>
        <h2 className="text-lg font-medium text-zinc-100">Validation</h2>
        <p className="mt-2 text-sm text-zinc-500">
          Run a situation first. Pre-validate, expected-outcome contract and
          post-verify diffs show up here.
        </p>
      </section>
    );
  }
  return (
    <section>
      <h2 className="text-lg font-medium text-zinc-100">Validation</h2>
      <p className="mt-2 text-sm text-zinc-400">
        Status {trace.status}
        {trace.verification
          ? ` · post-verify ${trace.verification.matched ? "matched" : "had diffs"}`
          : ""}
      </p>
      {!!trace.verification?.diffs?.length && (
        <ul className="mt-3 space-y-1 text-sm text-zinc-400">
          {trace.verification.diffs.map((diff) => (
            <li key={diff.field} className="font-mono text-xs">
              {diff.field}: expected {String(diff.expected)} · actual {String(diff.actual)}
            </li>
          ))}
        </ul>
      )}
      <TracePanel trace={trace} />
    </section>
  );
}

function ApprovalsPage() {
  const q = useQuery({ queryKey: ["approvals"], queryFn: api.approvals });
  return (
    <section>
      <h2 className="text-lg font-medium text-zinc-100">Approvals</h2>
      <p className="mt-1 text-sm text-zinc-500">
        Approve/reject actions land in Prompt 6. The queue is already visible.
      </p>
      <ul className="mt-4 space-y-2">
        {(q.data ?? []).map((row) => (
          <li key={row.id} className="rounded border border-zinc-800 p-3 text-sm">
            <p className="font-mono text-[11px] text-zinc-500">
              {row.id} · {row.status} · {row.urgency}
            </p>
            <p className="mt-1 text-zinc-300">{row.reason}</p>
          </li>
        ))}
        {q.data?.length === 0 && (
          <li className="text-sm text-zinc-500">No approval requests yet.</li>
        )}
      </ul>
    </section>
  );
}

function PosPage() {
  const q = useQuery({ queryKey: ["pos"], queryFn: api.pos });
  return (
    <section>
      <h2 className="text-lg font-medium text-zinc-100">Purchase Orders</h2>
      <ul className="mt-4 space-y-2">
        {(q.data ?? []).map((po) => (
          <li key={po.id} className="rounded border border-zinc-800 p-3 text-sm">
            <p className="font-mono text-[11px] text-zinc-500">
              {po.id} · {po.status} · {po.supplier_id} · {po.node_id}
            </p>
            <p className="mt-1 text-zinc-300">
              {po.lines?.length ?? 0} line(s) · {po.expected_delivery_date ?? "no ETA"}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
