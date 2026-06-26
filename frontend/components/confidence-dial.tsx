import { cn } from "@/lib/utils";

export interface ConfidenceDialProps {
  /** value in 0..1 */
  value: number;
  label?: string;
  sublabel?: string;
  size?: number;
  thickness?: number;
  /** render the percentage as the big number in the center */
  showPercent?: boolean;
  className?: string;
}

// Single accent treatment for every confidence level: the arc is always the
// Claude orange accent on a hairline border track. Magnitude is read from the
// arc length and the number, not from a shifting hue.
const DIAL_TONE = {
  ring: "stroke-primary",
  text: "text-primary",
};

/**
 * Reusable radial confidence gauge. Works for any 0..1 ratio
 * (confidence, acceptance rate, suite score, etc.).
 */
export function ConfidenceDial({
  value,
  label,
  sublabel,
  size = 96,
  thickness = 8,
  showPercent = true,
  className,
}: ConfidenceDialProps) {
  const clamped = Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
  const pct = Math.round(clamped * 100);
  // Inset the ring by half a stroke. SVG clips its overflow by default, so a
  // radius of (size - thickness) / 2 lands the ring's outer edge (and its
  // round line cap) exactly on the viewBox edge, shaving the top of the arc.
  // Pulling it in keeps the whole dial inside its box, and thus its card.
  const r = size / 2 - thickness;
  const c = 2 * Math.PI * r;
  const dash = c * clamped;
  const tone = DIAL_TONE;
  const center = size / 2;

  return (
    <div className={cn("flex flex-col items-center gap-2", className)}>
      <div className="relative" style={{ width: size, height: size }}>
        <svg
          width={size}
          height={size}
          viewBox={`0 0 ${size} ${size}`}
          className="-rotate-90"
        >
          <circle
            cx={center}
            cy={center}
            r={r}
            fill="none"
            strokeWidth={thickness}
            className="stroke-border"
          />
          <circle
            cx={center}
            cy={center}
            r={r}
            fill="none"
            strokeWidth={thickness}
            strokeLinecap="round"
            strokeDasharray={`${dash} ${c}`}
            className={cn("transition-all duration-700 ease-out", tone.ring)}
          />
        </svg>
        {/* Only the percentage sits inside the ring (it is narrow and always
            fits). Any word label is rendered below the ring so it can never
            collide with the stroke. */}
        <div className="absolute inset-0 flex items-center justify-center">
          {showPercent ? (
            <span
              className={cn("font-mono font-semibold tabular-nums", tone.text)}
              style={{ fontSize: Math.round(size * 0.26), lineHeight: 1 }}
            >
              {pct}%
            </span>
          ) : null}
        </div>
      </div>
      {sublabel ? (
        <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
          {sublabel}
        </span>
      ) : null}
      {label ? (
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
      ) : null}
    </div>
  );
}

export default ConfidenceDial;
