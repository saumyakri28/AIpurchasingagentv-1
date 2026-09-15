import type { Trace, TraceStep } from "../api/types";

const LAST_TRACE_KEY = "pa.lastTraceId";

export function rememberTrace(id: string) {
  try {
    sessionStorage.setItem(LAST_TRACE_KEY, id);
  } catch {
    /* private mode */
  }
}

export function readLastTraceId(): string | null {
  try {
    return sessionStorage.getItem(LAST_TRACE_KEY);
  } catch {
    return null;
  }
}

export function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function skuNode(trace: Trace | undefined): { sku: string; node: string } | null {
  if (!trace) return null;
  const intake = trace.intake ?? {};
  const sku = typeof intake.sku === "string" ? intake.sku : null;
  const node = typeof intake.node === "string" ? intake.node : null;
  if (sku && node) return { sku, node };
  return null;
}

export function recommendedQty(trace: Trace | undefined): number | null {
  if (!trace) return null;
  const intakeQty = trace.intake?.recommended_qty;
  if (typeof intakeQty === "number") return intakeQty;
  for (const step of trace.steps ?? []) {
    if (step.tool !== "compute_replenishment_plan") continue;
    const result = asRecord(step.result);
    const qty = result?.recommended_qty ?? result?.rounded_qty ?? result?.qty;
    if (typeof qty === "number") return qty;
  }
  return null;
}

export function stepsOf(steps: TraceStep[] | undefined, stage: string): TraceStep[] {
  return (steps ?? []).filter((s) => s.stage === stage);
}

export function lastTool(steps: TraceStep[] | undefined, tool: string): TraceStep | null {
  const hits = (steps ?? []).filter((s) => s.tool === tool);
  return hits[hits.length - 1] ?? null;
}

export const WORLD_TO_SCENARIO: Record<string, string> = {
  recommendation_review: "recommendation-review",
  supplier_shortfall: "supplier-shortfall",
  demand_change: "demand-change",
  constrained_buy: "constrained-buy",
};
