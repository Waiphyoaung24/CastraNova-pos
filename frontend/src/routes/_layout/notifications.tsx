import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"

import {
  type NotificationPreferenceUpdate,
  NotificationsService,
} from "@/client"
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
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Notifications</h1>
        <p className="text-muted-foreground">
          Choose which events notify you over LINE / Viber.
        </p>
      </div>

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
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Channel</TableHead>
              <TableHead>Event</TableHead>
              <TableHead className="text-right">Enabled</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((p) => (
              <TableRow key={p.id}>
                <TableCell>
                  <Badge variant="secondary">{p.channel}</Badge>
                </TableCell>
                <TableCell>{humanize(p.event_type)}</TableCell>
                <TableCell className="text-right">
                  <Checkbox
                    checked={p.enabled}
                    disabled={updateMutation.isPending}
                    aria-label={`${p.channel} ${humanize(p.event_type)}`}
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
