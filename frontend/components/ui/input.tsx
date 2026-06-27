import * as React from "react";

import { cn } from "@/lib/utils";

export type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  (
    {
      className,
      type,
      id,
      placeholder,
      "aria-label": ariaLabel,
      "aria-labelledby": ariaLabelledby,
      ...props
    },
    ref,
  ) => {
    // Always give the control a stable id so it satisfies the "form field
    // should have an id or name" check even when a caller omits one.
    const autoId = React.useId();
    const fieldId = id ?? autoId;
    // A placeholder-only field (no caller id, so no <label htmlFor> can target
    // it, and no explicit aria-label) still needs an accessible name. Fall back
    // to the placeholder text. Properly labeled fields always pass an explicit
    // id, so this never overrides a real, visible label.
    const fallbackLabel =
      !ariaLabel && !ariaLabelledby && id == null && placeholder
        ? placeholder
        : undefined;
    return (
      <input
        type={type}
        ref={ref}
        id={fieldId}
        placeholder={placeholder}
        aria-label={ariaLabel ?? fallbackLabel}
        aria-labelledby={ariaLabelledby}
        className={cn(
          "flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50",
          className,
        )}
        {...props}
      />
    );
  },
);
Input.displayName = "Input";

export { Input };
