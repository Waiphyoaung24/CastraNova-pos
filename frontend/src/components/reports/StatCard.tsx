import { ArrowDown, ArrowUp } from "lucide-react"
import type { ReactNode } from "react"

import type { MetricDelta } from "@/lib/reports"
import { cn } from "@/lib/utils"

interface StatCardProps {
  label: string
  value: ReactNode
  /** Month-over-month (or similar) change pill; omit when there's no comparison. */
  delta?: MetricDelta | null
  /** Caption shown beside the delta (e.g. "vs last month"). */
  deltaLabel?: string
  /** Secondary line shown when there's no delta (e.g. "62% of total"). */
  hint?: ReactNode
  className?: string
}

/**
 * A single headline figure for the CFO report bands: big number, a label, and
 * either a coloured up/down delta or a muted hint. "Good" is the caller's call
 * (revenue up is good, COGS up is not), so colour comes from `delta.good`, not
 * the direction.
 */
export function StatCard({
  label,
  value,
  delta,
  deltaLabel,
  hint,
  className,
}: StatCardProps) {
  return (
    <div className={cn("bg-card rounded-lg border p-4", className)}>
      <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
        {label}
      </p>
      <p className="num mt-1 text-2xl font-semibold">{value}</p>
      {delta ? (
        <p
          className={cn(
            "mt-1 flex items-center gap-1 text-xs",
            delta.direction === "flat"
              ? "text-muted-foreground"
              : delta.good
                ? "text-emerald-600 dark:text-emerald-400"
                : "text-destructive",
          )}
        >
          {delta.direction === "up" ? (
            <ArrowUp className="size-3" aria-hidden="true" />
          ) : delta.direction === "down" ? (
            <ArrowDown className="size-3" aria-hidden="true" />
          ) : null}
          <span className="num font-medium">{delta.value}</span>
          {deltaLabel ? (
            <span className="text-muted-foreground">{deltaLabel}</span>
          ) : null}
        </p>
      ) : hint ? (
        <p className="text-muted-foreground mt-1 text-xs">{hint}</p>
      ) : null}
    </div>
  )
}
