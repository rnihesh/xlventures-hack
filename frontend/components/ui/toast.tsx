"use client";

// Lightweight, dependency-free toast system.
//
// A module-level pub/sub store backs a single <Toaster /> mounted in the root
// layout. Anywhere in the app can call `toast("Saved", { variant: "success" })`
// to surface inline, auto-dismissing feedback without prop drilling or a
// provider. Accessible: the region is aria-live="polite" and each toast can be
// dismissed by keyboard.

import * as React from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Info,
  X,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";

export type ToastVariant = "success" | "error" | "info";

export interface ToastItem {
  id: number;
  title: string;
  description?: string;
  variant: ToastVariant;
  duration: number;
}

export interface ToastOptions {
  description?: string;
  variant?: ToastVariant;
  duration?: number;
}

type Listener = (toasts: ToastItem[]) => void;

let store: ToastItem[] = [];
const listeners = new Set<Listener>();
let counter = 0;

function emit() {
  const snapshot = [...store];
  for (const listener of listeners) listener(snapshot);
}

function dismiss(id: number) {
  store = store.filter((t) => t.id !== id);
  emit();
}

/** Queue a toast. Returns its id so callers can dismiss it early if needed. */
export function toast(title: string, opts: ToastOptions = {}): number {
  const id = ++counter;
  const item: ToastItem = {
    id,
    title,
    description: opts.description,
    variant: opts.variant ?? "info",
    duration: opts.duration ?? 3500,
  };
  // Cap the stack so a burst of actions never floods the screen.
  store = [...store, item].slice(-4);
  emit();
  return id;
}

const VARIANTS: Record<
  ToastVariant,
  { icon: LucideIcon; accent: string; iconClass: string }
> = {
  success: {
    icon: CheckCircle2,
    accent: "border-l-primary",
    iconClass: "text-primary",
  },
  error: {
    icon: AlertTriangle,
    accent: "border-l-destructive",
    iconClass: "text-destructive",
  },
  info: {
    icon: Info,
    accent: "border-l-muted-foreground",
    iconClass: "text-muted-foreground",
  },
};

function ToastCard({ item }: { item: ToastItem }) {
  const { icon: Icon, accent, iconClass } = VARIANTS[item.variant];

  React.useEffect(() => {
    if (item.duration <= 0) return;
    const timer = window.setTimeout(() => dismiss(item.id), item.duration);
    return () => window.clearTimeout(timer);
  }, [item.id, item.duration]);

  return (
    <div
      role="status"
      className={cn(
        "pointer-events-auto flex animate-rise items-start gap-3 rounded-lg border border-l-2 border-border bg-card px-4 py-3 shadow-lg",
        accent,
      )}
    >
      <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", iconClass)} aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-foreground">{item.title}</p>
        {item.description ? (
          <p className="mt-0.5 text-xs text-muted-foreground">
            {item.description}
          </p>
        ) : null}
      </div>
      <button
        type="button"
        onClick={() => dismiss(item.id)}
        aria-label="Dismiss notification"
        className="-mr-1 -mt-0.5 rounded-md p-0.5 text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

/** Mount once near the root. Renders the live toast stack. */
export function Toaster() {
  const [items, setItems] = React.useState<ToastItem[]>([]);

  React.useEffect(() => {
    const listener: Listener = (next) => setItems(next);
    listeners.add(listener);
    setItems([...store]);
    return () => {
      listeners.delete(listener);
    };
  }, []);

  return (
    <div
      aria-live="polite"
      aria-atomic="false"
      className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-[calc(100%-2rem)] max-w-sm flex-col gap-2"
    >
      {items.map((item) => (
        <ToastCard key={item.id} item={item} />
      ))}
    </div>
  );
}

export default Toaster;
