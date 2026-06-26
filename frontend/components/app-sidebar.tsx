"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Aperture,
  LayoutDashboard,
  Inbox,
  Play,
  Building2,
  GraduationCap,
  FlaskConical,
  Boxes,
  Moon,
  Sun,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";

const THEME_KEY = "aperture-theme";

function ThemeToggle() {
  const [theme, setTheme] = useState<"light" | "dark">("dark");
  const [mounted, setMounted] = useState(false);

  // Read the theme the no-flash script already applied to <html>.
  useEffect(() => {
    setMounted(true);
    setTheme(
      document.documentElement.classList.contains("dark") ? "dark" : "light",
    );
  }, []);

  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    const classes = document.documentElement.classList;
    if (next === "dark") classes.add("dark");
    else classes.remove("dark");
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch {
      /* storage may be unavailable; toggle still applies for the session */
    }
  };

  const isDark = theme === "dark";

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      title={isDark ? "Switch to light theme" : "Switch to dark theme"}
      className="flex w-full items-center justify-between rounded-lg border border-border bg-card px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
    >
      <span className="flex items-center gap-2.5">
        {/* Avoid an icon flip before hydration knows the real theme. */}
        {mounted && !isDark ? (
          <Sun className="h-4 w-4" aria-hidden />
        ) : (
          <Moon className="h-4 w-4" aria-hidden />
        )}
        {mounted ? (isDark ? "Dark" : "Light") : "Theme"}
      </span>
      <span className="text-[10px] uppercase tracking-[0.12em] opacity-70">
        Theme
      </span>
    </button>
  );
}

interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
  match?: (path: string) => boolean;
}

const PRIMARY: NavItem[] = [
  {
    label: "Overview",
    href: "/",
    icon: LayoutDashboard,
    match: (p) => p === "/",
  },
  {
    label: "Inbox",
    href: "/inbox",
    icon: Inbox,
    match: (p) => p.startsWith("/inbox"),
  },
  {
    label: "Run",
    href: "/run",
    icon: Play,
    match: (p) => p.startsWith("/run"),
  },
  {
    label: "Accounts",
    href: "/accounts",
    icon: Building2,
    match: (p) => p.startsWith("/accounts"),
  },
];

const INTELLIGENCE: NavItem[] = [
  {
    label: "Learning",
    href: "/learning",
    icon: GraduationCap,
    match: (p) => p.startsWith("/learning"),
  },
  {
    label: "Eval",
    href: "/eval",
    icon: FlaskConical,
    match: (p) => p.startsWith("/eval"),
  },
  {
    label: "Domains",
    href: "/domains",
    icon: Boxes,
    match: (p) => p.startsWith("/domains"),
  },
];

function NavLink({ item, active }: { item: NavItem; active: boolean }) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
        active
          ? "bg-accent text-accent-foreground"
          : "text-muted-foreground hover:bg-secondary hover:text-foreground",
      )}
    >
      <span
        className={cn(
          "absolute left-0 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r-full bg-primary transition-opacity",
          active ? "opacity-100" : "opacity-0",
        )}
        aria-hidden
      />
      <Icon
        className={cn(
          "h-4 w-4 shrink-0 transition-colors",
          active
            ? "text-primary"
            : "text-muted-foreground group-hover:text-foreground",
        )}
      />
      {item.label}
    </Link>
  );
}

export function AppSidebar() {
  const pathname = usePathname() || "/";

  const renderSection = (items: NavItem[]) =>
    items.map((item) => {
      const active = item.match
        ? item.match(pathname)
        : pathname.startsWith(item.href);
      return <NavLink key={item.href} item={item} active={active} />;
    });

  return (
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r border-border bg-[hsl(var(--sidebar))] md:flex">
      <div className="flex h-16 items-center gap-2.5 border-b border-border px-5">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
          <Aperture className="h-[18px] w-[18px]" />
        </div>
        <div className="leading-tight">
          <div className="text-sm font-semibold tracking-tight">Aperture</div>
          <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
            Decision Engine
          </div>
        </div>
      </div>

      <nav className="flex flex-1 flex-col gap-6 overflow-y-auto px-3 py-5 scroll-thin">
        <div className="flex flex-col gap-1">
          <div className="px-3 pb-1 text-eyebrow">Workspace</div>
          {renderSection(PRIMARY)}
        </div>
        <div className="flex flex-col gap-1">
          <div className="px-3 pb-1 text-eyebrow">Intelligence</div>
          {renderSection(INTELLIGENCE)}
        </div>
      </nav>

      <div className="space-y-3 border-t border-border p-3">
        <ThemeToggle />
        <div className="rounded-lg border border-border bg-card px-3 py-2.5">
          <div className="flex items-center gap-2">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
            </span>
            <span className="text-xs font-medium">Agent runtime online</span>
          </div>
          <p className="mt-1 text-[11px] leading-snug text-muted-foreground">
            Hybrid retrieval, memory, and human-gated approval are active.
          </p>
        </div>
      </div>
    </aside>
  );
}

export default AppSidebar;
