import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { FileSpreadsheet, FileText } from "lucide-react"
import { useState } from "react"

import { ReportsService } from "@/client"
import { PageHeader } from "@/components/Common/PageHeader"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import useCustomToast from "@/hooks/useCustomToast"
import { downloadReport } from "@/lib/report-download"
import {
  channelMarginExport,
  currentMonth,
  formatThb,
  isValidMonth,
  type ReportFormat,
} from "@/lib/reports"
import { requireAdmin } from "@/lib/route-guards"

// Admin-only: revenue/COGS/margin are financial fields redacted from staff.
export const Route = createFileRoute("/_layout/channel-margin")({
  component: ChannelMargin,
  beforeLoad: requireAdmin,
  head: () => ({
    meta: [{ title: "Channel margin - CastraNova POS" }],
  }),
})

function ChannelMargin() {
  const { showErrorToast } = useCustomToast()
  const [month, setMonth] = useState(currentMonth())
  const validMonth = isValidMonth(month)

  const { data, isPending, isError } = useQuery({
    queryKey: ["channel-margin", month],
    queryFn: () => ReportsService.channelMargin({ month }),
    enabled: validMonth,
  })

  async function handleExport(fmt: ReportFormat) {
    try {
      const { path, filename } = channelMarginExport(month, fmt)
      await downloadReport(path, filename)
    } catch (e) {
      showErrorToast(e instanceof Error ? e.message : "Export failed.")
    }
  }

  const rows = data?.channels ?? []

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Channel margin"
        description="Monthly revenue, COGS and margin by channel."
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
          No activity for {month}.
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Channel</TableHead>
              <TableHead className="text-right">Revenue</TableHead>
              <TableHead className="text-right">COGS</TableHead>
              <TableHead className="text-right">Margin</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.channel}>
                <TableCell className="font-medium">{r.channel}</TableCell>
                <TableCell className="num text-right">
                  {formatThb(r.revenue_thb)}
                </TableCell>
                <TableCell className="num text-right">
                  {formatThb(r.cogs_thb)}
                </TableCell>
                <TableCell className="num text-right">
                  {formatThb(r.margin_thb)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
          <TableFooter>
            <TableRow>
              <TableCell className="font-medium">Total</TableCell>
              <TableCell className="num text-right">
                {formatThb(data.total_revenue_thb)}
              </TableCell>
              <TableCell className="num text-right">
                {formatThb(data.total_cogs_thb)}
              </TableCell>
              <TableCell className="num text-right">
                {formatThb(data.total_margin_thb)}
              </TableCell>
            </TableRow>
          </TableFooter>
        </Table>
      )}
    </div>
  )
}
