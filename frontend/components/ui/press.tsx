"use client";

import * as React from "react";
import { Slot } from "@radix-ui/react-slot";

import { cn } from "@/lib/utils";

/*
  Press: a reusable tactile button wrapper.

  Behaves like a physical button. On pointer-down the element visibly moves
  DOWN and compresses (translate-y + scale + inset shadow). On release it
  springs back UP and overshoots slightly before settling.

  The spring is pure CSS: the transition uses an easeOutBack curve
  (cubic-bezier(0.34, 1.56, 0.64, 1)) so the transform overshoots its target
  on the way back to rest. The press-down uses a snappier, shorter duration
  so the compress feels immediate while the release feels bouncy. No JS
  timers and no extra dependencies.

  Use `asChild` to render the press behaviour onto an existing element such
  as a Next.js <Link>.
*/

const pressBase = cn(
  "will-change-transform",
  "transition-[transform,box-shadow,color,background-color] duration-150 ease-[cubic-bezier(0.34,1.56,0.64,1)]",
  // Compress on press: move down, shrink, and tuck in the shadow. The
  // shorter duration here makes the downstroke feel instant and snappy.
  "active:translate-y-[1.5px] active:scale-[0.97] active:duration-100 active:ease-[cubic-bezier(0.4,0,1,1)]",
  "active:shadow-[inset_0_1px_2px_rgba(28,25,23,0.16)]",
  // Keyboard focus ring in the Claude accent.
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--sb-accent,#D97757)] focus-visible:ring-offset-2 focus-visible:ring-offset-[hsl(var(--sidebar))]",
);

export interface PressProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** Render the press behaviour onto the single child element instead. */
  asChild?: boolean;
}

const Press = React.forwardRef<HTMLButtonElement, PressProps>(
  ({ asChild = false, className, type, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        ref={ref as React.Ref<HTMLButtonElement>}
        // Only set a default type when we actually render a <button>.
        {...(asChild ? {} : { type: type ?? "button" })}
        className={cn(pressBase, className)}
        {...props}
      />
    );
  },
);
Press.displayName = "Press";

export { Press };
export default Press;
