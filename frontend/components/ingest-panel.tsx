"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  CheckCircle2,
  FileUp,
  Globe,
  Loader2,
  Sparkles,
  Upload,
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
import { getAccounts } from "@/lib/api";
import type { Account } from "@/lib/types";
import {
  DEFAULT_SOURCES,
  getIngestSources,
  ingestText,
  ingestWeb,
  type IngestResponse,
  type IngestSource,
} from "@/lib/api/ingest";

// Native select styled to match the Input / Textarea controls (grayscale, with
// the shared orange focus ring). Kept local so the panel needs no new ui primitive.
const SELECT_CLASS =
  "flex h-10 w-full cursor-pointer appearance-none rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50";

interface DoneImport {
  title: string;
  source_type: string;
  chunks: number;
  account_id: string | null;
  persisted: string;
  ts: number;
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-eyebrow">{label}</span>
      {children}
      {hint ? (
        <span className="text-[11px] leading-snug text-muted-foreground">
          {hint}
        </span>
      ) : null}
    </label>
  );
}

export function IngestPanel() {
  const [sources, setSources] = useState<IngestSource[]>(DEFAULT_SOURCES);
  const [accounts, setAccounts] = useState<Account[]>([]);

  const [text, setText] = useState("");
  const [sourceType, setSourceType] = useState("meeting_notes");
  const [title, setTitle] = useState("");
  const [accountId, setAccountId] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const [webQuery, setWebQuery] = useState("");
  const [webBusy, setWebBusy] = useState(false);

  const [done, setDone] = useState<DoneImport[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    void getIngestSources(ctrl.signal).then(setSources);
    void getAccounts(ctrl.signal)
      .then((a) => setAccounts(Array.isArray(a) ? a : []))
      .catch(() => setAccounts([]));
    return () => ctrl.abort();
  }, []);

  const domain = useMemo(() => {
    const acc = accounts.find((a) => a.account_id === accountId);
    return acc?.domain ?? "customer_success";
  }, [accounts, accountId]);

  const charCount = text.trim().length;
  const canSubmit = charCount > 0 && !submitting;

  const record = (res: IngestResponse) =>
    setDone((prev) =>
      [
        {
          title: res.title,
          source_type: res.source_type,
          chunks: res.chunks_written,
          account_id: res.account_id,
          persisted: res.persisted,
          ts: Date.now(),
        },
        ...prev,
      ].slice(0, 6),
    );

  async function onImport() {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      const res = await ingestText({
        text,
        source_type: sourceType,
        title: title.trim() || null,
        account_id: accountId || null,
        domain,
      });
      record(res);
      toast("Imported into the corpus", {
        description: `${res.chunks_written} chunk${
          res.chunks_written === 1 ? "" : "s"
        } indexed, retrievable in the next run.`,
        variant: "success",
      });
      setText("");
      setTitle("");
    } catch (err) {
      toast("Import failed", {
        description: err instanceof Error ? err.message : "Unknown error",
        variant: "error",
      });
    } finally {
      setSubmitting(false);
    }
  }

  async function onFile(file: File) {
    try {
      const content = await file.text();
      setText(content);
      if (!title.trim()) setTitle(file.name.replace(/\.[^.]+$/, ""));
      if (/\.csv$/i.test(file.name)) setSourceType("crm_record");
      toast("File loaded", {
        description: `${file.name} ready to import (${content.trim().length} chars).`,
        variant: "info",
      });
    } catch {
      toast("Could not read that file", { variant: "error" });
    }
  }

  async function onWebSearch() {
    const q = webQuery.trim();
    if (!q || webBusy) return;
    setWebBusy(true);
    try {
      const res = await ingestWeb({
        query: q,
        account_id: accountId || null,
        domain,
      });
      if (res.ok) {
        record(res);
        toast("Web context ingested", {
          description: `${res.chunks_written} chunk${
            res.chunks_written === 1 ? "" : "s"
          } from live search.`,
          variant: "success",
        });
        setWebQuery("");
      } else {
        toast("No web context added", {
          description: res.detail || "Search unavailable or no results.",
          variant: "info",
        });
      }
    } finally {
      setWebBusy(false);
    }
  }

  const activeSource = sources.find((s) => s.key === sourceType);

  return (
    <div className="grid gap-6 lg:grid-cols-[1.6fr_1fr]">
      {/* Primary: paste / upload import */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-lg">
            <Upload className="h-5 w-5 text-primary" />
            Import an interaction
          </CardTitle>
          <CardDescription>
            Paste a meeting note, transcript, email, or CSV of CRM rows. It is
            chunked, embedded, and indexed so the engine can cite it on the next
            run.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <Field
            label="Interaction text"
            hint={
              activeSource
                ? `${activeSource.description} ${charCount} characters.`
                : `${charCount} characters.`
            }
          >
            <Textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={
                "Paste here, for example:\n\nQBR with the champion. Adoption of the analytics module stalled, two power users left, and they are evaluating a competitor before renewal..."
              }
              className="min-h-[220px] font-sans leading-relaxed"
            />
          </Field>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Source type">
              <div className="relative">
                <select
                  value={sourceType}
                  onChange={(e) => setSourceType(e.target.value)}
                  className={SELECT_CLASS}
                >
                  {sources.map((s) => (
                    <option key={s.key} value={s.key}>
                      {s.label}
                    </option>
                  ))}
                </select>
                <ChevronDown />
              </div>
            </Field>

            <Field label="Account" hint="Optional. Scopes the evidence to one account.">
              <div className="relative">
                <select
                  value={accountId}
                  onChange={(e) => setAccountId(e.target.value)}
                  className={SELECT_CLASS}
                >
                  <option value="">Shared knowledge (no account)</option>
                  {accounts.map((a) => (
                    <option key={a.account_id} value={a.account_id}>
                      {a.name}
                    </option>
                  ))}
                </select>
                <ChevronDown />
              </div>
            </Field>
          </div>

          <Field label="Title" hint="Optional. A label for this import.">
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Zephyr Dynamics QBR, 26 Jun"
            />
          </Field>

          <div className="flex flex-wrap items-center gap-3 pt-1">
            <Button onClick={onImport} disabled={!canSubmit}>
              {submitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="h-4 w-4" />
              )}
              {submitting ? "Importing" : "Import to corpus"}
            </Button>

            <input
              ref={fileRef}
              type="file"
              accept=".txt,.md,.csv,.tsv,.eml,.json,.log,text/*"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void onFile(f);
                e.target.value = "";
              }}
            />
            <Button
              type="button"
              variant="outline"
              onClick={() => fileRef.current?.click()}
            >
              <FileUp className="h-4 w-4" />
              Load a file
            </Button>

            <span className="text-[11px] text-muted-foreground">
              {domain.replace(/_/g, " ")}
            </span>
          </div>
        </CardContent>
      </Card>

      {/* Side rail: optional web search + recent imports */}
      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Globe className="h-4 w-4 text-primary" />
              Live web context
            </CardTitle>
            <CardDescription>
              Optional. Pulls public context for a topic and ingests it as web
              evidence. Degrades gracefully when offline.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Input
              value={webQuery}
              onChange={(e) => setWebQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void onWebSearch();
              }}
              placeholder="e.g. Acme Corp layoffs 2026"
            />
            <Button
              type="button"
              variant="secondary"
              className="w-full"
              onClick={onWebSearch}
              disabled={!webQuery.trim() || webBusy}
            >
              {webBusy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Globe className="h-4 w-4" />
              )}
              {webBusy ? "Searching" : "Search and ingest"}
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Recent imports</CardTitle>
            <CardDescription>
              This session. Each import is live in the retrieval corpus.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {done.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">
                Nothing imported yet.
              </p>
            ) : (
              <ul className="space-y-2.5">
                {done.map((d) => (
                  <li
                    key={d.ts}
                    className="flex items-start gap-2.5 rounded-md border border-border bg-card px-3 py-2.5"
                  >
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-sm font-medium">
                          {d.title}
                        </span>
                        <Badge variant="secondary" className="shrink-0">
                          {d.chunks} chunk{d.chunks === 1 ? "" : "s"}
                        </Badge>
                      </div>
                      <div className="mt-0.5 text-[11px] text-muted-foreground">
                        {d.source_type.replace(/_/g, " ")}
                        {d.account_id ? ` · ${d.account_id}` : " · shared"}
                        {" · "}
                        <span
                          className={cn(
                            d.persisted.includes("pgvector") && "text-primary",
                          )}
                        >
                          {d.persisted.includes("pgvector")
                            ? "pgvector + memory"
                            : "in-memory"}
                        </span>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

// Small chevron overlaid on the native selects (they are appearance-none).
function ChevronDown() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 16 16"
      className="pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
    >
      <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default IngestPanel;
