// Plain-language explanations for the signals the engine surfaces.
//
// Signals arrive as free-form text ("Steady usage; strong NPS from economic
// buyer"), so rather than a fixed enum we scan for known terms and compose a
// short, human explanation of what the signal means and why it matters. When
// nothing matches we fall back to a sensible generic description so every
// signal still gets a tooltip.

interface GlossaryEntry {
  // Lowercased substrings that indicate this concept is present.
  match: string[];
  explain: string;
}

const GLOSSARY: GlossaryEntry[] = [
  {
    match: ["nps", "net promoter"],
    explain:
      "NPS (Net Promoter Score) gauges how likely a contact is to recommend you. A strong score signals a healthy, durable relationship.",
  },
  {
    match: ["csat", "sentiment", "satisfaction"],
    explain:
      "A satisfaction or sentiment read on the account. Positive sentiment lowers risk; a downturn is an early churn warning.",
  },
  {
    match: ["usage", "active user", "dau", "wau", "mau", "adoption", "login"],
    explain:
      "Product usage and adoption trend. Steady or rising usage signals stickiness; a drop often precedes churn.",
  },
  {
    match: ["qbr", "business review", "ebr"],
    explain:
      "A QBR (Quarterly Business Review) keeps executives aligned on value. A skipped or overdue review means weak alignment.",
  },
  {
    match: ["ticket", "support", "bug", "case volume"],
    explain:
      "Support ticket activity. A spike points to friction or instability that can erode trust over time.",
  },
  {
    match: ["outage", "sev-1", "sev1", "incident", "downtime", "reliability"],
    explain:
      "A reliability incident. Outages, especially during critical periods, raise churn risk and warrant proactive follow-up.",
  },
  {
    match: ["escalation", "exec escalation", "executive"],
    explain:
      "An executive escalation. Leadership is now involved, so urgency and stakes are high.",
  },
  {
    match: ["churn", "cancel", "non-renew", "at risk", "detractor"],
    explain:
      "A churn-risk indicator. It suggests the account may reduce spend or not renew.",
  },
  {
    match: ["renewal", "contract end", "term end"],
    explain:
      "Renewal timing. Proximity to renewal raises the stakes of any open risk or opportunity.",
  },
  {
    match: ["expansion", "upsell", "cross-sell", "seats", "add seats", "growth"],
    explain:
      "Expansion potential. The account may be ready to buy more seats or products.",
  },
  {
    match: ["sso", "security review", "soc 2", "soc2", "compliance"],
    explain:
      "A security or SSO request. Often a buying signal from a maturing customer scaling its rollout.",
  },
  {
    match: ["champion", "economic buyer", "sponsor", "stakeholder", "advocate"],
    explain:
      "Stakeholder strength. A strong champion or economic-buyer relationship materially improves outcomes.",
  },
  {
    match: ["payment", "invoice", "overdue", "past due", "collections", "ar "],
    explain:
      "Payment status. Overdue invoices signal financial strain or relationship friction.",
  },
  {
    match: ["onboarding", "time to value", "ramp", "implementation"],
    explain:
      "Onboarding progress. Slow time-to-value early on is a leading indicator of later churn.",
  },
];

const GENERIC =
  "A behavioral or relationship indicator the agent weighed when scoring this action. It nudges confidence up or down based on account health.";

/**
 * Return a short plain-language explanation for a free-form signal string.
 * Combines every matched concept; falls back to a generic description.
 */
export function explainSignal(text: string): string {
  if (!text) return GENERIC;
  const lower = text.toLowerCase();
  const hits: string[] = [];
  for (const entry of GLOSSARY) {
    if (entry.match.some((m) => lower.includes(m))) {
      if (!hits.includes(entry.explain)) hits.push(entry.explain);
    }
    if (hits.length >= 2) break; // keep the tooltip short
  }
  return hits.length > 0 ? hits.join(" ") : GENERIC;
}

// Section-level explanations for the supporting / contradicting groupings.
export const SIGNAL_GROUP_HELP = {
  supporting:
    "Supporting signals are evidence that backs this recommendation: account facts that raise the agent's confidence in the play.",
  contradicting:
    "Contradicting signals are evidence that cuts against this recommendation: facts that lower confidence or argue for caution.",
} as const;
