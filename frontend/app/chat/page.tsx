"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { MessageSquare, Plus, Trash2 } from "lucide-react";

import { ChatPanel, type ChatTurn } from "@/components/chat-panel";
import {
  deleteSession,
  genId,
  getSession,
  listSessions,
  titleFor,
  upsertSession,
  type ChatSessionSummary,
} from "@/lib/chat-store";
import { cn } from "@/lib/utils";

export default function ChatPage() {
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  // null while the active conversation's turns are still loading from the DB.
  const [activeTurns, setActiveTurns] = useState<ChatTurn[] | null>(null);
  // Tracks the turns we handed to the panel so the panel's initial echo does
  // not trigger a redundant save.
  const loadedRef = useRef<string>("[]");

  // Load the conversation list on mount; start a fresh chat if there are none.
  useEffect(() => {
    let alive = true;
    (async () => {
      const list = await listSessions();
      if (!alive) return;
      if (list.length > 0) {
        setSessions(list);
        setActiveId(list[0].id);
      } else {
        const id = genId();
        setSessions([
          { id, title: "New chat", updated_at: new Date().toISOString() },
        ]);
        setActiveId(id);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  // Load the active conversation's turns whenever the selection changes.
  useEffect(() => {
    if (!activeId) return;
    let alive = true;
    setActiveTurns(null);
    (async () => {
      const session = await getSession(activeId);
      if (!alive) return;
      const turns = session?.turns ?? [];
      loadedRef.current = JSON.stringify(turns);
      setActiveTurns(turns);
    })();
    return () => {
      alive = false;
    };
  }, [activeId]);

  // Persist the active conversation when its turns change (skip the initial
  // echo and empty conversations).
  const onTurnsChange = useCallback(
    (turns: ChatTurn[]) => {
      if (!activeId) return;
      const serialized = JSON.stringify(turns);
      if (serialized === loadedRef.current) return;
      loadedRef.current = serialized;
      if (turns.length === 0) return;
      const title = titleFor(turns);
      void upsertSession(activeId, title, turns);
      setSessions((prev) => {
        const now = new Date().toISOString();
        const without = prev.filter((s) => s.id !== activeId);
        return [{ id: activeId, title, updated_at: now }, ...without];
      });
    },
    [activeId],
  );

  const startNewChat = useCallback(() => {
    const empty = sessions.find((s) => s.title === "New chat");
    if (empty) {
      setActiveId(empty.id);
      return;
    }
    const id = genId();
    setSessions((prev) => [
      { id, title: "New chat", updated_at: new Date().toISOString() },
      ...prev,
    ]);
    setActiveId(id);
  }, [sessions]);

  const removeChat = useCallback(
    (id: string) => {
      void deleteSession(id);
      setSessions((prev) => {
        const next = prev.filter((s) => s.id !== id);
        if (next.length === 0) {
          const fresh = genId();
          setActiveId(fresh);
          return [
            { id: fresh, title: "New chat", updated_at: new Date().toISOString() },
          ];
        }
        if (activeId === id) setActiveId(next[0].id);
        return next;
      });
    },
    [activeId],
  );

  return (
    <div className="flex h-screen flex-1 flex-col">
      <header className="flex items-center justify-between border-b border-border px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-secondary text-secondary-foreground">
            <MessageSquare className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-sm font-medium text-muted-foreground">Chat</h1>
            <p className="text-lg font-semibold tracking-tight">
              Ask the platform anything
            </p>
          </div>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        {/* Conversation history rail (persisted in Postgres) */}
        <aside className="flex w-60 shrink-0 flex-col border-r border-border bg-card/40">
          <div className="p-3">
            <button
              onClick={startNewChat}
              className="flex w-full items-center justify-center gap-2 rounded-lg border border-border bg-background px-3 py-2 text-sm font-medium transition-colors hover:bg-secondary active:translate-y-px"
            >
              <Plus className="h-4 w-4" /> New chat
            </button>
          </div>
          <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-2 pb-3">
            <div className="px-1 pb-1 text-eyebrow">History</div>
            {sessions.length === 0 ? (
              <p className="px-2 py-2 text-xs text-muted-foreground">
                No conversations yet.
              </p>
            ) : (
              <ul className="space-y-0.5">
                {sessions.map((s) => (
                  <li key={s.id}>
                    <div
                      className={cn(
                        "group flex items-center gap-1 rounded-md px-2 py-2 text-sm transition-colors",
                        s.id === activeId
                          ? "bg-primary/10 text-foreground"
                          : "text-muted-foreground hover:bg-secondary hover:text-foreground",
                      )}
                    >
                      <button
                        onClick={() => setActiveId(s.id)}
                        className="min-w-0 flex-1 truncate text-left"
                        title={s.title}
                      >
                        {s.title || "New chat"}
                      </button>
                      <button
                        onClick={() => removeChat(s.id)}
                        aria-label="Delete conversation"
                        className="shrink-0 rounded p-1 text-muted-foreground opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>

        {/* Active conversation */}
        <div className="min-h-0 flex-1">
          {activeId && activeTurns !== null ? (
            <ChatPanel
              key={activeId}
              initialTurns={activeTurns}
              onTurnsChange={onTurnsChange}
            />
          ) : null}
        </div>
      </div>
    </div>
  );
}
