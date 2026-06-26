"use client";

// A dependency-free hint tooltip (no Radix). A small help icon reveals a short
// plain-language explanation on hover, focus, or tap. Built for accessibility:
// it is a real button, toggles on keyboard focus, and the bubble is a
// role="tooltip" wired up via aria-describedby.

import { useId, useState, type ReactNode } from "react";
import { HelpCircle } from "lucide-react";

import { cn } from "@/lib/utils";

export interface InfoHintProps {
  // The explanation to show. Plain text or rich nodes both work.
  text: ReactNode;
  // Accessible label for the trigger button.
  label?: string;
  // Where the bubble sits relative to the trigger.
  side?: "top" | "bottom";
  // Horizontal anchoring, to avoid clipping near a container edge.
  align?: "center" | "start" | "end";
  className?: string;
  // Optional override for the trigger icon size.
  iconClassName?: string;
}

export function InfoHint({
  text,
  label = "What this means",
  side = "top",
  align = "center",
  className,
  iconClassName,
}: InfoHintProps) {
  const [open, setOpen] = useState(false);
  const id = useId();

  const sideClasses =
    side === "top"
      ? "bottom-full mb-1.5"
      : "top-full mt-1.5";
  const alignClasses =
    align === "center"
      ? "left-1/2 -translate-x-1/2"
      : align === "start"
        ? "left-0"
        : "right-0";

  return (
    <span className={cn("relative inline-flex align-middle", className)}>
      <button
        type="button"
        aria-label={label}
        aria-describedby={open ? id : undefined}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className="inline-flex items-center justify-center rounded-full text-muted-foreground/70 transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background"
      >
        <HelpCircle className={cn("h-3.5 w-3.5", iconClassName)} aria-hidden />
      </button>
      {open && (
        <span
          role="tooltip"
          id={id}
          className={cn(
            "absolute z-50 w-60 max-w-[16rem] rounded-lg border border-border bg-card px-3 py-2 text-left text-xs font-normal normal-case leading-relaxed tracking-normal text-foreground shadow-lg",
            sideClasses,
            alignClasses,
          )}
        >
          {text}
        </span>
      )}
    </span>
  );
}

export default InfoHint;
