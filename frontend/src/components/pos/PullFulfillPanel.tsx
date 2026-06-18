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
  lineCap,
  projectedPullState,
} from "@/lib/pull-fulfill"

interface PullFulfillPanelProps {
  pull: ProjectPullPublic
  projectLabel: string
  customerLabel: string
  /** product_id -> model name, for PART line labels. */
  productNames: Map<string, string>
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

function lineLabel(
  line: ProjectPullLinePublic,
  productNames: Map<string, string>,
): string {
  if (line.line_kind === "UNIT") return line.unit_serial ?? "(no serial)"
  return productNames.get(line.product_id) ?? line.product_id
}

export function PullFulfillPanel({
  pull,
  projectLabel,
  customerLabel,
  productNames,
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

  return (
    <div className="space-y-4">
      <Button type="button" variant="ghost" size="sm" onClick={onBack}>
        <ArrowLeft /> Back to queue
      </Button>

      <div>
        <h2 className="text-lg font-semibold">{projectLabel}</h2>
        <p className="text-muted-foreground text-sm">{customerLabel}</p>
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
        <Badge variant="outline">This pull is {pull.state}</Badge>
      )}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Line</TableHead>
            <TableHead className="text-muted-foreground">Type</TableHead>
            <TableHead className="text-center">Fulfilled / Requested</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {pull.lines.map((line) => {
            const cap = lineCap(line)
            const qty = draft[line.id] ?? 0
            return (
              <TableRow key={line.id}>
                <TableCell className="num font-medium">
                  {lineLabel(line, productNames)}
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
                      aria-label={`Decrease ${lineLabel(line, productNames)}`}
                      onClick={() => onQtyChange(line, qty - 1)}
                    >
                      <Minus />
                    </Button>
                    <span className="num w-16 text-center" aria-hidden="true">
                      {qty} / {cap}
                    </span>
                    <span className="sr-only" aria-live="polite">
                      {`${lineLabel(line, productNames)} ${qty} of ${cap}`}
                    </span>
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      className="size-11"
                      disabled={!canFulfill || qty >= cap}
                      aria-label={`Increase ${lineLabel(line, productNames)}`}
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
        <span className="text-muted-foreground text-sm">Will settle as</span>
        <Badge variant={projected === "FULFILLED" ? "default" : "destructive"}>
          {projected}
        </Badge>
      </div>

      <button
        type="button"
        onClick={onSubmit}
        disabled={!canFulfill}
        className="bg-cta text-cta-foreground hover:bg-cta/90 focus-visible:ring-ring focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none flex h-11 w-full items-center justify-center rounded-md px-4 text-sm font-semibold disabled:pointer-events-none disabled:opacity-50"
      >
        {isPending ? "Fulfilling…" : "Fulfill pull"}
      </button>
    </div>
  )
}
