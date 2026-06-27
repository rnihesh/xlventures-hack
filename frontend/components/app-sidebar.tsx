"use client";

import { useEffect, useState, type CSSProperties } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Aperture,
  LayoutDashboard,
  Inbox,
  Bot,
  Play,
  Building2,
  Contact2,
  Upload,
  GraduationCap,
  FlaskConical,
  Workflow,
  Network,
  Boxes,
  SlidersHorizontal,
  Settings,
  ShieldCheck,
  Moon,
  Sun,
  LogOut,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { Press } from "@/components/ui/press";
import { useAuth } from "@/lib/auth-context";

const THEME_KEY = "aperture-theme";
const COLLAPSE_KEY = "aperture-sidebar-collapsed";

// Pixel widths the <aside> and the page offset (app-shell) share via a CSS
// variable, so the main content slides in step with the sidebar width.
const WIDTH_EXPANDED = "16rem";
const WIDTH_COLLAPSED = "4.5rem";

/*
  Scoped Claude-orange accent for the sidebar. Exposed as CSS variables on the
  <aside> so the nav links, brand mark, focus rings, and status dot can all
  reference one source of truth without leaking new hues elsewhere.
*/
const ACCENT_VARS = {
  "--sb-accent": "#D97757",
  "--sb-accent-hover": "#C2613F",
  "--sb-accent-subtle": "rgba(217,119,87,0.12)",
} as CSSProperties;

function ThemeToggle({ collapsed }: { collapsed: boolean }) {
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
  const label = isDark ? "Switch to light theme" : "Switch to dark theme";

  return (
    <Press
      onClick={toggle}
      aria-label={label}
      title={label}
      className={cn(
        "flex w-full items-center rounded-lg border border-border bg-card text-sm font-medium text-muted-foreground hover:bg-secondary hover:text-foreground",
        collapsed ? "justify-center px-0 py-2" : "justify-between px-3 py-2",
      )}
    >
      <span className="flex items-center gap-2.5">
        {/* Avoid an icon flip before hydration knows the real theme. */}
        {mounted && !isDark ? (
          <Sun className="h-4 w-4" aria-hidden />
        ) : (
          <Moon className="h-4 w-4" aria-hidden />
        )}
        {!collapsed && (mounted ? (isDark ? "Dark" : "Light") : "Theme")}
      </span>
      {!collapsed && (
        <span className="text-[10px] uppercase tracking-[0.12em] opacity-70">
          Theme
        </span>
      )}
    </Press>
  );
}

function initialFor(user: { name?: string | null; email: string }): string {
  const source = (user.name?.trim() || user.email || "?").trim();
  return source.charAt(0).toUpperCase();
}

function UserWidget({ collapsed }: { collapsed: boolean }) {
  const { user, org, logout } = useAuth();
  const router = useRouter();

  if (!user) return null;

  const handleLogout = async () => {
    await logout();
    router.replace("/login");
  };

  const displayName = user.name?.trim() || user.email;

  // Collapsed: the avatar doubles as the sign-out affordance to save width.
  if (collapsed) {
    return (
      <Press
        onClick={handleLogout}
        aria-label={`Sign out ${displayName}`}
        title={`${displayName} - sign out`}
        className="group relative flex w-full items-center justify-center rounded-lg border border-border bg-card py-2.5 text-muted-foreground hover:text-foreground"
      >
        <span
          className="flex h-8 w-8 items-center justify-center rounded-full bg-[var(--sb-accent)] text-sm font-semibold text-white group-hover:opacity-0"
          aria-hidden
        >
          {initialFor(user)}
        </span>
        <LogOut className="absolute h-4 w-4 opacity-0 transition-opacity group-hover:opacity-100" />
      </Press>
    );
  }

  return (
    <div className="flex items-center gap-2.5 rounded-lg border border-border bg-card px-3 py-2.5">
      <div
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--sb-accent)] text-sm font-semibold text-white"
        aria-hidden
      >
        {initialFor(user)}
      </div>
      <div className="min-w-0 flex-1 leading-tight">
        <div className="truncate text-sm font-medium" title={displayName}>
          {displayName}
        </div>
        <div
          className="truncate text-[11px] text-muted-foreground"
          title={org?.name}
        >
          {org?.name ?? "Workspace"}
        </div>
      </div>
      <Press
        onClick={handleLogout}
        aria-label="Sign out"
        title="Sign out"
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground"
      >
        <LogOut className="h-4 w-4" />
      </Press>
    </div>
  );
}

interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
  match?: (path: string) => boolean;
  // When true the item only renders for admins (user.is_admin).
  adminOnly?: boolean;
}

interface NavSection {
  label: string;
  items: NavItem[];
}

// Grouped so the nav reads top to bottom as the way the platform is used:
// first the decision surfaces you work day to day, then the platform you
// configure, then the insight loops, then the system settings.
const SECTIONS: NavSection[] = [
  {
    label: "Decide",
    items: [
      {
        label: "Overview",
        href: "/dashboard",
        icon: LayoutDashboard,
        match: (p) => p === "/dashboard",
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
      {
        label: "Contacts",
        href: "/contacts",
        icon: Contact2,
        match: (p) => p.startsWith("/contacts"),
      },
    ],
  },
  {
    label: "Platform",
    items: [
      {
        label: "Copilot",
        href: "/chat",
        icon: Bot,
        match: (p) => p.startsWith("/chat"),
      },
      {
        label: "Agents",
        href: "/agents",
        icon: Workflow,
        match: (p) => p.startsWith("/agents"),
      },
      {
        label: "Domains",
        href: "/domains",
        icon: Boxes,
        match: (p) => p.startsWith("/domains"),
      },
      {
        label: "Workflow",
        href: "/workflow",
        icon: Network,
        match: (p) => p.startsWith("/workflow"),
      },
      {
        label: "Rules",
        href: "/rules",
        icon: SlidersHorizontal,
        match: (p) => p.startsWith("/rules"),
      },
      {
        label: "Ingest",
        href: "/ingest",
        icon: Upload,
        match: (p) => p.startsWith("/ingest"),
      },
    ],
  },
  {
    label: "Insight",
    items: [
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
    ],
  },
  {
    label: "System",
    items: [
      {
        label: "Settings",
        href: "/settings",
        icon: Settings,
        match: (p) => p.startsWith("/settings"),
      },
      {
        label: "Admin",
        href: "/admin",
        icon: ShieldCheck,
        match: (p) => p.startsWith("/admin"),
        adminOnly: true,
      },
    ],
  },
];

function NavLink({
  item,
  active,
  collapsed,
  onNavigate,
}: {
  item: NavItem;
  active: boolean;
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  const Icon = item.icon;
  return (
    <Press asChild>
      <Link
        href={item.href}
        onClick={onNavigate}
        aria-current={active ? "page" : undefined}
        // When collapsed the icon is the only affordance, so the native title
        // tooltip names the destination on hover.
        title={collapsed ? item.label : undefined}
        className={cn(
          "group relative flex items-center rounded-lg py-2 text-sm font-medium",
          collapsed ? "justify-center px-0" : "gap-3 px-3",
          active
            ? // Active route: subtle Claude-orange wash + accent text.
              "bg-[var(--sb-accent-subtle)] text-[var(--sb-accent)]"
            : // Idle: muted, with a faint neutral wash and a gentle lift on hover.
              "text-muted-foreground hover:-translate-y-px hover:bg-secondary hover:text-foreground",
        )}
      >
        <span
          className={cn(
            "absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-[var(--sb-accent)] transition-opacity",
            active ? "opacity-100" : "opacity-0",
          )}
          aria-hidden
        />
        <Icon
          className={cn(
            "h-4 w-4 shrink-0 transition-colors",
            active
              ? "text-[var(--sb-accent)]"
              : "text-muted-foreground group-hover:text-foreground",
          )}
        />
        {!collapsed && item.label}
      </Link>
    </Press>
  );
}

export function AppSidebar({
  mobileOpen = false,
  onClose,
}: {
  // Below md the sidebar is an off-canvas drawer driven by the app shell.
  mobileOpen?: boolean;
  onClose?: () => void;
} = {}) {
  const pathname = usePathname() || "/";
  const { user } = useAuth();
  // Start expanded; the stored preference is restored on mount.
  const [collapsed, setCollapsed] = useState(false);

  // Restore the persisted collapse state once on mount.
  useEffect(() => {
    try {
      setCollapsed(localStorage.getItem(COLLAPSE_KEY) === "1");
    } catch {
      /* storage unavailable; default expanded */
    }
  }, []);

  // Drive the page offset (in app-shell) from a single CSS variable.
  useEffect(() => {
    document.documentElement.style.setProperty(
      "--sidebar-w",
      collapsed ? WIDTH_COLLAPSED : WIDTH_EXPANDED,
    );
  }, [collapsed]);

  const toggle = () => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(COLLAPSE_KEY, next ? "1" : "0");
      } catch {
        /* storage unavailable; toggle still applies for the session */
      }
      return next;
    });
  };

  const renderSection = (items: NavItem[]) =>
    items
      .filter((item) => !item.adminOnly || user?.is_admin)
      .map((item) => {
      const active = item.match
        ? item.match(pathname)
        : pathname.startsWith(item.href);
      return (
        <NavLink
          key={item.href}
          item={item}
          active={active}
          collapsed={collapsed}
          onNavigate={onClose}
        />
      );
    });

  return (
    <>
      {/* Scrim behind the mobile drawer; tap to dismiss. Hidden at md+. */}
      {mobileOpen ? (
        <div
          className="fixed inset-0 z-40 bg-foreground/40 backdrop-blur-sm md:hidden"
          onClick={onClose}
          aria-hidden
        />
      ) : null}
      <aside
        style={{
          ...ACCENT_VARS,
          width: collapsed ? WIDTH_COLLAPSED : WIDTH_EXPANDED,
        }}
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex flex-col border-r border-border bg-[hsl(var(--sidebar))] transition-transform duration-300 ease-out md:z-30 md:translate-x-0 md:transition-[width]",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
      <div
        className={cn(
          "flex h-20 items-center border-b border-border",
          collapsed ? "justify-center px-0" : "gap-2.5 px-5",
        )}
      >
        {/* The brand mark doubles as the collapse toggle. */}
        <Press
          onClick={toggle}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-pressed={collapsed}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--sb-accent)] text-white shadow-sm transition-transform hover:scale-105 active:scale-95"
        >
          <Aperture className="h-[18px] w-[18px]" />
        </Press>
        {!collapsed && (
          <div className="leading-tight">
            <div className="text-sm font-semibold tracking-tight">Aperture</div>
            <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
              Decision Engine
            </div>
          </div>
        )}
      </div>

      <nav className="flex flex-1 flex-col gap-6 overflow-y-auto px-3 py-5 scroll-thin">
        {SECTIONS.map((section) => (
          <div key={section.label} className="flex flex-col gap-1">
            {!collapsed && (
              <div className="px-3 pb-1 text-eyebrow">{section.label}</div>
            )}
            {renderSection(section.items)}
          </div>
        ))}
      </nav>

        <div className="space-y-3 border-t border-border p-3">
          <ThemeToggle collapsed={collapsed} />
          <UserWidget collapsed={collapsed} />
        </div>
      </aside>
    </>
  );
}

export default AppSidebar;
