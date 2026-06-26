"use client";

import { useState } from "react";
import {
  Check,
  Copy,
  Hash,
  ListTodo,
  Loader2,
  Mail,
  Send,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";
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
  type Artifact,
  type ArtifactType,
  type AuditRecord,
  type CrmTaskArtifact,
  type EmailArtifact,
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
      {copied ? <Check className="text-emerald-500" /> : <Copy />}
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

  const resolvedAccountId =
    accountId ?? recommendation?.account_id ?? null;

  async function run(type: ArtifactType) {
    setPendingType(type);
    setError(null);
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
          <p className="text-sm text-rose-600 dark:text-rose-400">{error}</p>
        ) : null}

        {artifact && activeType ? (
          <>
            <Separator />
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold">
                  {TYPE_LABEL[activeType]}
                </span>
                <Badge variant="outline">Editable preview</Badge>
              </div>
              <CopyButton text={copyText()} />
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
          </>
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
