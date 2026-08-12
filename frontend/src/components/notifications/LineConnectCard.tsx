import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useState } from "react"

import { NotificationsService } from "@/client"
import { Button } from "@/components/ui/button"
import useCustomToast from "@/hooks/useCustomToast"

const POLL_INTERVAL_MS = 3_000
// The server-side code TTL is ~10 min; this is a shorter client-side give-up
// so the UI doesn't poll silently forever if the user never sends the code.
const POLL_TIMEOUT_MS = 2 * 60 * 1_000

/** LINE connect/reconnect card.
 *
 * Deliberately has no dedicated status endpoint. The preference grid's
 * `channel_connected` flag already reports exactly whether line_user_id is
 * set, and this card has to refetch that query on success anyway -- so it
 * polls the query it was going to invalidate. That is also what keeps this
 * feature from touching any Telegram file.
 *
 * Not a refactor of TelegramConnectCard: that is the change most likely to
 * regress the working Telegram flow, and it would buy little -- there is no
 * confirm poll, no username display and no already-linked branch here. */
export function LineConnectCard() {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()

  const [polling, setPolling] = useState(false)
  const [pollStartedAt, setPollStartedAt] = useState<number | null>(null)
  const [pollTimedOut, setPollTimedOut] = useState(false)

  const { data: preferences } = useQuery({
    queryKey: ["notification-preferences"],
    queryFn: () => NotificationsService.readNotificationPreferences(),
    refetchInterval: polling ? POLL_INTERVAL_MS : false,
  })

  const connected =
    preferences?.some((p) => p.channel === "LINE" && p.channel_connected) ??
    false

  const connectMutation = useMutation({
    mutationFn: () => NotificationsService.connectLine(),
    onSuccess: () => {
      setPolling(true)
      setPollStartedAt(Date.now())
      setPollTimedOut(false)
    },
    onError: () =>
      showErrorToast("Could not start connecting LINE. Try again."),
  })

  // Connected: stop polling and celebrate. The grid query is already fresh --
  // it is what told us -- so there is nothing to invalidate here.
  useEffect(() => {
    if (!polling || !connected) return
    setPolling(false)
    setPollStartedAt(null)
    showSuccessToast("LINE connected.")
  }, [polling, connected, showSuccessToast])

  // Give up client-side so the card doesn't poll forever if the user never
  // sends the code.
  useEffect(() => {
    if (pollStartedAt === null) return
    const remaining = POLL_TIMEOUT_MS - (Date.now() - pollStartedAt)
    const giveUp = () => {
      setPollTimedOut(true)
      setPolling(false)
      setPollStartedAt(null)
    }
    if (remaining <= 0) {
      giveUp()
      return
    }
    const timer = setTimeout(giveUp, remaining)
    return () => clearTimeout(timer)
  }, [pollStartedAt])

  const disconnectMutation = useMutation({
    mutationFn: () => NotificationsService.disconnectLine(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notification-preferences"] })
      showSuccessToast("LINE disconnected.")
    },
    onError: () => showErrorToast("Could not disconnect LINE. Try again."),
  })

  const connectData = connectMutation.data

  return (
    <div className="bg-card flex flex-col gap-4 rounded-lg border p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium">LINE</p>
          <p className="text-muted-foreground text-sm">
            {connected ? "Connected." : "Not connected."}
          </p>
        </div>
        <div className="flex gap-2">
          {connected && (
            <Button
              variant="destructive"
              onClick={() => disconnectMutation.mutate()}
              disabled={disconnectMutation.isPending}
            >
              {disconnectMutation.isPending ? "Disconnecting…" : "Disconnect"}
            </Button>
          )}
          <Button
            variant={connected ? "outline" : "default"}
            onClick={() => connectMutation.mutate()}
            disabled={connectMutation.isPending || polling}
          >
            {connected ? "Reconnect" : "Connect LINE"}
          </Button>
        </div>
      </div>

      {polling && connectData && (
        <div className="flex flex-col items-center gap-3 border-t pt-4 sm:flex-row sm:items-start">
          <img
            src={connectData.qr_code_data_uri}
            alt="Scan to connect LINE"
            className="size-40 rounded border"
          />
          <div className="flex flex-col gap-2">
            <p className="text-sm">
              Scan the QR code, or open this link on your phone:
            </p>
            <a
              href={connectData.deep_link}
              target="_blank"
              rel="noreferrer"
              className="text-primary text-sm break-all underline"
            >
              {connectData.deep_link}
            </a>
            <p className="text-muted-foreground text-xs">
              LINE opens with the code already typed — just tap send. This
              updates automatically once you do.
            </p>
          </div>
        </div>
      )}

      {pollTimedOut && (
        <p className="text-muted-foreground text-sm">
          Didn't detect a connection — tap Reconnect to try again.
        </p>
      )}
    </div>
  )
}
