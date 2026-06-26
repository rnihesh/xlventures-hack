import Link from "next/link";
import {
  Inbox,
  Play,
  GraduationCap,
  FlaskConical,
  Boxes,
  ArrowRight,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

const navItems = [
  { label: "Inbox", href: "/", icon: Inbox, active: true },
  { label: "Runs", href: "/run", icon: Play, active: false },
  { label: "Learning", href: "/", icon: GraduationCap, active: false },
  { label: "Eval", href: "/", icon: FlaskConical, active: false },
  { label: "Domains", href: "/", icon: Boxes, active: false },
];

const features = [
  {
    title: "Evidence-backed",
    description:
      "Every recommendation cites sources with snippets and character spans you can verify.",
  },
  {
    title: "Confidence scored",
    description:
      "Calibrated confidence with supporting and contradicting signals surfaced up front.",
  },
  {
    title: "Human in the loop",
    description:
      "Approve, reject, or edit any proposed action before it ever leaves the platform.",
  },
];

export default function HomePage() {
  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-64 shrink-0 flex-col border-r border-border bg-card/40 px-4 py-6 md:flex">
        <div className="mb-8 flex items-center gap-2 px-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <Sparkles className="h-5 w-5" />
          </div>
          <span className="text-lg font-semibold tracking-tight">Aperture</span>
        </div>
        <nav className="flex flex-col gap-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <Link
                key={item.label}
                href={item.href}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  item.active
                    ? "bg-secondary text-secondary-foreground"
                    : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground"
                )}
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="mt-auto rounded-lg border border-border bg-background/60 p-3 text-xs text-muted-foreground">
          Connected to the agent runtime. Start a run to generate your next best action.
        </div>
      </aside>

      <main className="flex flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-border px-6 py-4">
          <div>
            <h1 className="text-sm font-medium text-muted-foreground">Inbox</h1>
            <p className="text-lg font-semibold tracking-tight">
              Next Best Action
            </p>
          </div>
          <Button asChild>
            <Link href="/run">
              New run
              <ArrowRight className="ml-2 h-4 w-4" />
            </Link>
          </Button>
        </header>

        <div className="flex flex-1 flex-col items-center justify-center gap-10 px-6 py-16">
          <div className="max-w-2xl text-center">
            <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-border bg-secondary/50 px-3 py-1 text-xs font-medium text-muted-foreground">
              <Sparkles className="h-3.5 w-3.5" />
              Explainable agentic recommendations
            </div>
            <h2 className="text-balance text-4xl font-semibold tracking-tight sm:text-5xl">
              Aperture
            </h2>
            <p className="mt-4 text-balance text-lg text-muted-foreground">
              Turn raw account signals into evidence-backed next best actions, with
              full reasoning, citations, and a human approval step.
            </p>
            <div className="mt-8 flex items-center justify-center gap-3">
              <Button asChild size="lg">
                <Link href="/run">
                  Start a run
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Link>
              </Button>
              <Button asChild size="lg" variant="outline">
                <Link href="/run">View live trace</Link>
              </Button>
            </div>
          </div>

          <div className="grid w-full max-w-4xl gap-4 sm:grid-cols-3">
            {features.map((feature) => (
              <Card key={feature.title}>
                <CardHeader>
                  <CardTitle className="text-base">{feature.title}</CardTitle>
                  <CardDescription>{feature.description}</CardDescription>
                </CardHeader>
                <CardContent className="pt-0" />
              </Card>
            ))}
          </div>
        </div>
      </main>
    </div>
  );
}
