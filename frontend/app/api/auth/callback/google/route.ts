// Google sign-in callback (redirect URI: http://localhost:3000/api/auth/callback/google).
//
// Google sends the user here after consent. We hand the ?code + ?state to the
// backend (POST /auth/google/exchange), which validates the CSRF state, resolves
// the Google account email, finds or creates the user, and returns a Set-Cookie
// for the session. We relay that cookie onto the redirect so the browser is
// signed in, then bounce to /dashboard. Cookies are host-only on "localhost"
// (port-agnostic), so a cookie set here is also sent to the API on :8000.

import { NextRequest, NextResponse } from "next/server";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://localhost:8200";

// Public origin of THIS app, PINNED to a server-side configured value. Behind a
// reverse proxy the server binds to 0.0.0.0:3200, so req.url would redirect to
// 0.0.0.0. We must NOT derive it from request headers (Host / X-Forwarded-Host
// are client-controllable -> open redirect / OAuth phishing). NEXT_PUBLIC_SITE_URL
// is baked at build time (prod: https://aperture.niheshr.com). req.nextUrl.origin
// is only the local-dev fallback when SITE_URL is unset.
function appOrigin(req: NextRequest): string {
  return (
    process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/$/, "") || req.nextUrl.origin
  );
}

function loginError(req: NextRequest, reason: string): NextResponse {
  const url = new URL("/login", appOrigin(req));
  url.searchParams.set("error", reason);
  return NextResponse.redirect(url);
}

export async function GET(req: NextRequest): Promise<NextResponse> {
  const params = req.nextUrl.searchParams;
  const code = params.get("code");
  const error = params.get("error");
  const state = params.get("state");

  if (error || !code || !state) {
    return loginError(req, error === "access_denied" ? "denied" : "google");
  }

  try {
    const res = await fetch(`${API_BASE}/auth/google/exchange`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        // Forward the browser's cookies so the backend sees the google_oauth_state
        // cookie it set on /auth/google/start (binds the flow to this browser).
        Cookie: req.headers.get("cookie") ?? "",
      },
      body: JSON.stringify({ code, state }),
      cache: "no-store",
    });

    if (!res.ok) {
      return loginError(req, "google");
    }

    const redirectRes = NextResponse.redirect(
      new URL("/dashboard", appOrigin(req)),
    );
    // Relay the backend's session cookie to the browser so the user is signed in.
    const setCookie = res.headers.get("set-cookie");
    if (setCookie) {
      redirectRes.headers.set("set-cookie", setCookie);
    }
    return redirectRes;
  } catch {
    return loginError(req, "google");
  }
}
