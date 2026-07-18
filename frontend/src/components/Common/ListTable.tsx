import { type ReactNode, useLayoutEffect, useRef, useState } from "react"

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
//
// That reservation is only applied when the rows actually overflow the
// max-height (see `needsScroll` below). A short list that fits without
// scrolling has nothing to reserve room for; reserving it anyway left an
// unfilled, transparent strip down the right edge of every row — most visible
// as a gap in the hover/selected highlight, since row backgrounds live on
// `<tr>` and can't paint past their own `<table>`'s width. The header and body
// must reserve the SAME amount (zero or the real gutter) or their colgroup
// widths drift apart.
const FROZEN_BG = "overflow-hidden bg-muted"

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
  const bodyRef = useRef<HTMLDivElement>(null)
  const bodyTableRef = useRef<HTMLTableElement>(null)

  // Whether the rows actually overflow maxHeightClassName right now. Observes
  // the body's own <table> (not the fixed-height wrapper) so a row count
  // change is what re-triggers the check, not the wrapper's own box size.
  const [needsScroll, setNeedsScroll] = useState(false)
  useLayoutEffect(() => {
    const wrapper = bodyRef.current
    const table = bodyTableRef.current
    if (!wrapper || !table) return
    const check = () =>
      setNeedsScroll(wrapper.scrollHeight > wrapper.clientHeight)
    check()
    const ro = new ResizeObserver(check)
    ro.observe(table)
    return () => ro.disconnect()
  }, [])
  const gutter = needsScroll ? "scrollbar-thin gutter-stable" : ""

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
      <div ref={headRef} className={cn(FROZEN_BG, gutter)}>
        <table className={TABLE} style={style}>
          {cols}
          <TableHeader className="bg-muted">{head}</TableHeader>
        </table>
      </div>

      <div
        ref={bodyRef}
        className={cn("overflow-auto", gutter, maxHeightClassName)}
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
        <table ref={bodyTableRef} className={TABLE} style={style}>
          {cols}
          <TableBody>{children}</TableBody>
        </table>
      </div>

      {footer ? (
        <div ref={footRef} className={cn(FROZEN_BG, gutter, "border-t")}>
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
