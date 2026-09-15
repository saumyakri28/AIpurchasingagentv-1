/** View models for the operator console. Values always come from the API. */

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
  brief?: string;
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

export type Alternative = {
  option: string;
  why_not: string;
};

export type ExpectedOutcome = {
  po_status?: string | null;
  ordered_qty?: number | null;
  committed_cost?: number | null;
  budget_remaining_after?: number | null;
  storage_used_after?: number | null;
  projected_cover_days?: number | null;
  stockout_risk?: string | null;
};

export type Decision = {
  decision: string;
  final_quantity?: number | null;
  supplier_id?: string | null;
  node?: string | null;
  expected_delivery_date?: string | null;
  confidence?: number;
  reasoning_summary?: string;
  key_factors?: KeyFactor[];
  constraints_considered?: string[];
  alternatives_considered?: Alternative[];
  expected_outcome?: ExpectedOutcome;
  requires_human_approval?: boolean;
  approval_reason?: string | null;
};

export type VerificationDiff = {
  field: string;
  expected: unknown;
  actual: unknown;
};

export type Verification = {
  matched: boolean;
  diffs: VerificationDiff[];
};

export type TraceStep = {
  stage: string;
  tool?: string | null;
  arguments?: Record<string, unknown> | null;
  result?: unknown;
  latency_ms?: number | null;
  note?: string | null;
};

export type TraceSummary = {
  id: string;
  scenario_type?: string | null;
  status: string;
  created_at?: string | null;
  completed_at?: string | null;
  decision?: string | null;
  plan?: string | null;
  matched?: boolean | null;
  po_id?: string | null;
};

export type Trace = TraceSummary & {
  intake?: Record<string, unknown>;
  steps?: TraceStep[];
  decision?: Decision | string | null;
  verification?: Verification | null;
  actions?: {
    id: string;
    step_index: number;
    tool_name?: string | null;
    arguments?: Record<string, unknown> | null;
    result?: unknown;
    latency_ms?: number | null;
  }[];
};

export type ConstraintRow = {
  name: string;
  status: string;
  actual?: number | string | null;
  limit?: number | string | null;
  slack?: number | null;
  message?: string;
};

export type CoverPoint = {
  date: string;
  stock: number;
  forecast: number;
  incoming: number;
};

export type CoverChart = {
  sku: string;
  node: string;
  as_of: string;
  coverage_days: number | null;
  projected_stockout_date: string | null;
  lead_time_days: number;
  lead_time_end: string;
  series: CoverPoint[];
};

export type WorldSummary = {
  world: string | null;
  as_of: string;
  inventory_positions: number;
  open_po_count: number;
  pending_approvals: number;
  open_pos: {
    id: string;
    status: string;
    supplier_id: string;
    node_id: string;
    expected_delivery_date?: string | null;
    ordered_qty: number;
    confirmed_qty: number;
  }[];
  budgets: {
    id: string;
    node_id: string;
    category: string;
    remaining: number;
    allocated: number;
    committed: number;
  }[];
  hygiene: { count: number; purchase_orders: { po_id: string; flags: string[]; overdue_days?: number | null }[] };
  events: {
    id: string;
    ts?: string | null;
    event_type: string;
    entity_type?: string | null;
    entity_id?: string | null;
  }[];
};

export type Approval = {
  id: string;
  trace_id?: string | null;
  status: string;
  reason: string;
  urgency: string;
  options_considered?: unknown[];
  action_payload?: Record<string, unknown>;
  created_at?: string | null;
  decided_by?: string | null;
  decided_at?: string | null;
};

export type PurchaseOrder = {
  id: string;
  supplier_id: string;
  node_id: string;
  status: string;
  created_at?: string | null;
  expected_delivery_date?: string | null;
  total_cost?: number;
  created_by?: string;
  lines?: {
    id: string;
    product_id: string;
    ordered_qty: number;
    confirmed_qty: number;
    received_qty: number;
    unit_price: number;
  }[];
  events?: { id: string; ts?: string | null; event_type: string; payload?: unknown }[];
};

export type EvalAssertion = { category: string; passed: boolean; notes?: string };

export type EvalDimension = { passed: boolean; notes?: string; pass_rate?: number };

export type EvalCaseRow = {
  id: string;
  description?: string;
  passed: boolean;
  stability?: number;
  decision?: string | null;
  assertions: EvalAssertion[];
  dimensions?: Record<string, EvalDimension>;
  repeats?: unknown[];
};

export type EvalRun = {
  id: string;
  kind?: string;
  suite?: string;
  llm?: string;
  repeat?: number;
  scenario_type?: string | null;
  status: string;
  created_at?: string | null;
  passed: boolean;
  assertions: EvalAssertion[];
  decision?: string | null;
  matched?: boolean | null;
  cases_passed?: number;
  cases_total?: number;
  stability_mean?: number;
  cases?: EvalCaseRow[];
  markdown?: string;
  trace?: Trace;
};

export function asDecision(value: Trace["decision"]): Decision | null {
  if (!value || typeof value === "string") return null;
  return value;
}
