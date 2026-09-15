import type { paths } from "./schema";
import type {
  Approval,
  CoverChart,
  EvalRun,
  InsightDef,
  PurchaseOrder,
  Scenario,
  Trace,
  TraceSummary,
  WorldSummary,
} from "./types";

export type {
  Approval,
  CoverChart,
  EvalRun,
  InsightDef,
  PurchaseOrder,
  Scenario,
  ScenarioVariant,
  Trace,
  TraceStep,
  TraceSummary,
  WorldSummary,
} from "./types";

type Methods<P extends keyof paths> = {
  [M in keyof paths[P]]-?: paths[P][M] extends { responses: unknown } ? M : never;
}[keyof paths[P]];

export class ApiError extends Error {
  status: number;
  body: string;
  constructor(path: string, status: number, body: string) {
    super(`${path} failed: ${status} ${body}`);
    this.status = status;
    this.body = body;
  }
}

const BASE = import.meta.env.VITE_API_URL ?? "";

async function send<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      accept: "application/json",
      ...(init?.body ? { "content-type": "application/json" } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    throw new ApiError(path, response.status, await response.text());
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

/** Compile-time check that a path exists on the generated OpenAPI document. */
function route<P extends keyof paths>(path: P, _method: Methods<P>): string {
  return path;
}

const SCENARIO_RUN: Record<string, keyof paths> = {
  "recommendation-review": "/agent/run/recommendation-review",
  "supplier-shortfall": "/agent/run/supplier-shortfall",
  "demand-change": "/agent/run/demand-change",
  "constrained-buy": "/agent/run/constrained-buy",
};

export const api = {
  health: () => send<{ status: string; service: string }>(route("/health", "get")),
  scenarios: () => send<Scenario[]>(route("/scenarios", "get")),
  world: () => send<WorldSummary>(route("/insights/world", "get")),
  runScenario: (id: string, body: Record<string, unknown>) =>
    send<Trace>(SCENARIO_RUN[id] ?? "/agent/run", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  runAgent: (intake: Record<string, unknown>, script?: unknown[]) =>
    send<Trace>(route("/agent/run", "post"), {
      method: "POST",
      body: JSON.stringify({ intake, script }),
    }),
  traces: () => send<TraceSummary[]>(route("/traces", "get")),
  trace: (id: string) => send<Trace>(`/traces/${id}`),
  insights: () => send<InsightDef[]>(route("/insights", "get")),
  insight: (id: string, query?: Record<string, string>) => {
    const suffix = query ? `?${new URLSearchParams(query)}` : "";
    return send<unknown>(`/insights/${id}${suffix}`);
  },
  stockCover: (sku: string, node: string) =>
    send<CoverChart>(`${route("/insights/stock-cover", "get")}?${new URLSearchParams({ sku, node })}`),
  pos: () => send<PurchaseOrder[]>(route("/pos", "get")),
  po: (id: string) => send<PurchaseOrder>(`/pos/${id}`),
  approvals: () => send<Approval[]>(route("/approvals", "get")),
  approval: (id: string) => send<Approval>(`/approvals/${id}`),
  approve: (id: string) =>
    send<Record<string, unknown>>(`/approvals/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ decided_by: "buyer" }),
    }),
  rejectApproval: (id: string) =>
    send<Record<string, unknown>>(`/approvals/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ decided_by: "buyer" }),
    }),
  modifyApprove: (id: string, qty: number) =>
    send<Record<string, unknown>>(`/approvals/${id}/modify`, {
      method: "POST",
      body: JSON.stringify({ qty, decided_by: "buyer" }),
    }),
  evals: () => send<EvalRun[]>(route("/evals", "get")),
  evalRun: (id: string) => send<EvalRun>(`/evals/${id}`),
  evalReport: () => send<{ markdown: string | null; report: EvalRun | null }>("/evals/report"),
  runEvals: (body?: { suite?: string; repeat?: number; llm?: string }) =>
    send<EvalRun>("/evals/run", {
      method: "POST",
      body: JSON.stringify(body ?? { suite: "all", repeat: 1, llm: "fake" }),
    }),
};
