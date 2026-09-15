export const CONSTRAINTS = [
  ["C1", "budget_sufficient"],
  ["C2", "storage_capacity_available"],
  ["C3", "moq_satisfied"],
  ["C4", "order_multiple_satisfied"],
  ["C5", "max_order_qty_respected"],
  ["C6", "supplier_active_and_sells_product"],
  ["C7", "lead_time_beats_stockout"],
  ["C8", "no_redundant_coverage_with_open_pos"],
  ["C9", "shelf_life_vs_cover_days"],
  ["C10", "receiving_capacity_per_day"],
  ["C11", "supplier_reliability_floor"],
  ["C12", "total_cover_within_max_weeks_of_supply"],
] as const;

export type ConstraintTone = "pass" | "warn" | "fail" | "idle";

export function toneForStatus(status?: string): ConstraintTone {
  const s = (status || "").toLowerCase();
  if (s === "fail" || s === "block" || s === "blocked") return "fail";
  if (s === "warn" || s === "warning") return "warn";
  if (s === "pass" || s === "ok") return "pass";
  return "idle";
}

export function verdictTone(decision?: string | null): ConstraintTone {
  switch ((decision || "").toLowerCase()) {
    case "accept":
      return "pass";
    case "modify":
      return "pass";
    case "reject":
      return "warn";
    case "investigate_further":
      return "warn";
    case "escalate":
      return "fail";
    default:
      return "idle";
  }
}

export const toneClass: Record<ConstraintTone, string> = {
  pass: "text-emerald-400 border-emerald-800 bg-emerald-950/40",
  warn: "text-amber-300 border-amber-800 bg-amber-950/40",
  fail: "text-rose-400 border-rose-800 bg-rose-950/50",
  idle: "text-zinc-400 border-zinc-800 bg-zinc-900/40",
};

export const toneDot: Record<ConstraintTone, string> = {
  pass: "bg-emerald-400",
  warn: "bg-amber-400",
  fail: "bg-rose-400",
  idle: "bg-zinc-600",
};

export const NAV = [
  { id: "situations", to: "/", key: "1", label: "Situations" },
  { id: "run", to: "/run", key: "2", label: "Run" },
  { id: "validation", to: "/validation", key: "3", label: "Validation" },
  { id: "approvals", to: "/approvals", key: "4", label: "Approvals" },
  { id: "pos", to: "/pos", key: "5", label: "Purchase Orders" },
  { id: "evals", to: "/evals", key: "6", label: "Evaluation" },
] as const;
