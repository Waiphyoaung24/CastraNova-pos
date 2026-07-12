import { type ReactNode, useRef } from "react"

import { TableBody, TableFooter, TableHeader } from "@/components/ui/table"
import { cn } from "@/lib/utils"

interface ListTableProps {
  /**
   * Column widths in column order, e.g. ["17%", "17%", "16%", …]. They must sum
   * to 100%: `table-fixed` hands out exactly what the colgroup asks for, so a
   * short sum leaves a ragged gap at the right edge. The same colgroup is
   * rendered into every table below, which is what keeps them aligned.
   */
  widths: string[]
  /** The header's `<TableRow><TableHead/>…</TableRow>`. Lives in its own table. */
  head: ReactNode
  /** The body's `<TableRow>`s. */
  children: ReactNode
  /** Optional totals `<TableRow>`, pinned below the rows in a third table. */
  footer?: ReactNode
  /**
   * Floor for the table width, in px. Set it whenever the columns cannot
   * survive the narrowest desktop viewport (768px ⇒ ~460px of table): the
   * tables stop shrinking and the body scroller gains a horizontal scrollbar,
   * with the header/footer mirroring its scrollLeft.
   */
  minWidth?: number
  /** Overrides the default 60vh cap on the row area. */
  maxHeightClassName?: string
  className?: string
}

// `table-fixed` is what lets the colgroup — rather than the content — decide the
// columns, so the header table and the body table land on identical geometry.
const TABLE =
  "w-full table-fixed caption-bottom text-sm " +
  "[&_th]:overflow-hidden [&_th]:text-ellipsis " +
  "[&_td]:overflow-hidden [&_td]:text-ellipsis"

// The header/footer wrappers are `overflow-hidden`, which still makes them
// scroll containers — so `scrollbar-gutter: stable` reserves exactly the gutter
// the body scroller consumes, and we can drive their scrollLeft from JS.
// `scrollbar-thin` must be on all three: the reserved gutter is derived from the
// used scrollbar width, so a wrapper without it would reserve a *wider* default
// gutter and the columns would drift apart.
const FROZEN = "scrollbar-thin gutter-stable overflow-hidden bg-muted"

/**
 * The list-table shell: a frozen, tinted header band above a scrolling row
 * area, so the vertical scrollbar runs beside the rows only. Wrap it in
 * `<ListShell loading>` for the refetch overlay.
 */
export function ListTable({
  widths,
  head,
  children,
  footer,
  minWidth,
  maxHeightClassName = "max-h-[60vh]",
  className,
}: ListTableProps) {
  const headRef = useRef<HTMLDivElement>(null)
  const footRef = useRef<HTMLDivElement>(null)

  const cols = (
    <colgroup>
      {widths.map((w, i) => (
        <col key={i} style={{ width: w }} />
      ))}
    </colgroup>
  )
  const style = minWidth ? { minWidth: `${minWidth}px` } : undefined

  return (
    <div className={cn("overflow-hidden rounded-lg border", className)}>
      <div ref={headRef} className={FROZEN}>
        <table className={TABLE} style={style}>
          {cols}
          <TableHeader className="bg-muted">{head}</TableHeader>
        </table>
      </div>

      <div
        className={cn(
          "scrollbar-thin gutter-stable overflow-auto",
          maxHeightClassName,
        )}
        onScroll={
          minWidth
            ? (e) => {
                const left = e.currentTarget.scrollLeft
                if (headRef.current) headRef.current.scrollLeft = left
                if (footRef.current) footRef.current.scrollLeft = left
              }
            : undefined
        }
      >
        <table className={TABLE} style={style}>
          {cols}
          <TableBody>{children}</TableBody>
        </table>
      </div>

      {footer ? (
        <div ref={footRef} className={cn(FROZEN, "border-t")}>
          <table className={TABLE} style={style}>
            {cols}
            <TableFooter className="border-t-0 bg-transparent">
              {footer}
            </TableFooter>
          </table>
        </div>
      ) : null}
    </div>
  )
}
