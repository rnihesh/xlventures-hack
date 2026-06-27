// Typed client for the run history list (GET /runs). Runs are org-scoped and
// stored server-side; this powers the "Recent runs" panel so a user can see and
// reopen what they have run.

import { API_BASE } from "@/lib/api";
import { authHeaders } from "@/lib/auth";

export interface RunSummary {
  run_id: string;
  account_id: string | null;
  account_name: string | null;
  domain: string | null;
  status: string | null;
  created_at: string | null;
  signal_summary: string | null;
  action_title: string | null;
  confidence: number | null;
  has_recommendation: boolean;
}

export async function getRuns(signal?: AbortSignal): Promise<RunSummary[]> {
  try {
    const res = await fetch(`${API_BASE}/runs`, {
      headers: authHeaders(),
      credentials: "include",
      signal,
    });
    if (!res.ok) return [];
    const data = (await res.json()) as { runs?: RunSummary[] };
    return data.runs ?? [];
  } catch {
    return [];
  }
}
