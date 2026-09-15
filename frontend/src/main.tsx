import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import App from "./App";
import { ApprovalsPage } from "./pages/ApprovalsPage";
import { EvalsPage } from "./pages/EvalsPage";
import { PosPage } from "./pages/PosPage";
import { RunPage } from "./pages/RunPage";
import { SituationsPage } from "./pages/SituationsPage";
import { ValidationPage } from "./pages/ValidationPage";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<App />}>
            <Route path="/" element={<SituationsPage />} />
            <Route path="/run" element={<RunPage />} />
            <Route path="/run/:traceId" element={<RunPage />} />
            <Route path="/validation" element={<ValidationPage />} />
            <Route path="/validation/:traceId" element={<ValidationPage />} />
            <Route path="/approvals" element={<ApprovalsPage />} />
            <Route path="/pos" element={<PosPage />} />
            <Route path="/pos/:poId" element={<PosPage />} />
            <Route path="/evals" element={<EvalsPage />} />
            <Route path="/evals/:runId" element={<EvalsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
