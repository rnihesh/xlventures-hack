"use client";

import { useEffect, useState } from "react";
import { Check, Copy, Mail, MessageSquare, Pencil, SquareCheck } from "lucide-react";

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import type { Artifact } from "@/lib/types";

// ---------------------------------------------------------------------------
// ArtifactPreview
//
// Renders a generated action artifact (customer email, CRM follow-up task, or
// Slack message) in an editable card with a copy-to-clipboard control. Works
// fully offline: copy falls back to a hidden textarea + execCommand when the
// async clipboard API is unavailable (insecure origin, older browser).
//
// Controlled or uncontrolled: pass `onChange` to lift edits into a parent, or
// omit it to let the card manage its own draft state.
// ---------------------------------------------------------------------------

const KIND_META: Record<
  Artifact["kind"],
  { label: string; icon: typeof Mail; tone: "info" | "success" | "secondary" }
> = {
  email: { label: "Email", icon: Mail, tone: "info" },
  crm_task: { label: "CRM task", icon: SquareCheck, tone: "success" },
  slack: { label: "Slack message", icon: MessageSquare, tone: "secondary" },
};

// Render an artifact as a plain-text block suitable for the clipboard.
function artifactToText(artifact: Artifact): string {
  switch (artifact.kind) {
    case "email": {
      const lines: string[] = [];
      if (artifact.to) lines.push(`To: ${artifact.to}`);
      if (artifact.cc) lines.push(`Cc: ${artifact.cc}`);
      lines.push(`Subject: ${artifact.subject}`);
      lines.push("");
      lines.push(artifact.body);
      return lines.join("\n");
    }
    case "crm_task": {
      const lines: string[] = [`Task: ${artifact.title}`];
      if (artifact.assignee) lines.push(`Assignee: ${artifact.assignee}`);
      if (artifact.due_date) lines.push(`Due: ${artifact.due_date}`);
      if (artifact.priority) lines.push(`Priority: ${artifact.priority}`);
      lines.push("");
      lines.push(artifact.description);
      return lines.join("\n");
    }
    case "slack": {
      const prefix = artifact.channel ? `${artifact.channel}\n` : "";
      return `${prefix}${artifact.message}`;
    }
    default:
      return "";
  }
}

// Best-effort clipboard write that degrades gracefully offline / on http.
async function copyText(text: string): Promise<boolean> {
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // fall through to the legacy path
  }
  if (typeof document === "undefined") return false;
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

interface FieldProps {
  label: string;
  children: React.ReactNode;
}

function Field({ label, children }: FieldProps) {
  return (
    <label className="block space-y-1.5">
      <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70">
        {label}
      </span>
      {children}
    </label>
  );
}

export interface ArtifactPreviewProps {
  artifact: Artifact;
  // When provided the component is controlled: edits are reported here.
  onChange?: (next: Artifact) => void;
  // Toggle inline editing. Read-only mode still allows copy-to-clipboard.
  editable?: boolean;
  className?: string;
}

export function ArtifactPreview({
  artifact,
  onChange,
  editable = true,
  className,
}: ArtifactPreviewProps) {
  // Local draft so the card works uncontrolled; kept in sync when the incoming
  // artifact reference changes (e.g. a fresh recommendation).
  const [draft, setDraft] = useState<Artifact>(artifact);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    setDraft(artifact);
  }, [artifact]);

  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1600);
    return () => clearTimeout(t);
  }, [copied]);

  function update(patch: Partial<Artifact>) {
    // The patch always targets the current kind, so the union stays valid.
    const next = { ...draft, ...patch } as Artifact;
    setDraft(next);
    onChange?.(next);
  }

  async function onCopy() {
    const ok = await copyText(artifactToText(draft));
    if (ok) setCopied(true);
  }

  const meta = KIND_META[draft.kind];
  const Icon = meta.icon;

  return (
    <Card className={cn("overflow-hidden", className)}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-sm font-semibold tracking-tight">
            <Icon className="h-4 w-4 text-muted-foreground" />
            {meta.label}
            <Badge variant={meta.tone} className="font-normal">
              draft
            </Badge>
          </CardTitle>
          <div className="flex items-center gap-2">
            {editable && (
              <span className="flex items-center gap-1 text-[10px] uppercase tracking-wide text-muted-foreground/60">
                <Pencil className="h-3 w-3" />
                editable
              </span>
            )}
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={onCopy}
              aria-label="Copy to clipboard"
              className="h-8 px-2.5"
            >
              {copied ? (
                <Check className="h-3.5 w-3.5 text-emerald-500" />
              ) : (
                <Copy className="h-3.5 w-3.5" />
              )}
              <span className="text-xs">{copied ? "Copied" : "Copy"}</span>
            </Button>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-3">
        {draft.kind === "email" && (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="To">
                <Input
                  value={draft.to ?? ""}
                  readOnly={!editable}
                  placeholder="recipient@account.com"
                  onChange={(e) => update({ to: e.target.value })}
                />
              </Field>
              <Field label="Cc">
                <Input
                  value={draft.cc ?? ""}
                  readOnly={!editable}
                  placeholder="optional"
                  onChange={(e) => update({ cc: e.target.value })}
                />
              </Field>
            </div>
            <Field label="Subject">
              <Input
                value={draft.subject}
                readOnly={!editable}
                onChange={(e) => update({ subject: e.target.value })}
              />
            </Field>
            <Field label="Body">
              <Textarea
                value={draft.body}
                readOnly={!editable}
                rows={8}
                className="min-h-[160px] resize-y font-sans leading-relaxed"
                onChange={(e) => update({ body: e.target.value })}
              />
            </Field>
          </>
        )}

        {draft.kind === "crm_task" && (
          <>
            <Field label="Title">
              <Input
                value={draft.title}
                readOnly={!editable}
                onChange={(e) => update({ title: e.target.value })}
              />
            </Field>
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Assignee">
                <Input
                  value={draft.assignee ?? ""}
                  readOnly={!editable}
                  placeholder="owner"
                  onChange={(e) => update({ assignee: e.target.value })}
                />
              </Field>
              <Field label="Due date">
                <Input
                  type="date"
                  value={draft.due_date ?? ""}
                  readOnly={!editable}
                  onChange={(e) => update({ due_date: e.target.value })}
                />
              </Field>
              <Field label="Priority">
                <Input
                  value={draft.priority ?? ""}
                  readOnly={!editable}
                  placeholder="medium"
                  onChange={(e) => update({ priority: e.target.value })}
                />
              </Field>
            </div>
            <Field label="Description">
              <Textarea
                value={draft.description}
                readOnly={!editable}
                rows={6}
                className="min-h-[120px] resize-y leading-relaxed"
                onChange={(e) => update({ description: e.target.value })}
              />
            </Field>
          </>
        )}

        {draft.kind === "slack" && (
          <>
            <Field label="Channel">
              <Input
                value={draft.channel ?? ""}
                readOnly={!editable}
                placeholder="#account-team"
                className="font-mono text-[13px]"
                onChange={(e) => update({ channel: e.target.value })}
              />
            </Field>
            <Field label="Message">
              <Textarea
                value={draft.message}
                readOnly={!editable}
                rows={6}
                className="min-h-[120px] resize-y leading-relaxed"
                onChange={(e) => update({ message: e.target.value })}
              />
            </Field>
          </>
        )}
      </CardContent>
    </Card>
  );
}

export default ArtifactPreview;
