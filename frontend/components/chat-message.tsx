"use client";

import { useState } from "react";
import { Aperture, ChevronRight, Sparkles, User } from "lucide-react";

import { cn } from "@/lib/utils";
import { Markdown } from "@/components/markdown";
import { ChatToolTimeline } from "@/components/tool-call-panel";
import type { ChatRole, ChatToolCall } from "@/lib/types";

// The on-brand assistant mark: an aperture glyph on a Claude-orange tile. Used
// for every assistant turn so the agent reads as a first-class platform actor.
export function AssistantAvatar({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-white shadow-sm ring-1 ring-primary/30",
        className,
      )}
    >
      <Aperture className="h-4 w-4" aria-hidden />
    </div>
  );
}

// Animated "Thinking..." cue shown while the assistant is reasoning before or
// between tool calls (no tokens and no tool actively running yet).
function ThinkingIndicator() {
  return (
    <div className="inline-flex items-center gap-2 rounded-full border border-border bg-card/70 px-2.5 py-1 text-[12px] text-muted-foreground">
      <span className="inline-flex items-center gap-1">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary [animation-delay:150ms]" />
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary [animation-delay:300ms]" />
      </span>
      Thinking...
    </div>
  );
}

// Optional reasoning text the stream may surface, rendered as a subtle,
// collapsible "Thoughts" block. Degrades to nothing when no text is present.
function ThoughtsBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-dashed border-border bg-muted/30">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1.5 px-2.5 py-1.5 text-left text-[11px] font-medium text-muted-foreground transition-colors hover:text-foreground"
      >
        <Sparkles className="h-3 w-3 text-primary/70" aria-hidden />
        Thoughts
        <ChevronRight
          className={cn(
            "ml-auto h-3.5 w-3.5 transition-transform",
            open && "rotate-90",
          )}
          aria-hidden
        />
      </button>
      {open && (
        <p className="whitespace-pre-wrap break-words px-2.5 pb-2 text-[11px] leading-relaxed text-muted-foreground">
          {text}
        </p>
      )}
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
  // Optional reasoning text the stream may surface. Absent today; read so the
  // UI lights up automatically if a future slice streams it.
  thoughts?: string;
}

export function ChatMessage({
  role,
  content,
  toolCalls,
  streaming = false,
  thoughts,
}: ChatMessageProps) {
  const isUser = role === "user";
  const calls = toolCalls ?? [];
  const lastCall = calls[calls.length - 1];
  const toolRunning =
    streaming && lastCall !== undefined && lastCall.summary === undefined;
  // Reasoning beat: streaming, nothing rendered yet, and no tool is mid-flight.
  const showThinking = streaming && content.length === 0 && !toolRunning;

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
        <AssistantAvatar className="mt-0.5" />
        <div className="min-w-0 flex-1 space-y-2">
          {thoughts && thoughts.trim().length > 0 && (
            <ThoughtsBlock text={thoughts} />
          )}
          {calls.length > 0 && (
            <ChatToolTimeline calls={calls} streaming={streaming} />
          )}
          {showThinking && <ThinkingIndicator />}
          {content.length > 0 && (
            <div className="rounded-2xl rounded-tl-sm border border-border bg-card px-4 py-2.5 text-sm leading-relaxed text-card-foreground">
              <Markdown content={content} />
              {streaming && (
                <span className="ml-0.5 inline-block h-4 w-[2px] -translate-y-px animate-pulse bg-primary align-middle" />
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default ChatMessage;
