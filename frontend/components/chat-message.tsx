"use client";

import { Check, Loader2, Sparkles, User, Wrench } from "lucide-react";

import { cn } from "@/lib/utils";
import { Markdown } from "@/components/markdown";
import type { ChatRole, ChatToolCall } from "@/lib/types";

// A compact one-line summary for a tool call. Falls back to a stringified
// preview of the arguments when the backend has not (yet) returned a summary.
function toolSummaryText(call: ChatToolCall): string {
  if (call.summary && call.summary.trim().length > 0) return call.summary;
  if (call.args && Object.keys(call.args).length > 0) {
    const preview = Object.entries(call.args)
      .slice(0, 3)
      .map(([k, v]) => `${k}: ${formatArgValue(v)}`)
      .join(", ");
    return preview;
  }
  return "Running...";
}

function formatArgValue(v: unknown): string {
  if (typeof v === "string") return v.length > 40 ? `${v.slice(0, 40)}...` : v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return Array.isArray(v) ? `[${v.length}]` : "...";
}

// One tool call rendered as a restrained chip: an accent marker, the tool name
// in Geist Mono, and a one-line result summary.
function ToolChip({ call, pending }: { call: ChatToolCall; pending: boolean }) {
  return (
    <div
      className={cn(
        "flex items-center gap-2.5 rounded-lg border bg-card/70 px-2.5 py-2 transition-colors",
        pending ? "border-primary/40" : "border-border",
      )}
    >
      {/* Tool icon in an accent-tinted tile */}
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
        <Wrench className="h-3.5 w-3.5" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="truncate font-mono text-[12px] font-semibold text-foreground">
            {call.tool}
          </span>
          <span className="rounded bg-secondary px-1 py-px text-[9px] font-medium uppercase tracking-wide text-muted-foreground">
            tool
          </span>
        </div>
        <p className="mt-0.5 truncate text-[12px] leading-snug text-muted-foreground">
          {toolSummaryText(call)}
        </p>
      </div>
      {/* Status: spinner while in flight, accent check when settled */}
      <span className="shrink-0">
        {pending ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" aria-hidden />
        ) : (
          <Check className="h-3.5 w-3.5 text-primary" aria-hidden />
        )}
      </span>
    </div>
  );
}

export interface ChatMessageProps {
  role: ChatRole;
  content: string;
  toolCalls?: ChatToolCall[];
  // True while the assistant turn is still streaming, so we can show a caret
  // and mark the latest tool call as in-flight.
  streaming?: boolean;
}

export function ChatMessage({
  role,
  content,
  toolCalls,
  streaming = false,
}: ChatMessageProps) {
  const isUser = role === "user";
  const calls = toolCalls ?? [];
  const showCaret = streaming && content.length === 0 && calls.length === 0;

  if (isUser) {
    return (
      <div className="flex animate-rise justify-end">
        <div className="flex max-w-[85%] items-start gap-3">
          <div className="rounded-2xl rounded-tr-sm bg-secondary px-4 py-2.5 text-sm leading-relaxed text-secondary-foreground">
            <p className="whitespace-pre-wrap break-words">{content}</p>
          </div>
          <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-border bg-card text-muted-foreground">
            <User className="h-3.5 w-3.5" aria-hidden />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex animate-rise justify-start">
      <div className="flex max-w-[85%] items-start gap-3">
        <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-white shadow-sm">
          <Sparkles className="h-3.5 w-3.5" aria-hidden />
        </div>
        <div className="min-w-0 flex-1 space-y-2">
          {calls.length > 0 && (
            <div className="space-y-1.5">
              {calls.map((call, i) => (
                <ToolChip
                  key={`${call.tool}-${i}`}
                  call={call}
                  pending={streaming && i === calls.length - 1 && !call.summary}
                />
              ))}
            </div>
          )}
          {(content.length > 0 || showCaret) && (
            <div className="rounded-2xl rounded-tl-sm border border-border bg-card px-4 py-2.5 text-sm leading-relaxed text-card-foreground">
              {content.length > 0 && <Markdown content={content} />}
              <p className="whitespace-pre-wrap break-words">
                {streaming && content.length > 0 && (
                  <span className="ml-0.5 inline-block h-4 w-[2px] -translate-y-px animate-pulse bg-primary align-middle" />
                )}
                {showCaret && (
                  <span className="inline-flex items-center gap-1 text-muted-foreground">
                    <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
                    <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary [animation-delay:150ms]" />
                    <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary [animation-delay:300ms]" />
                  </span>
                )}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default ChatMessage;
