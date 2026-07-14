import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { FileSpreadsheet, FileText } from "lucide-react"
import { useState } from "react"

import { ReportsService } from "@/client"
import { ListShell } from "@/components/Common/ListShell"
import { ListTable } from "@/components/Common/ListTable"
import { PageHeader } from "@/components/Common/PageHeader"
import { MetricBar } from "@/components/reports/MetricBar"
import { StatCard } from "@/components/reports/StatCard"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { TableCell, TableHead, TableRow } from "@/components/ui/table"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import useCustomToast from "@/hooks/useCustomToast"
import { useIsMobile } from "@/hooks/useMobile"
import { downloadReport } from "@/lib/report-download"
import {
  channelMarginExport,
  currentMonth,
  formatPct,
  formatThb,
  isValidMonth,
  type MarginChannel,
  type MarginGroupBy,
  marginPct,
  momChange,
  pointChange,
  previousMonth,
  type ReportFormat,
  sharePct,
} from "@/lib/reports"
import { requireAdmin } from "@/lib/route-guards"

const GROUP_BY_LABELS: Record<MarginGroupBy, string> = {
  channel: "Channel",
  product: "Product",
  customer: "Customer",
  project: "Project",
}

const ALL_CHANNELS = "all"

// Column widths in header order (Channel/Product/Customer/Project, Revenue,
// COGS, Margin, Margin %); sum to 100%.
const MARGIN_WIDTHS = ["32%", "17%", "17%", "17%", "17%"]

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
  const [groupBy, setGroupBy] = useState<MarginGroupBy>("channel")
  const [channel, setChannel] = useState<MarginChannel | undefined>(undefined)
  const validMonth = isValidMonth(month)
  const prevMonth = previousMonth(month)

  const { data, isPending, isError, isPlaceholderData, isFetching } = useQuery({
    queryKey: ["channel-margin", month, groupBy, channel ?? "all"],
    queryFn: () => ReportsService.channelMargin({ month, groupBy, channel }),
    enabled: validMonth,
    placeholderData: keepPreviousData,
  })
  const listLoading = isPlaceholderData || isFetching
  // Prior month, fetched only to power the month-over-month deltas. If it has no
  // data the deltas simply don't render — they're never required for the report.
  const { data: prevData } = useQuery({
    queryKey: ["channel-margin", prevMonth, groupBy, channel ?? "all"],
    queryFn: () =>
      ReportsService.channelMargin({ month: prevMonth, groupBy, channel }),
    enabled: validMonth,
  })

  async function handleExport(fmt: ReportFormat) {
    try {
      const { path, filename } = channelMarginExport(
        month,
        fmt,
        groupBy,
        channel,
      )
      await downloadReport(path, filename)
    } catch (e) {
      showErrorToast(e instanceof Error ? e.message : "Export failed.")
    }
  }

  const rows = data?.rows ?? []
  const firstColumnLabel = GROUP_BY_LABELS[groupBy]

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
        <div className="flex flex-col gap-1.5">
          <Label>Group by</Label>
          <Tabs
            value={groupBy}
            onValueChange={(v) => setGroupBy(v as MarginGroupBy)}
          >
            <TabsList>
              <TabsTrigger value="channel">Channel</TabsTrigger>
              <TabsTrigger value="product">Product</TabsTrigger>
              <TabsTrigger value="customer">Customer</TabsTrigger>
              <TabsTrigger value="project">Project</TabsTrigger>
            </TabsList>
          </Tabs>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="channel-filter">Channel</Label>
          <Select
            value={channel ?? ALL_CHANNELS}
            onValueChange={(v) =>
              setChannel(v === ALL_CHANNELS ? undefined : (v as MarginChannel))
            }
          >
            <SelectTrigger id="channel-filter" className="w-full sm:w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_CHANNELS}>All</SelectItem>
              <SelectItem value="SALE">SALE</SelectItem>
              <SelectItem value="MAINTENANCE">MAINTENANCE</SelectItem>
              <SelectItem value="PROJECT">PROJECT</SelectItem>
            </SelectContent>
          </Select>
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

          {groupBy === "channel" ? (
            <div className="space-y-3 rounded-lg border p-4">
              <h2 className="text-sm font-semibold">Revenue mix by channel</h2>
              {rows.map((r) => {
                const share = sharePct(r.revenue_thb, data.total_revenue_thb)
                return (
                  <MetricBar
                    key={r.key}
                    label={r.label}
                    pct={share}
                    value={`${formatThb(r.revenue_thb)} · ${formatPct(share)}`}
                  />
                )
              })}
            </div>
          ) : null}
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
        <ListShell loading={listLoading}>
          <div className="space-y-3">
            {rows.map((r) => {
              const mPct = marginPct(r.margin_thb, r.revenue_thb)
              return (
                <div key={r.key} className="bg-card rounded-lg border p-4">
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-medium">{r.label}</span>
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
        </ListShell>
      ) : (
        <ListShell loading={listLoading}>
          <ListTable
            widths={MARGIN_WIDTHS}
            minWidth={720}
            head={
              <TableRow>
                <TableHead>{firstColumnLabel}</TableHead>
                <TableHead className="text-right">Revenue</TableHead>
                <TableHead className="text-right">COGS</TableHead>
                <TableHead className="text-right">Margin</TableHead>
                <TableHead className="text-right">Margin %</TableHead>
              </TableRow>
            }
            footer={
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
            }
          >
            {rows.map((r) => {
              const mPct = marginPct(r.margin_thb, r.revenue_thb)
              return (
                <TableRow key={r.key}>
                  <TableCell className="font-medium">{r.label}</TableCell>
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
          </ListTable>
        </ListShell>
      )}
    </div>
  )
}
