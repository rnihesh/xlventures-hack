// Compact, tooltip-friendly explanations for the supporting / contradicting
// signal chips on a recommendation card.
//
// Signals arrive as free-form text ("Executive sponsor departed", "Hit 95% seat
// utilisation"), so the explanation must be DIRECTION-AWARE: the same concept
// reads as a risk or an opportunity depending on the wording. Rather than keep a
// second, drifting copy of that logic here, we delegate to the canonical
// direction-aware helper in signal-info so a negative signal can never render a
// positive blurb.

import { explainSignal as composeExplanation } from "./signal-info";

/**
 * Return a short plain-language explanation for a free-form signal string.
 * Direction-aware: "Executive sponsor departed" reads as a lost champion (risk),
 * while "Hit 95% seat utilisation" reads as strong adoption (opportunity).
 */
export function explainSignal(text: string): string {
  return composeExplanation(text);
}

// Section-level explanations for the supporting / contradicting groupings.
export const SIGNAL_GROUP_HELP = {
  supporting:
    "Supporting signals are evidence that backs this recommendation: account facts that raise the agent's confidence in the play.",
  contradicting:
    "Contradicting signals are evidence that cuts against this recommendation: facts that lower confidence or argue for caution.",
} as const;
