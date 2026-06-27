"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  CheckCircle2,
  FileUp,
  Globe,
  Loader2,
  Sparkles,
  Upload,
  Wand2,
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
  exampleForSource,
  getIngestSources,
  getRecentIngests,
  ingestText,
  ingestWeb,
  type ExtractedSignal,
  type IngestResponse,
  type IngestSource,
  type RecentIngest,
} from "@/lib/api/ingest";

// Native select styled to match the Input / Textarea controls (grayscale, with
// the shared orange focus ring). Kept local so the panel needs no new ui primitive.
const SELECT_CLASS =
  "flex h-10 w-full cursor-pointer appearance-none rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50";

// Categories that read as risk get the destructive accent; everything else uses
// the neutral secondary chip. Keeps the palette grayscale + Claude orange.
const RISK_CATEGORIES = new Set(["churn_risk", "competitor", "support", "pricing"]);

function signalVariant(category: string): "danger" | "secondary" {
  return RISK_CATEGORIES.has(category) ? "danger" : "secondary";
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
  // The source type is auto-detected from the text/file. Stays auto until the
  // user manually overrides it, so they never have to think about it.
  const [sourceAuto, setSourceAuto] = useState(true);
  const [title, setTitle] = useState("");
  const [accountId, setAccountId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);

  const [webQuery, setWebQuery] = useState("");
  const [webBusy, setWebBusy] = useState(false);

  const [lastResult, setLastResult] = useState<IngestResponse | null>(null);
  const [recent, setRecent] = useState<RecentIngest[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);

  const refreshRecent = useCallback((signal?: AbortSignal) => {
    void getRecentIngests(signal).then((items) => setRecent(items));
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    void getIngestSources(ctrl.signal).then(setSources);
    void getAccounts(ctrl.signal)
      .then((a) => setAccounts(Array.isArray(a) ? a : []))
      .catch(() => setAccounts([]));
    refreshRecent(ctrl.signal);
    return () => ctrl.abort();
  }, [refreshRecent]);

  const accountName = useCallback(
    (id: string | null | undefined) => {
      if (!id) return null;
      return accounts.find((a) => a.account_id === id)?.name ?? id;
    },
    [accounts],
  );

  const domain = useMemo(() => {
    const acc = accounts.find((a) => a.account_id === accountId);
    return acc?.domain ?? "customer_success";
  }, [accounts, accountId]);

  const charCount = text.trim().length;
  const canSubmit = charCount > 0 && !submitting;

  // Deep link into a fresh NBA run for the just-ingested account, prefilled with
  // the strongest extracted signal so the engine grounds on the new evidence.
  const nbaHref = useMemo(() => {
    if (!lastResult) return null;
    const params = new URLSearchParams();
    if (lastResult.account_id) params.set("account_id", lastResult.account_id);
    params.set("domain", lastResult.domain || "customer_success");
    const signal =
      lastResult.extracted_signals[0]?.text || lastResult.title || "";
    if (signal) params.set("signal", signal);
    return `/run?${params.toString()}`;
  }, [lastResult]);

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
      setLastResult(res);
      refreshRecent();
      toast(res.duplicate ? "Already in the corpus" : "Imported into the corpus", {
        description: res.duplicate
          ? "This exact interaction was ingested before, so it was not duplicated."
          : `${res.chunks_written} chunk${
              res.chunks_written === 1 ? "" : "s"
            } indexed, ${res.extracted_signals.length} signal${
              res.extracted_signals.length === 1 ? "" : "s"
            } extracted.`,
        variant: res.duplicate ? "info" : "success",
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

  function onUseExample() {
    setText(exampleForSource(sourceType));
    toast("Example loaded", {
      description: "Edit it or import as is to see the extracted signals.",
      variant: "info",
    });
  }

  async function onFile(file: File) {
    try {
      const content = await file.text();
      setText(content);
      if (!title.trim()) setTitle(file.name.replace(/\.[^.]+$/, ""));
      const detected = detectSource(file.name, content);
      setSourceType(detected);
      toast("File loaded", {
        description: `${file.name} detected as ${detected.replace(/_/g, " ")} (${content.trim().length} chars).`,
        variant: "info",
      });
    } catch {
      toast("Could not read that file", { variant: "error" });
    }
  }

  // Detect the source type from the file's NAME and CONTENT so the user does not
  // have to label anything: email headers, a transcript's speaker turns, CSV
  // rows, or CRM note structure are recognised automatically.
  function detectSource(name: string, content: string): string {
    const n = name.toLowerCase();
    const head = content.slice(0, 800);
    const low = head.toLowerCase();
    const lines = head.split("\n");
    const speakerLines = lines.filter((l) => /^\s*[A-Za-z][\w .'-]{0,24}:\s+\S/.test(l)).length;

    if (/\.csv$|\.tsv$/.test(n)) return "crm_record";
    if (/\.eml$/.test(n)) return "email";
    // Content first (the name is often generic or absent).
    if (/^\s*(from|to|subject|sent|cc)\s*:/im.test(head) || low.includes(" wrote:")) return "email";
    if (low.includes("transcript") || low.includes("attendees") || speakerLines >= 3) return "call_transcript";
    if (low.includes("crm ") || low.includes("account notes") || low.includes("timeline of") || low.includes("account id")) return "crm_record";
    if (low.includes("chat log") || low.includes("slack")) return "chat_message";
    // Name hints as a fallback.
    if (n.includes("transcript") || n.includes("call")) return "call_transcript";
    if (n.includes("email") || n.includes("mail")) return "email";
    if (n.includes("crm") || n.includes("note")) return "crm_record";
    if (n.includes("chat")) return "chat_message";
    return sourceType;
  }

  // Ingest several files at once, each as its own citeable evidence document
  // under the selected account. One file still loads into the editor instead.
  async function onFiles(files: File[]) {
    if (!files.length) return;
    setUploading(true);
    let ok = 0;
    let dup = 0;
    let fail = 0;
    let signals = 0;
    let last: IngestResponse | null = null;
    for (const file of files) {
      try {
        const content = (await file.text()).trim();
        if (!content) {
          fail += 1;
          continue;
        }
        const res = await ingestText({
          text: content,
          source_type: detectSource(file.name, content),
          title: file.name.replace(/\.[^.]+$/, ""),
          account_id: accountId || null,
          domain,
        });
        last = res;
        if (res.duplicate) dup += 1;
        else {
          ok += 1;
          signals += res.extracted_signals.length;
        }
      } catch {
        fail += 1;
      }
    }
    if (last) setLastResult(last);
    refreshRecent();
    setUploading(false);
    toast(`Uploaded ${files.length} file${files.length === 1 ? "" : "s"}`, {
      description: `${ok} imported, ${dup} duplicate, ${fail} failed, ${signals} signal${
        signals === 1 ? "" : "s"
      } extracted.`,
      variant: fail && !ok ? "error" : "success",
    });
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
        setLastResult(res);
        refreshRecent();
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
      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Upload className="h-5 w-5 text-primary" />
              Import an interaction
            </CardTitle>
            <CardDescription>
              Paste a meeting note, transcript, email, chat log, or CRM update,
              or upload several files at once (each becomes its own evidence
              document). Everything is chunked, embedded, and indexed, and a
              deterministic pass extracts candidate signals so the next run can
              cite it.
            </CardDescription>
          </CardHeader>
          <CardContent
            className={cn(
              "space-y-5 rounded-b-xl transition-colors",
              dragging && "bg-primary/5 ring-2 ring-inset ring-primary/40",
            )}
            onDragOver={(e) => {
              if (e.dataTransfer.types.includes("Files")) {
                e.preventDefault();
                setDragging(true);
              }
            }}
            onDragLeave={(e) => {
              if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragging(false);
            }}
            onDrop={(e) => {
              const list = Array.from(e.dataTransfer.files ?? []);
              if (!list.length) return;
              e.preventDefault();
              setDragging(false);
              if (list.length === 1) void onFile(list[0]);
              else void onFiles(list);
            }}
          >
            {dragging ? (
              <div className="pointer-events-none rounded-lg border border-dashed border-primary/50 bg-card/80 px-4 py-3 text-center text-sm text-primary">
                Drop to ingest. Type is detected automatically.
              </div>
            ) : null}
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
                onChange={(e) => {
                  const v = e.target.value;
                  setText(v);
                  if (sourceAuto && v.trim().length > 40) {
                    setSourceType(detectSource("", v));
                  }
                }}
                placeholder={
                  "Paste here, for example:\n\nQBR with the champion. Adoption of the analytics module stalled, two power users left, and they are evaluating a competitor before renewal..."
                }
                className="min-h-[220px] font-sans leading-relaxed"
              />
            </Field>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field
                label="Source type"
                hint={sourceAuto ? "Auto-detected. Override if needed." : "Manual override."}
              >
                <div className="relative">
                  <select
                    value={sourceType}
                    onChange={(e) => {
                      setSourceType(e.target.value);
                      setSourceAuto(false);
                    }}
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

              <Field
                label="Account"
                hint="Optional. Scopes the evidence to one account."
              >
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

            <Field label="Title" hint="Optional. We derive one from the text if blank.">
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

              <Button type="button" variant="outline" onClick={onUseExample}>
                <Wand2 className="h-4 w-4" />
                Use example
              </Button>

              <input
                ref={fileRef}
                type="file"
                multiple
                accept=".txt,.md,.csv,.tsv,.eml,.json,.log,text/*"
                className="hidden"
                onChange={(e) => {
                  const list = Array.from(e.target.files ?? []);
                  if (list.length === 1) void onFile(list[0]);
                  else if (list.length > 1) void onFiles(list);
                  e.target.value = "";
                }}
              />
              <Button
                type="button"
                variant="outline"
                onClick={() => fileRef.current?.click()}
                disabled={uploading}
              >
                {uploading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <FileUp className="h-4 w-4" />
                )}
                {uploading ? "Uploading" : "Upload files"}
              </Button>

              <span className="text-[11px] text-muted-foreground">
                {domain.replace(/_/g, " ")}
              </span>
            </div>
          </CardContent>
        </Card>

        {/* Confirmation: extracted title + signals + NBA shortcut */}
        {lastResult ? (
          <Card className="border-primary/30">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <CheckCircle2 className="h-4 w-4 text-primary" />
                {lastResult.duplicate
                  ? "Already ingested"
                  : "Ingested and ready to cite"}
              </CardTitle>
              <CardDescription>
                <span className="font-medium text-foreground">
                  {lastResult.title}
                </span>{" "}
                · {lastResult.source_type.replace(/_/g, " ")}
                {lastResult.account_id
                  ? ` · ${accountName(lastResult.account_id)}`
                  : " · shared knowledge"}{" "}
                · {lastResult.chunks_written} chunk
                {lastResult.chunks_written === 1 ? "" : "s"} · {lastResult.chars}{" "}
                chars
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <p className="text-eyebrow mb-2">Extracted signals</p>
                {lastResult.extracted_signals.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No obvious churn, renewal, usage, or sentiment cues found in
                    this text. It is still indexed and retrievable.
                  </p>
                ) : (
                  <ul className="space-y-2">
                    {lastResult.extracted_signals.map((s, i) => (
                      <SignalRow key={`${s.category}-${i}`} signal={s} />
                    ))}
                  </ul>
                )}
              </div>

              {nbaHref ? (
                <div className="flex flex-wrap items-center gap-3 border-t border-border pt-4">
                  <Button asChild>
                    <Link href={nbaHref}>
                      Run an NBA on this {lastResult.account_id ? "account" : "evidence"}
                      <ArrowRight className="h-4 w-4" />
                    </Link>
                  </Button>
                  <span className="text-[11px] text-muted-foreground">
                    Opens a fresh run prefilled with the strongest signal.
                  </span>
                </div>
              ) : null}
            </CardContent>
          </Card>
        ) : null}
      </div>

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
            <CardTitle className="text-base">Recently ingested</CardTitle>
            <CardDescription>
              This workspace, most recent first. Each one is live in the
              retrieval corpus.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {recent.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">
                Nothing ingested yet.
              </p>
            ) : (
              <ul className="space-y-2.5">
                {recent.map((d) => (
                  <li
                    key={d.id}
                    className="flex items-start gap-2.5 rounded-md border border-border bg-card px-3 py-2.5"
                  >
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-sm font-medium">
                          {d.title}
                        </span>
                        {d.extracted_signals.length ? (
                          <Badge variant="secondary" className="shrink-0">
                            {d.extracted_signals.length} signal
                            {d.extracted_signals.length === 1 ? "" : "s"}
                          </Badge>
                        ) : null}
                      </div>
                      <div className="mt-0.5 text-[11px] text-muted-foreground">
                        {d.source_type.replace(/_/g, " ")}
                        {d.account_id
                          ? ` · ${accountName(d.account_id)}`
                          : " · shared"}
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

function SignalRow({ signal }: { signal: ExtractedSignal }) {
  return (
    <li className="flex items-start gap-2.5 rounded-md border border-border bg-card px-3 py-2">
      <Badge variant={signalVariant(signal.category)} className="mt-0.5 shrink-0">
        {signal.label}
      </Badge>
      <span className="min-w-0 flex-1 text-sm leading-snug text-foreground">
        {signal.text}
      </span>
    </li>
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
