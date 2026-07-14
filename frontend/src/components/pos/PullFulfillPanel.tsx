import { ArrowLeft, Minus, Plus } from "lucide-react"
import type { Ref } from "react"
import type {
  ProjectPullLinePublic,
  ProjectPullPublic,
} from "@/client/types.gen"
import { ScanField, type ScanFieldHandle } from "@/components/ScanField"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  type FulfillDraft,
  fulfilledLineCount,
  lineCap,
  projectedPullState,
} from "@/lib/pull-fulfill"

interface PullFulfillPanelProps {
  pull: ProjectPullPublic
  projectLabel: string
  customerLabel: string
  draft: FulfillDraft
  scanRef: Ref<ScanFieldHandle>
  onScan: (code: string) => void
  isSearching: boolean
  notFound: boolean
  isError: boolean
  scanNotice: string
  onQtyChange: (line: ProjectPullLinePublic, qty: number) => void
  onSubmit: () => void
  onBack: () => void
  isPending: boolean
}

function lineLabel(line: ProjectPullLinePublic): string {
  if (line.line_kind === "UNIT") return line.unit_serial ?? "(no serial)"
  return `${line.model_name} (${line.product_sku})`
}

export function PullFulfillPanel({
  pull,
  projectLabel,
  customerLabel,
  draft,
  scanRef,
  onScan,
  isSearching,
  notFound,
  isError,
  scanNotice,
  onQtyChange,
  onSubmit,
  onBack,
  isPending,
}: PullFulfillPanelProps) {
  const canFulfill = pull.state === "PENDING" && !isPending
  const projected = projectedPullState(pull.lines, draft)
  const given = fulfilledLineCount(pull.lines, draft)
  const total = pull.lines.length
  const pct = total === 0 ? 0 : Math.round((given / total) * 100)
  const stateWord =
    pull.state === "FULFILLED"
      ? "done"
      : pull.state === "CANCELLED"
        ? "cancelled"
        : "short"

  return (
    <div className="space-y-4">
      <Button type="button" variant="ghost" size="sm" onClick={onBack}>
        <ArrowLeft /> Back to requests
      </Button>

      <div>
        <h2 className="text-lg font-semibold">{projectLabel}</h2>
        <p className="text-muted-foreground text-sm">{customerLabel}</p>
      </div>

      <div>
        <p className="text-sm font-medium">
          Given out: {given} of {total} {total === 1 ? "item" : "items"}
        </p>
        <div className="bg-muted mt-2 h-2 w-full overflow-hidden rounded-full">
          <div className="bg-cta h-full" style={{ width: `${pct}%` }} />
        </div>
      </div>

      {pull.state === "PENDING" ? (
        <ScanField
          ref={scanRef}
          label="Scan item"
          clearOnScan
          onScan={onScan}
          status={
            <>
              <p
                aria-live="assertive"
                className="text-muted-foreground min-h-5 text-sm"
              >
                {isError
                  ? "Scan lookup failed. Try again."
                  : notFound
                    ? "No item found for that code."
                    : scanNotice}
              </p>
              <p
                aria-live="polite"
                className="text-muted-foreground min-h-5 text-sm"
              >
                {isSearching ? "Searching…" : ""}
              </p>
            </>
          }
        />
      ) : (
        <Badge variant="outline">This request is {stateWord}</Badge>
      )}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Item</TableHead>
            <TableHead className="text-muted-foreground">Kind</TableHead>
            <TableHead className="text-center">Given / Needed</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {pull.lines.map((line) => {
            const cap = lineCap(line)
            const qty = draft[line.id] ?? 0
            return (
              <TableRow key={line.id}>
                <TableCell className="num font-medium">
                  {lineLabel(line)}
                </TableCell>
                <TableCell className="text-muted-foreground text-xs">
                  {line.line_kind}
                </TableCell>
                <TableCell>
                  <div className="flex items-center justify-center gap-1">
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      className="size-11"
                      disabled={!canFulfill || qty <= 0}
                      aria-label={`Decrease ${lineLabel(line)}`}
                      onClick={() => onQtyChange(line, qty - 1)}
                    >
                      <Minus />
                    </Button>
                    <span className="num w-16 text-center" aria-hidden="true">
                      {qty} / {cap}
                    </span>
                    <span className="sr-only" aria-live="polite">
                      {`${lineLabel(line)} ${qty} of ${cap}`}
                    </span>
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      className="size-11"
                      disabled={!canFulfill || qty >= cap}
                      aria-label={`Increase ${lineLabel(line)}`}
                      onClick={() => onQtyChange(line, qty + 1)}
                    >
                      <Plus />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>

      <div className="flex items-center justify-end gap-4">
        <span className="text-muted-foreground text-sm">When you finish</span>
        <Badge variant={projected === "FULFILLED" ? "default" : "destructive"}>
          {projected === "FULFILLED" ? "All items ready" : "Some items short"}
        </Badge>
      </div>

      <button
        type="button"
        onClick={onSubmit}
        disabled={!canFulfill}
        className="bg-cta text-cta-foreground hover:bg-cta/90 focus-visible:ring-ring focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none flex h-11 w-full items-center justify-center rounded-md px-4 text-sm font-semibold disabled:pointer-events-none disabled:opacity-50"
      >
        {isPending ? "Saving…" : "Done — give out parts"}
      </button>
    </div>
  )
}
