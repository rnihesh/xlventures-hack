"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Check,
  CheckCircle2,
  Copy,
  Hash,
  ListTodo,
  Loader2,
  Mail,
  Plus,
  PlugZap,
  RefreshCw,
  Send,
  Settings,
  User,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { listContacts, type Contact } from "@/lib/api/contacts";
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

// A saved-but-not-yet-sent generated artifact for one kind. Cached in component
// state so switching tabs shows the saved draft instead of regenerating it.
interface CachedArtifact {
  artifact: Artifact;
  audit: AuditRecord;
}

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

// A removable recipient chip (a saved contact or a typed address).
function RecipientChip({
  label,
  title,
  onRemove,
}: {
  label: string;
  title?: string;
  onRemove: () => void;
}) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full border border-border bg-muted/50 py-0.5 pl-2.5 pr-1 text-xs"
      title={title}
    >
      {label}
      <button
        type="button"
        onClick={onRemove}
        className="rounded-full p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
        aria-label={`Remove ${label}`}
      >
        <X className="size-3" />
      </button>
    </span>
  );
}

function looksLikeEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());
}

export function ExecutePanel({
  recommendation,
  runId,
  accountId,
  className,
}: ExecutePanelProps) {
  const [activeType, setActiveType] = useState<ArtifactType | null>(null);
  const [pendingType, setPendingType] = useState<ArtifactType | null>(null);
  // Generated artifacts cached per kind: the first click of a kind generates
  // once, switching tabs shows the saved draft, and Regenerate re-runs it.
  const [cache, setCache] = useState<
    Partial<Record<ArtifactType, CachedArtifact>>
  >({});
  // Send outcomes cached per kind so a sent email stays "sent" after switching.
  const [sendResults, setSendResults] = useState<
    Partial<Record<ArtifactType, SendResult>>
  >({});
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  // Email recipients: any number of saved contacts plus any number of typed
  // addresses. The send fans out to all of them; empty falls back to the
  // account's own contact.
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [selectedContactIds, setSelectedContactIds] = useState<string[]>([]);
  const [customEmails, setCustomEmails] = useState<string[]>([]);
  const [emailInput, setEmailInput] = useState<string>("");

  const active = activeType ? cache[activeType] : undefined;
  const artifact = active?.artifact ?? null;
  const audit = active?.audit ?? null;
  const sendResult = (activeType ? sendResults[activeType] : null) ?? null;
  const sent = sendResult?.sent === true;

  const resolvedAccountId = accountId ?? recommendation?.account_id ?? null;

  // Load the org's contacts once so the email picker can target saved people.
  useEffect(() => {
    const ctrl = new AbortController();
    void listContacts(ctrl.signal).then(setContacts);
    return () => ctrl.abort();
  }, []);

  const selectedContacts = selectedContactIds
    .map((id) => contacts.find((c) => c.id === id))
    .filter((c): c is Contact => Boolean(c));

  // True when the user has chosen at least one explicit recipient. When false,
  // an email send falls back to the account's own contact.
  const hasExplicitRecipients =
    selectedContacts.length > 0 || customEmails.length > 0;

  function addContact(id: string) {
    if (!id) return;
    setSelectedContactIds((prev) =>
      prev.includes(id) ? prev : [...prev, id],
    );
    setSendResults((prev) => ({ ...prev, email: undefined }));
  }

  function removeContact(id: string) {
    setSelectedContactIds((prev) => prev.filter((c) => c !== id));
    setSendResults((prev) => ({ ...prev, email: undefined }));
  }

  function addEmail() {
    const value = emailInput.trim();
    if (!value) return;
    if (!looksLikeEmail(value)) {
      toast("That does not look like an email", {
        description: "Enter an address like name@company.com.",
        variant: "error",
      });
      return;
    }
    setCustomEmails((prev) =>
      prev.some((e) => e.toLowerCase() === value.toLowerCase())
        ? prev
        : [...prev, value],
    );
    setEmailInput("");
    setSendResults((prev) => ({ ...prev, email: undefined }));
  }

  function removeEmail(value: string) {
    setCustomEmails((prev) => prev.filter((e) => e !== value));
    setSendResults((prev) => ({ ...prev, email: undefined }));
  }

  // Contacts not already chosen, for the "add a saved contact" dropdown.
  const availableContacts = contacts.filter(
    (c) => !selectedContactIds.includes(c.id),
  );

  // Generate (or regenerate) the artifact for a kind. With force=false an
  // already-cached kind is just shown again (no network, no regeneration).
  async function run(type: ArtifactType, force = false) {
    setActiveType(type);
    setError(null);
    if (!force && cache[type]) return;
    setPendingType(type);
    try {
      const res = await executeAction({
        artifact_type: type,
        run_id: runId ?? undefined,
        recommendation: recommendation ?? undefined,
        account_id: resolvedAccountId ?? undefined,
      });
      setCache((prev) => ({
        ...prev,
        [type]: { artifact: res.artifact, audit: res.audit },
      }));
      // A fresh draft invalidates any prior send for this kind.
      setSendResults((prev) => ({ ...prev, [type]: undefined }));
      toast(`${TYPE_LABEL[type]} ${force ? "regenerated" : "ready"}`, {
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

  // Patch the active kind's cached artifact in place. An edit invalidates a
  // prior send so the user can re-send the revision.
  function patch(next: Partial<Artifact>) {
    if (!activeType) return;
    const type = activeType;
    setCache((prev) => {
      const cur = prev[type];
      if (!cur) return prev;
      return {
        ...prev,
        [type]: { ...cur, artifact: { ...cur.artifact, ...next } as Artifact },
      };
    });
    setSendResults((prev) => ({ ...prev, [type]: undefined }));
  }

  // Recipient(s) shown in the success line: where the artifact actually went.
  function sentTo(result: SendResult): string | null {
    if (result.to) return result.to;
    if (activeType && artifact && isSlack(artifact, activeType)) {
      return (artifact as SlackArtifact).channel;
    }
    if (activeType === "email") {
      if (selectedContacts.length || customEmails.length) {
        return [...selectedContacts.map((c) => c.email), ...customEmails].join(
          ", ",
        );
      }
      return resolvedAccountId;
    }
    return null;
  }

  // Really dispatch the (possibly edited) artifact through its channel. The
  // human stays in the loop: this only runs on an explicit click, and the
  // result is rendered inline (success or connect-in-settings), never a throw.
  async function send() {
    if (!artifact || !activeType || sending) return;
    const type = activeType;
    setSending(true);
    setError(null);
    const action = recommendation?.action;
    try {
      const result = await sendArtifact({
        artifact_type: type,
        artifact,
        run_id: runId ?? undefined,
        account_id: resolvedAccountId ?? undefined,
        recommendation_id: recommendation?.id ?? undefined,
        action_key: action?.key ?? undefined,
        // For email, target the chosen saved contacts and/or typed addresses.
        // Omitted when none are set, so the backend falls back to the account.
        contact_ids:
          type === "email" && selectedContactIds.length
            ? selectedContactIds
            : undefined,
        recipients:
          type === "email" && customEmails.length ? customEmails : undefined,
      });
      setSendResults((prev) => ({ ...prev, [type]: result }));
      if (result.sent) {
        const where = sentTo(result);
        toast(`${TYPE_LABEL[type]} sent`, {
          description: where
            ? `Delivered to ${where}.`
            : "Delivered successfully.",
          variant: "success",
        });
      } else {
        toast(`${CHANNEL_NOUN[type]} not connected`, {
          description: "Connect it in Settings, then send again.",
          variant: "info",
        });
      }
    } finally {
      setSending(false);
    }
  }

  const regenerating = pendingType !== null && pendingType === activeType;

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
            const isCached = Boolean(cache[type]);
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
                ) : isCached ? (
                  <Check className={isActive ? "" : "text-primary"} />
                ) : (
                  <Icon />
                )}
                {label}
              </Button>
            );
          })}
        </div>

        {error ? <p className="text-sm text-destructive">{error}</p> : null}

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
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => run(activeType, true)}
                  disabled={pendingType !== null}
                  className="gap-1.5"
                >
                  {regenerating ? (
                    <Loader2 className="animate-spin" />
                  ) : (
                    <RefreshCw />
                  )}
                  Regenerate
                </Button>
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
                <Field label="Recipients">
                  <div className="space-y-2">
                    {hasExplicitRecipients ? (
                      <div className="flex flex-wrap gap-1.5">
                        {selectedContacts.map((c) => (
                          <RecipientChip
                            key={c.id}
                            label={c.name}
                            title={c.email}
                            onRemove={() => removeContact(c.id)}
                          />
                        ))}
                        {customEmails.map((e) => (
                          <RecipientChip
                            key={e}
                            label={e}
                            onRemove={() => removeEmail(e)}
                          />
                        ))}
                      </div>
                    ) : null}
                    <div className="flex flex-wrap items-center gap-2">
                      {availableContacts.length > 0 ? (
                        <Select
                          value=""
                          onChange={(e) => addContact(e.target.value)}
                          className="w-auto min-w-44"
                        >
                          <option value="">Add a saved contact...</option>
                          {availableContacts.map((c) => (
                            <option key={c.id} value={c.id}>
                              {c.name} ({c.email})
                            </option>
                          ))}
                        </Select>
                      ) : null}
                      <div className="flex items-center gap-1.5">
                        <Input
                          type="email"
                          value={emailInput}
                          placeholder="name@company.com"
                          onChange={(e) => setEmailInput(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              e.preventDefault();
                              addEmail();
                            }
                          }}
                          className="w-52"
                        />
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={addEmail}
                          disabled={!emailInput.trim()}
                          className="gap-1.5"
                        >
                          <Plus />
                          Add
                        </Button>
                      </div>
                    </div>
                  </div>
                </Field>
                <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <User className="size-3.5" />
                  {hasExplicitRecipients
                    ? `Will send to ${
                        selectedContacts.length + customEmails.length
                      } recipient${
                        selectedContacts.length + customEmails.length === 1
                          ? ""
                          : "s"
                      }`
                    : resolvedAccountId
                      ? `Will send to this account's contact (${resolvedAccountId})`
                      : "Will send to this account's contact"}
                </p>
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
                      {sentTo(sendResult) ? ` to ${sentTo(sendResult)}` : ""}
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
