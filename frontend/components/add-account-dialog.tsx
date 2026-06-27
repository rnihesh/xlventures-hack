"use client";

// Add-account experience: a self-contained modal form to create an account in
// the caller's org. No external dialog dependency (works offline), grayscale +
// Claude orange, Geist. On submit it POSTs /accounts, then either routes to the
// new account 360 or hands the created account back to the caller to refresh.

import * as React from "react";
import { useRouter } from "next/navigation";
import { FileUp, Loader2, Plus, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";
import { getDomains } from "@/lib/api";
import { createAccount, type AccountInput } from "@/lib/api/accounts-admin";
import { ingestText } from "@/lib/api/ingest";

// Tag an attached context file by its name so a batch (crm-notes, transcript,
// email) is categorised sensibly. Falls back to a generic document.
// Returns a recognized backend source-type key (see ingest SOURCE_TYPES) so the
// 360 renders the right label instead of falling back to a generic "Document".
function guessSource(name: string): string {
  const n = name.toLowerCase();
  if (/\.csv$|\.tsv$/.test(n)) return "crm_record";
  if (/\.eml$/.test(n) || n.includes("email")) return "email";
  if (n.includes("transcript") || n.includes("call")) return "call_transcript";
  if (n.includes("crm") || n.includes("note")) return "crm_record";
  if (n.includes("chat") || n.includes("slack")) return "chat_message";
  return "document";
}
import type { Account, DomainSummary } from "@/lib/types";

const RISK_LEVELS = ["critical", "high", "medium", "low"] as const;
const SEGMENTS = ["Enterprise", "Mid-Market", "SMB", "Startup"] as const;

const FALLBACK_DOMAINS: { key: string; label: string }[] = [
  { key: "customer_success", label: "Customer Success" },
  { key: "saas_sales", label: "SaaS Sales" },
  { key: "collections", label: "Collections" },
];

export interface AddAccountDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  // When provided, the dialog calls this with the created account and closes,
  // letting the caller refresh in place. Otherwise it routes to the new 360.
  onCreated?: (account: Account) => void;
}

function Field({
  label,
  htmlFor,
  hint,
  children,
}: {
  label: string;
  htmlFor: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label
        htmlFor={htmlFor}
        className="block text-xs font-medium text-foreground"
      >
        {label}
      </label>
      {children}
      {hint ? (
        <p className="text-[11px] text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  );
}

export function AddAccountDialog({
  open,
  onOpenChange,
  onCreated,
}: AddAccountDialogProps) {
  const router = useRouter();
  const [domains, setDomains] = React.useState<DomainSummary[] | null>(null);
  const [submitting, setSubmitting] = React.useState(false);

  const [name, setName] = React.useState("");
  const [domain, setDomain] = React.useState("customer_success");
  const [industry, setIndustry] = React.useState("");
  const [segment, setSegment] = React.useState("Enterprise");
  const [arr, setArr] = React.useState("");
  const [health, setHealth] = React.useState(60);
  const [risk, setRisk] = React.useState("medium");
  const [owner, setOwner] = React.useState("");
  const [renewal, setRenewal] = React.useState("");
  const [signals, setSignals] = React.useState("");
  const [notes, setNotes] = React.useState("");
  const [files, setFiles] = React.useState<File[]>([]);
  const fileRef = React.useRef<HTMLInputElement>(null);

  // Load domains once when the dialog first opens, for the domain select.
  React.useEffect(() => {
    if (!open || domains !== null) return;
    const ctrl = new AbortController();
    void getDomains(ctrl.signal)
      .then(setDomains)
      .catch(() => setDomains([]));
    return () => ctrl.abort();
  }, [open, domains]);

  // Close on Escape and lock body scroll while the modal is open.
  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onOpenChange(false);
    };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onOpenChange]);

  function reset() {
    setName("");
    setDomain("customer_success");
    setIndustry("");
    setSegment("Enterprise");
    setArr("");
    setHealth(60);
    setRisk("medium");
    setOwner("");
    setRenewal("");
    setSignals("");
    setNotes("");
    setFiles([]);
  }

  const domainOptions = React.useMemo(() => {
    if (domains && domains.length > 0) {
      return domains.map((d) => ({ key: d.key, label: d.display_name }));
    }
    return FALLBACK_DOMAINS;
  }, [domains]);

  function addFiles(list: FileList | null) {
    const incoming = Array.from(list ?? []);
    if (!incoming.length) return;
    setFiles((prev) => {
      const seen = new Set(prev.map((f) => `${f.name}:${f.size}`));
      return [...prev, ...incoming.filter((f) => !seen.has(`${f.name}:${f.size}`))];
    });
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting) return;
    if (!name.trim()) {
      toast("Account name is required", { variant: "error" });
      return;
    }

    const payload: AccountInput = {
      name: name.trim(),
      domain,
      industry: industry.trim() || undefined,
      segment: segment.trim() || undefined,
      arr: arr.trim() ? Number(arr) : undefined,
      health_score: health,
      risk_level: risk,
      owner: owner.trim() || undefined,
      renewal_date: renewal || undefined,
      signals: signals
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      notes: notes.trim() || undefined,
    };

    setSubmitting(true);
    try {
      const account = await createAccount(payload);
      // Attach any dropped/picked context files as evidence for this account.
      let ingested = 0;
      for (const f of files) {
        try {
          const content = (await f.text()).trim();
          if (!content) continue;
          await ingestText({
            text: content,
            source_type: guessSource(f.name),
            title: f.name.replace(/\.[^.]+$/, ""),
            account_id: account.account_id,
            domain,
          });
          ingested += 1;
        } catch {
          /* best effort: account is created either way */
        }
      }
      toast(`Added ${account.name}`, {
        variant: "success",
        description: ingested
          ? `${ingested} context file${ingested === 1 ? "" : "s"} attached as evidence.`
          : "The account is now in your inbox.",
      });
      reset();
      onOpenChange(false);
      if (onCreated) {
        onCreated(account);
      } else {
        router.push(`/accounts/${encodeURIComponent(account.account_id)}`);
      }
    } catch {
      toast("Could not create the account", {
        variant: "error",
        description: "Check your connection and try again.",
      });
    } finally {
      setSubmitting(false);
    }
  }

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 p-4 backdrop-blur-sm"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onOpenChange(false);
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-account-title"
        className="flex max-h-[90vh] w-full max-w-lg flex-col overflow-hidden rounded-xl border border-border bg-card shadow-lg"
      >
        <div className="flex shrink-0 items-start justify-between gap-4 border-b border-border px-5 py-4">
          <div>
            <div className="text-eyebrow">New account</div>
            <h2
              id="add-account-title"
              className="mt-0.5 text-lg font-semibold text-foreground"
            >
              Add an account
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Capture the basics and any context. Notes are ingested as evidence
              for the next best action.
            </p>
          </div>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            aria-label="Close"
            className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={onSubmit} className="flex min-h-0 flex-1 flex-col">
          <div className="flex-1 space-y-4 overflow-y-auto px-5 py-5">
          <Field label="Account name" htmlFor="acc-name">
            <Input
              id="acc-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Northwind Labs"
              autoFocus
              required
            />
          </Field>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Domain" htmlFor="acc-domain">
              <Select
                id="acc-domain"
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
              >
                {domainOptions.map((d) => (
                  <option key={d.key} value={d.key}>
                    {d.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Industry" htmlFor="acc-industry">
              <Input
                id="acc-industry"
                value={industry}
                onChange={(e) => setIndustry(e.target.value)}
                placeholder="Manufacturing"
              />
            </Field>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Segment" htmlFor="acc-segment">
              <Select
                id="acc-segment"
                value={segment}
                onChange={(e) => setSegment(e.target.value)}
              >
                {SEGMENTS.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="ARR (USD)" htmlFor="acc-arr">
              <Input
                id="acc-arr"
                type="number"
                min={0}
                step={1000}
                inputMode="numeric"
                value={arr}
                onChange={(e) => setArr(e.target.value)}
                placeholder="180000"
              />
            </Field>
          </div>

          <Field
            label={`Health score: ${health}`}
            htmlFor="acc-health"
            hint="0 is critical, 100 is thriving."
          >
            <input
              id="acc-health"
              type="range"
              min={0}
              max={100}
              value={health}
              onChange={(e) => setHealth(Number(e.target.value))}
              className="h-2 w-full cursor-pointer appearance-none rounded-full bg-muted accent-primary"
            />
          </Field>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Risk level" htmlFor="acc-risk">
              <Select
                id="acc-risk"
                value={risk}
                onChange={(e) => setRisk(e.target.value)}
              >
                {RISK_LEVELS.map((r) => (
                  <option key={r} value={r} className="capitalize">
                    {r}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Renewal date" htmlFor="acc-renewal">
              <Input
                id="acc-renewal"
                type="date"
                value={renewal}
                onChange={(e) => setRenewal(e.target.value)}
              />
            </Field>
          </div>

          <Field label="Owner (CSM)" htmlFor="acc-owner">
            <Input
              id="acc-owner"
              value={owner}
              onChange={(e) => setOwner(e.target.value)}
              placeholder="J. Okafor"
            />
          </Field>

          <Field
            label="Signals"
            htmlFor="acc-signals"
            hint="Comma separated, e.g. support ticket spike, QBR skipped."
          >
            <Input
              id="acc-signals"
              value={signals}
              onChange={(e) => setSignals(e.target.value)}
              placeholder="support ticket spike, usage decline"
            />
          </Field>

          <Field
            label="Notes / context"
            htmlFor="acc-notes"
            hint="Pasted notes, transcript, or context. Ingested as evidence."
          >
            <Textarea
              id="acc-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Last QBR was cancelled. Champion flagged budget pressure for next renewal."
              rows={4}
            />
          </Field>

          <Field
            label="Attach context files"
            htmlFor="acc-files"
            hint="Drop or pick files (CRM notes, transcript, email). The type is detected automatically and each is ingested as evidence for this account."
          >
            <div
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                addFiles(e.dataTransfer.files);
              }}
              onClick={() => fileRef.current?.click()}
              className="flex cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed border-border bg-muted/30 px-4 py-6 text-center transition-colors hover:border-primary/50 hover:bg-muted/50"
            >
              <FileUp className="h-5 w-5 text-muted-foreground" aria-hidden />
              <p className="mt-2 text-sm text-foreground">
                Drop files here or click to browse
              </p>
              <p className="text-xs text-muted-foreground">
                .txt .md .csv .eml .json, multiple allowed
              </p>
              <input
                id="acc-files"
                ref={fileRef}
                type="file"
                multiple
                accept=".txt,.md,.csv,.tsv,.eml,.json,.log,text/*"
                className="hidden"
                onChange={(e) => {
                  addFiles(e.target.files);
                  e.target.value = "";
                }}
              />
            </div>
            {files.length > 0 ? (
              <ul className="mt-2 space-y-1">
                {files.map((f, i) => (
                  <li
                    key={`${f.name}-${i}`}
                    className="flex items-center justify-between rounded-md bg-muted/40 px-2.5 py-1.5 text-xs"
                  >
                    <span className="truncate">
                      {f.name}{" "}
                      <span className="text-muted-foreground">
                        ({guessSource(f.name).replace(/_/g, " ")})
                      </span>
                    </span>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setFiles((p) => p.filter((_, idx) => idx !== i));
                      }}
                      className="ml-2 shrink-0 text-muted-foreground hover:text-foreground"
                      aria-label={`Remove ${f.name}`}
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </Field>

          </div>
          <div className="flex shrink-0 items-center justify-end gap-2 border-t border-border bg-card px-5 py-4">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={submitting}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Plus className="h-4 w-4" />
              )}
              Add account
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

// Convenience trigger that owns its open state. Drop it into any header or
// empty state; pass `onCreated` to refresh the surrounding list in place.
export interface AddAccountButtonProps {
  onCreated?: (account: Account) => void;
  variant?: "default" | "outline" | "secondary";
  size?: "default" | "sm";
  className?: string;
  label?: string;
}

export function AddAccountButton({
  onCreated,
  variant = "default",
  size = "default",
  className,
  label = "Add account",
}: AddAccountButtonProps) {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <Button
        type="button"
        variant={variant}
        size={size}
        className={cn(className)}
        onClick={() => setOpen(true)}
      >
        <Plus className="h-4 w-4" />
        {label}
      </Button>
      <AddAccountDialog
        open={open}
        onOpenChange={setOpen}
        onCreated={onCreated}
      />
    </>
  );
}

export default AddAccountDialog;
