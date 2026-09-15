# Demo — four scenarios

Same agent, four intakes. Clock is frozen at **2026-09-15**. Default LLM is FakeLLM (no API key).

If the console is unavailable, Scenario 1 still runs in the terminal:

```bash
make setup && make demo
```

Expect `verdict   REJECT` on `REC-OVERBUY`. Details are in README §1.

For the UI:

```bash
make setup && make seed && make dev
```

Open [http://localhost:5173](http://localhost:5173). Header must read **api ok**. If it says **api unreachable**, restart `make dev-backend`. Keys `1`–`6` switch screens. Each **Run agent** click **reseeds** that scenario’s world.

---

## S1 — Purchase Recommendation Review

**Situations** (key `1`) → card `recommendation-review`.

### Overbuy (default) — reject

1. Variant: **REC-OVERBUY — reject (open PO already covers)**.
2. Click **Run agent**.
3. **Run** (key `2`): **REJECT** chip. Timeline shows `get_recommendation` → `get_open_purchase_orders` (`PO-COVERED` 800 confirmed) → `compute_replenishment_plan` (`rounded_qty=0`, cover ~38 days) → `validate_action` failed.
4. Right column: C8 / C12 not idle-green.
5. **Validation** (key `3`): no write, post-verify matched.
6. **Purchase Orders** (key `5`): still `PO-COVERED`; no agent PO.

### Healthy — accept 140

1. Variant: **REC-HEALTHY — accept**.
2. Click **Run agent**.
3. **ACCEPT** chip, quantity 140, a new PO on Acme, post-verify matched.
4. POs page shows an agent-created confirmed order.

### MOQ — escalate

1. Variant: **REC-MOQ — modify toward MOQ (then escalate if C7 blocks)**.
2. Click **Run agent**.
3. **ESCALATE** (or a modify attempt then escalate). Need ~320 vs Acme MOQ 1000; rounded 1000 misses the stockout date / over-covers. No illegal 1000-unit buy.

---

## S2 — Supplier Cannot Fulfil

Card `supplier-shortfall`. World already has `PO-SHORTFALL` at 500 ordered / 250 confirmed.

### Gap — modify, QuickShip 80

1. Variant: **PO-SHORTFALL 500→250 — bridge with QuickShip**.
2. Click **Run agent**.
3. **MODIFY**, quantity **80**, supplier `SUP-FAST`.
4. Look for: on-hand 70 + 250 arriving **2026-09-22** still stocks out **2026-09-20**; 3-day QuickShip is the bridge. A **new** PO, not a split of the Acme line.
5. Validation: `expected_outcome.po_status=confirmed` matches the DB. If a later supplier call had come back partial, this is the screen that would paint the mismatch (see README §7 / E11 for a captured recovery).

### Covered — accept the short

1. Variant: **PO-SHORTFALL 500→250 — accept the short (cover holds)**.
2. Click **Run agent**.
3. **ACCEPT**, **no new PO**. FakeLLM uses the accept-the-short script. Eval E7 reseeds `supplier_shortfall_covered` (on-hand **2000**) so the numbers actually hold; the console reseeds `supplier_shortfall` (on-hand 70). With a live model this variant should look like **gap**, not covered.

---

## S3 — Demand / Forecast Changed

Card `demand-change`. Use `get_demand_stats`: `spike_detected` vs `anomaly_flag`.

### Promo — reject

1. Variant: **SKU-PROMO — reject (one-off bulk invoice)**.
2. Click **Run agent**.
3. **REJECT**. Rec of 600 treats a promo day as the new run-rate. No PO.

### Spike — investigate further (UI default)

1. Variant: **SKU-SPIKE — investigate further**.
2. Click **Run agent**.
3. **INVESTIGATE_FURTHER**. Forecast still ~18 u/day; do not invent a buy qty.

### Increase — modify 240 (eval script)

1. Variant: **SKU-SPIKE — modify 240**.
2. Click **Run agent**.
3. **MODIFY** 240 (multiple of 24). Same world as spike; different canned script (eval E9).

### Missing node — investigate

1. Variant: **SKU-SPIKE at DC-SOUTH — investigate**.
2. Click **Run agent**.
3. **INVESTIGATE_FURTHER**. No South inventory row. Never a fabricated South qty.

---

## S4 — Purchasing Constraint

Card `constrained-buy`. Binding constraint comes from `validate_action`, not from the model’s prose.

### Budget — escalate, never buy 400

1. Variant: **SKU-BUDGET — escalate (coffee envelope $600 vs $6400)**.
2. Click **Run agent**.
3. **ESCALATE**. C1 fails; `suggested_max_feasible_qty=0` (even MOQ 50 = $800). Approvals may show a parked request. **Purchase Orders** must not contain a 400-unit coffee PO.

### Storage — modify 96

1. Variant: **SKU-STORAGE — modify to 96 (South cube)**.
2. Click **Run agent**.
3. **MODIFY** **96**, not 800. C2 was binding; engine suggested 96.

### MOQ vs stockout — escalate

1. Variant: **SKU-MOQ — escalate**.
2. Click **Run agent**.
3. **ESCALATE**. Acme 1000 is too much and too slow; QuickShip is still a day late. No silent 1000-unit buy.

---

## Evaluation screen

Key `6`. **Run evals** posts `suite=all`, `llm=fake` (no key). Expect 13/13 on FakeLLM. Open a run to see the seven dimensions, not a single score.

```bash
make eval
```

writes `backend/evals/report.md`.
