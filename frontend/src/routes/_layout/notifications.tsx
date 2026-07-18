import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Bell } from "lucide-react"

import {
  type NotificationPreferenceUpdate,
  NotificationsService,
} from "@/client"
import { ListShell } from "@/components/Common/ListShell"
import { ListTable } from "@/components/Common/ListTable"
import { PageHeader } from "@/components/Common/PageHeader"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
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

// Column widths in header order (Send to, Event, Enabled); sum to 100%.
const NOTIFICATION_WIDTHS = ["22%", "66%", "12%"]

function Notifications() {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()
  const isMobile = useIsMobile()

  const { data, isPending, isError, isPlaceholderData, isFetching } = useQuery({
    queryKey: ["notification-preferences"],
    queryFn: () => NotificationsService.readNotificationPreferences(),
  })
  const listLoading = isPlaceholderData || isFetching

  const updateMutation = useMutation({
    mutationFn: (pref: NotificationPreferenceUpdate) =>
      NotificationsService.updateNotificationPreferences({
        requestBody: { preferences: [pref] },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notification-preferences"] })
      showSuccessToast("Preference updated.")
    },
    onError: () =>
      showErrorToast("Could not update the preference. Try again."),
  })

  const rows = data ?? []

  // Rows the user has never opted into are synthetic (id: null), so many rows
  // can share id=null at once. Key on the pair instead, which is always unique.
  const rowKey = (p: { channel: string; event_type: string }) =>
    `${p.channel}-${p.event_type}`

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Notifications"
        description="Choose which events get sent to you on LINE, Viber, or Telegram."
      />

      <Alert>
        <Bell />
        <AlertTitle>Get notified your way</AlertTitle>
        <AlertDescription>
          Turn on the events you want pushed to LINE, Viber, or Telegram — low
          stock, stock requests, and more. Toggle each one on or off; changes
          save instantly.
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
            {rows.map((p) => (
              <div
                key={rowKey(p)}
                className="bg-card flex items-center justify-between gap-3 rounded-lg border p-4"
              >
                <div className="min-w-0">
                  <Badge variant="secondary">{channelLabel(p.channel)}</Badge>
                  <p className="mt-1 truncate text-sm">
                    {humanize(p.event_type)}
                  </p>
                </div>
                <Checkbox
                  checked={p.enabled}
                  disabled={updateMutation.isPending}
                  aria-label={`${channelLabel(p.channel)} ${humanize(p.event_type)}`}
                  onCheckedChange={(checked) =>
                    updateMutation.mutate({
                      channel: p.channel,
                      event_type: p.event_type,
                      enabled: checked === true,
                    })
                  }
                />
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
                <TableHead>Send to</TableHead>
                <TableHead>Event</TableHead>
                <TableHead className="text-right">Enabled</TableHead>
              </TableRow>
            }
          >
            {rows.map((p) => (
              <TableRow key={rowKey(p)}>
                <TableCell>
                  <Badge variant="secondary">{channelLabel(p.channel)}</Badge>
                </TableCell>
                <TableCell>{humanize(p.event_type)}</TableCell>
                <TableCell className="overflow-visible! text-right">
                  <Checkbox
                    checked={p.enabled}
                    disabled={updateMutation.isPending}
                    aria-label={`${channelLabel(p.channel)} ${humanize(p.event_type)}`}
                    onCheckedChange={(checked) =>
                      updateMutation.mutate({
                        channel: p.channel,
                        event_type: p.event_type,
                        enabled: checked === true,
                      })
                    }
                  />
                </TableCell>
              </TableRow>
            ))}
          </ListTable>
        </ListShell>
      )}
    </div>
  )
}
