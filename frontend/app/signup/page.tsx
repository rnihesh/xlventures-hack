"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { CheckCircle2, Loader2 } from "lucide-react";

import { AuthScreen } from "@/components/auth-screen";
import { Button } from "@/components/ui/button";
import { GoogleButton } from "@/components/google-button";
import { Input } from "@/components/ui/input";
import { API_BASE } from "@/lib/api";
import { authHeaders } from "@/lib/auth";

interface SignupResult {
  // Dev convenience: when SES is unavailable the backend returns the verify
  // link directly so the flow can complete without an inbox.
  verify_link?: string;
  verification_link?: string;
  link?: string;
}

export default function SignupPage() {
  const [name, setName] = useState("");
  const [orgName, setOrgName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [verifyLink, setVerifyLink] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const res = await fetch(`${API_BASE}/auth/signup`, {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        credentials: "include",
        body: JSON.stringify({
          name: name.trim(),
          org_name: orgName.trim(),
          email: email.trim(),
          password,
        }),
      });
      if (!res.ok) {
        let detail = "Could not create your account.";
        if (res.status === 409) detail = "That email is already registered.";
        try {
          const body = (await res.json()) as { detail?: string };
          if (body.detail) detail = body.detail;
        } catch {
          /* keep status-based message */
        }
        throw new Error(detail);
      }
      const body = (await res.json().catch(() => ({}))) as SignupResult;
      const link = body.verify_link ?? body.verification_link ?? body.link ?? null;
      setVerifyLink(link);
      setDone(true);
    } catch (err) {
      setError((err as Error).message || "Could not create your account.");
    } finally {
      setSubmitting(false);
    }
  }

  if (done) {
    return (
      <AuthScreen
        title="Check your email"
        subtitle={`We sent a verification link to ${email || "your inbox"}. Confirm it to activate your workspace.`}
        footer={
          <Link href="/login" className="font-medium text-primary hover:underline">
            Back to sign in
          </Link>
        }
      >
        <div className="space-y-4">
          <div className="flex items-start gap-3 rounded-lg border border-border bg-card p-4">
            <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
            <p className="text-sm text-muted-foreground">
              Open the link in your email to verify your address, then sign in.
            </p>
          </div>
          {verifyLink ? (
            <div className="space-y-2 rounded-lg border border-dashed border-border bg-secondary/40 p-4">
              <p className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
                Dev verification link
              </p>
              <a
                href={verifyLink}
                className="block break-all text-sm font-medium text-primary hover:underline"
              >
                {verifyLink}
              </a>
            </div>
          ) : null}
        </div>
      </AuthScreen>
    );
  }

  return (
    <AuthScreen
      title="Create your workspace"
      subtitle="Start with a clean, private organization."
      footer={
        <>
          Already have an account?{" "}
          <Link href="/login" className="font-medium text-primary hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-4">
        <div className="space-y-1.5">
          <label htmlFor="name" className="text-sm font-medium">
            Your name
          </label>
          <Input
            id="name"
            autoComplete="name"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Ada Lovelace"
          />
        </div>
        <div className="space-y-1.5">
          <label htmlFor="org" className="text-sm font-medium">
            Organization name
          </label>
          <Input
            id="org"
            autoComplete="organization"
            required
            value={orgName}
            onChange={(e) => setOrgName(e.target.value)}
            placeholder="Acme Inc"
          />
        </div>
        <div className="space-y-1.5">
          <label htmlFor="email" className="text-sm font-medium">
            Work email
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
            autoComplete="new-password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="At least 8 characters"
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
              Creating
            </>
          ) : (
            "Create account"
          )}
        </Button>

        <div className="flex items-center gap-3 py-1">
          <span className="h-px flex-1 bg-border" />
          <span className="text-xs text-muted-foreground">or</span>
          <span className="h-px flex-1 bg-border" />
        </div>
        <GoogleButton label="Sign up with Google" />
      </form>
    </AuthScreen>
  );
}
