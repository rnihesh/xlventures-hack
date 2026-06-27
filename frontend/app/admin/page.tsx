"use client";

// Admin panel. Org/user/usage oversight across the whole deployment, gated to
// admins. The backend enforces a 403 for non-admins; this page also checks
// user.is_admin client-side so a non-admin who lands here sees an honest
// "not authorized" state instead of a flash of empty tables.

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, ShieldOff, DollarSign, Cpu } from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/lib/auth-context";
import {
  getAdminOverview,
  getAdminOrgs,
  getAdminUsage,
  getAdminUsers,
  type AdminOrg,
  type AdminOverview,
  type AdminUsageReport,
  type AdminUser,
} from "@/lib/api/admin";

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

function formatCost(v: number): string {
  return `$${(v ?? 0).toLocaleString("en-US", {
    minimumFractionDigits: 4,
    maximumFractionDigits: 4,
  })}`;
}

// Compact cost for chart axes and tooltips: two decimals keeps the y axis
// legible where the cards use four.
function formatCostShort(v: number): string {
  return `$${(v ?? 0).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatTokens(v: number): string {
  return (v ?? 0).toLocaleString("en-US");
}

function formatCount(v: number): string {
  return (v ?? 0).toLocaleString("en-US");
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "--";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "--";
  return d.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "--";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "--";
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function shortDay(value: string): string {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

const RANGES = [7, 30, 90] as const;

// ---------------------------------------------------------------------------
// Daily usage chart: a recharts area chart per series (cost + tokens). Themed
// grayscale with the single Claude-orange accent (#D97757); no default hues.
// ---------------------------------------------------------------------------

const ACCENT = "#D97757";
const AXIS_LINE = "#e7e5e4"; // muted gridlines and axes
const TICK_COLOR = "#78716c"; // muted tick labels

function UsageChart({
  series,
  valueKey,
  format,
  label,
  gradientId,
}: {
  series: { day: string; total_tokens: number; cost_usd: number }[];
  valueKey: "cost_usd" | "total_tokens";
  format: (v: number) => string;
  label: string;
  gradientId: string;
}) {
  if (series.length < 2) {
    return (
      <div className="flex h-[220px] items-center justify-center text-xs text-muted-foreground">
        A trend appears once at least two days of usage are recorded.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={220}>
      <AreaChart
        data={series}
        margin={{ top: 8, right: 12, left: 0, bottom: 0 }}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={ACCENT} stopOpacity={0.28} />
            <stop offset="100%" stopColor={ACCENT} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={AXIS_LINE} strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="day"
          tickFormatter={shortDay}
          tick={{ fill: TICK_COLOR, fontSize: 11 }}
          tickLine={false}
          axisLine={{ stroke: AXIS_LINE }}
          minTickGap={24}
        />
        <YAxis
          tickFormatter={format}
          tick={{ fill: TICK_COLOR, fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          width={64}
        />
        <Tooltip
          cursor={{ stroke: AXIS_LINE, strokeWidth: 1 }}
          contentStyle={{
            background: "#ffffff",
            border: `1px solid ${AXIS_LINE}`,
            borderRadius: 8,
            fontSize: 12,
            color: "#1c1917",
            boxShadow: "none",
          }}
          labelStyle={{ color: TICK_COLOR, marginBottom: 2 }}
          labelFormatter={(value) => shortDay(String(value))}
          formatter={(value) => [format(Number(value)), label]}
        />
        <Area
          type="monotone"
          dataKey={valueKey}
          stroke={ACCENT}
          strokeWidth={2}
          fill={`url(#${gradientId})`}
          dot={false}
          activeDot={{ r: 3, fill: ACCENT, stroke: ACCENT }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

// ---------------------------------------------------------------------------
// Small reusable header stat card, matching the eval-panel header card style.
// ---------------------------------------------------------------------------

function StatCard({
  label,
  value,
  accent,
  hint,
}: {
  label: string;
  value: string;
  accent?: boolean;
  hint?: string;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription className="text-xs font-medium uppercase tracking-wide">
          {label}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div
          className={
            "text-3xl font-semibold tabular-nums" +
            (accent ? " text-primary" : "")
          }
        >
          {value}
        </div>
        {hint ? (
          <span className="mt-1 block text-[11px] font-normal text-muted-foreground">
            {hint}
          </span>
        ) : null}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Lightweight table primitives, matching account-table.tsx visual style.
// ---------------------------------------------------------------------------

function TableShell({
  head,
  children,
  cols,
  empty,
}: {
  head: React.ReactNode;
  children: React.ReactNode;
  cols: number;
  empty?: boolean;
}) {
  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-card">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-border bg-muted/40 text-left">{head}</tr>
        </thead>
        <tbody>
          {empty ? (
            <tr>
              <td
                colSpan={cols}
                className="px-4 py-10 text-center text-sm text-muted-foreground"
              >
                Nothing to show yet.
              </td>
            </tr>
          ) : (
            children
          )}
        </tbody>
      </table>
    </div>
  );
}

function Th({
  children,
  align,
}: {
  children: React.ReactNode;
  align?: "right";
}) {
  return (
    <th
      scope="col"
      className={
        "px-4 py-2.5 text-eyebrow font-semibold" +
        (align === "right" ? " text-right" : "")
      }
    >
      {children}
    </th>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function AdminPage() {
  const { user, loading: authLoading } = useAuth();
  const [days, setDays] = useState<number>(30);

  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [usage, setUsage] = useState<AdminUsageReport | null>(null);
  const [orgs, setOrgs] = useState<AdminOrg[] | null>(null);
  const [users, setUsers] = useState<AdminUser[] | null>(null);

  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [forbidden, setForbidden] = useState(false);

  const isAdmin = !!user?.is_admin;

  // Windowed data (overview + usage) refetches whenever the range changes.
  const loadWindowed = useCallback(
    async (signal?: AbortSignal) => {
      const [ov, us] = await Promise.all([
        getAdminOverview(days, signal),
        getAdminUsage(days, signal),
      ]);
      setOverview(ov);
      setUsage(us);
    },
    [days],
  );

  useEffect(() => {
    if (authLoading || !isAdmin) return;
    const controller = new AbortController();
    let alive = true;
    setLoading(true);
    setFailed(false);
    setForbidden(false);
    (async () => {
      try {
        const [, , os, usr] = await Promise.all([
          loadWindowed(controller.signal),
          Promise.resolve(),
          getAdminOrgs(controller.signal),
          getAdminUsers(controller.signal),
        ]);
        if (!alive) return;
        setOrgs(os);
        setUsers(usr);
      } catch (err) {
        if (!alive) return;
        const status = (err as { status?: number } | null)?.status;
        if (status === 403) setForbidden(true);
        else setFailed(true);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
      controller.abort();
    };
  }, [authLoading, isAdmin, loadWindowed]);

  // Auth still resolving: show a neutral loading shell.
  if (authLoading) {
    return (
      <div className="mx-auto w-full max-w-6xl px-6 py-8">
        <Skeleton className="h-10 w-64 rounded-lg" />
        <div className="mt-6 grid gap-4 sm:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-lg" />
          ))}
        </div>
      </div>
    );
  }

  // Signed in but not an admin (or the backend rejected with 403).
  if (!isAdmin || forbidden) {
    return (
      <div className="mx-auto flex w-full max-w-6xl flex-col items-center justify-center px-6 py-24 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-secondary text-muted-foreground">
          <ShieldOff className="h-6 w-6" />
        </div>
        <h1 className="mt-5 text-lg font-semibold tracking-tight">
          Not authorized
        </h1>
        <p className="mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
          The admin panel is limited to administrators. Your account does not
          have admin access.
        </p>
      </div>
    );
  }

  const rangeSelector = (
    <Select
      aria-label="Usage window in days"
      value={String(days)}
      onChange={(e) => setDays(Number(e.target.value))}
      className="h-9 w-36"
    >
      {RANGES.map((r) => (
        <option key={r} value={r}>
          Last {r} days
        </option>
      ))}
    </Select>
  );

  return (
    <div className="mx-auto w-full max-w-6xl px-6 py-8">
      <PageHeader
        eyebrow="System"
        title="Admin"
        description="Organizations, users, and OpenAI usage across the whole deployment."
        actions={rangeSelector}
      />

      {failed ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border bg-card px-6 py-20 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-secondary text-muted-foreground">
            <AlertTriangle className="h-6 w-6" />
          </div>
          <h2 className="mt-5 text-lg font-semibold tracking-tight">
            Admin data unavailable
          </h2>
          <p className="mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
            The admin service could not be reached, so no numbers are shown.
          </p>
        </div>
      ) : loading || !overview || !usage ? (
        <div className="flex flex-col gap-6">
          <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-6">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-24 rounded-lg" />
            ))}
          </div>
          <Skeleton className="h-64 rounded-lg" />
          <Skeleton className="h-64 rounded-lg" />
        </div>
      ) : (
        <div className="flex flex-col gap-10">
          {/* Overview header cards */}
          <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-6">
            <StatCard label="Orgs" value={formatCount(overview.orgs)} />
            <StatCard label="Users" value={formatCount(overview.users)} />
            <StatCard label="Accounts" value={formatCount(overview.accounts)} />
            <StatCard label="Runs" value={formatCount(overview.runs)} />
            <StatCard
              label={`OpenAI cost (${overview.days}d)`}
              value={formatCost(overview.usage.cost_usd)}
              accent
              hint={`all time ${formatCost(overview.usage_all_time.cost_usd)}`}
            />
            <StatCard
              label="Total tokens"
              value={formatTokens(overview.usage.total_tokens)}
              hint={`${formatCount(overview.usage.events)} events`}
            />
          </div>

          {/* OpenAI usage */}
          <section className="flex flex-col gap-4">
            <div>
              <h2 className="text-base font-semibold tracking-tight">
                OpenAI usage
              </h2>
              <p className="text-sm text-muted-foreground">
                Daily spend and token volume over the last {usage.days} days.
              </p>
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <Card>
                <CardHeader className="pb-2">
                  <CardDescription className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide">
                    <DollarSign className="h-3.5 w-3.5" />
                    Daily cost (USD)
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <UsageChart
                    series={usage.daily}
                    valueKey="cost_usd"
                    format={formatCostShort}
                    label="Cost"
                    gradientId="admin-cost"
                  />
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardDescription className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide">
                    <Cpu className="h-3.5 w-3.5" />
                    Daily tokens
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <UsageChart
                    series={usage.daily}
                    valueKey="total_tokens"
                    format={formatTokens}
                    label="Tokens"
                    gradientId="admin-tokens"
                  />
                </CardContent>
              </Card>
            </div>

            {/* By model */}
            <div>
              <h3 className="mb-2 text-sm font-semibold tracking-tight">
                By model
              </h3>
              <TableShell
                cols={5}
                empty={usage.by_model.length === 0}
                head={
                  <>
                    <Th>Model</Th>
                    <Th>Kind</Th>
                    <Th align="right">Events</Th>
                    <Th align="right">Tokens</Th>
                    <Th align="right">Cost</Th>
                  </>
                }
              >
                {usage.by_model.map((m) => (
                  <tr
                    key={`${m.model}:${m.kind}`}
                    className="border-b border-border last:border-0 hover:bg-accent/40"
                  >
                    <td className="px-4 py-3 font-medium">{m.model}</td>
                    <td className="px-4 py-3 text-muted-foreground">
                      {m.kind}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {formatCount(m.events)}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {formatTokens(m.total_tokens)}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-primary">
                      {formatCost(m.cost_usd)}
                    </td>
                  </tr>
                ))}
              </TableShell>
            </div>

            {/* By org */}
            <div>
              <h3 className="mb-2 text-sm font-semibold tracking-tight">
                By organization
              </h3>
              <TableShell
                cols={5}
                empty={usage.by_org.length === 0}
                head={
                  <>
                    <Th>Org</Th>
                    <Th align="right">Events</Th>
                    <Th align="right">Tokens</Th>
                    <Th align="right">Cost</Th>
                    <Th align="right">Last used</Th>
                  </>
                }
              >
                {usage.by_org.map((o) => (
                  <tr
                    key={o.org_id}
                    className="border-b border-border last:border-0 hover:bg-accent/40"
                  >
                    <td className="px-4 py-3 font-medium">
                      {o.org_name ?? o.org_id}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {formatCount(o.events)}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {formatTokens(o.total_tokens)}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-primary">
                      {formatCost(o.cost_usd)}
                    </td>
                    <td className="px-4 py-3 text-right text-muted-foreground">
                      {formatDateTime(o.last_used)}
                    </td>
                  </tr>
                ))}
              </TableShell>
            </div>
          </section>

          {/* Signups / Orgs */}
          <section className="flex flex-col gap-4">
            <div>
              <h2 className="text-base font-semibold tracking-tight">
                Signups and organizations
              </h2>
              <p className="text-sm text-muted-foreground">
                Every workspace, when it signed up, and what it has used.
              </p>
            </div>
            <TableShell
              cols={8}
              empty={!orgs || orgs.length === 0}
              head={
                <>
                  <Th>Org</Th>
                  <Th>Created</Th>
                  <Th align="right">Users</Th>
                  <Th align="right">Accounts</Th>
                  <Th align="right">Runs</Th>
                  <Th align="right">Last run</Th>
                  <Th align="right">Tokens</Th>
                  <Th align="right">Cost</Th>
                </>
              }
            >
              {(orgs ?? []).map((o) => (
                <tr
                  key={o.id}
                  className="border-b border-border last:border-0 hover:bg-accent/40"
                >
                  <td className="px-4 py-3 font-medium">{o.name}</td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {formatDate(o.created_at)}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    {formatCount(o.users)}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    {formatCount(o.accounts)}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    {formatCount(o.runs)}
                  </td>
                  <td className="px-4 py-3 text-right text-muted-foreground">
                    {formatDateTime(o.last_run)}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    {formatTokens(o.total_tokens)}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-primary">
                    {formatCost(o.cost_usd)}
                  </td>
                </tr>
              ))}
            </TableShell>
          </section>

          {/* Users */}
          <section className="flex flex-col gap-4">
            <div>
              <h2 className="text-base font-semibold tracking-tight">Users</h2>
              <p className="text-sm text-muted-foreground">
                Everyone with an account across all organizations.
              </p>
            </div>
            <TableShell
              cols={7}
              empty={!users || users.length === 0}
              head={
                <>
                  <Th>Email</Th>
                  <Th>Name</Th>
                  <Th>Org</Th>
                  <Th>Role</Th>
                  <Th>Verified</Th>
                  <Th>Signed up</Th>
                  <Th align="right">Last login</Th>
                </>
              }
            >
              {(users ?? []).map((u) => (
                <tr
                  key={u.id}
                  className="border-b border-border last:border-0 hover:bg-accent/40"
                >
                  <td className="px-4 py-3 font-medium">{u.email}</td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {u.name ?? "--"}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {u.org_name ?? u.org_id}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">{u.role}</td>
                  <td className="px-4 py-3">
                    <span
                      className={
                        "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset " +
                        (u.email_verified
                          ? "bg-primary/10 text-primary ring-primary/20"
                          : "bg-muted text-muted-foreground ring-border")
                      }
                    >
                      {u.email_verified ? "Verified" : "Pending"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {formatDate(u.created_at)}
                  </td>
                  <td className="px-4 py-3 text-right text-muted-foreground">
                    {formatDateTime(u.last_login_at)}
                  </td>
                </tr>
              ))}
            </TableShell>
          </section>
        </div>
      )}
    </div>
  );
}
