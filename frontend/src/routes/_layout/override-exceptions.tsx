import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { FileSpreadsheet, FileText } from "lucide-react"
import { useState } from "react"

import { ReportsService } from "@/client"
import { PageHeader } from "@/components/Common/PageHeader"
import { StatCard } from "@/components/reports/StatCard"
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
import { useIsMobile } from "@/hooks/useMobile"
import { formatDeviationPct } from "@/lib/pricing-overrides"
import { downloadReport } from "@/lib/report-download"
import {
  currentMonth,
  formatPct,
  formatThb,
  isValidMonth,
  overrideExceptionsExport,
  type ReportFormat,
  sharePct,
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

/** "62% of total" caption for an outcome count, omitted when there are none. */
function shareHint(part: number, total: number): string | undefined {
  if (total === 0) return undefined
  return `${formatPct(sharePct(String(part), String(total)), 0)} of total`
}

function formatDate(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleDateString() : "—"
}

function OverrideExceptions() {
  const { showErrorToast } = useCustomToast()
  const isMobile = useIsMobile()
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
      <PageHeader
        title="Override exceptions"
        description="Monthly pricing-override requests and their approval outcomes."
      />

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
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <StatCard label="Total" value={data.total} />
          <StatCard
            label="Auto-approved"
            value={data.auto_approved}
            hint={shareHint(data.auto_approved, data.total)}
          />
          <StatCard
            label="Pending"
            value={data.pending}
            hint={shareHint(data.pending, data.total)}
          />
          <StatCard
            label="Approved"
            value={data.approved}
            hint={shareHint(data.approved, data.total)}
          />
          <StatCard
            label="Rejected"
            value={data.rejected}
            hint={shareHint(data.rejected, data.total)}
          />
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
      ) : isMobile ? (
        <div className="space-y-3">
          {rows.map((r) => (
            <div key={r.id} className="bg-card rounded-lg border p-4">
              <div className="flex items-start justify-between gap-3">
                <span className="num font-medium">{r.sku}</span>
                <Badge variant="secondary">{r.state}</Badge>
              </div>
              <div className="mt-2 flex items-baseline gap-2 text-sm">
                <span className="num text-muted-foreground line-through">
                  {formatThb(r.default_price_thb)}
                </span>
                <span className="num font-semibold">
                  {formatThb(r.requested_price_thb)}
                </span>
                <span className="num text-muted-foreground">
                  ({formatDeviationPct(r.deviation_pct)})
                </span>
              </div>
              {r.reason ? (
                <p className="text-muted-foreground mt-2 text-sm">{r.reason}</p>
              ) : null}
              <p className="text-muted-foreground mt-2 border-t pt-2 text-xs">
                Raised {formatDate(r.created_at)} · Decided{" "}
                {formatDate(r.decided_at)}
              </p>
            </div>
          ))}
        </div>
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
              <TableHead>Raised</TableHead>
              <TableHead>Decided</TableHead>
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
                <TableCell className="text-muted-foreground num">
                  {formatDate(r.created_at)}
                </TableCell>
                <TableCell className="text-muted-foreground num">
                  {formatDate(r.decided_at)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
