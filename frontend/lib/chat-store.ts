"use client";

// Multi-conversation chat history, persisted in Postgres via the backend API
// (falls back to the backend's in-memory store when no database is configured).
import { API_BASE } from "@/lib/api";
import { authHeaders } from "@/lib/auth";
import type { ChatTurn } from "@/components/chat-panel";

export interface ChatSessionSummary {
  id: string;
  title: string;
  updated_at: string;
}

export interface ChatSession {
  id: string;
  title: string;
  turns: ChatTurn[];
  updated_at?: string;
}

export function genId(): string {
  return Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
}

// Derive a short title from the first user message in the conversation.
export function titleFor(turns: ChatTurn[]): string {
  const firstUser = turns.find((t) => t.role === "user" && t.content.trim());
  if (!firstUser) return "New chat";
  const text = firstUser.content.trim().replace(/\s+/g, " ");
  return text.length > 48 ? `${text.slice(0, 48)}...` : text;
}

export async function listSessions(): Promise<ChatSessionSummary[]> {
  try {
    const res = await fetch(`${API_BASE}/chat/sessions`, {
      headers: authHeaders({ Accept: "application/json" }),
      credentials: "include",
      cache: "no-store",
    });
    if (!res.ok) return [];
    return (await res.json()) as ChatSessionSummary[];
  } catch {
    return [];
  }
}

export async function getSession(id: string): Promise<ChatSession | null> {
  try {
    const res = await fetch(`${API_BASE}/chat/sessions/${encodeURIComponent(id)}`, {
      headers: authHeaders({ Accept: "application/json" }),
      credentials: "include",
      cache: "no-store",
    });
    if (!res.ok) return null;
    return (await res.json()) as ChatSession;
  } catch {
    return null;
  }
}

export async function upsertSession(
  id: string,
  title: string,
  turns: ChatTurn[],
): Promise<void> {
  try {
    await fetch(`${API_BASE}/chat/sessions/${encodeURIComponent(id)}`, {
      method: "PUT",
      headers: authHeaders({ "Content-Type": "application/json" }),
      credentials: "include",
      body: JSON.stringify({ title, turns }),
      // Survive a navigate-away / tab close so a flush-on-unmount save lands.
      keepalive: true,
    });
  } catch {
    // best effort: a failed save should not break the chat UI
  }
}

export async function deleteSession(id: string): Promise<void> {
  try {
    await fetch(`${API_BASE}/chat/sessions/${encodeURIComponent(id)}`, {
      method: "DELETE",
      headers: authHeaders(),
      credentials: "include",
    });
  } catch {
    // ignore
  }
}
