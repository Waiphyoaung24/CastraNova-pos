import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { FileSpreadsheet, FileText } from "lucide-react"
import { useMemo, useState } from "react"

import { ReportsService } from "@/client"
import { LIST_SCROLL, ListShell } from "@/components/Common/ListShell"
import { PageHeader } from "@/components/Common/PageHeader"
import { MetricBar } from "@/components/reports/MetricBar"
import { StatCard } from "@/components/reports/StatCard"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import useCustomToast from "@/hooks/useCustomToast"
import { useIsMobile } from "@/hooks/useMobile"
import { downloadReport } from "@/lib/report-download"
import {
  holdingPeriodExport,
  type ReportFormat,
  sharePct,
  summarizeHolding,
} from "@/lib/reports"
import { requireAdmin } from "@/lib/route-guards"

// Admin-only: holding period exposes received_at/cost-adjacent ageing the
// staff dashboards intentionally omit.
export const Route = createFileRoute("/_layout/holding-period")({
  component: HoldingPeriod,
  beforeLoad: requireAdmin,
  head: () => ({
    meta: [{ title: "Holding period - CastraNova POS" }],
  }),
})

// Oldest bucket reads as a risk; escalate the bar colour with age.
const BUCKET_TONE: Record<string, "default" | "warning" | "danger"> = {
  "0–30": "default",
  "31–60": "default",
  "61–90": "warning",
  "90+": "danger",
}

function HoldingPeriod() {
  const { showErrorToast } = useCustomToast()
  const isMobile = useIsMobile()
  const [overThresholdOnly, setOverThresholdOnly] = useState(false)

  const { data, isPending, isError, isPlaceholderData, isFetching } = useQuery({
    queryKey: ["holding-period", overThresholdOnly],
    queryFn: () => ReportsService.holdingPeriod({ overThresholdOnly }),
    placeholderData: keepPreviousData,
  })
  const listLoading = isPlaceholderData || isFetching

  async function handleExport(fmt: ReportFormat) {
    try {
      const { path, filename } = holdingPeriodExport(overThresholdOnly, fmt)
      await downloadReport(path, filename)
    } catch (e) {
      showErrorToast(e instanceof Error ? e.message : "Export failed.")
    }
  }

  const rows = data?.rows ?? []
  const summary = useMemo(() => summarizeHolding(rows), [rows])
  // Oldest first — the rows a CFO cares about (cash tied up longest) lead.
  const sortedRows = useMemo(
    () => [...rows].sort((a, b) => b.holding_days - a.holding_days),
    [rows],
  )

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Holding period"
        description={
          <>
            Days in stock per unit / batch
            {data ? `, flagged over ${data.threshold_days} days` : ""}.
          </>
        }
      />

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <Checkbox
            id="over-threshold"
            checked={overThresholdOnly}
            onCheckedChange={(v) => setOverThresholdOnly(v === true)}
          />
          <Label htmlFor="over-threshold">Over threshold only</Label>
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={() => handleExport("pdf")}
          disabled={!data}
        >
          <FileText className="size-4" />
          PDF
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => handleExport("xlsx")}
          disabled={!data}
        >
          <FileSpreadsheet className="size-4" />
          Excel
        </Button>
      </div>

      {rows.length > 0 ? (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            <StatCard label="Lines" value={summary.lineCount} />
            <StatCard label="Units on hand" value={summary.totalQty} />
            <StatCard
              label="Over threshold"
              value={summary.overThresholdCount}
              hint={`of ${summary.lineCount} lines`}
            />
            <StatCard label="Oldest" value={`${summary.maxDays} days`} />
            <StatCard label="Average age" value={`${summary.avgDays} days`} />
          </div>

          <div className="space-y-3 rounded-lg border p-4">
            <h2 className="text-sm font-semibold">Ageing distribution</h2>
            {summary.buckets.map((b) => (
              <MetricBar
                key={b.label}
                label={`${b.label} days`}
                pct={sharePct(String(b.count), String(summary.lineCount))}
                value={`${b.count} lines · ${b.qty} qty`}
                tone={BUCKET_TONE[b.label]}
              />
            ))}
          </div>
        </>
      ) : null}

      {isPending ? (
        <p className="text-muted-foreground py-6 text-center text-sm">
          Loading…
        </p>
      ) : isError ? (
        <p className="text-muted-foreground py-6 text-center text-sm">
          Could not load the report.
        </p>
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground py-6 text-center text-sm">
          {overThresholdOnly
            ? "Nothing is over the holding threshold."
            : "No stock on hand."}
        </p>
      ) : isMobile ? (
        <ListShell loading={listLoading}>
          <div className="space-y-3">
            {sortedRows.map((r) => (
              <div
                key={`${r.product_id}-${r.reference}`}
                className="bg-card rounded-lg border p-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="num font-medium">{r.sku}</span>
                      <Badge variant="secondary">{r.tracking_mode}</Badge>
                    </div>
                    <p className="num text-muted-foreground truncate text-sm">
                      {r.reference}
                    </p>
                  </div>
                  <div className="shrink-0 text-right">
                    {r.over_threshold ? (
                      <Badge variant="destructive">{r.holding_days} days</Badge>
                    ) : (
                      <span className="num font-semibold">
                        {r.holding_days} days
                      </span>
                    )}
                    <div className="text-muted-foreground mt-1 text-xs">
                      qty {r.quantity}
                    </div>
                  </div>
                </div>
                <p className="text-muted-foreground mt-2 text-xs">
                  Received {new Date(r.received_at).toLocaleDateString()}
                </p>
              </div>
            ))}
          </div>
        </ListShell>
      ) : (
        <ListShell loading={listLoading}>
          <Table containerClassName={LIST_SCROLL}>
            <TableHeader className="bg-background sticky top-0 z-10">
              <TableRow>
                <TableHead>SKU</TableHead>
                <TableHead>Reference</TableHead>
                <TableHead>Mode</TableHead>
                <TableHead>Received</TableHead>
                <TableHead className="text-right">Qty</TableHead>
                <TableHead className="text-right">Holding days</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortedRows.map((r) => (
                <TableRow key={`${r.product_id}-${r.reference}`}>
                  <TableCell className="num font-medium">{r.sku}</TableCell>
                  <TableCell className="num">{r.reference}</TableCell>
                  <TableCell>
                    <Badge variant="secondary">{r.tracking_mode}</Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {new Date(r.received_at).toLocaleDateString()}
                  </TableCell>
                  <TableCell className="num text-right">{r.quantity}</TableCell>
                  <TableCell className="num text-right">
                    {r.over_threshold ? (
                      <Badge variant="destructive">{r.holding_days}</Badge>
                    ) : (
                      r.holding_days
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </ListShell>
      )}
    </div>
  )
}
