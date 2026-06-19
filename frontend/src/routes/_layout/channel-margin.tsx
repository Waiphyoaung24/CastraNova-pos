import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { FileSpreadsheet, FileText } from "lucide-react"
import { useState } from "react"

import { ReportsService } from "@/client"
import { PageHeader } from "@/components/Common/PageHeader"
import { MetricBar } from "@/components/reports/MetricBar"
import { StatCard } from "@/components/reports/StatCard"
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
import { useIsMobile } from "@/hooks/useMobile"
import { downloadReport } from "@/lib/report-download"
import {
  channelMarginExport,
  currentMonth,
  formatPct,
  formatThb,
  isValidMonth,
  marginPct,
  momChange,
  pointChange,
  previousMonth,
  type ReportFormat,
  sharePct,
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
  const isMobile = useIsMobile()
  const [month, setMonth] = useState(currentMonth())
  const validMonth = isValidMonth(month)
  const prevMonth = previousMonth(month)

  const { data, isPending, isError } = useQuery({
    queryKey: ["channel-margin", month],
    queryFn: () => ReportsService.channelMargin({ month }),
    enabled: validMonth,
  })
  // Prior month, fetched only to power the month-over-month deltas. If it has no
  // data the deltas simply don't render — they're never required for the report.
  const { data: prevData } = useQuery({
    queryKey: ["channel-margin", prevMonth],
    queryFn: () => ReportsService.channelMargin({ month: prevMonth }),
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

  // Headline deltas vs. the prior month. COGS inverts — a rise is unfavourable.
  const revenueDelta =
    data && prevData
      ? momChange(data.total_revenue_thb, prevData.total_revenue_thb)
      : null
  const cogsDelta =
    data && prevData
      ? momChange(data.total_cogs_thb, prevData.total_cogs_thb, {
          invert: true,
        })
      : null
  const marginDelta =
    data && prevData
      ? momChange(data.total_margin_thb, prevData.total_margin_thb)
      : null
  const blendedMarginPct = data
    ? marginPct(data.total_margin_thb, data.total_revenue_thb)
    : null
  const prevBlendedMarginPct = prevData
    ? marginPct(prevData.total_margin_thb, prevData.total_revenue_thb)
    : null
  const marginPctDelta =
    blendedMarginPct != null
      ? pointChange(blendedMarginPct, prevBlendedMarginPct)
      : null

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

      {data && rows.length > 0 ? (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard
              label="Revenue"
              value={formatThb(data.total_revenue_thb)}
              delta={revenueDelta}
              deltaLabel="vs last month"
            />
            <StatCard
              label="COGS"
              value={formatThb(data.total_cogs_thb)}
              delta={cogsDelta}
              deltaLabel="vs last month"
            />
            <StatCard
              label="Margin"
              value={formatThb(data.total_margin_thb)}
              delta={marginDelta}
              deltaLabel="vs last month"
            />
            <StatCard
              label="Margin %"
              value={
                blendedMarginPct == null ? "—" : formatPct(blendedMarginPct)
              }
              delta={marginPctDelta}
              deltaLabel="vs last month"
            />
          </div>

          <div className="space-y-3 rounded-lg border p-4">
            <h2 className="text-sm font-semibold">Revenue mix by channel</h2>
            {rows.map((r) => {
              const share = sharePct(r.revenue_thb, data.total_revenue_thb)
              return (
                <MetricBar
                  key={r.channel}
                  label={r.channel}
                  pct={share}
                  value={`${formatThb(r.revenue_thb)} · ${formatPct(share)}`}
                />
              )
            })}
          </div>
        </>
      ) : null}

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
      ) : isMobile ? (
        <div className="space-y-3">
          {rows.map((r) => {
            const mPct = marginPct(r.margin_thb, r.revenue_thb)
            return (
              <div key={r.channel} className="bg-card rounded-lg border p-4">
                <div className="flex items-center justify-between gap-3">
                  <span className="font-medium">{r.channel}</span>
                  <span className="num text-lg font-semibold">
                    {formatThb(r.margin_thb)}
                  </span>
                </div>
                <dl className="text-muted-foreground mt-3 grid grid-cols-2 gap-y-1 border-t pt-3 text-sm">
                  <dt>Revenue</dt>
                  <dd className="num text-foreground text-right">
                    {formatThb(r.revenue_thb)}
                  </dd>
                  <dt>COGS</dt>
                  <dd className="num text-foreground text-right">
                    {formatThb(r.cogs_thb)}
                  </dd>
                  <dt>Margin %</dt>
                  <dd className="num text-foreground text-right">
                    {mPct == null ? "—" : formatPct(mPct)}
                  </dd>
                </dl>
              </div>
            )
          })}
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Channel</TableHead>
              <TableHead className="text-right">Revenue</TableHead>
              <TableHead className="text-right">COGS</TableHead>
              <TableHead className="text-right">Margin</TableHead>
              <TableHead className="text-right">Margin %</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => {
              const mPct = marginPct(r.margin_thb, r.revenue_thb)
              return (
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
                  <TableCell className="num text-right">
                    {mPct == null ? "—" : formatPct(mPct)}
                  </TableCell>
                </TableRow>
              )
            })}
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
              <TableCell className="num text-right">
                {blendedMarginPct == null ? "—" : formatPct(blendedMarginPct)}
              </TableCell>
            </TableRow>
          </TableFooter>
        </Table>
      )}
    </div>
  )
}
