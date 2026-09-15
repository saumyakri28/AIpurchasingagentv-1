import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type ScenarioVariant } from "../api/client";
import { ErrorBanner } from "../components/Chrome";
import { WORLD_TO_SCENARIO, rememberTrace } from "../lib/trace";

function invalidateWorld(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: ["world"] });
  void qc.invalidateQueries({ queryKey: ["pos"] });
  void qc.invalidateQueries({ queryKey: ["approvals"] });
  void qc.invalidateQueries({ queryKey: ["traces"] });
  void qc.invalidateQueries({ queryKey: ["evals"] });
}

export function SituationsPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const scenarios = useQuery({ queryKey: ["scenarios"], queryFn: api.scenarios });
  const world = useQuery({ queryKey: ["world"], queryFn: api.world });
  const [picked, setPicked] = useState<Record<string, string>>({});
  const [runningId, setRunningId] = useState<string | null>(null);

  const run = useMutation({
    mutationFn: ({ scenario, variant, seed }: { scenario: string; variant?: string; seed: boolean }) =>
      api.runScenario(scenario, { variant, seed }),
    onMutate: ({ scenario }) => setRunningId(scenario),
    onSettled: () => setRunningId(null),
    onSuccess: (trace) => {
      if (trace.id) rememberTrace(trace.id);
      invalidateWorld(qc);
      if (trace.id) navigate(`/run/${trace.id}`);
    },
  });

  const summary = world.data;
  const pendingEvents = (summary?.events ?? []).filter((e) => e.event_type !== "world_seeded");
  const hygiene = summary?.hygiene.purchase_orders ?? [];
  const worldScenario = summary?.world ? WORLD_TO_SCENARIO[summary.world] : undefined;

  return (
    <div className="h-full overflow-auto p-4">
      <header className="mb-3 flex items-baseline justify-between gap-3">
        <div>
          <h2 className="text-sm font-medium text-zinc-100">Situations</h2>
          <p className="mt-0.5 max-w-3xl text-[12px] text-zinc-500">
            Same agent, four intakes. Run reseeds that world. Keys 1–6 switch screens.
          </p>
        </div>
      </header>

      {scenarios.isError && <ErrorBanner error={scenarios.error} />}
      {run.isError && <ErrorBanner error={run.error} />}

      <section className="mb-4 grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-8">
        <Stat label="world" value={summary?.world ?? "—"} />
        <Stat label="as of" value={summary?.as_of ?? "—"} />
        <Stat label="positions" value={summary?.inventory_positions} />
        <Stat label="open POs" value={summary?.open_po_count} />
        <Stat label="approvals" value={summary?.pending_approvals} warn={!!summary?.pending_approvals} />
        <Stat label="hygiene" value={summary?.hygiene.count} warn={!!summary?.hygiene.count} />
        <Stat
          label="budget left"
          value={
            summary?.budgets?.length
              ? summary.budgets.map((b) => `${b.category} ${Math.round(b.remaining)}`).join(" · ")
              : "—"
          }
        />
        <Stat
          label="inbound"
          value={summary?.open_pos?.length ? summary.open_pos.map((p) => p.id).join(" ") : "—"}
        />
      </section>

      {scenarios.isLoading && <p className="text-[12px] text-zinc-500">Loading catalogue…</p>}

      <div className="grid grid-cols-1 gap-2 lg:grid-cols-2">
        {(scenarios.data ?? []).map((scenario) => {
          const variantId = picked[scenario.id] ?? scenario.default_variant;
          const variant =
            scenario.variants.find((row) => row.id === variantId) ?? scenario.variants[0];
          const live = worldScenario === scenario.id;
          return (
            <article
              key={scenario.id}
              className={`rounded border bg-zinc-900/40 p-3 ${live ? "border-teal-800" : "border-zinc-800"}`}
            >
              <div className="flex items-baseline justify-between gap-2">
                <p className="font-mono text-[10px] uppercase tracking-widest text-teal-500">{scenario.id}</p>
                {live && (
                  <span className="font-mono text-[10px] uppercase text-teal-400">current world</span>
                )}
              </div>
              <h3 className="mt-1 text-[13px] font-medium text-zinc-100">{scenario.title}</h3>
              <p className="mt-1 text-[12px] leading-snug text-zinc-400">{scenario.summary}</p>
              <label className="mt-2 block font-mono text-[10px] uppercase tracking-widest text-zinc-500">
                variant
                <select
                  className="mt-1 w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-[12px] text-zinc-200"
                  value={variant?.id ?? ""}
                  onChange={(e) => setPicked((prev) => ({ ...prev, [scenario.id]: e.target.value }))}
                >
                  {scenario.variants.map((row: ScenarioVariant) => (
                    <option key={row.id} value={row.id}>
                      {row.label}
                    </option>
                  ))}
                </select>
              </label>
              {variant?.note && <p className="mt-1.5 text-[11px] text-zinc-500">{variant.note}</p>}
              <p className="mt-1 font-mono text-[10px] text-zinc-600">
                expect {variant?.expected_decision ?? "—"} · world {scenario.world}
              </p>
              <button
                type="button"
                disabled={run.isPending}
                onClick={() => variant && run.mutate({ scenario: scenario.id, variant: variant.id, seed: true })}
                className="mt-2 rounded border border-teal-800 bg-teal-950/70 px-2.5 py-1 font-mono text-[11px] text-teal-100 hover:border-teal-600 disabled:opacity-50"
              >
                {runningId === scenario.id ? "Running…" : "Run agent"}
              </button>
            </article>
          );
        })}
      </div>

      <h3 className="mb-2 mt-5 font-mono text-[10px] uppercase tracking-widest text-zinc-500">
        Pending events
      </h3>
      <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
        {(summary?.pending_approvals ?? 0) > 0 && (
          <article className="rounded border border-amber-900/60 bg-amber-950/20 p-3">
            <p className="font-mono text-[10px] uppercase tracking-widest text-amber-400">pending approval</p>
            <p className="mt-1 text-[12px] text-zinc-300">{summary?.pending_approvals} parked action(s)</p>
            <div className="mt-2 flex gap-2">
              <Link
                to="/approvals"
                className="rounded border border-zinc-700 px-2 py-1 font-mono text-[11px] text-zinc-200"
              >
                Open queue
              </Link>
              {worldScenario && (
                <RunPending
                  disabled={run.isPending}
                  busy={runningId === worldScenario}
                  onClick={() => run.mutate({ scenario: worldScenario, seed: false })}
                />
              )}
            </div>
          </article>
        )}
        {hygiene.map((row) => (
          <article key={row.po_id} className="rounded border border-amber-900/50 bg-zinc-900/40 p-3">
            <p className="font-mono text-[10px] uppercase tracking-widest text-amber-400">
              {row.flags.join(" · ")}
            </p>
            <p className="mt-1 font-mono text-[12px] text-zinc-200">{row.po_id}</p>
            <p className="text-[11px] text-zinc-500">{row.overdue_days ?? 0}d overdue</p>
            <div className="mt-2 flex gap-2">
              <Link
                to={`/pos/${row.po_id}`}
                className="rounded border border-zinc-700 px-2 py-1 font-mono text-[11px] text-zinc-200"
              >
                Open PO
              </Link>
              {worldScenario && (
                <RunPending
                  disabled={run.isPending}
                  busy={runningId === `${worldScenario}:${row.po_id}`}
                  onClick={() => {
                    setRunningId(`${worldScenario}:${row.po_id}`);
                    run.mutate({ scenario: worldScenario, seed: false });
                  }}
                />
              )}
            </div>
          </article>
        ))}
        {pendingEvents.map((event) => (
          <article key={event.id} className="rounded border border-zinc-800 bg-zinc-900/40 p-3">
            <p className="font-mono text-[10px] uppercase tracking-widest text-zinc-500">{event.event_type}</p>
            <p className="mt-1 font-mono text-[12px] text-zinc-200">
              {event.entity_type} {event.entity_id}
            </p>
            <p className="text-[11px] text-zinc-600">{event.ts ?? ""}</p>
            <div className="mt-2 flex gap-2">
              {event.entity_type === "purchase_order" && event.entity_id && (
                <Link
                  to={`/pos/${event.entity_id}`}
                  className="rounded border border-zinc-700 px-2 py-1 font-mono text-[11px] text-zinc-200"
                >
                  Open PO
                </Link>
              )}
              {worldScenario && (
                <RunPending
                  disabled={run.isPending}
                  busy={runningId === event.id}
                  onClick={() => {
                    setRunningId(event.id);
                    run.mutate({ scenario: worldScenario, seed: false });
                  }}
                />
              )}
            </div>
          </article>
        ))}
        {!summary?.pending_approvals && hygiene.length === 0 && pendingEvents.length === 0 && (
          <p className="text-[12px] text-zinc-500">No pending events in the current world.</p>
        )}
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  warn,
}: {
  label: string;
  value: string | number | undefined;
  warn?: boolean;
}) {
  return (
    <div className={`rounded border px-2 py-1.5 ${warn ? "border-amber-900/60" : "border-zinc-800"}`}>
      <p className="font-mono text-[10px] uppercase tracking-widest text-zinc-600">{label}</p>
      <p className="truncate font-mono text-[11px] text-zinc-200">{value ?? "—"}</p>
    </div>
  );
}

function RunPending({
  disabled,
  busy,
  onClick,
}: {
  disabled: boolean;
  busy: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="rounded border border-teal-800 bg-teal-950/60 px-2 py-1 font-mono text-[11px] text-teal-100 disabled:opacity-50"
    >
      {busy ? "Running…" : "Run agent"}
    </button>
  );
}
