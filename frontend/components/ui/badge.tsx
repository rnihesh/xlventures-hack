import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors focus:outline-none",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        outline: "border-border text-foreground",
        muted: "border-transparent bg-muted text-muted-foreground",
        success:
          "border-transparent bg-emerald-500/12 text-emerald-600 ring-1 ring-inset ring-emerald-500/20 dark:text-emerald-400",
        warning:
          "border-transparent bg-amber-500/12 text-amber-600 ring-1 ring-inset ring-amber-500/20 dark:text-amber-400",
        danger:
          "border-transparent bg-rose-500/12 text-rose-600 ring-1 ring-inset ring-rose-500/20 dark:text-rose-400",
        info:
          "border-transparent bg-sky-500/12 text-sky-600 ring-1 ring-inset ring-sky-500/20 dark:text-sky-400",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
