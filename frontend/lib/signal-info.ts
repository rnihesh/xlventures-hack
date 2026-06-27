// Plain-language explanations for the signals the engine surfaces.
//
// Signals arrive as free-form text (for example "Steady usage; strong NPS from
// economic buyer" or "Executive sponsor departed"), so instead of a fixed enum
// we scan for known concepts AND the direction of the signal (is this good news
// or bad news?), then compose a short, human explanation: what the signal means
// and why it matters. Every signal still gets an answer thanks to a sensible
// generic fallback.
//
// The key correctness property: explanations are DIRECTION-AWARE. The same
// concept reads differently depending on the wording. "Executive sponsor
// departed" is a lost champion (a risk), while "Executive sponsor engaged" is a
// strong advocate (good news). We never default a negative signal to a positive
// blurb.
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

interface Blurb {
  meaning: string;
  whyItMatters: string;
}

interface Family {
  // Lowercased substrings that indicate this concept is present.
  match: string[];
  // Direction-specific wording. We always provide the variant that matches the
  // detected direction; defaultTone is used when the signal text carries no
  // explicit up/down cue.
  variants: Partial<Record<SignalTone, Blurb>>;
  defaultTone: SignalTone;
}

// Words that reveal the DIRECTION of a signal, independent of the concept.
// These let "usage" (neutral on its own) become a risk in "usage down" and an
// opportunity in "usage up".
const NEGATIVE_CUES = [
  "down",
  "drop",
  "declin",
  "decreas",
  "dip",
  "fell",
  "falling",
  "sinking",
  "low",
  "weak",
  "poor",
  "unresolved",
  "departed",
  "departure",
  "left the",
  "leaving",
  "resign",
  "churn",
  "cancel",
  "non-renew",
  "downgrad",
  "downsell",
  "reduc",
  "shrink",
  "at risk",
  "at-risk",
  "dispute",
  "overdue",
  "past due",
  "missed",
  "miss ",
  "skipped",
  "stalled",
  "stall",
  "delay",
  "slip",
  "lost",
  "losing",
  "no-show",
  "no show",
  "blocker",
  "blocked",
  "frustrat",
  "angry",
  "upset",
  "complaint",
  "escalat",
  "sev-1",
  "sev1",
  "sev 1",
  "outage",
  "incident",
  "downtime",
  "detractor",
  "disengag",
  "gone dark",
  "gone quiet",
  "quiet",
  "concern",
  "threat",
  "broke",
  "broken",
  "late",
];

const POSITIVE_CUES = [
  "up ",
  "rose",
  "rising",
  "increas",
  "grew",
  "growing",
  "growth",
  "strong",
  "healthy",
  "stable",
  "steady",
  "exceed",
  "exceeded",
  "hit ",
  "high",
  "renewed",
  "expanded",
  "expansion",
  "upsell",
  "engaged",
  "advocate",
  "promoter",
  "on track",
  "improv",
  "resolved",
  "won",
  "win ",
  "positive",
  "scaling",
  "ramping",
  "adopt",
  "success",
];

// Detect the direction of a signal from its wording. Returns null when there is
// no clear up/down cue, so each family can fall back to its own default read.
function detectDirection(lower: string): SignalTone | null {
  let neg = 0;
  let pos = 0;
  for (const w of NEGATIVE_CUES) if (lower.includes(w)) neg += 1;
  for (const w of POSITIVE_CUES) if (lower.includes(w)) pos += 1;
  if (neg === 0 && pos === 0) return null;
  if (neg > pos) return "negative";
  if (pos > neg) return "positive";
  // Tie with cues on both sides: lean to caution, the safer read for a CS team.
  return "negative";
}

// Ordered by specificity: the most decisive concepts come first so a combined
// signal (for example "usage down + escalation") is summarized by its sharpest
// drivers rather than a softer match. Concept matchers avoid bare words that
// collide across families (for example expansion uses "add seats", not "seats",
// so "seat utilisation" stays with usage).
const FAMILIES: Family[] = [
  {
    // Reliability incidents and executive escalations: almost always a fire.
    match: [
      "escalation",
      "exec escalation",
      "sev-1",
      "sev1",
      "sev 1",
      "sev-2",
      "p1 ",
      "outage",
      "incident",
      "downtime",
      "reliability",
    ],
    variants: {
      negative: {
        meaning:
          "An issue has escalated, or the product had a major incident such as an outage or Sev-1.",
        whyItMatters:
          "Leadership is watching and trust is on the line, so a fast, senior-level response is expected.",
      },
      positive: {
        meaning: "A prior escalation or major incident has been resolved.",
        whyItMatters:
          "Closing out a high-visibility problem rebuilds trust, as long as the follow-through is visible.",
      },
    },
    defaultTone: "negative",
  },
  {
    // Direct churn-risk language.
    match: [
      "churn",
      "cancel",
      "non-renew",
      "at risk",
      "at-risk",
      "detractor",
      "threatening to leave",
    ],
    variants: {
      negative: {
        meaning: "There is a direct sign the customer may leave or cut back.",
        whyItMatters:
          "This points straight at lost revenue, so it is the clearest call to intervene before renewal.",
      },
    },
    defaultTone: "negative",
  },
  {
    // Billing and payment health.
    match: [
      "payment",
      "invoice",
      "overdue",
      "past due",
      "collections",
      "billing",
      "credit hold",
      "ar ",
    ],
    variants: {
      negative: {
        meaning:
          "There is a billing problem, such as an overdue, disputed, or unpaid invoice.",
        whyItMatters:
          "Payment friction often signals financial strain or dissatisfaction and can stall a renewal.",
      },
      positive: {
        meaning:
          "Billing is healthy: invoices are being paid on time or a payment dispute was resolved.",
        whyItMatters:
          "Clean payment behavior reflects commitment and clears a common renewal blocker.",
      },
    },
    defaultTone: "negative",
  },
  {
    // Support load and ticket volume.
    match: ["ticket", "support", "bug", "case volume", "cases", "backlog"],
    variants: {
      negative: {
        meaning:
          "Support load is elevated: a rise in tickets, bugs, or open cases.",
        whyItMatters:
          "A spike points to friction or instability that wears down confidence if left unaddressed.",
      },
      positive: {
        meaning:
          "Support load is light or improving: tickets are being resolved or trending down.",
        whyItMatters:
          "Low, well-handled support volume reflects a stable, healthy account.",
      },
      neutral: {
        meaning: "This reflects the current level of support activity.",
        whyItMatters:
          "Rising tickets signal friction, while a calm queue signals stability.",
      },
    },
    defaultTone: "negative",
  },
  {
    // Renewal status.
    match: ["renewal", "contract end", "term end", "up for renewal", "renew"],
    variants: {
      positive: {
        meaning: "The contract was renewed or the renewal is on track.",
        whyItMatters:
          "A completed renewal locks in revenue and confirms the customer still sees value.",
      },
      negative: {
        meaning:
          "Renewal is at risk: a non-renewal, downgrade, or stalled negotiation.",
        whyItMatters:
          "A shaky renewal puts current revenue directly on the line.",
      },
      neutral: {
        meaning: "The renewal date is a factor in this signal.",
        whyItMatters:
          "The closer renewal gets, the higher the stakes on any open risk or opportunity.",
      },
    },
    defaultTone: "neutral",
  },
  {
    // Onboarding and time to value.
    match: [
      "onboarding",
      "time to value",
      "time-to-value",
      "ramp",
      "implementation",
      "go-live",
      "go live",
      "rollout",
      "kickoff",
    ],
    variants: {
      positive: {
        meaning:
          "Onboarding is on track: the customer is ramping and reaching first value.",
        whyItMatters:
          "Early momentum is one of the strongest predictors of long-term retention.",
      },
      negative: {
        meaning:
          "Onboarding is stalling: a slow ramp or delayed time to value.",
        whyItMatters:
          "A slow start is a leading indicator of churn well before renewal.",
      },
      neutral: {
        meaning:
          "This is about how the customer is getting started and reaching first value.",
        whyItMatters:
          "Early momentum matters a lot: a slow start predicts churn later.",
      },
    },
    defaultTone: "neutral",
  },
  {
    // Expansion appetite. Uses "add seats" (not bare "seats") so seat
    // utilisation stays with the usage family.
    match: [
      "expansion",
      "upsell",
      "cross-sell",
      "cross sell",
      "add seats",
      "add-on",
      "new product",
      "more seats",
    ],
    variants: {
      positive: {
        meaning:
          "The account is showing appetite to buy more, such as extra seats or products.",
        whyItMatters:
          "This is an opening to grow revenue while the customer is already engaged and seeing value.",
      },
      negative: {
        meaning:
          "An expansion has stalled or been pulled back, such as a downsell or fewer seats.",
        whyItMatters:
          "Shrinking commitment signals fading value and often precedes churn.",
      },
    },
    defaultTone: "positive",
  },
  {
    // Sentiment, NPS, and CSAT.
    match: [
      "nps",
      "net promoter",
      "csat",
      "sentiment",
      "satisfaction",
      "promoter",
      "mood",
    ],
    variants: {
      positive: {
        meaning:
          "Sentiment is strong: a high NPS or CSAT, or promoter-level feedback.",
        whyItMatters:
          "Happy, vocal customers renew, expand, and refer, the healthiest relationship signal there is.",
      },
      negative: {
        meaning:
          "Sentiment is weak: a low score, detractor feedback, or a souring mood.",
        whyItMatters:
          "Falling satisfaction is an early churn warning that usually shows up before a formal exit.",
      },
      neutral: {
        meaning:
          "A read on how the customer currently feels (NPS, CSAT, or sentiment).",
        whyItMatters:
          "Sentiment shifts are an early signal of where the relationship is heading.",
      },
    },
    defaultTone: "neutral",
  },
  {
    // Champion, sponsor, and economic buyer relationships.
    match: [
      "champion",
      "economic buyer",
      "sponsor",
      "stakeholder",
      "advocate",
      "decision maker",
      "decision-maker",
      "exec sponsor",
      "executive sponsor",
    ],
    variants: {
      positive: {
        meaning:
          "A key stakeholder (a champion or the budget holder) is engaged and backing you.",
        whyItMatters:
          "A strong internal advocate materially improves renewal and expansion outcomes.",
      },
      negative: {
        meaning:
          "A key relationship has weakened or been lost: a champion or sponsor has departed, gone quiet, or disengaged.",
        whyItMatters:
          "Losing your internal advocate removes the person who defends the renewal from the inside, a serious risk.",
      },
      neutral: {
        meaning:
          "This concerns a key stakeholder, such as a champion or the economic buyer.",
        whyItMatters:
          "The strength of that relationship is one of the biggest drivers of renewal and expansion.",
      },
    },
    defaultTone: "neutral",
  },
  {
    // Usage and adoption, including seat utilisation.
    match: [
      "usage",
      "active user",
      "dau",
      "wau",
      "mau",
      "adoption",
      "login",
      "logins",
      "utilis",
      "utiliz",
      "feature use",
    ],
    variants: {
      positive: {
        meaning: "Product usage is strong or climbing.",
        whyItMatters:
          "Heavy adoption makes the product sticky and hard to rip out, a strong retention signal.",
      },
      negative: {
        meaning: "Product usage has fallen or is sitting low.",
        whyItMatters:
          "Declining adoption is one of the earliest and most reliable churn warnings.",
      },
      neutral: {
        meaning: "This reflects how much the product is actually being used.",
        whyItMatters:
          "Usage trend is a leading indicator: steady or rising is sticky, a drop often precedes churn.",
      },
    },
    defaultTone: "neutral",
  },
  {
    // Business reviews.
    match: ["qbr", "business review", "ebr", "check-in", "check in"],
    variants: {
      positive: {
        meaning:
          "A business review took place, keeping executives aligned on value.",
        whyItMatters:
          "A held review reinforces the relationship and surfaces the next opportunity.",
      },
      negative: {
        meaning: "A business review was skipped or is overdue.",
        whyItMatters:
          "A missed review means executive alignment is slipping, a quiet but real risk.",
      },
      neutral: {
        meaning:
          "This concerns a business review, the regular check-in that keeps executives aligned on value.",
        whyItMatters:
          "A held review reinforces the relationship, while a skipped one means alignment is slipping.",
      },
    },
    defaultTone: "neutral",
  },
  {
    // Security and compliance requests.
    match: [
      "sso",
      "security review",
      "soc 2",
      "soc2",
      "compliance",
      "saml",
      "scim",
      "penetration test",
    ],
    variants: {
      positive: {
        meaning:
          "A security or SSO request, typically as the customer scales its rollout.",
        whyItMatters:
          "These requests usually come from a maturing, committed customer, so it is often a buying signal.",
      },
      negative: {
        meaning:
          "A security or compliance concern is blocking progress.",
        whyItMatters:
          "Unmet security requirements can stall a rollout or hold up a renewal.",
      },
      neutral: {
        meaning:
          "The customer is asking about security or SSO as part of its rollout.",
        whyItMatters:
          "Security maturity usually signals a committed customer, but unmet requirements can block progress.",
      },
    },
    defaultTone: "positive",
  },
];

const GENERIC: SignalInfo = {
  meaning:
    "This is a behavioral or relationship indicator the agent weighed when reading the account.",
  whyItMatters:
    "It nudges the health read and the recommended next action up or down based on what it implies.",
  tone: "neutral",
};

// Pick the wording for a family given the resolved tone, falling back to the
// family default and then any available variant so we never render nothing.
function blurbFor(family: Family, tone: SignalTone): Blurb {
  return (
    family.variants[tone] ??
    family.variants[family.defaultTone] ??
    family.variants.neutral ??
    family.variants.negative ??
    family.variants.positive ?? {
      meaning: GENERIC.meaning,
      whyItMatters: GENERIC.whyItMatters,
    }
  );
}

/**
 * Return a structured, plain-language explanation for a free-form signal.
 * The explanation is direction-aware: the same concept reads as a risk or an
 * opportunity depending on the wording, so a negative signal never renders a
 * positive blurb. Combines up to two matched concepts; falls back to a generic
 * description so every signal is explained.
 */
export function signalInfo(text: string): SignalInfo {
  if (!text) return GENERIC;
  const lower = text.toLowerCase();
  const direction = detectDirection(lower);

  const matched: Family[] = [];
  for (const family of FAMILIES) {
    if (family.match.some((m) => lower.includes(m))) matched.push(family);
    if (matched.length >= 2) break; // keep explanations short
  }

  if (matched.length === 0) {
    return { ...GENERIC, tone: direction ?? "neutral" };
  }

  // Each family resolves to the detected direction when present, otherwise to
  // its own default read. The overall tone follows the first (sharpest) family.
  const toneFor = (family: Family): SignalTone => direction ?? family.defaultTone;
  const blurbs = matched.map((f) => blurbFor(f, toneFor(f)));

  return {
    meaning: blurbs.map((b) => b.meaning).join(" "),
    whyItMatters: blurbs.map((b) => b.whyItMatters).join(" "),
    tone: toneFor(matched[0]),
  };
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
