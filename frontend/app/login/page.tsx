"use client";

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { KeyRound, Loader2 } from "lucide-react";

import { AuthScreen } from "@/components/auth-screen";
import { Button } from "@/components/ui/button";
import { GoogleButton } from "@/components/google-button";
import { Input } from "@/components/ui/input";
import { API_BASE } from "@/lib/api";
import { authHeaders } from "@/lib/auth";
import { useAuth } from "@/lib/auth-context";
import { isPasskeySupported, loginWithPasskey } from "@/lib/api/passkey";

export default function LoginPage() {
  const router = useRouter();
  const { refresh } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [passkeyLoading, setPasskeyLoading] = useState(false);
  const [passkeyReady, setPasskeyReady] = useState(false);

  // WebAuthn is a client-only API; detect support after mount to keep the
  // server-rendered markup stable and avoid a hydration mismatch.
  useEffect(() => {
    setPasskeyReady(isPasskeySupported());
  }, []);

  async function onPasskey() {
    setError(null);
    setPasskeyLoading(true);
    try {
      // A filled email targets that account's passkeys; otherwise fall back to
      // a discoverable (usernameless) credential.
      await loginWithPasskey(email.trim() || undefined);
      await refresh();
      router.replace("/dashboard");
    } catch (err) {
      setError((err as Error).message || "Could not sign in with a passkey.");
      setPasskeyLoading(false);
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        credentials: "include",
        body: JSON.stringify({ email: email.trim(), password }),
      });
      if (!res.ok) {
        let detail = "Invalid email or password.";
        if (res.status === 403) {
          detail = "Please verify your email before signing in.";
        }
        try {
          const body = (await res.json()) as { detail?: string };
          if (body.detail) detail = body.detail;
        } catch {
          /* keep status-based message */
        }
        throw new Error(detail);
      }
      await refresh();
      router.replace("/dashboard");
    } catch (err) {
      setError((err as Error).message || "Could not sign in.");
      setSubmitting(false);
    }
  }

  return (
    <AuthScreen
      title="Welcome back"
      subtitle="Sign in to your Aperture workspace."
      footer={
        <>
          New here?{" "}
          <Link
            href="/signup"
            className="font-medium text-primary hover:underline"
          >
            Create an account
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-4">
        <div className="space-y-1.5">
          <label htmlFor="email" className="text-sm font-medium">
            Email
          </label>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@company.com"
          />
        </div>
        <div className="space-y-1.5">
          <label htmlFor="password" className="text-sm font-medium">
            Password
          </label>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Enter your password"
          />
        </div>

        {error ? (
          <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </p>
        ) : null}

        <Button type="submit" className="w-full" disabled={submitting}>
          {submitting ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Signing in
            </>
          ) : (
            "Sign in"
          )}
        </Button>

        <div className="flex items-center gap-3 py-1">
          <span className="h-px flex-1 bg-border" />
          <span className="text-xs text-muted-foreground">or</span>
          <span className="h-px flex-1 bg-border" />
        </div>
        <GoogleButton />
        {passkeyReady ? (
          <Button
            type="button"
            variant="outline"
            className="w-full"
            onClick={onPasskey}
            disabled={passkeyLoading || submitting}
          >
            {passkeyLoading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <KeyRound className="h-4 w-4" />
            )}
            Sign in with a passkey
          </Button>
        ) : null}
      </form>
    </AuthScreen>
  );
}
