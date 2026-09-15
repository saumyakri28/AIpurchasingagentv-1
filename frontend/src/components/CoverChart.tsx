import type { CoverChart } from "../api/types";

export function CoverChart({ data }: { data: CoverChart }) {
  const width = 320;
  const height = 120;
  const pad = 8;
  const series = data.series.slice(0, 42);
  if (series.length < 2) {
    return <p className="text-[12px] text-zinc-500">No cover series for this SKU.</p>;
  }
  const stocks = series.map((p) => p.stock);
  const forecasts = series.map((p) => p.forecast);
  const maxY = Math.max(1, ...stocks, ...forecasts);
  const x = (i: number) => pad + (i / (series.length - 1)) * (width - pad * 2);
  const y = (v: number) => height - pad - (v / maxY) * (height - pad * 2);
  const stockPath = series.map((p, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(p.stock)}`).join(" ");
  const fcstPath = series.map((p, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(p.forecast)}`).join(" ");
  const stockoutIdx = data.projected_stockout_date
    ? series.findIndex((p) => p.date === data.projected_stockout_date)
    : -1;
  const leadIdx = Math.min(series.length - 1, data.lead_time_days);

  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full text-zinc-500" role="img" aria-label="Stock cover">
        <rect x={x(0)} width={x(leadIdx) - x(0)} y={pad} height={height - pad * 2} className="fill-teal-950/80" />
        {series.map((p, i) =>
          p.incoming > 0 ? (
            <rect
              key={`in-${p.date}`}
              x={x(i) - 1.5}
              y={y(p.incoming)}
              width={3}
              height={Math.max(1, height - pad - y(p.incoming))}
              className="fill-teal-700/70"
            />
          ) : null,
        )}
        <path d={fcstPath} fill="none" stroke="currentColor" strokeWidth="1" strokeDasharray="3 3" />
        <path d={stockPath} fill="none" stroke="#0d9488" strokeWidth="1.5" />
        {stockoutIdx >= 0 && (
          <line x1={x(stockoutIdx)} x2={x(stockoutIdx)} y1={pad} y2={height - pad} stroke="#f43f5e" strokeWidth="1" />
        )}
      </svg>
      <dl className="mt-1 grid grid-cols-2 gap-x-2 font-mono text-[10px] text-zinc-500">
        <div>cover {data.coverage_days ?? "∞"}d</div>
        <div>lead {data.lead_time_days}d → {data.lead_time_end}</div>
        <div className="text-rose-400">stockout {data.projected_stockout_date ?? "none"}</div>
        <div className="text-teal-500">solid = projected stock · bars = inbound · dashed = forecast</div>
      </dl>
    </div>
  );
}
