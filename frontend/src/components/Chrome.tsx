import { useState, type ReactNode } from "react";
import { ApiError } from "../api/client";

export function JsonCollapse({
  label,
  value,
  defaultOpen = false,
}: {
  label: string;
  value: unknown;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button
        type="button"
        className="font-mono text-[11px] text-zinc-500 hover:text-zinc-300"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {open ? "▾" : "▸"} {label}
      </button>
      {open && (
        <pre className="mt-1 max-h-48 overflow-auto rounded border border-zinc-800 bg-zinc-950 p-2 font-mono text-[10px] leading-snug text-zinc-400">
          {JSON.stringify(value, null, 2)}
        </pre>
      )}
    </div>
  );
}

export function Panel({
  title,
  children,
  className = "",
}: {
  title: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`flex min-h-0 flex-col border-zinc-800 ${className}`}>
      <header className="shrink-0 border-b border-zinc-800 px-3 py-1.5 font-mono text-[10px] uppercase tracking-widest text-zinc-500">
        {title}
      </header>
      <div className="min-h-0 flex-1 overflow-auto p-3">{children}</div>
    </section>
  );
}

export function ErrorBanner({ error }: { error: unknown }) {
  if (!error) return null;
  const message =
    error instanceof ApiError
      ? error.body || error.message
      : error instanceof Error
        ? error.message
        : String(error);
  return (
    <p className="rounded border border-rose-900/70 bg-rose-950/50 px-3 py-2 text-[12px] text-rose-200">
      {message}
    </p>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="text-[12px] text-zinc-500">{children}</p>;
}
