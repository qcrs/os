import type { Catalog, EvidenceSnapshot, RunView, SystemHealth, TaskFlowIndex } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail ?? `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const studioApi = {
  evidence: () => request<EvidenceSnapshot>("/api/v1/evidence/current"),
  catalog: () => request<Catalog>("/api/v1/catalog"),
  health: () => request<SystemHealth>("/api/v1/system/health"),
  runs: () => request<RunView[]>("/api/v1/runs"),
  run: (runId: string) => request<RunView>(`/api/v1/runs/${runId}`),
  createRun: (recipeId: string) =>
    request<RunView>("/api/v1/runs", {
      method: "POST",
      body: JSON.stringify({ recipe_id: recipeId }),
    }),
  cancelRun: (runId: string) =>
    request<RunView>(`/api/v1/runs/${runId}/cancel`, { method: "POST" }),
  artifacts: (runId: string) =>
    request<{ run_id: string; artifacts: Array<{ path: string; size_bytes: number }> }>(
      `/api/v1/runs/${runId}/artifacts`,
    ),
  taskFlow: (runId: string, taskId = "") => {
    const query = taskId ? `?task_id=${encodeURIComponent(taskId)}` : "";
    return request<TaskFlowIndex>(`/api/v1/runs/${runId}/task-flow${query}`);
  },
};
