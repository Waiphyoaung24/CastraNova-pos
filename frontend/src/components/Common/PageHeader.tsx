import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

interface PageHeaderProps {
  title: ReactNode
  description?: ReactNode
  /** Right-aligned slot: action buttons or a status pill. */
  actions?: ReactNode
  /** Inline element rendered beside the title (e.g. a status Badge). */
  badge?: ReactNode
  /** Eyebrow link rendered above the title (e.g. a back-link). */
  backLink?: ReactNode
  /** Extra content below the description (e.g. a sub-link). */
  footer?: ReactNode
  /** Merged into the h1 class — for `num` or responsive size overrides. */
  titleClassName?: string
}

export function PageHeader({
  title,
  description,
  actions,
  badge,
  backLink,
  footer,
  titleClassName,
}: PageHeaderProps) {
  return (
    <div>
      {backLink}
      <div
        className={cn(
          "flex items-start justify-between gap-3",
          backLink && "mt-2",
        )}
      >
        <div className="min-w-0">
          <div className="flex items-center gap-3">
            <h1
              className={cn(
                "text-2xl font-bold tracking-tight",
                titleClassName,
              )}
            >
              {title}
            </h1>
            {badge}
          </div>
          {description && (
            <p className="text-muted-foreground">{description}</p>
          )}
          {footer}
        </div>
        {actions}
      </div>
    </div>
  )
}
