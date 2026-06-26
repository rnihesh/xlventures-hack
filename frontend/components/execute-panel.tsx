"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Check,
  CheckCircle2,
  Copy,
  Hash,
  ListTodo,
  Loader2,
  Mail,
  PlugZap,
  Send,
  Settings,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { toast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";
import type { Recommendation } from "@/lib/types";
import {
  executeAction,
  sendArtifact,
  type Artifact,
  type ArtifactType,
  type AuditRecord,
  type CrmTaskArtifact,
  type EmailArtifact,
  type SendResult,
  type SlackArtifact,
} from "@/lib/api/actions";

interface ExecutePanelProps {
  // Provide a recommendation directly, or a run_id to use the stored one.
  recommendation?: Recommendation | null;
  runId?: string | null;
  accountId?: string | null;
  className?: string;
}

interface ActionDef {
  type: ArtifactType;
  label: string;
  icon: typeof Mail;
}

const ACTIONS: ActionDef[] = [
  { type: "email", label: "Draft email", icon: Mail },
  { type: "crm_task", label: "Create CRM task", icon: ListTodo },
  { type: "slack", label: "Slack handoff", icon: Hash },
];

const TYPE_LABEL: Record<ArtifactType, string> = {
  email: "Email draft",
  crm_task: "CRM task",
  slack: "Slack handoff",
};

// Short, human channel noun used in send results and the connect-in-settings
// hint, eg "Connect Email in Settings to send".
const CHANNEL_NOUN: Record<ArtifactType, string> = {
  email: "Email",
  crm_task: "CRM",
  slack: "Slack",
};

// A not-sent result is a missing-connection state (vs a hard failure) when the
// backend reports a *_not_configured / *_not_connected reason.
function isNotConfigured(reason?: string): boolean {
  if (!reason) return true;
  return /not_configured|not_connected/.test(reason);
}

function isEmail(a: Artifact, t: ArtifactType): a is EmailArtifact {
  return t === "email";
}
function isTask(a: Artifact, t: ArtifactType): a is CrmTaskArtifact {
  return t === "crm_task";
}
function isSlack(a: Artifact, t: ArtifactType): a is SlackArtifact {
  return t === "slack";
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={copy}
      className="gap-1.5"
    >
      {copied ? <Check className="text-primary" /> : <Copy />}
      {copied ? "Copied" : "Copy"}
    </Button>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </label>
      {children}
    </div>
  );
}

export function ExecutePanel({
  recommendation,
  runId,
  accountId,
  className,
}: ExecutePanelProps) {
  const [activeType, setActiveType] = useState<ArtifactType | null>(null);
  const [pendingType, setPendingType] = useState<ArtifactType | null>(null);
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [audit, setAudit] = useState<AuditRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [sendResult, setSendResult] = useState<SendResult | null>(null);

  const sent = sendResult?.sent === true;

  const resolvedAccountId =
    accountId ?? recommendation?.account_id ?? null;

  async function run(type: ArtifactType) {
    setPendingType(type);
    setError(null);
    setSendResult(null);
    try {
      const res = await executeAction({
        artifact_type: type,
        run_id: runId ?? undefined,
        recommendation: recommendation ?? undefined,
        account_id: resolvedAccountId ?? undefined,
      });
      setArtifact(res.artifact);
      setAudit(res.audit);
      setActiveType(type);
      toast(`${TYPE_LABEL[type]} ready`, {
        description: "Review, edit inline, and copy it when you are happy.",
        variant: "success",
      });
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to generate artifact";
      setError(message);
      toast("Could not generate artifact", {
        description: message,
        variant: "error",
      });
    } finally {
      setPendingType(null);
    }
  }

  // Copy text reflects the current (possibly edited) artifact.
  function copyText(): string {
    if (!artifact || !activeType) return "";
    if (isEmail(artifact, activeType)) {
      return `Subject: ${artifact.subject}\n\n${artifact.body}`;
    }
    if (isTask(artifact, activeType)) {
      return `${artifact.title}\nDue: ${artifact.due}\n\n${artifact.notes}`;
    }
    if (isSlack(artifact, activeType)) {
      return `${artifact.channel}\n\n${artifact.message}`;
    }
    return "";
  }

  function patch(next: Partial<Artifact>) {
    setArtifact((prev) => (prev ? ({ ...prev, ...next } as Artifact) : prev));
    // An edit invalidates a prior send so the user can re-send the revision.
    setSendResult(null);
  }

  // Recipient shown in the success line: where the artifact actually went.
  function sentTo(result: SendResult): string | null {
    if (result.to) return result.to;
    if (activeType && isSlack(artifact as Artifact, activeType)) {
      return (artifact as SlackArtifact).channel;
    }
    if (activeType === "email" && resolvedAccountId) return resolvedAccountId;
    return null;
  }

  // Really dispatch the (possibly edited) artifact through its channel. The
  // human stays in the loop: this only runs on an explicit click, and the
  // result is rendered inline (success or connect-in-settings), never a throw.
  async function send() {
    if (!artifact || !activeType || sending) return;
    setSending(true);
    setError(null);
    const action = recommendation?.action;
    try {
      const result = await sendArtifact({
        artifact_type: activeType,
        artifact,
        run_id: runId ?? undefined,
        account_id: resolvedAccountId ?? undefined,
        recommendation_id: recommendation?.id ?? undefined,
        action_key: action?.key ?? undefined,
      });
      setSendResult(result);
      if (result.sent) {
        const where = sentTo(result);
        toast(`${TYPE_LABEL[activeType]} sent`, {
          description: where
            ? `Delivered to ${where}.`
            : "Delivered successfully.",
          variant: "success",
        });
      } else {
        toast(`${CHANNEL_NOUN[activeType]} not connected`, {
          description: "Connect it in Settings, then send again.",
          variant: "info",
        });
      }
    } finally {
      setSending(false);
    }
  }

  return (
    <Card className={cn("w-full", className)}>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Send className="size-4 text-primary" />
              Execute this play
            </CardTitle>
            <CardDescription>
              Turn the recommendation into a ready-to-use artifact in one click.
            </CardDescription>
          </div>
          {audit ? (
            <Badge variant={audit.source === "llm" ? "info" : "muted"}>
              {audit.source === "llm" ? "AI generated" : "Template"}
            </Badge>
          ) : null}
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="flex flex-wrap gap-2">
          {ACTIONS.map(({ type, label, icon: Icon }) => {
            const loading = pendingType === type;
            const isActive = activeType === type;
            return (
              <Button
                key={type}
                type="button"
                variant={isActive ? "default" : "outline"}
                size="sm"
                disabled={pendingType !== null}
                onClick={() => run(type)}
                className="gap-1.5"
              >
                {loading ? (
                  <Loader2 className="animate-spin" />
                ) : (
                  <Icon />
                )}
                {label}
              </Button>
            );
          })}
        </div>

        {error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : null}

        {artifact && activeType ? (
          <div className="space-y-4 rounded-xl border border-border bg-background/50 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold">
                  {TYPE_LABEL[activeType]}
                </span>
                <Badge variant={sent ? "success" : "outline"}>
                  {sent ? "Sent" : "Editable preview"}
                </Badge>
              </div>
              <div className="flex items-center gap-2">
                <CopyButton text={copyText()} />
                <Button
                  type="button"
                  size="sm"
                  onClick={send}
                  disabled={sent || sending}
                  className="gap-1.5"
                >
                  {sending ? (
                    <Loader2 className="animate-spin" />
                  ) : sent ? (
                    <Check />
                  ) : (
                    <Send />
                  )}
                  {sending ? "Sending" : sent ? "Sent" : "Send"}
                </Button>
              </div>
            </div>

            {isEmail(artifact, activeType) ? (
              <div className="space-y-3">
                <Field label="Subject">
                  <Input
                    value={artifact.subject}
                    onChange={(e) =>
                      patch({ subject: e.target.value } as Partial<EmailArtifact>)
                    }
                  />
                </Field>
                <Field label="Body">
                  <Textarea
                    value={artifact.body}
                    rows={10}
                    onChange={(e) =>
                      patch({ body: e.target.value } as Partial<EmailArtifact>)
                    }
                  />
                </Field>
              </div>
            ) : null}

            {isTask(artifact, activeType) ? (
              <div className="space-y-3">
                <Field label="Title">
                  <Input
                    value={artifact.title}
                    onChange={(e) =>
                      patch({ title: e.target.value } as Partial<CrmTaskArtifact>)
                    }
                  />
                </Field>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Due">
                    <Input
                      value={artifact.due}
                      onChange={(e) =>
                        patch({ due: e.target.value } as Partial<CrmTaskArtifact>)
                      }
                    />
                  </Field>
                  <Field label="Priority">
                    <Input
                      value={artifact.priority ?? ""}
                      onChange={(e) =>
                        patch({
                          priority: e.target.value,
                        } as Partial<CrmTaskArtifact>)
                      }
                    />
                  </Field>
                </div>
                <Field label="Notes">
                  <Textarea
                    value={artifact.notes}
                    rows={5}
                    onChange={(e) =>
                      patch({ notes: e.target.value } as Partial<CrmTaskArtifact>)
                    }
                  />
                </Field>
              </div>
            ) : null}

            {isSlack(artifact, activeType) ? (
              <div className="space-y-3">
                <Field label="Channel">
                  <Input
                    value={artifact.channel}
                    onChange={(e) =>
                      patch({ channel: e.target.value } as Partial<SlackArtifact>)
                    }
                  />
                </Field>
                <Field label="Message">
                  <Textarea
                    value={artifact.message}
                    rows={8}
                    className="font-mono text-xs"
                    onChange={(e) =>
                      patch({ message: e.target.value } as Partial<SlackArtifact>)
                    }
                  />
                </Field>
              </div>
            ) : null}

            {sendResult ? (
              sendResult.sent ? (
                <div className="flex items-start gap-3 rounded-lg border border-primary/25 bg-primary/5 p-3">
                  <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" />
                  <div className="space-y-0.5 text-sm">
                    <p className="font-medium text-foreground">
                      {CHANNEL_NOUN[activeType]} sent
                      {sentTo(sendResult)
                        ? ` to ${sentTo(sendResult)}`
                        : ""}
                    </p>
                    {sendResult.detail ? (
                      <p className="text-muted-foreground">
                        {sendResult.detail}
                      </p>
                    ) : (
                      <p className="text-muted-foreground">
                        Delivered and logged to the audit trail.
                      </p>
                    )}
                  </div>
                </div>
              ) : isNotConfigured(sendResult.reason) ? (
                <div className="flex flex-wrap items-start gap-3 rounded-lg border border-border bg-muted/40 p-3">
                  <PlugZap className="mt-0.5 size-4 shrink-0 text-primary" />
                  <div className="min-w-0 flex-1 space-y-2 text-sm">
                    <div className="space-y-0.5">
                      <p className="font-medium text-foreground">
                        Connect {CHANNEL_NOUN[activeType]} in Settings to send
                      </p>
                      <p className="text-muted-foreground">
                        {sendResult.detail ??
                          `Your draft is saved. Add ${CHANNEL_NOUN[activeType]} credentials, then send again.`}
                      </p>
                    </div>
                    <Button asChild size="sm" variant="outline" className="gap-1.5">
                      <Link href="/settings">
                        <Settings />
                        Open Settings
                      </Link>
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="flex items-start gap-3 rounded-lg border border-destructive/25 bg-destructive/5 p-3">
                  <Send className="mt-0.5 size-4 shrink-0 text-destructive" />
                  <div className="space-y-0.5 text-sm">
                    <p className="font-medium text-destructive">
                      Could not send {CHANNEL_NOUN[activeType]}
                    </p>
                    <p className="text-muted-foreground">
                      {sendResult.detail ??
                        sendResult.reason ??
                        "The channel rejected the send. Try again or edit the draft."}
                    </p>
                  </div>
                </div>
              )
            ) : null}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            Pick an action to generate a draft you can edit and copy.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

export default ExecutePanel;
