import type { TraceStep } from "../api/types";
import { CONSTRAINTS, type ConstraintTone, toneForStatus } from "../lib/status";

export type Meter = {
  code: string;
  name: string;
  status: string;
  tone: ConstraintTone;
  actual: string;
  limit: string;
  slack: string;
  message: string;
  binding: boolean;
};

function lastValidate(steps: TraceStep[] | undefined): Record<string, unknown> | null {
  if (!steps) return null;
  for (let i = steps.length - 1; i >= 0; i -= 1) {
    const step = steps[i];
    if (step.tool === "validate_action" && step.result && typeof step.result === "object") {
      return step.result as Record<string, unknown>;
    }
  }
  return null;
}

function fmt(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  return String(value);
}

export function metersFromTrace(steps: TraceStep[] | undefined): Meter[] {
  const report = lastValidate(steps);
  const results = (report?.results as Record<string, unknown>[] | undefined) ?? [];
  const binding = report?.binding_constraint as Record<string, unknown> | undefined;
  const byName = new Map(results.map((row) => [String(row.name), row]));
  return CONSTRAINTS.map(([code, name]) => {
    const row = byName.get(name);
    const status = String(row?.status ?? "idle");
    return {
      code,
      name,
      status,
      tone: toneForStatus(status),
      actual: fmt(row?.actual),
      limit: fmt(row?.limit),
      slack: fmt(row?.slack),
      message: String(row?.message ?? ""),
      binding: Boolean(binding && binding.name === name && status === "fail"),
    };
  });
}
