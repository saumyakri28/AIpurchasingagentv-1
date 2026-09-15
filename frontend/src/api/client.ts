export type HealthResponse = {
  status: string;
  service: string;
};

export type ScenarioVariant = {
  id: string;
  label: string;
  intake: Record<string, unknown>;
  expected_decision: string;
  note?: string;
};

export type Scenario = {
  id: string;
  title: string;
  endpoint: string;
  world: string;
  summary: string;
  default_variant: string;
  variants: ScenarioVariant[];
};

export type InsightDef = {
  id: string;
  title: string;
  endpoint: string;
  summary: string;
};

export type KeyFactor = {
  factor: string;
  evidence_value: string;
  source_tool: string;
  impact: string;
};

export type Trace = {
  id: string;
  status: string;
  plan?: string | null;
  po_id?: string | null;
  decision?: {
    decision: string;
    final_quantity?: number | null;
    supplier_id?: string | null;
    node?: string | null;
    confidence?: number;
    reasoning_summary?: string;
    key_factors?: KeyFactor[];
    requires_human_approval?: boolean;
  } | null;
  verification?: {
    matched: boolean;
    diffs: { field: string; expected: unknown; actual: unknown }[];
  } | null;
  steps?: { stage: string; tool?: string | null }[];
};

const API_BASE = import.meta.env.VITE_API_URL ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${path} failed: ${response.status} ${detail}`);
  }
  return response.json() as Promise<T>;
}

const SCENARIO_PATH: Record<string, string> = {
  "recommendation-review": "/agent/run/recommendation-review",
  "supplier-shortfall": "/agent/run/supplier-shortfall",
  "demand-change": "/agent/run/demand-change",
  "constrained-buy": "/agent/run/constrained-buy",
};

export const api = {
  health: () => request<HealthResponse>("/health"),
  scenarios: () => request<Scenario[]>("/scenarios"),
  runScenario: (id: string, body: Record<string, unknown>) =>
    request<Trace>(SCENARIO_PATH[id] ?? "/agent/run", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  insightCatalogue: () => request<InsightDef[]>("/insights"),
  insight: (id: string, query?: Record<string, string>) => {
    const params = new URLSearchParams(query);
    const suffix = params.toString() ? `?${params}` : "";
    return request<unknown>(`/insights/${id}${suffix}`);
  },
  pos: () => request<{ id: string; status: string; supplier_id: string; node_id: string; expected_delivery_date?: string; lines?: unknown[] }[]>("/pos"),
  approvals: () =>
    request<{ id: string; status: string; reason: string; urgency: string }[]>("/approvals"),
};
