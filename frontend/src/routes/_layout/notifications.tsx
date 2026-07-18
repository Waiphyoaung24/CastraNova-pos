import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Bell } from "lucide-react"
import { useMemo, useState } from "react"

import {
  type NotificationChannel,
  type NotificationPreferencePublic,
  type NotificationPreferenceUpdate,
  NotificationsService,
} from "@/client"
import { ListShell } from "@/components/Common/ListShell"
import { ListTable } from "@/components/Common/ListTable"
import { PageHeader } from "@/components/Common/PageHeader"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { TableCell, TableHead, TableRow } from "@/components/ui/table"
import useCustomToast from "@/hooks/useCustomToast"
import { useIsMobile } from "@/hooks/useMobile"
import { channelLabel } from "@/lib/labels"
import { requireAuth } from "@/lib/route-guards"

// Both roles (FR-018): per-user opt-in for LINE/Viber/Telegram notification events.
export const Route = createFileRoute("/_layout/notifications")({
  component: Notifications,
  beforeLoad: requireAuth,
  head: () => ({
    meta: [{ title: "Notifications - CastraNova POS" }],
  }),
})

function humanize(value: string): string {
  const lower = value.replace(/_/g, " ").toLowerCase()
  return lower.charAt(0).toUpperCase() + lower.slice(1)
}

// Rows the user has never opted into are synthetic (id: null), so many rows
// can share id=null at once. Key on the pair instead, which is always unique.
function rowKey(p: { channel: string; event_type: string }): string {
  return `${p.channel}-${p.event_type}`
}

const CHANNEL_ORDER: NotificationChannel[] = ["TELEGRAM", "LINE", "VIBER"]

// Column widths in header order (Event, Telegram, LINE, Viber); sum to 100%.
const NOTIFICATION_WIDTHS = ["40%", "20%", "20%", "20%"]

type EventGrid = {
  eventType: string
  cells: Partial<Record<NotificationChannel, NotificationPreferencePublic>>
}

function groupByEvent(rows: NotificationPreferencePublic[]): EventGrid[] {
  const byEvent = new Map<string, EventGrid>()
  for (const row of rows) {
    let group = byEvent.get(row.event_type)
    if (!group) {
      group = { eventType: row.event_type, cells: {} }
      byEvent.set(row.event_type, group)
    }
    group.cells[row.channel] = row
  }
  return [...byEvent.values()]
}

function Notifications() {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()
  const isMobile = useIsMobile()

  const { data, isPending, isError, isPlaceholderData, isFetching } = useQuery({
    queryKey: ["notification-preferences"],
    queryFn: () => NotificationsService.readNotificationPreferences(),
  })
  const listLoading = isPlaceholderData || isFetching

  // Local, unsaved edits: rowKey -> the checkbox's new value. A transaction
  // (single PATCH) only starts when Save is clicked, not on every click.
  const [pending, setPending] = useState<Map<string, boolean>>(new Map())

  const saveMutation = useMutation({
    mutationFn: (preferences: NotificationPreferenceUpdate[]) =>
      NotificationsService.updateNotificationPreferences({
        requestBody: { preferences },
      }),
    onSuccess: () => {
      setPending(new Map())
      queryClient.invalidateQueries({ queryKey: ["notification-preferences"] })
      showSuccessToast("Preferences saved.")
    },
    onError: () => showErrorToast("Could not save preferences. Try again."),
  })

  const rows = useMemo(() => data ?? [], [data])
  const events = useMemo(() => groupByEvent(rows), [rows])

  function effectiveEnabled(p: NotificationPreferencePublic): boolean {
    return pending.get(rowKey(p)) ?? p.enabled
  }

  function toggle(p: NotificationPreferencePublic, checked: boolean) {
    setPending((prev) => {
      const next = new Map(prev)
      const key = rowKey(p)
      // Toggling back to the saved value clears its dirty entry, so Save
      // stays disabled unless something would actually change.
      if (checked === p.enabled) {
        next.delete(key)
      } else {
        next.set(key, checked)
      }
      return next
    })
  }

  function handleSave() {
    const byKey = new Map(rows.map((p) => [rowKey(p), p]))
    const preferences: NotificationPreferenceUpdate[] = [...pending.entries()]
      .map(([key, enabled]) => {
        const p = byKey.get(key)
        return p && { channel: p.channel, event_type: p.event_type, enabled }
      })
      .filter((p): p is NotificationPreferenceUpdate => !!p)
    if (preferences.length > 0) saveMutation.mutate(preferences)
  }

  const isDirty = pending.size > 0
  const controlsDisabled = saveMutation.isPending

  function checkboxFor(
    cell: NotificationPreferencePublic | undefined,
    event: string,
  ) {
    if (!cell) return null
    const label = `${channelLabel(cell.channel)} ${humanize(event)}`
    return (
      <Checkbox
        checked={effectiveEnabled(cell)}
        disabled={controlsDisabled || !cell.channel_connected}
        aria-label={label}
        title={
          cell.channel_connected
            ? undefined
            : `Connect ${channelLabel(cell.channel)} to enable`
        }
        onCheckedChange={(checked) => toggle(cell, checked === true)}
      />
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Notifications"
        description="Choose which events get sent to you on Telegram, LINE, or Viber."
      />

      <Alert>
        <Bell />
        <AlertTitle>Get notified your way</AlertTitle>
        <AlertDescription>
          Turn on the events you want pushed to Telegram, LINE, or Viber — low
          stock, stock requests, and more. A channel's switches are disabled
          until it's connected. Make your changes, then Save.
        </AlertDescription>
      </Alert>

      {isPending ? (
        <p className="text-muted-foreground py-6 text-center text-sm">
          Loading…
        </p>
      ) : isError ? (
        <p className="text-muted-foreground py-6 text-center text-sm">
          Could not load preferences.
        </p>
      ) : isMobile ? (
        <ListShell loading={listLoading}>
          <div className="space-y-3">
            {events.map(({ eventType, cells }) => (
              <div
                key={eventType}
                className="bg-card flex flex-col gap-3 rounded-lg border p-4"
              >
                <p className="text-sm font-medium">{humanize(eventType)}</p>
                <div className="flex items-center gap-4">
                  {CHANNEL_ORDER.map((channel) => (
                    <div key={channel} className="flex items-center gap-2">
                      {checkboxFor(cells[channel], eventType)}
                      <span className="text-muted-foreground text-xs">
                        {channelLabel(channel)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </ListShell>
      ) : (
        <ListShell loading={listLoading}>
          <ListTable
            widths={NOTIFICATION_WIDTHS}
            minWidth={560}
            head={
              <TableRow>
                <TableHead>Event</TableHead>
                {CHANNEL_ORDER.map((channel) => (
                  <TableHead key={channel} className="text-right">
                    {channelLabel(channel)}
                  </TableHead>
                ))}
              </TableRow>
            }
          >
            {events.map(({ eventType, cells }) => (
              <TableRow key={eventType}>
                <TableCell>{humanize(eventType)}</TableCell>
                {CHANNEL_ORDER.map((channel) => (
                  <TableCell
                    key={channel}
                    className="overflow-visible! text-right"
                  >
                    {checkboxFor(cells[channel], eventType)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </ListTable>
        </ListShell>
      )}

      {!isPending && !isError && (
        <div className="flex justify-end">
          <Button
            onClick={handleSave}
            disabled={!isDirty || saveMutation.isPending}
          >
            {saveMutation.isPending ? "Saving…" : "Save"}
          </Button>
        </div>
      )}
    </div>
  )
}
