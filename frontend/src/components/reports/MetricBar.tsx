import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

type MetricTone = "default" | "warning" | "danger"

interface MetricBarProps {
  label: ReactNode
  /** Fill width as a 0–100 percentage; clamped defensively. */
  pct: number
  /** Right-aligned value text (e.g. "฿12,000 · 34%"). */
  value?: ReactNode
  tone?: MetricTone
  className?: string
}

const TONE_FILL: Record<MetricTone, string> = {
  default: "bg-primary",
  warning: "bg-amber-500",
  danger: "bg-destructive",
}

/**
 * A labelled horizontal bar for proportional report data — revenue mix per
 * channel, ageing-bucket distribution. The value is always rendered as text, so
 * the bar itself is decorative (aria-hidden) rather than a chart that needs ARIA.
 */
export function MetricBar({
  label,
  pct,
  value,
  tone = "default",
  className,
}: MetricBarProps) {
  const width = Math.max(0, Math.min(100, pct))
  return (
    <div className={cn("space-y-1.5", className)}>
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="text-muted-foreground">{label}</span>
        {value != null ? (
          <span className="num font-medium">{value}</span>
        ) : null}
      </div>
      <div className="bg-muted h-2 w-full overflow-hidden rounded-full">
        <div
          className={cn("h-full rounded-full", TONE_FILL[tone])}
          style={{ width: `${width}%` }}
          aria-hidden="true"
        />
      </div>
    </div>
  )
}
