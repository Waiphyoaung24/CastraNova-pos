import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { FileSpreadsheet, FileText } from "lucide-react"
import { useState } from "react"

import { ReportsService } from "@/client"
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
import { downloadReport } from "@/lib/report-download"
import { holdingPeriodExport, type ReportFormat } from "@/lib/reports"
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

function HoldingPeriod() {
  const { showErrorToast } = useCustomToast()
  const [overThresholdOnly, setOverThresholdOnly] = useState(false)

  const { data, isPending, isError } = useQuery({
    queryKey: ["holding-period", overThresholdOnly],
    queryFn: () => ReportsService.holdingPeriod({ overThresholdOnly }),
  })

  async function handleExport(fmt: ReportFormat) {
    try {
      const { path, filename } = holdingPeriodExport(overThresholdOnly, fmt)
      await downloadReport(path, filename)
    } catch (e) {
      showErrorToast(e instanceof Error ? e.message : "Export failed.")
    }
  }

  const rows = data?.rows ?? []

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Holding period</h1>
        <p className="text-muted-foreground">
          Days in stock per unit / batch
          {data ? `, flagged over ${data.threshold_days} days` : ""}.
        </p>
      </div>

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
      ) : (
        <Table>
          <TableHeader>
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
            {rows.map((r) => (
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
      )}
    </div>
  )
}
