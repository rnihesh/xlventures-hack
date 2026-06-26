"use client";

// Public product hero / landing page. No auth wall: anyone can read the pitch
// and sign in or sign up. Signed-in users get an "Open app" shortcut.

import Link from "next/link";
import {
  Aperture,
  ArrowRight,
  BrainCircuit,
  FileSearch,
  GitBranch,
  ShieldCheck,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth-context";

const FEATURES: { icon: LucideIcon; title: string; desc: string }[] = [
  {
    icon: BrainCircuit,
    title: "Planner + specialist agents",
    desc: "A LangGraph planner routes specialists to score risk, retrieve evidence, and rank the next best action.",
  },
  {
    icon: FileSearch,
    title: "Explainable, cited",
    desc: "Every recommendation ships with a confidence score and span-level citations you can audit.",
  },
  {
    icon: ShieldCheck,
    title: "Policy + human approval",
    desc: "Guardrails gate risky plays; nothing executes until a human approves it.",
  },
  {
    icon: GitBranch,
    title: "Learns from outcomes",
    desc: "Approvals, edits, and results distill into memory that sharpens future calls.",
  },
];

export default function LandingPage() {
  const { user, loading } = useAuth();

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Nav */}
      <header className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-5">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <Aperture className="h-5 w-5" />
          </span>
          <div className="leading-tight">
            <div className="text-sm font-semibold tracking-tight">Aperture</div>
            <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
              Decision engine
            </div>
          </div>
        </div>
        <nav className="flex items-center gap-2">
          {!loading && user ? (
            <Button asChild>
              <Link href="/dashboard">
                Open app
                <ArrowRight className="ml-1 h-4 w-4" />
              </Link>
            </Button>
          ) : (
            <>
              <Button asChild variant="ghost">
                <Link href="/login">Sign in</Link>
              </Button>
              <Button asChild>
                <Link href="/signup">Get started</Link>
              </Button>
            </>
          )}
        </nav>
      </header>

      {/* Hero */}
      <section className="mx-auto w-full max-w-4xl px-6 pb-16 pt-16 text-center sm:pt-24">
        <div className="mx-auto mb-5 inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-muted-foreground">
          <Sparkles className="h-3.5 w-3.5 text-primary" />
          Agentic decision intelligence
        </div>
        <h1 className="text-balance text-4xl font-semibold tracking-tight sm:text-6xl">
          Turn raw signals into{" "}
          <span className="text-primary">explainable next best actions</span>.
        </h1>
        <p className="mx-auto mt-5 max-w-2xl text-pretty text-base text-muted-foreground sm:text-lg">
          Aperture reasons over your accounts with a team of agents, grounds
          every call in cited evidence, scores its confidence, and gates it
          behind your approval. The flagship is Customer Success, the engine is
          any B2B domain.
        </p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          {!loading && user ? (
            <Button asChild size="lg">
              <Link href="/dashboard">
                Open the app
                <ArrowRight className="ml-1 h-4 w-4" />
              </Link>
            </Button>
          ) : (
            <>
              <Button asChild size="lg">
                <Link href="/signup">
                  Start free
                  <ArrowRight className="ml-1 h-4 w-4" />
                </Link>
              </Button>
              <Button asChild size="lg" variant="outline">
                <Link href="/login">Sign in</Link>
              </Button>
            </>
          )}
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          Try the demo workspace: demo@niheshr.com / demo1234
        </p>
      </section>

      {/* Features */}
      <section className="mx-auto w-full max-w-5xl px-6 pb-24">
        <div className="grid gap-4 sm:grid-cols-2">
          {FEATURES.map((f) => {
            const Icon = f.icon;
            return (
              <div
                key={f.title}
                className="rounded-2xl border border-border bg-card p-6"
              >
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
                  <Icon className="h-5 w-5" />
                </span>
                <h3 className="mt-4 text-base font-semibold tracking-tight">
                  {f.title}
                </h3>
                <p className="mt-1.5 text-sm text-muted-foreground">{f.desc}</p>
              </div>
            );
          })}
        </div>
      </section>

      <footer className="border-t border-border">
        <div className="mx-auto w-full max-w-6xl px-6 py-6 text-xs text-muted-foreground">
          Aperture: Intelligent Next Best Action platform.
        </div>
      </footer>
    </div>
  );
}
