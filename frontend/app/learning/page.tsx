"use client";

import { useEffect, useState } from "react";
import { GraduationCap } from "lucide-react";

import { LearningPanel, type LearningData } from "@/components/learning-panel";
import { Skeleton } from "@/components/ui/skeleton";
import { getLearning } from "@/lib/api";

const FALLBACK: LearningData = {
  accepted_rate: 0.78,
  before_after: {
    kpi: "Net revenue retention",
    before: "104%",
    after: "112%",
    note: "After the loop learned which save plays land, NRR on at-risk cohorts climbed 8 points.",
  },
  episodes: [
    {
      id: "ep_004",
      account_id: "acct_001",
      domain: "customer_success",
      situation: "Usage down 38% MoM, two failed logins from the champion.",
      action_key: "exec_business_review",
      decision: "approve",
      reason: null,
      recommendation: {
        action: { title: "Schedule an executive business review" },
        confidence: { score: 0.82 },
      },
      outcome: { note: "Meeting booked, renewal de-risked." },
    },
    {
      id: "ep_003",
      account_id: "acct_007",
      domain: "customer_success",
      situation: "Champion left, NPS dropped to 4. Last run pushed a discount.",
      action_key: "offer_discount",
      decision: "reject",
      reason: "Discount needs VP approval and reads as desperate here",
      improved: true,
      recommendation: {
        action: { title: "Offer a 15% renewal discount" },
        confidence: { score: 0.61 },
      },
      outcome: {
        note: "Now weights stakeholder re-mapping above price concessions.",
      },
    },
    {
      id: "ep_002",
      account_id: "acct_003",
      domain: "customer_success",
      situation: "Support tickets spiking on the integrations module.",
      action_key: "technical_escalation",
      decision: "edit",
      reason: "Looped in solutions engineering instead of generic CSM",
      recommendation: {
        action: { title: "Open a technical escalation" },
        confidence: { score: 0.74 },
      },
      outcome: { note: "Edited play became the new default for this signal." },
    },
    {
      id: "ep_001",
      account_id: "acct_011",
      domain: "customer_success",
      situation: "Healthy usage, expansion signal on seat utilization.",
      action_key: "upsell_seats",
      decision: "approve",
      reason: null,
      recommendation: {
        action: { title: "Propose a seat expansion" },
        confidence: { score: 0.88 },
      },
      outcome: { note: "Closed a 12-seat expansion." },
    },
  ],
};

export default function LearningPage() {
  const [data, setData] = useState<LearningData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = (await getLearning()) as LearningData;
        if (alive && res && Array.isArray(res.episodes)) {
          setData(res);
        } else if (alive) {
          setData(FALLBACK);
        }
      } catch {
        if (alive) setData(FALLBACK);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="flex flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-border px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-secondary text-secondary-foreground">
              <GraduationCap className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-sm font-medium text-muted-foreground">
                Learning
              </h1>
              <p className="text-lg font-semibold tracking-tight">
                Memory and the feedback loop
              </p>
            </div>
          </div>
        </header>

        <div className="mx-auto w-full max-w-5xl px-6 py-8">
          {loading || !data ? (
            <div className="grid gap-4 lg:grid-cols-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-40 rounded-lg" />
              ))}
            </div>
          ) : (
            <LearningPanel data={data} />
          )}
        </div>
    </div>
  );
}
