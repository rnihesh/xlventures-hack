// Plain-language explanations for the signals the engine surfaces.
//
// Signals arrive as free-form text (for example "Steady usage; strong NPS from
// economic buyer"), so instead of a fixed enum we scan for known terms and
// compose a short, human explanation: what the signal means and why it matters.
// Every signal still gets an answer thanks to a sensible generic fallback.
//
// This is the canonical, structured helper used by the accounts experience.
// It returns a tone (positive / negative / neutral) so the UI can tint the
// explanation without inventing new colors outside the grayscale + orange set.

export type SignalTone = "positive" | "negative" | "neutral";

export interface SignalInfo {
  // One plain sentence: what this signal actually is.
  meaning: string;
  // One plain sentence: why a non-expert should care about it.
  whyItMatters: string;
  // Overall read for someone skimming: good news, a warning, or neutral.
  tone: SignalTone;
}

interface GlossaryEntry {
  // Lowercased substrings that indicate this concept is present.
  match: string[];
  meaning: string;
  whyItMatters: string;
  tone: SignalTone;
}

// Ordered by specificity: the most decisive concepts come first so a combined
// signal (for example "usage down + escalation") is summarized by its sharpest
// drivers rather than a softer match.
const GLOSSARY: GlossaryEntry[] = [
  {
    match: ["outage", "sev-1", "sev1", "incident", "downtime", "reliability"],
    meaning: "The product had a reliability problem, such as an outage or major incident.",
    whyItMatters: "Downtime erodes trust fast and is a common trigger for churn, so it needs a proactive, visible response.",
    tone: "negative",
  },
  {
    match: ["escalation", "exec escalation"],
    meaning: "An issue has been escalated to senior leadership on the customer side.",
    whyItMatters: "Executives are now watching, so the stakes and urgency are high and a fast, senior-level reply is expected.",
    tone: "negative",
  },
  {
    match: ["churn", "cancel", "non-renew", "at risk", "detractor"],
    meaning: "There is a direct sign the customer may leave or cut back.",
    whyItMatters: "This points straight at lost revenue, so it is the clearest call to intervene before renewal.",
    tone: "negative",
  },
  {
    match: ["payment", "invoice", "overdue", "past due", "collections"],
    meaning: "There is a billing or payment problem, such as an overdue invoice.",
    whyItMatters: "Late payments often signal financial strain or friction in the relationship that can stall a renewal.",
    tone: "negative",
  },
  {
    match: ["ticket", "support", "bug", "case volume"],
    meaning: "Support activity is notable, often a rise in tickets or open cases.",
    whyItMatters: "A spike points to friction or instability that wears down confidence over time if left unaddressed.",
    tone: "negative",
  },
  {
    match: ["expansion", "upsell", "cross-sell", "add seats", "seats", "growth"],
    meaning: "The account is showing appetite to buy more, such as extra seats or products.",
    whyItMatters: "This is an opening to grow revenue while the customer is already engaged and seeing value.",
    tone: "positive",
  },
  {
    match: ["sso", "security review", "soc 2", "soc2", "compliance"],
    meaning: "The customer is asking about security or SSO, typically as they scale their rollout.",
    whyItMatters: "These requests usually come from a maturing, committed customer, so it is often a buying signal.",
    tone: "positive",
  },
  {
    match: ["champion", "economic buyer", "sponsor", "stakeholder", "advocate"],
    meaning: "A key person (a champion or the budget-holder) is involved and engaged.",
    whyItMatters: "A strong internal advocate materially improves renewal and expansion outcomes.",
    tone: "positive",
  },
  {
    match: ["nps", "net promoter"],
    meaning: "NPS (Net Promoter Score) measures how likely a contact is to recommend you.",
    whyItMatters: "A strong score signals a durable, healthy relationship, while a weak one is an early warning.",
    tone: "positive",
  },
  {
    match: ["csat", "sentiment", "satisfaction"],
    meaning: "This is a read on how satisfied the customer feels right now.",
    whyItMatters: "Positive sentiment lowers risk, while a downturn is an early churn warning.",
    tone: "neutral",
  },
  {
    match: ["usage", "active user", "dau", "wau", "mau", "adoption", "login"],
    meaning: "This reflects how much the product is actually being used.",
    whyItMatters: "Steady or rising usage means the product is sticky, while a drop often comes before churn.",
    tone: "neutral",
  },
  {
    match: ["qbr", "business review", "ebr"],
    meaning: "This concerns a business review, the regular check-in that keeps executives aligned on value.",
    whyItMatters: "A held review reinforces the relationship, while a skipped one means alignment is slipping.",
    tone: "neutral",
  },
  {
    match: ["renewal", "contract end", "term end"],
    meaning: "The renewal date is a factor in this signal.",
    whyItMatters: "The closer renewal gets, the higher the stakes on any open risk or opportunity.",
    tone: "neutral",
  },
  {
    match: ["onboarding", "time to value", "ramp", "implementation"],
    meaning: "This is about how the customer is getting started and reaching first value.",
    whyItMatters: "A slow start is a leading indicator of churn later, so early momentum matters a lot.",
    tone: "neutral",
  },
];

const GENERIC: SignalInfo = {
  meaning: "This is a behavioral or relationship indicator the agent weighed when reading the account.",
  whyItMatters: "It nudges the health read and the recommended next action up or down based on what it implies.",
  tone: "neutral",
};

// Positive words that should soften a steady or healthy read when present.
const POSITIVE_HINTS = ["steady", "strong", "healthy", "stable", "growing", "engaged", "exceeded", "on track"];
const NEGATIVE_HINTS = ["down", "drop", "declin", "spike", "missed", "skipped", "stalled", "lost", "delay"];

function resolveTone(text: string, matched: GlossaryEntry[]): SignalTone {
  const lower = text.toLowerCase();
  // An explicit negative word in the raw signal wins: "usage down" is bad even
  // though "usage" on its own is neutral.
  if (NEGATIVE_HINTS.some((w) => lower.includes(w))) return "negative";
  if (matched.some((m) => m.tone === "negative")) return "negative";
  if (POSITIVE_HINTS.some((w) => lower.includes(w))) return "positive";
  if (matched.some((m) => m.tone === "positive")) return "positive";
  return "neutral";
}

/**
 * Return a structured, plain-language explanation for a free-form signal.
 * Combines up to two matched concepts; falls back to a generic description so
 * every signal is explained.
 */
export function signalInfo(text: string): SignalInfo {
  if (!text) return GENERIC;
  const lower = text.toLowerCase();
  const matched: GlossaryEntry[] = [];
  for (const entry of GLOSSARY) {
    if (entry.match.some((m) => lower.includes(m))) matched.push(entry);
    if (matched.length >= 2) break; // keep explanations short
  }
  if (matched.length === 0) {
    return { ...GENERIC, tone: resolveTone(text, matched) };
  }
  const meaning = matched.map((m) => m.meaning).join(" ");
  const whyItMatters = matched.map((m) => m.whyItMatters).join(" ");
  return { meaning, whyItMatters, tone: resolveTone(text, matched) };
}

/**
 * Convenience one-liner ("what it means: why it matters") for compact spots
 * like tooltips. Built on top of signalInfo so the wording stays consistent.
 */
export function explainSignal(text: string): string {
  const info = signalInfo(text);
  return `${info.meaning} ${info.whyItMatters}`;
}

// Section-level explanations reused across the accounts experience.
export const SIGNAL_SECTION_HELP = {
  signals:
    "Signals are the facts we have gathered about this account: product usage, support activity, relationship health, and billing. Each one below is explained in plain language.",
  documents:
    "These are the source records and documents the agent reviewed to back up its read of the account. Each item links a claim to where it came from.",
  history:
    "Every past recommendation for this account, what your team decided, and the outcome where we have it.",
} as const;
