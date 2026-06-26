"use client";

import { useCallback, useEffect, useRef, useState } from "react";

// ---------------------------------------------------------------------------
// Shared contract types (frozen). Defined here and re-exported so this slice
// is self contained; components in this slice import them from this module.
// ---------------------------------------------------------------------------

export type AgentEventType =
  | "run.started"
  | "node.started"
  | "node.finished"
  | "token"
  | "recommendation"
  | "hitl.required"
  | "run.finished"
  | "error";

export interface AgentEvent {
  id: string;
  run_id: string;
  seq: number;
  type: AgentEventType;
  ts: string;
  data: Record<string, unknown>;
}

export interface Evidence {
  claim: string;
  source_id: string;
  source_type: string;
  snippet: string;
  span: { start: number; end: number };
}

export interface RecommendationAction {
  key: string;
  title: string;
  description: string;
}

export interface Confidence {
  score: number;
  method: string;
  label: string;
}

export interface RiskOpportunity {
  type: "risk" | "opportunity";
  summary: string;
}

export interface ExpectedImpact {
  kpi: string;
  direction: "up" | "down";
  estimate: string;
}

export type RecommendationStatus = "proposed" | "approved" | "rejected" | "edited";

export interface Recommendation {
  id: string;
  run_id: string;
  account_id: string;
  domain: string;
  action: RecommendationAction;
  rationale: string;
  evidence: Evidence[];
  signals: { supporting: string[]; contradicting: string[] };
  confidence: Confidence;
  risk_opportunity: RiskOpportunity;
  counterfactual: string;
  expected_impact: ExpectedImpact;
  status: RecommendationStatus;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Hook surface
// ---------------------------------------------------------------------------

export type RunStatus =
  | "idle"
  | "starting"
  | "streaming"
  | "hitl"
  | "finished"
  | "error";

export interface StartInput {
  domain: string;
  account_id: string;
  signal: { type: string; content: string };
}

export type HitlDecision = "approve" | "reject" | "edit";

export interface UseAgentStream {
  runId: string | null;
  status: RunStatus;
  events: AgentEvent[];
  recommendation: Recommendation | null;
  hitlRequired: boolean;
  error: string | null;
  start: (input: StartInput) => Promise<void>;
  submitHitl: (
    decision: HitlDecision,
    editedAction: RecommendationAction | null,
    reason: string | null,
  ) => Promise<void>;
  reset: () => void;
}

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://localhost:8000";

// Parse a raw SSE chunk buffer into complete "data: ...\n\n" frames. Returns the
// decoded JSON payloads found and the leftover (incomplete) buffer tail.
function drainFrames(buffer: string): { events: unknown[]; rest: string } {
  const events: unknown[] = [];
  let rest = buffer;
  let sep = rest.indexOf("\n\n");
  while (sep !== -1) {
    const rawFrame = rest.slice(0, sep);
    rest = rest.slice(sep + 2);
    // A frame can carry multiple "data:" lines per the SSE spec; join them.
    const dataLines = rawFrame
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).replace(/^ /, ""));
    if (dataLines.length > 0) {
      const payload = dataLines.join("\n").trim();
      if (payload.length > 0) {
        try {
          events.push(JSON.parse(payload));
        } catch {
          // Ignore malformed frame, keep streaming.
        }
      }
    }
    sep = rest.indexOf("\n\n");
  }
  return { events, rest };
}

export function useAgentStream(): UseAgentStream {
  const [runId, setRunId] = useState<string | null>(null);
  const [status, setStatus] = useState<RunStatus>("idle");
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  const [hitlRequired, setHitlRequired] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);

  const cleanup = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  useEffect(() => cleanup, [cleanup]);

  const handleEvent = useCallback((evt: AgentEvent) => {
    setEvents((prev) => [...prev, evt]);
    switch (evt.type) {
      case "run.started":
        setStatus("streaming");
        break;
      case "recommendation": {
        const rec = (evt.data?.recommendation ?? evt.data) as Recommendation;
        if (rec && typeof rec === "object" && "action" in rec) {
          setRecommendation(rec);
        }
        break;
      }
      case "hitl.required":
        setHitlRequired(true);
        setStatus("hitl");
        break;
      case "run.finished":
        setStatus((s) => (s === "hitl" ? s : "finished"));
        break;
      case "error":
        setError(
          typeof evt.data?.message === "string"
            ? (evt.data.message as string)
            : "Run error",
        );
        setStatus("error");
        break;
      default:
        break;
    }
  }, []);

  const consumeStream = useCallback(
    async (id: string) => {
      const controller = new AbortController();
      abortRef.current = controller;
      const res = await fetch(`${API_BASE}/runs/${id}/stream`, {
        method: "GET",
        headers: { Accept: "text/event-stream" },
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        throw new Error(`Stream failed (${res.status})`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const { events: frames, rest } = drainFrames(buffer);
        buffer = rest;
        for (const frame of frames) {
          handleEvent(frame as AgentEvent);
        }
      }
      // Flush any trailing frame.
      buffer += decoder.decode();
      const { events: tail } = drainFrames(buffer + "\n\n");
      for (const frame of tail) {
        handleEvent(frame as AgentEvent);
      }
    },
    [handleEvent],
  );

  const reset = useCallback(() => {
    cleanup();
    setRunId(null);
    setStatus("idle");
    setEvents([]);
    setRecommendation(null);
    setHitlRequired(false);
    setError(null);
  }, [cleanup]);

  const start = useCallback(
    async (input: StartInput) => {
      reset();
      setStatus("starting");
      try {
        const res = await fetch(`${API_BASE}/runs`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(input),
        });
        if (!res.ok) {
          throw new Error(`Failed to start run (${res.status})`);
        }
        const body = (await res.json()) as { run_id: string };
        setRunId(body.run_id);
        await consumeStream(body.run_id);
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        setError((err as Error).message || "Unknown error");
        setStatus("error");
      }
    },
    [consumeStream, reset],
  );

  const submitHitl = useCallback(
    async (
      decision: HitlDecision,
      editedAction: RecommendationAction | null,
      reason: string | null,
    ) => {
      if (!runId) return;
      try {
        const res = await fetch(`${API_BASE}/runs/${runId}/hitl`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            decision,
            edited_action: editedAction,
            reason,
          }),
        });
        if (!res.ok) {
          throw new Error(`HITL submit failed (${res.status})`);
        }
        setHitlRequired(false);
        const nextStatus: RecommendationStatus =
          decision === "approve"
            ? "approved"
            : decision === "reject"
              ? "rejected"
              : "edited";
        setRecommendation((prev) =>
          prev
            ? {
                ...prev,
                status: nextStatus,
                action: editedAction ?? prev.action,
              }
            : prev,
        );
        setStatus("finished");
      } catch (err) {
        setError((err as Error).message || "HITL error");
      }
    },
    [runId],
  );

  return {
    runId,
    status,
    events,
    recommendation,
    hitlRequired,
    error,
    start,
    submitHitl,
    reset,
  };
}
