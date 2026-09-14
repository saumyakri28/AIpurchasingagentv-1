# Architecture

> Scaffold. Full diagrams land in Prompt 8. The mermaid below is the target shape of the system so later prompts fill modules rather than invent structure.

## Request path

```mermaid
flowchart LR
  UI[Buyer console] --> API[FastAPI routers]
  API --> Intake[Intake]
  Intake --> Loop[Agent loop]
  Loop --> Registry[Tool registry]
  Registry --> Domain[Calculators + ConstraintEngine + Policy]
  Domain --> DB[(SQLite source of truth)]
  Registry --> Supplier[Mock supplier API]
  Loop --> Trace[(DecisionTrace)]
```

## Write-action cycle (non-negotiable)

```mermaid
flowchart TD
  Decide[DECIDE + expected_outcome contract] --> Pre[PRE-VALIDATE ConstraintEngine]
  Pre -->|blocking| Revise[LLM revises — max 2]
  Revise --> Pre
  Pre -->|pass| Exec[EXECUTE write tool]
  Exec --> Post[POST-VERIFY re-read DB]
  Post -->|match| Report[REPORT trace]
  Post -->|mismatch| Recon[RECONCILE — max 2]
  Recon --> Decide
```

## Scenario 2 sequence (partial confirmation)

```mermaid
sequenceDiagram
  participant Agent
  participant Tools
  participant DB
  participant Supplier as Mock supplier API
  Agent->>Tools: investigate PO + inventory + forecast
  Agent->>Agent: declare expected_outcome
  Agent->>Tools: pre-validate
  Agent->>Supplier: submit / observe confirmed_qty
  Agent->>DB: post-verify persisted state
  alt mismatch (e.g. 250 of 500)
    Agent->>Tools: compensating action or escalate
    Agent->>DB: re-verify combined position
  end
```

## Data model

ER diagram is added in Prompt 1 / Prompt 8 once tables exist.
