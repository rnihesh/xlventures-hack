// Shared page header.
//
// One header style across every screen: an uppercase eyebrow, the display
// title, a one-line subtitle, and an optional cluster of actions on the right.
// Matches the established dashboard / inbox / accounts pages so the platform
// reads as one product.

import { cn } from "@/lib/utils";

export interface PageHeaderProps {
  eyebrow: string;
  title: string;
  description?: string;
  // Right-aligned actions (search, primary button, selectors, badges).
  actions?: React.ReactNode;
  className?: string;
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  className,
}: PageHeaderProps) {
  return (
    <header
      className={cn(
        "mb-6 flex flex-wrap items-end justify-between gap-4",
        className,
      )}
    >
      <div className="min-w-0">
        <div className="text-eyebrow">{eyebrow}</div>
        <h1 className="mt-1 text-display">{title}</h1>
        {description ? (
          <p className="mt-1.5 max-w-xl text-sm text-muted-foreground">
            {description}
          </p>
        ) : null}
      </div>
      {actions ? (
        <div className="flex items-center gap-2">{actions}</div>
      ) : null}
    </header>
  );
}

export default PageHeader;
