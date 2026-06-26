"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";

import { AuthScreen } from "@/components/auth-screen";
import { Button } from "@/components/ui/button";
import { API_BASE } from "@/lib/api";
import { authHeaders } from "@/lib/auth";

type VerifyState = "verifying" | "success" | "error" | "missing";

function VerifyInner() {
  const params = useSearchParams();
  const token = params.get("token");
  const [state, setState] = useState<VerifyState>(token ? "verifying" : "missing");
  const [message, setMessage] = useState<string | null>(null);
  const ran = useRef(false);

  useEffect(() => {
    if (!token || ran.current) return;
    ran.current = true;
    (async () => {
      try {
        const res = await fetch(
          `${API_BASE}/auth/verify?token=${encodeURIComponent(token)}`,
          {
            headers: authHeaders({ Accept: "application/json" }),
            credentials: "include",
            cache: "no-store",
          },
        );
        if (!res.ok) {
          let detail = "This verification link is invalid or has expired.";
          try {
            const body = (await res.json()) as { detail?: string };
            if (body.detail) detail = body.detail;
          } catch {
            /* keep status-based message */
          }
          setMessage(detail);
          setState("error");
          return;
        }
        setState("success");
      } catch {
        setMessage("Could not reach the server. Please try again.");
        setState("error");
      }
    })();
  }, [token]);

  if (state === "missing") {
    return (
      <AuthScreen
        title="Missing token"
        subtitle="This page expects a verification token in the link."
        footer={
          <Link href="/login" className="font-medium text-primary hover:underline">
            Back to sign in
          </Link>
        }
      >
        <div className="flex items-start gap-3 rounded-lg border border-border bg-card p-4">
          <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            Open the verification link from your email to continue.
          </p>
        </div>
      </AuthScreen>
    );
  }

  if (state === "verifying") {
    return (
      <AuthScreen title="Verifying your email" subtitle="One moment.">
        <div className="flex items-center gap-3 rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin text-primary" />
          Confirming your verification link.
        </div>
      </AuthScreen>
    );
  }

  if (state === "success") {
    return (
      <AuthScreen
        title="Email verified"
        subtitle="Your workspace is ready. Sign in to get started."
      >
        <div className="space-y-5">
          <div className="flex items-start gap-3 rounded-lg border border-border bg-card p-4">
            <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
            <p className="text-sm text-muted-foreground">
              Your email address is confirmed.
            </p>
          </div>
          <Button asChild className="w-full">
            <Link href="/login">Continue to sign in</Link>
          </Button>
        </div>
      </AuthScreen>
    );
  }

  return (
    <AuthScreen
      title="Verification failed"
      footer={
        <Link href="/login" className="font-medium text-primary hover:underline">
          Back to sign in
        </Link>
      }
    >
      <div className="flex items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/10 p-4">
        <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
        <p className="text-sm text-destructive">
          {message ?? "This verification link is invalid or has expired."}
        </p>
      </div>
    </AuthScreen>
  );
}

export default function VerifyPage() {
  return (
    <Suspense
      fallback={
        <AuthScreen title="Verifying your email" subtitle="One moment.">
          <div className="flex items-center gap-3 rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin text-primary" />
            Loading.
          </div>
        </AuthScreen>
      }
    >
      <VerifyInner />
    </Suspense>
  );
}
