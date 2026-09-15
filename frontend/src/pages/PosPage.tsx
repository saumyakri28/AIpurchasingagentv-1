import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { Empty, ErrorBanner, JsonCollapse } from "../components/Chrome";
import { toneClass, toneForStatus } from "../lib/status";

function poTone(status: string) {
  const s = status.toLowerCase();
  if (s.includes("cancel") || s.includes("fail")) return toneForStatus("fail");
  if (s.includes("pending") || s.includes("short")) return toneForStatus("warn");
  if (s.includes("confirm") || s.includes("submit") || s.includes("receiv")) return toneForStatus("pass");
  return toneForStatus("idle");
}

export function PosPage() {
  const { poId } = useParams();
  const navigate = useNavigate();
  const list = useQuery({ queryKey: ["pos"], queryFn: api.pos });
  const detail = useQuery({
    queryKey: ["po", poId],
    queryFn: () => api.po(poId!),
    enabled: !!poId,
  });

  return (
    <div className="flex h-full min-h-0">
      <aside className="w-72 shrink-0 overflow-auto border-r border-zinc-800">
        <header className="sticky top-0 border-b border-zinc-800 bg-zinc-950 px-3 py-2">
          <h2 className="text-[13px] font-medium text-zinc-100">Purchase Orders</h2>
          <p className="font-mono text-[10px] text-zinc-600">{list.data?.length ?? 0} rows</p>
        </header>
        {list.isError && (
          <div className="p-2">
            <ErrorBanner error={list.error} />
          </div>
        )}
        <ul>
          {(list.data ?? []).map((po) => (
            <li key={po.id}>
              <button
                type="button"
                onClick={() => navigate(`/pos/${po.id}`)}
                className={`w-full border-b border-zinc-900 px-3 py-2 text-left ${
                  poId === po.id ? "bg-zinc-900" : "hover:bg-zinc-900/50"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-[12px] text-zinc-100">{po.id}</span>
                  <span className={`rounded border px-1 font-mono text-[10px] uppercase ${toneClass[poTone(po.status)]}`}>
                    {po.status}
                  </span>
                </div>
                <p className="mt-0.5 font-mono text-[10px] text-zinc-500">
                  {po.supplier_id} · {po.node_id} · {po.expected_delivery_date ?? "no ETA"}
                </p>
              </button>
            </li>
          ))}
          {list.data?.length === 0 && (
            <li className="p-3">
              <Empty>No purchase orders in this world.</Empty>
            </li>
          )}
        </ul>
      </aside>
      <section className="min-h-0 flex-1 overflow-auto p-4">
        {!poId && <Empty>Select a PO. Status history and the event-log audit trail load from the API.</Empty>}
        {detail.isError && <ErrorBanner error={detail.error} />}
        {detail.data && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-baseline gap-2">
              <h3 className="font-mono text-sm text-zinc-100">{detail.data.id}</h3>
              <span className={`rounded border px-1.5 py-0.5 font-mono text-[10px] uppercase ${toneClass[poTone(detail.data.status)]}`}>
                {detail.data.status}
              </span>
              <span className="font-mono text-[11px] text-zinc-500">
                {detail.data.supplier_id} → {detail.data.node_id}
              </span>
            </div>
            <dl className="grid grid-cols-2 gap-2 font-mono text-[11px] md:grid-cols-4">
              <div>
                <dt className="text-zinc-600">created</dt>
                <dd>{detail.data.created_at ?? "—"}</dd>
              </div>
              <div>
                <dt className="text-zinc-600">ETA</dt>
                <dd>{detail.data.expected_delivery_date ?? "—"}</dd>
              </div>
              <div>
                <dt className="text-zinc-600">cost</dt>
                <dd>{detail.data.total_cost ?? "—"}</dd>
              </div>
              <div>
                <dt className="text-zinc-600">by</dt>
                <dd>{detail.data.created_by ?? "—"}</dd>
              </div>
            </dl>
            <table className="w-full text-left font-mono text-[11px]">
              <thead className="text-[10px] uppercase tracking-widest text-zinc-600">
                <tr>
                  <th className="py-1">line</th>
                  <th>ordered</th>
                  <th>confirmed</th>
                  <th>received</th>
                  <th>price</th>
                </tr>
              </thead>
              <tbody>
                {(detail.data.lines ?? []).map((line) => (
                  <tr key={line.id} className="border-t border-zinc-800">
                    <td className="py-1 pr-2">{line.product_id}</td>
                    <td>{line.ordered_qty}</td>
                    <td>{line.confirmed_qty}</td>
                    <td>{line.received_qty}</td>
                    <td>{line.unit_price}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div>
              <h4 className="font-mono text-[10px] uppercase tracking-widest text-zinc-500">status history / audit</h4>
              <ol className="mt-2 space-y-2 border-l border-zinc-800 pl-3">
                {(detail.data.events ?? []).map((event) => (
                  <li key={event.id}>
                    <p className="font-mono text-[11px] text-zinc-200">{event.event_type}</p>
                    <p className="font-mono text-[10px] text-zinc-600">{event.ts ?? ""}</p>
                    {event.payload != null && <JsonCollapse label="payload" value={event.payload} />}
                  </li>
                ))}
                {(detail.data.events ?? []).length === 0 && <li><Empty>No event-log rows for this PO.</Empty></li>}
              </ol>
            </div>
            <Link to="/" className="font-mono text-[11px] text-zinc-500">
              ← situations
            </Link>
          </div>
        )}
      </section>
    </div>
  );
}
