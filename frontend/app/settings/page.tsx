"use client";

// Per-org integration settings. One card per connector (SES email, Slack,
// Google, and a CRM stub). Status is read from GET /integrations and every
// mutation is scoped to the caller's org via the nba_session cookie
// (credentials:"include" lives in the typed client). Fully offline-safe: with
// no backend the list resolves empty and every card renders "not configured".

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Settings2,
  Mail,
  Hash,
  Database,
  CheckCircle2,
  CircleDashed,
  Save,
  Send,
  Link2,
  Unlink,
  ShieldCheck,
  Building2,
  AtSign,
} from "lucide-react";

import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { toast } from "@/components/ui/toast";
import { useAuth } from "@/lib/auth-context";
import { API_BASE } from "@/lib/api";
import { authHeaders } from "@/lib/auth";
import {
  listIntegrations,
  saveIntegration,
  deleteIntegration,
  googleStart,
  testSlack,
  type Connector,
  type ConnectorKind,
  type ConnectorStatus,
} from "@/lib/api/integrations";

// The verified SES sending domain. Only senders on this domain are accepted.
const VERIFIED_DOMAIN = "niheshr.com";

function isConnected(status: ConnectorStatus | undefined): boolean {
  return status === "connected";
}

function StatusPill({ status }: { status: ConnectorStatus | undefined }) {
  const connected = isConnected(status);
  return (
    <Badge variant={connected ? "success" : "muted"}>
      {connected ? (
        <CheckCircle2 className="h-3 w-3" aria-hidden />
      ) : (
        <CircleDashed className="h-3 w-3" aria-hidden />
      )}
      {connected ? "Connected" : "Not connected"}
    </Badge>
  );
}

function ConnectorShell({
  icon: Icon,
  title,
  description,
  status,
  children,
  footer,
}: {
  icon: typeof Mail;
  title: string;
  description: string;
  status?: ConnectorStatus;
  children?: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <Card className="flex flex-col">
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-secondary text-secondary-foreground">
              <Icon className="h-5 w-5" aria-hidden />
            </div>
            <div>
              <CardTitle className="text-base">{title}</CardTitle>
              <CardDescription className="mt-0.5">
                {description}
              </CardDescription>
            </div>
          </div>
          <StatusPill status={status} />
        </div>
      </CardHeader>
      <CardContent className="flex-1 space-y-3">{children}</CardContent>
      {footer ? (
        <CardFooter className="gap-2 border-t border-border pt-4">
          {footer}
        </CardFooter>
      ) : null}
    </Card>
  );
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
      {children}
    </label>
  );
}

// ---------------------------------------------------------------------------
// Email (SES)
// ---------------------------------------------------------------------------

function EmailCard({
  connector,
  onChange,
}: {
  connector?: Connector;
  onChange: () => void;
}) {
  const { org } = useAuth();
  const initial = connector?.config.sender_email ?? "";
  const [sender, setSender] = useState(initial);
  const [saving, setSaving] = useState(false);

  // Re-sync when the backend status arrives after first paint.
  useEffect(() => {
    setSender(connector?.config.sender_email ?? "");
  }, [connector?.config.sender_email]);

  const save = async () => {
    const value = sender.trim();
    if (!value) {
      toast("Enter a sender email", { variant: "error" });
      return;
    }
    if (!value.toLowerCase().endsWith(`@${VERIFIED_DOMAIN}`)) {
      toast("Sender must use the verified domain", {
        variant: "error",
        description: `Use an address on @${VERIFIED_DOMAIN}.`,
      });
      return;
    }
    setSaving(true);
    try {
      await saveIntegration("ses", { sender_email: value });
      toast("Email sender saved", { variant: "success" });
      onChange();
    } catch {
      toast("Could not save sender", {
        variant: "error",
        description: "The integrations service is unavailable.",
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <ConnectorShell
      icon={Mail}
      title="Email (SES)"
      description={`Send approved actions from ${org?.name ?? "your workspace"} over Amazon SES.`}
      status={connector?.status}
      footer={
        <Button onClick={save} disabled={saving} className="ml-auto">
          <Save className="h-4 w-4" />
          {saving ? "Saving" : "Save"}
        </Button>
      }
    >
      <div>
        <FieldLabel>Sender email</FieldLabel>
        <Input
          type="email"
          value={sender}
          onChange={(e) => setSender(e.target.value)}
          placeholder={`success@${VERIFIED_DOMAIN}`}
          autoComplete="off"
          spellCheck={false}
        />
      </div>
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <ShieldCheck className="h-3.5 w-3.5 text-primary" aria-hidden />
        Verified domain{" "}
        <span className="font-medium text-foreground">@{VERIFIED_DOMAIN}</span>
      </p>
    </ConnectorShell>
  );
}

// ---------------------------------------------------------------------------
// Slack
// ---------------------------------------------------------------------------

function SlackCard({
  connector,
  onChange,
}: {
  connector?: Connector;
  onChange: () => void;
}) {
  const [webhook, setWebhook] = useState(connector?.config.webhook_url ?? "");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    setWebhook(connector?.config.webhook_url ?? "");
  }, [connector?.config.webhook_url]);

  const save = async () => {
    const value = webhook.trim();
    if (!value.startsWith("https://hooks.slack.com/")) {
      toast("Enter a valid Slack webhook URL", {
        variant: "error",
        description: "It should start with https://hooks.slack.com/",
      });
      return;
    }
    setSaving(true);
    try {
      await saveIntegration("slack", { webhook_url: value });
      toast("Slack webhook saved", { variant: "success" });
      onChange();
    } catch {
      toast("Could not save webhook", { variant: "error" });
    } finally {
      setSaving(false);
    }
  };

  // Save the webhook, then ask the backend to post a real test message to it.
  const sendTest = async () => {
    const value = webhook.trim();
    if (!value.startsWith("https://hooks.slack.com/")) {
      toast("Enter and save a valid Slack webhook first", { variant: "error" });
      return;
    }
    setTesting(true);
    try {
      await saveIntegration("slack", { webhook_url: value });
      const res = await testSlack();
      if (res.sent) {
        toast("Test message sent", {
          variant: "success",
          description: "Check your Slack channel.",
        });
      } else {
        toast("Slack test failed", {
          variant: "error",
          description: res.reason || "Could not reach Slack.",
        });
      }
      onChange();
    } catch {
      toast("Could not send test", {
        variant: "error",
        description: "The integrations service is unavailable.",
      });
    } finally {
      setTesting(false);
    }
  };

  return (
    <ConnectorShell
      icon={Hash}
      title="Slack"
      description="Notify a channel when a recommendation is approved."
      status={connector?.status}
      footer={
        <>
          <Button
            variant="outline"
            onClick={sendTest}
            disabled={testing || saving}
          >
            <Send className="h-4 w-4" />
            {testing ? "Sending" : "Send test"}
          </Button>
          <Button onClick={save} disabled={saving} className="ml-auto">
            <Save className="h-4 w-4" />
            {saving ? "Saving" : "Save"}
          </Button>
        </>
      }
    >
      <div>
        <FieldLabel>Incoming webhook URL</FieldLabel>
        <Input
          type="url"
          value={webhook}
          onChange={(e) => setWebhook(e.target.value)}
          placeholder="https://hooks.slack.com/services/T000/B000/XXXX"
          autoComplete="off"
          spellCheck={false}
        />
      </div>
      <p className="text-xs text-muted-foreground">
        Create an incoming webhook in your Slack workspace and paste the URL
        here. We never post without an approved action.
      </p>
    </ConnectorShell>
  );
}

// ---------------------------------------------------------------------------
// Google
// ---------------------------------------------------------------------------

function GoogleCard({
  connector,
  onChange,
}: {
  connector?: Connector;
  onChange: () => void;
}) {
  const [connecting, setConnecting] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const connected = isConnected(connector?.status);
  const email = connector?.config.email;

  const connect = async () => {
    setConnecting(true);
    try {
      const { url, configured } = await googleStart();
      if (!configured || !url) {
        toast("Google OAuth is not configured", {
          variant: "error",
          description: "Set GOOGLE_CLIENT_ID and GOOGLE_REDIRECT_URI to enable.",
        });
        return;
      }
      // Hand off to Google's consent screen; the backend callback stores the
      // tokens and returns the user here.
      window.location.assign(url);
    } catch {
      toast("Could not start Google connect", { variant: "error" });
    } finally {
      setConnecting(false);
    }
  };

  const disconnect = async () => {
    setDisconnecting(true);
    try {
      await deleteIntegration("google");
      toast("Google disconnected", { variant: "success" });
      onChange();
    } catch {
      toast("Could not disconnect", { variant: "error" });
    } finally {
      setDisconnecting(false);
    }
  };

  return (
    <ConnectorShell
      icon={Mail}
      title="Google (Gmail)"
      description="Send from a connected Google account via the Gmail API."
      status={connector?.status}
      footer={
        connected ? (
          <Button
            variant="outline"
            onClick={disconnect}
            disabled={disconnecting}
            className="ml-auto"
          >
            <Unlink className="h-4 w-4" />
            {disconnecting ? "Disconnecting" : "Disconnect"}
          </Button>
        ) : (
          <Button onClick={connect} disabled={connecting} className="ml-auto">
            <Link2 className="h-4 w-4" />
            {connecting ? "Opening" : "Connect Google"}
          </Button>
        )
      }
    >
      {connected ? (
        <div className="rounded-lg border border-border bg-background/60 p-3">
          <div className="text-xs text-muted-foreground">Connected account</div>
          <div className="mt-0.5 truncate text-sm font-medium">
            {email ?? "Google account"}
          </div>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          Connect a Google account to send approved emails from your own
          mailbox. We request only send scope and store tokens server-side.
        </p>
      )}
    </ConnectorShell>
  );
}

// ---------------------------------------------------------------------------
// CRM (stub)
// ---------------------------------------------------------------------------

function CrmCard() {
  return (
    <ConnectorShell
      icon={Database}
      title="CRM"
      description="Sync accounts and write back outcomes to your CRM."
      status="not_configured"
      footer={
        <Button variant="outline" disabled className="ml-auto">
          Coming soon
        </Button>
      }
    >
      <p className="text-xs text-muted-foreground">
        Salesforce and HubSpot connectors are on the roadmap. Account signals
        already flow in through Ingest in the meantime.
      </p>
    </ConnectorShell>
  );
}

// ---------------------------------------------------------------------------
// Workspace (org name + signed-in user)
// ---------------------------------------------------------------------------

function WorkspaceCard() {
  const { org, user, refresh } = useAuth();
  const [name, setName] = useState(org?.name ?? "");
  const [saving, setSaving] = useState(false);

  // Re-sync once the session resolves after first paint.
  useEffect(() => {
    setName(org?.name ?? "");
  }, [org?.name]);

  const dirty = name.trim().length > 0 && name.trim() !== (org?.name ?? "");

  const save = async () => {
    const value = name.trim();
    if (!value) {
      toast("Enter a workspace name", { variant: "error" });
      return;
    }
    setSaving(true);
    try {
      const res = await fetch(`${API_BASE}/auth/org`, {
        method: "PUT",
        headers: authHeaders({ "Content-Type": "application/json" }),
        credentials: "include",
        body: JSON.stringify({ name: value }),
      });
      if (!res.ok) throw new Error(`PUT /auth/org failed (${res.status})`);
      await refresh();
      toast("Workspace name saved", { variant: "success" });
    } catch {
      toast("Could not save workspace name", {
        variant: "error",
        description: "Sign in and try again.",
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-secondary text-secondary-foreground">
            <Building2 className="h-5 w-5" aria-hidden />
          </div>
          <div>
            <CardTitle className="text-base">Workspace</CardTitle>
            <CardDescription className="mt-0.5">
              Name this workspace and review who is signed in.
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-2">
        <div>
          <FieldLabel>Workspace name</FieldLabel>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Acme Customer Success"
            maxLength={120}
            spellCheck={false}
          />
        </div>
        <div>
          <FieldLabel>Signed in as</FieldLabel>
          <div className="flex h-9 items-center gap-2 rounded-md border border-border bg-background/60 px-3 text-sm">
            <AtSign className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
            <span className="truncate" title={user?.email}>
              {user?.email ?? "Not signed in"}
            </span>
          </div>
        </div>
      </CardContent>
      <CardFooter className="gap-2 border-t border-border pt-4">
        <Button
          onClick={save}
          disabled={saving || !dirty}
          className="ml-auto"
        >
          <Save className="h-4 w-4" />
          {saving ? "Saving" : "Save"}
        </Button>
      </CardFooter>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function SettingsPage() {
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const list = await listIntegrations(signal);
    setConnectors(list);
  }, []);

  useEffect(() => {
    const ac = new AbortController();
    (async () => {
      try {
        await refresh(ac.signal);
      } finally {
        if (!ac.signal.aborted) setLoading(false);
      }
    })();
    return () => ac.abort();
  }, [refresh]);

  const byKind = useMemo(() => {
    const map = new Map<ConnectorKind, Connector>();
    for (const c of connectors) map.set(c.kind, c);
    return map;
  }, [connectors]);

  const reload = useCallback(() => {
    void refresh();
  }, [refresh]);

  return (
    <div className="flex flex-1 flex-col">
      <header className="flex items-center justify-between border-b border-border px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-secondary text-secondary-foreground">
            <Settings2 className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-sm font-medium text-muted-foreground">
              Settings
            </h1>
            <p className="text-lg font-semibold tracking-tight">
              Integrations
            </p>
          </div>
        </div>
        {loading ? (
          <span className="text-xs text-muted-foreground">Loading status</span>
        ) : null}
      </header>

      <div className="mx-auto w-full max-w-5xl px-6 py-8">
        <p className="mb-6 max-w-2xl text-sm leading-relaxed text-muted-foreground">
          Connect the channels Aperture uses to deliver approved next best
          actions. Every connector is scoped to your workspace, and nothing is
          sent without a human approval.
        </p>
        <div className="mb-5">
          <WorkspaceCard />
        </div>
        <div className="grid gap-5 md:grid-cols-2">
          {/* Email always sends from the platform sender over SES (no per-user
              config). Google is a sign-in method, not a mail connector. */}
          <SlackCard connector={byKind.get("slack")} onChange={reload} />
          <CrmCard />
        </div>
      </div>
    </div>
  );
}
