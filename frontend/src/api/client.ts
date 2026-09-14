export type HealthResponse = {
  status: string;
  service: string;
};

export type Scenario = {
  id: string;
  title: string;
};

const API_BASE = import.meta.env.VITE_API_URL ?? "";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    throw new Error(`${path} failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => getJson<HealthResponse>("/health"),
  scenarios: () => getJson<Scenario[]>("/scenarios"),
};
