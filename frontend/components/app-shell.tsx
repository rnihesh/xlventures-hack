"use client";

// Decides the chrome around every page. Auth screens (/login, /signup,
// /verify) render full-bleed with no sidebar. Everything else is gated: while
// the session resolves we show a quiet loader, and an unauthenticated visitor
// is redirected to /login before any app data renders.

import { useEffect, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Aperture } from "lucide-react";

import { AppSidebar } from "@/components/app-sidebar";
import { useAuth } from "@/lib/auth-context";

const PUBLIC_ROUTES = ["/login", "/signup", "/verify"];

function isPublic(pathname: string): boolean {
  // The marketing landing page is public and full-bleed (no app chrome).
  if (pathname === "/") return true;
  return PUBLIC_ROUTES.some(
    (route) => pathname === route || pathname.startsWith(`${route}/`),
  );
}

function Splash() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="flex flex-col items-center gap-3 text-muted-foreground">
        <div className="flex h-10 w-10 animate-pulse items-center justify-center rounded-xl bg-primary text-primary-foreground">
          <Aperture className="h-5 w-5" />
        </div>
        <span className="text-xs uppercase tracking-[0.18em]">Aperture</span>
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() || "/";
  const router = useRouter();
  const { user, loading } = useAuth();
  const publicRoute = isPublic(pathname);

  useEffect(() => {
    if (!loading && !user && !publicRoute) {
      router.replace("/login");
    }
  }, [loading, user, publicRoute, router]);

  // Public auth screens own the full viewport.
  if (publicRoute) {
    return <>{children}</>;
  }

  // Hold the protected shell until we know who (if anyone) is signed in.
  if (loading || !user) {
    return <Splash />;
  }

  return (
    <div className="flex min-h-screen">
      <AppSidebar />
      <div className="flex min-h-screen flex-1 flex-col transition-[padding] duration-300 ease-out md:pl-[var(--sidebar-w,16rem)]">
        <main className="flex-1">{children}</main>
      </div>
    </div>
  );
}

export default AppShell;
