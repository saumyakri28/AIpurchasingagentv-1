import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, type Approval } from "../api/client";
import { Empty, ErrorBanner } from "../components/Chrome";
import { toneClass, toneForStatus } from "../lib/status";

export function ApprovalsPage() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["approvals"], queryFn: api.approvals });
  const [qty, setQty] = useState<Record<string, string>>({});
  const [active, setActive] = useState<string | null>(null);

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["approvals"] });
    void qc.invalidateQueries({ queryKey: ["pos"] });
    void qc.invalidateQueries({ queryKey: ["traces"] });
    void qc.invalidateQueries({ queryKey: ["world"] });
    void qc.invalidateQueries({ queryKey: ["evals"] });
  };

  const approve = useMutation({
    mutationFn: (id: string) => api.approve(id),
    onSuccess: invalidate,
  });
  const reject = useMutation({
    mutationFn: (id: string) => api.rejectApproval(id),
    onSuccess: invalidate,
  });
  const modify = useMutation({
    mutationFn: ({ id, n }: { id: string; n: number }) => api.modifyApprove(id, n),
    onSuccess: invalidate,
  });

  const rows = q.data ?? [];
  const pending = rows.filter((r) => r.status === "pending");
  const rest = rows.filter((r) => r.status !== "pending");
  const busy = approve.isPending || reject.isPending || modify.isPending;

  return (
    <div className="h-full overflow-auto p-4">
      <h2 className="text-sm font-medium text-zinc-100">Approvals</h2>
      <p className="mt-0.5 text-[12px] text-zinc-500">
        Approve re-enters the loop: submit the pending PO, then post-verify against the trace contract.
      </p>
      {(q.isError || approve.isError || reject.isError || modify.isError) && (
        <div className="mt-3 space-y-2">
          <ErrorBanner error={q.error} />
          <ErrorBanner error={approve.error} />
          <ErrorBanner error={reject.error} />
          <ErrorBanner error={modify.error} />
        </div>
      )}
      <ul className="mt-4 space-y-2">
        {pending.map((row) => (
          <ApprovalCard
            key={row.id}
            row={row}
            qty={qty[row.id] ?? ""}
            onQty={(v) => setQty((p) => ({ ...p, [row.id]: v }))}
            busy={busy}
            expanded={active === row.id}
            onToggle={() => setActive((id) => (id === row.id ? null : row.id))}
            onApprove={() => approve.mutate(row.id)}
            onReject={() => reject.mutate(row.id)}
            onModify={() => {
              const n = Number(qty[row.id]);
              if (Number.isFinite(n) && n > 0) modify.mutate({ id: row.id, n });
            }}
          />
        ))}
        {rest.map((row) => (
          <ApprovalCard
            key={row.id}
            row={row}
            qty={qty[row.id] ?? ""}
            onQty={(v) => setQty((p) => ({ ...p, [row.id]: v }))}
            busy
            expanded={active === row.id}
            onToggle={() => setActive((id) => (id === row.id ? null : row.id))}
          />
        ))}
        {rows.length === 0 && <li><Empty>No approval requests yet. Low-confidence writes park here.</Empty></li>}
      </ul>
    </div>
  );
}

function ApprovalCard({
  row,
  qty,
  onQty,
  busy,
  expanded,
  onToggle,
  onApprove,
  onReject,
  onModify,
}: {
  row: Approval;
  qty: string;
  onQty: (v: string) => void;
  busy: boolean;
  expanded: boolean;
  onToggle: () => void;
  onApprove?: () => void;
  onReject?: () => void;
  onModify?: () => void;
}) {
  const pending = row.status === "pending";
  const payload = row.action_payload ?? {};
  const poId = typeof payload.po_id === "string" ? payload.po_id : null;
  const options = Array.isArray(row.options_considered) ? row.options_considered : [];
  return (
    <li className="rounded border border-zinc-800 bg-zinc-900/40 p-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className={`rounded border px-1.5 py-0.5 font-mono text-[10px] uppercase ${toneClass[toneForStatus(row.status === "pending" ? "warn" : row.status === "rejected" ? "fail" : "pass")]}`}>
          {row.status}
        </span>
        <span className="font-mono text-[11px] text-zinc-500">{row.id}</span>
        <span className="font-mono text-[10px] uppercase text-amber-300">{row.urgency}</span>
        {row.trace_id && (
          <Link to={`/run/${row.trace_id}`} className="font-mono text-[11px] text-teal-400">
            trace
          </Link>
        )}
        {poId && (
          <Link to={`/pos/${poId}`} className="font-mono text-[11px] text-zinc-400">
            {poId}
          </Link>
        )}
        <button type="button" onClick={onToggle} className="ml-auto font-mono text-[11px] text-zinc-500">
          {expanded ? "collapse" : "detail"}
        </button>
      </div>
      <p className="mt-2 text-[12px] text-zinc-300">{row.reason}</p>
      {pending && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={onApprove}
            className="rounded border border-emerald-800 bg-emerald-950/50 px-2 py-1 font-mono text-[11px] text-emerald-200 disabled:opacity-50"
          >
            Approve
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={onReject}
            className="rounded border border-rose-800 bg-rose-950/40 px-2 py-1 font-mono text-[11px] text-rose-200 disabled:opacity-50"
          >
            Reject
          </button>
          <label className="flex items-center gap-1 font-mono text-[11px] text-zinc-500">
            qty
            <input
              className="w-20 rounded border border-zinc-700 bg-zinc-950 px-1.5 py-1 text-zinc-200"
              value={qty}
              onChange={(e) => onQty(e.target.value)}
              inputMode="numeric"
            />
          </label>
          <button
            type="button"
            disabled={busy || !qty}
            onClick={onModify}
            className="rounded border border-teal-800 bg-teal-950/50 px-2 py-1 font-mono text-[11px] text-teal-100 disabled:opacity-50"
          >
            Modify-and-approve
          </button>
        </div>
      )}
      {expanded && (
        <div className="mt-3 space-y-2 border-t border-zinc-800 pt-2">
          <p className="font-mono text-[10px] uppercase tracking-widest text-zinc-500">options considered</p>
          {options.length === 0 && <Empty>None recorded on this request.</Empty>}
          <ul className="space-y-1 text-[12px] text-zinc-400">
            {options.map((opt, i) => {
              if (opt && typeof opt === "object" && "option" in opt) {
                const rowOpt = opt as { option: string; why_not?: string };
                return (
                  <li key={i}>
                    <span className="text-zinc-200">{rowOpt.option}</span>
                    {rowOpt.why_not ? <span> — {rowOpt.why_not}</span> : null}
                  </li>
                );
              }
              return (
                <li key={i} className="font-mono text-[11px]">
                  {JSON.stringify(opt)}
                </li>
              );
            })}
          </ul>
          <pre className="max-h-40 overflow-auto rounded border border-zinc-800 bg-zinc-950 p-2 font-mono text-[10px] text-zinc-500">
            {JSON.stringify(payload, null, 2)}
          </pre>
        </div>
      )}
    </li>
  );
}
