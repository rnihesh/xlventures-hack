"use client";

// Shared visual frame for the auth screens: a brand panel on the left (hidden
// on small viewports) and a centered card on the right. Grayscale surfaces with
// a single Claude-orange accent, matching the app shell.

import Link from "next/link";
import { Aperture } from "lucide-react";
import type { ReactNode } from "react";

const HIGHLIGHTS = [
  "Evidence-backed next best actions",
  "Confidence scored and human gated",
  "Improves with every approval",
];

export function AuthScreen({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="grid min-h-screen bg-background lg:grid-cols-2">
      {/* Brand / value panel */}
      <div className="relative hidden flex-col justify-between overflow-hidden border-r border-border bg-[hsl(var(--sidebar))] p-12 lg:flex">
        <div
          aria-hidden
          className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-primary/10 blur-3xl"
        />
        <Link href="/" className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
            <Aperture className="h-5 w-5" />
          </div>
          <div className="leading-tight">
            <div className="text-sm font-semibold tracking-tight">Aperture</div>
            <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
              Decision Engine
            </div>
          </div>
        </Link>

        <div className="relative max-w-sm space-y-6">
          <h2 className="text-2xl font-semibold leading-snug tracking-tight">
            Turn signals into explainable next best actions.
          </h2>
          <ul className="space-y-3">
            {HIGHLIGHTS.map((line) => (
              <li
                key={line}
                className="flex items-center gap-3 text-sm text-muted-foreground"
              >
                <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                {line}
              </li>
            ))}
          </ul>
        </div>

        <p className="relative text-xs text-muted-foreground">
          Agentic decision intelligence, gated by human approval.
        </p>
      </div>

      {/* Form panel */}
      <div className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden">
            <div className="flex items-center gap-2.5">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                <Aperture className="h-[18px] w-[18px]" />
              </div>
              <span className="text-sm font-semibold tracking-tight">
                Aperture
              </span>
            </div>
          </div>

          <div className="mb-7 space-y-1.5">
            <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
            {subtitle ? (
              <p className="text-sm text-muted-foreground">{subtitle}</p>
            ) : null}
          </div>

          {children}

          {footer ? (
            <div className="mt-8 text-center text-sm text-muted-foreground">
              {footer}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export default AuthScreen;
