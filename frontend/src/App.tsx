import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet } from "react-router-dom";
import { api } from "./api/client";
import { useKeyboardNav } from "./lib/keys";
import { NAV } from "./lib/status";

export default function App() {
  useKeyboardNav();
  const health = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 20_000,
  });
  const healthy = health.data?.status === "ok";

  return (
    <div className="flex h-screen flex-col">
      <header className="flex shrink-0 items-center justify-between border-b border-zinc-800 px-4 py-2">
        <div className="flex items-baseline gap-3">
          <h1 className="text-[13px] font-semibold tracking-wide text-zinc-100">Purchasing Agent</h1>
          <span className="font-mono text-[10px] uppercase tracking-widest text-zinc-500">Operator console</span>
        </div>
        <div className="flex items-center gap-2 font-mono text-[11px] text-zinc-400">
          <span className={`h-1.5 w-1.5 rounded-full ${healthy ? "bg-emerald-400" : "bg-amber-400"}`} />
          {health.isLoading ? "checking api" : healthy ? "api ok" : "api unreachable"}
          <span className="text-zinc-700">·</span>
          <span className="text-zinc-600">keys 1–6</span>
        </div>
      </header>
      <div className="flex min-h-0 flex-1">
        <nav className="w-44 shrink-0 overflow-auto border-r border-zinc-800 px-2 py-3">
          <ul className="space-y-0.5">
            {NAV.map((item) => (
              <li key={item.id}>
                <NavLink
                  to={item.to}
                  end={item.to === "/"}
                  className={({ isActive }) =>
                    `flex items-center justify-between rounded px-2 py-1.5 text-[12px] ${
                      isActive ? "bg-zinc-800 text-zinc-100" : "text-zinc-500 hover:text-zinc-300"
                    }`
                  }
                >
                  <span>{item.label}</span>
                  <kbd className="font-mono text-[10px] text-zinc-600">{item.key}</kbd>
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <main className="min-h-0 min-w-0 flex-1">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
