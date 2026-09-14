import { useQuery } from "@tanstack/react-query";
import { api } from "./api/client";

const NAV = [
  { id: "situations", label: "Situations" },
  { id: "run", label: "Run" },
  { id: "validation", label: "Validation" },
  { id: "approvals", label: "Approvals" },
  { id: "pos", label: "Purchase Orders" },
  { id: "evals", label: "Evaluation" },
] as const;

export default function App() {
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const scenarios = useQuery({ queryKey: ["scenarios"], queryFn: api.scenarios });
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
                  className={`w-full rounded px-2 py-1.5 text-left text-sm ${
                    item.id === "situations"
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
          <div className="mb-4 flex items-end justify-between">
            <div>
              <h2 className="text-lg font-medium text-zinc-100">Situations</h2>
              <p className="mt-1 text-sm text-zinc-500">
                Four assignment entry points. Agent runs land in Prompt 5; this
                shell only proves the API is reachable.
              </p>
            </div>
          </div>

          {scenarios.isError && (
            <p className="mb-4 rounded border border-amber-900/60 bg-amber-950/40 px-3 py-2 text-sm text-amber-200">
              Could not load scenarios. Run <code className="font-mono">make dev</code>{" "}
              so the FastAPI server is on :8000.
            </p>
          )}

          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {(scenarios.data ?? []).map((scenario) => (
              <article
                key={scenario.id}
                className="rounded-md border border-zinc-800 bg-zinc-900/40 p-4"
              >
                <p className="font-mono text-[11px] uppercase tracking-widest text-teal-500">
                  {scenario.id}
                </p>
                <h3 className="mt-1 text-sm font-medium text-zinc-100">
                  {scenario.title}
                </h3>
                <button
                  type="button"
                  disabled
                  className="mt-3 rounded border border-zinc-700 px-3 py-1 text-xs text-zinc-500"
                >
                  Run agent (Prompt 5)
                </button>
              </article>
            ))}
          </div>
        </main>
      </div>
    </div>
  );
}
