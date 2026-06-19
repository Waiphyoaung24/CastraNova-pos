import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Bell } from "lucide-react"

import {
  type NotificationPreferenceUpdate,
  NotificationsService,
} from "@/client"
import { PageHeader } from "@/components/Common/PageHeader"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Checkbox } from "@/components/ui/checkbox"
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
import { channelLabel } from "@/lib/labels"
import { requireAuth } from "@/lib/route-guards"

// Both roles (FR-018): per-user opt-in for LINE/Viber notification events.
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

function Notifications() {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()
  const isMobile = useIsMobile()

  const { data, isPending, isError } = useQuery({
    queryKey: ["notification-preferences"],
    queryFn: () => NotificationsService.readNotificationPreferences(),
  })

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

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Notifications"
        description="Choose which events get sent to you on LINE or Viber."
      />

      <Alert>
        <Bell />
        <AlertTitle>Get notified your way</AlertTitle>
        <AlertDescription>
          Turn on the events you want pushed to LINE or Viber — low stock,
          pulls, and more. Toggle each one on or off; changes save instantly.
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
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground py-6 text-center text-sm">
          No notification channels configured.
        </p>
      ) : isMobile ? (
        <div className="space-y-3">
          {rows.map((p) => (
            <div
              key={p.id}
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
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Send to</TableHead>
              <TableHead>Event</TableHead>
              <TableHead className="text-right">Enabled</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((p) => (
              <TableRow key={p.id}>
                <TableCell>
                  <Badge variant="secondary">{channelLabel(p.channel)}</Badge>
                </TableCell>
                <TableCell>{humanize(p.event_type)}</TableCell>
                <TableCell className="text-right">
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
          </TableBody>
        </Table>
      )}
    </div>
  )
}
