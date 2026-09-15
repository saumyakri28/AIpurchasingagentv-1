# Purchasing agent eval report

Each column is a separate grader. There is no single opaque score.
Stability is the share of repeats that matched the modal (decision, pass-vector).

- id: `EV-20260915083109`
- llm: `fake`
- suite: `all`
- repeat: 3
- created: 2026-09-15T08:31:09Z
- cases passed: 13/13
- mean stability: 1.0

| Case | Decision | Info | Constraint | Action | Validation | Recovery | Explain | Stability | Overall |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E1 | pass | pass | pass | pass | pass | pass | pass | 1.0 | pass |
| E2 | pass | pass | pass | pass | pass | pass | pass | 1.0 | pass |
| E3 | pass | pass | pass | pass | pass | pass | pass | 1.0 | pass |
| E4 | pass | pass | pass | pass | pass | pass | pass | 1.0 | pass |
| E5 | pass | pass | pass | pass | pass | pass | pass | 1.0 | pass |
| E6 | pass | pass | pass | pass | pass | pass | pass | 1.0 | pass |
| E7 | pass | pass | pass | pass | pass | pass | pass | 1.0 | pass |
| E8 | pass | pass | pass | pass | pass | pass | pass | 1.0 | pass |
| E9 | pass | pass | pass | pass | pass | pass | pass | 1.0 | pass |
| E10 | pass | pass | pass | pass | pass | pass | pass | 1.0 | pass |
| E11 | pass | pass | pass | pass | pass | pass | pass | 1.0 | pass |
| E12 | pass | pass | pass | pass | pass | pass | pass | 1.0 | pass |
| E13 | pass | pass | pass | pass | pass | pass | pass | 1.0 | pass |

## Case notes

### E1 — Recommendation is actually right — accept REC-HEALTHY.

Decision: `accept` · stability 1.0

- **Decision**: pass (pass_rate=1.0) — got accept allowed ['accept']; qty 140 in range
- **Info**: pass (pass_rate=1.0) — required tools present before the decision
- **Constraint**: pass (pass_rate=1.0) — budgets, storage and executed PO lines hold
- **Action**: pass (pass_rate=1.0) — create_purchase_order matched
- **Validation**: pass (pass_rate=1.0) — pre-validation and post-verify reports present
- **Recovery**: pass (pass_rate=1.0) — not a failure-injection case
- **Explain**: pass (pass_rate=1.0) — all cited numbers appear in a tool result

### E2 — Open PO already covers demand — reject REC-OVERBUY.

Decision: `reject` · stability 1.0

- **Decision**: pass (pass_rate=1.0) — got reject allowed ['reject']
- **Info**: pass (pass_rate=1.0) — required tools present before the decision
- **Constraint**: pass (pass_rate=1.0) — budgets, storage and executed PO lines hold
- **Action**: pass (pass_rate=1.0) — no write
- **Validation**: pass (pass_rate=1.0) — pre-validation and post-verify reports present
- **Recovery**: pass (pass_rate=1.0) — not a failure-injection case
- **Explain**: pass (pass_rate=1.0) — all cited numbers appear in a tool result

### E3 — Need ~320 but MOQ 1000 — modify toward MOQ then escalate if C7/C12 block; state the cost of excess.

Decision: `escalate` · stability 1.0

- **Decision**: pass (pass_rate=1.0) — got escalate allowed ['escalate', 'modify']
- **Info**: pass (pass_rate=1.0) — required tools present before the decision
- **Constraint**: pass (pass_rate=1.0) — budgets, storage and executed PO lines hold
- **Action**: pass (pass_rate=1.0) — escalate matched
- **Validation**: pass (pass_rate=1.0) — pre-validation and post-verify reports present
- **Recovery**: pass (pass_rate=1.0) — not a failure-injection case
- **Explain**: pass (pass_rate=1.0) — all cited numbers appear in a tool result

### E4 — Budget insufficient — do not buy 400. suggested_max is 0 so escalate with an approval request (partial buy is not feasible).

Decision: `escalate` · stability 1.0

- **Decision**: pass (pass_rate=1.0) — got escalate allowed ['escalate']
- **Info**: pass (pass_rate=1.0) — required tools present before the decision
- **Constraint**: pass (pass_rate=1.0) — budgets, storage and executed PO lines hold
- **Action**: pass (pass_rate=1.0) — escalate matched
- **Validation**: pass (pass_rate=1.0) — pre-validation and post-verify reports present
- **Recovery**: pass (pass_rate=1.0) — not a failure-injection case
- **Explain**: pass (pass_rate=1.0) — all cited numbers appear in a tool result

### E5 — Storage full — reduce to suggested_max_feasible_qty 96. Do not execute 800.

Decision: `modify` · stability 1.0

- **Decision**: pass (pass_rate=1.0) — got modify allowed ['modify']; qty 96 in range
- **Info**: pass (pass_rate=1.0) — required tools present before the decision
- **Constraint**: pass (pass_rate=1.0) — budgets, storage and executed PO lines hold
- **Action**: pass (pass_rate=1.0) — create_purchase_order matched
- **Validation**: pass (pass_rate=1.0) — pre-validation and post-verify reports present
- **Recovery**: pass (pass_rate=1.0) — not a failure-injection case
- **Explain**: pass (pass_rate=1.0) — all cited numbers appear in a tool result

### E6 — Lead time misses the stockout date — do not buy from Acme; escalate or switch to a faster supplier.

Decision: `escalate` · stability 1.0

- **Decision**: pass (pass_rate=1.0) — got escalate allowed ['escalate', 'modify']
- **Info**: pass (pass_rate=1.0) — required tools present before the decision
- **Constraint**: pass (pass_rate=1.0) — budgets, storage and executed PO lines hold
- **Action**: pass (pass_rate=1.0) — escalate matched
- **Validation**: pass (pass_rate=1.0) — pre-validation and post-verify reports present
- **Recovery**: pass (pass_rate=1.0) — not a failure-injection case
- **Explain**: pass (pass_rate=1.0) — all cited numbers appear in a tool result

### E7 — Supplier confirms 250 of 500 but inventory is sufficient — accept the short, no new PO.

Decision: `accept` · stability 1.0

- **Decision**: pass (pass_rate=1.0) — got accept allowed ['accept']
- **Info**: pass (pass_rate=1.0) — required tools present before the decision
- **Constraint**: pass (pass_rate=1.0) — budgets, storage and executed PO lines hold
- **Action**: pass (pass_rate=1.0) — no write
- **Validation**: pass (pass_rate=1.0) — pre-validation and post-verify reports present
- **Recovery**: pass (pass_rate=1.0) — not a failure-injection case
- **Explain**: pass (pass_rate=1.0) — all cited numbers appear in a tool result

### E8 — Supplier confirms 250 of 500 and inventory is insufficient — source remainder from QuickShip; QuickShip then partial-confirms. Detect mismatch, reconcile, do not report success.

Decision: `escalate` · stability 1.0

- **Decision**: pass (pass_rate=1.0) — got escalate allowed ['escalate']
- **Info**: pass (pass_rate=1.0) — required tools present before the decision
- **Constraint**: pass (pass_rate=1.0) — budgets, storage and executed PO lines hold
- **Action**: pass (pass_rate=1.0) — create_purchase_order matched
- **Validation**: pass (pass_rate=1.0) — pre-validation and post-verify reports present
- **Recovery**: pass (pass_rate=1.0) — detected mismatch and compensated / escalated
- **Explain**: pass (pass_rate=1.0) — all cited numbers appear in a tool result

### E9 — Real demand spike — increase qty (do not keep the stale 180 rec).

Decision: `modify` · stability 1.0

- **Decision**: pass (pass_rate=1.0) — got modify allowed ['modify']; qty 240 in range
- **Info**: pass (pass_rate=1.0) — required tools present before the decision
- **Constraint**: pass (pass_rate=1.0) — budgets, storage and executed PO lines hold
- **Action**: pass (pass_rate=1.0) — create_purchase_order matched
- **Validation**: pass (pass_rate=1.0) — pre-validation and post-verify reports present
- **Recovery**: pass (pass_rate=1.0) — not a failure-injection case
- **Explain**: pass (pass_rate=1.0) — all cited numbers appear in a tool result

### E10 — Promo-driven one-off spike — do NOT increase. Anti-overreaction.

Decision: `reject` · stability 1.0

- **Decision**: pass (pass_rate=1.0) — got reject allowed ['reject']
- **Info**: pass (pass_rate=1.0) — required tools present before the decision
- **Constraint**: pass (pass_rate=1.0) — budgets, storage and executed PO lines hold
- **Action**: pass (pass_rate=1.0) — no write
- **Validation**: pass (pass_rate=1.0) — pre-validation and post-verify reports present
- **Recovery**: pass (pass_rate=1.0) — not a failure-injection case
- **Explain**: pass (pass_rate=1.0) — all cited numbers appear in a tool result

### E11 — Supplier API rejects the submitted PO — detect via post-verify, recover, re-verify. Do not report success.

Decision: `escalate` · stability 1.0

- **Decision**: pass (pass_rate=1.0) — got escalate allowed ['escalate']
- **Info**: pass (pass_rate=1.0) — required tools present before the decision
- **Constraint**: pass (pass_rate=1.0) — budgets, storage and executed PO lines hold
- **Action**: pass (pass_rate=1.0) — create_purchase_order matched
- **Validation**: pass (pass_rate=1.0) — pre-validation and post-verify reports present
- **Recovery**: pass (pass_rate=1.0) — detected mismatch and compensated / escalated
- **Explain**: pass (pass_rate=1.0) — all cited numbers appear in a tool result

### E12 — Supplier confirms then silently revises lead time — detect the delivery-date diff and re-plan (escalate).

Decision: `escalate` · stability 1.0

- **Decision**: pass (pass_rate=1.0) — got escalate allowed ['escalate']
- **Info**: pass (pass_rate=1.0) — required tools present before the decision
- **Constraint**: pass (pass_rate=1.0) — budgets, storage and executed PO lines hold
- **Action**: pass (pass_rate=1.0) — create_purchase_order matched
- **Validation**: pass (pass_rate=1.0) — pre-validation and post-verify reports present
- **Recovery**: pass (pass_rate=1.0) — detected mismatch and compensated / escalated
- **Explain**: pass (pass_rate=1.0) — all cited numbers appear in a tool result

### E13 — Missing / contradictory node data — investigate_further or escalate. Never fabricate a South qty.

Decision: `investigate_further` · stability 1.0

- **Decision**: pass (pass_rate=1.0) — got investigate_further allowed ['escalate', 'investigate_further']
- **Info**: pass (pass_rate=1.0) — required tools present before the decision
- **Constraint**: pass (pass_rate=1.0) — budgets, storage and executed PO lines hold
- **Action**: pass (pass_rate=1.0) — no write
- **Validation**: pass (pass_rate=1.0) — pre-validation and post-verify reports present
- **Recovery**: pass (pass_rate=1.0) — not a failure-injection case
- **Explain**: pass (pass_rate=1.0) — all cited numbers appear in a tool result

