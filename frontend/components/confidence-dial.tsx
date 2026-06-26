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

function toneFor(v: number) {
  if (v >= 0.75)
    return {
      ring: "stroke-emerald-500",
      text: "text-emerald-500",
      glow: "shadow-emerald-500/20",
    };
  if (v >= 0.5)
    return {
      ring: "stroke-amber-500",
      text: "text-amber-500",
      glow: "shadow-amber-500/20",
    };
  return {
    ring: "stroke-rose-500",
    text: "text-rose-500",
    glow: "shadow-rose-500/20",
  };
}

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
  const r = (size - thickness) / 2;
  const c = 2 * Math.PI * r;
  const dash = c * clamped;
  const tone = toneFor(clamped);
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
            className="stroke-muted"
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
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          {showPercent ? (
            <span className={cn("text-xl font-semibold tabular-nums", tone.text)}>
              {pct}%
            </span>
          ) : null}
          {sublabel ? (
            <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
              {sublabel}
            </span>
          ) : null}
        </div>
      </div>
      {label ? (
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
      ) : null}
    </div>
  );
}

export default ConfidenceDial;
