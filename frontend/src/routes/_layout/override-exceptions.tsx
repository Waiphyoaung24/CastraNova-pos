import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { FileSpreadsheet, FileText } from "lucide-react"
import { useState } from "react"

import { ReportsService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
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
import { formatDeviationPct } from "@/lib/pricing-overrides"
import { downloadReport } from "@/lib/report-download"
import {
  currentMonth,
  formatThb,
  isValidMonth,
  overrideExceptionsExport,
  type ReportFormat,
} from "@/lib/reports"
import { requireAdmin } from "@/lib/route-guards"

// Admin-only: monthly pricing-override exceptions (FR-010, §8). Audit view of
// every override request raised in a month, with the approval breakdown.
export const Route = createFileRoute("/_layout/override-exceptions")({
  component: OverrideExceptions,
  beforeLoad: requireAdmin,
  head: () => ({
    meta: [{ title: "Override exceptions - CastraNova POS" }],
  }),
})

function OverrideExceptions() {
  const { showErrorToast } = useCustomToast()
  const [month, setMonth] = useState(currentMonth())
  const validMonth = isValidMonth(month)

  const { data, isPending, isError } = useQuery({
    queryKey: ["override-exceptions", month],
    queryFn: () => ReportsService.overrideExceptions({ month }),
    enabled: validMonth,
  })

  async function handleExport(fmt: ReportFormat) {
    try {
      const { path, filename } = overrideExceptionsExport(month, fmt)
      await downloadReport(path, filename)
    } catch (e) {
      showErrorToast(e instanceof Error ? e.message : "Export failed.")
    }
  }

  const rows = data?.rows ?? []

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">
          Override exceptions
        </h1>
        <p className="text-muted-foreground">
          Monthly pricing-override requests and their approval outcomes.
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="month">Month</Label>
          <Input
            id="month"
            type="month"
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            className="w-full sm:w-48"
          />
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

      {data && (
        <div className="flex flex-wrap gap-2">
          <Count label="Total" value={data.total} />
          <Count label="Auto-approved" value={data.auto_approved} />
          <Count label="Pending" value={data.pending} />
          <Count label="Approved" value={data.approved} />
          <Count label="Rejected" value={data.rejected} />
        </div>
      )}

      {!validMonth ? (
        <p className="text-muted-foreground py-6 text-center text-sm">
          Pick a month to view the report.
        </p>
      ) : isPending ? (
        <p className="text-muted-foreground py-6 text-center text-sm">
          Loading…
        </p>
      ) : isError ? (
        <p className="text-muted-foreground py-6 text-center text-sm">
          Could not load the report.
        </p>
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground py-6 text-center text-sm">
          No override requests for {month}.
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Product</TableHead>
              <TableHead className="text-right">Default</TableHead>
              <TableHead className="text-right">Requested</TableHead>
              <TableHead className="text-right">Deviation</TableHead>
              <TableHead>Reason</TableHead>
              <TableHead>State</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.id}>
                <TableCell className="num font-medium">{r.sku}</TableCell>
                <TableCell className="num text-right">
                  {formatThb(r.default_price_thb)}
                </TableCell>
                <TableCell className="num text-right">
                  {formatThb(r.requested_price_thb)}
                </TableCell>
                <TableCell className="num text-right">
                  {formatDeviationPct(r.deviation_pct)}
                </TableCell>
                <TableCell className="text-muted-foreground max-w-xs truncate">
                  {r.reason}
                </TableCell>
                <TableCell>
                  <Badge variant="secondary">{r.state}</Badge>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}

function Count({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-muted/50 rounded-md px-3 py-2">
      <span className="text-muted-foreground text-xs uppercase tracking-wide">
        {label}
      </span>{" "}
      <span className="num font-semibold">{value}</span>
    </div>
  )
}
