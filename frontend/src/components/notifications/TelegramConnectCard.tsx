import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertTriangle } from "lucide-react"
import { useEffect, useState } from "react"

import { NotificationsService } from "@/client"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import useCustomToast from "@/hooks/useCustomToast"

const POLL_INTERVAL_MS = 3_000
// The server-side code TTL is ~10 min; this is a shorter client-side give-up
// so the UI doesn't poll silently forever if the user never taps Start.
const POLL_TIMEOUT_MS = 2 * 60 * 1_000

/** Telegram connect/reconnect card: mint a code, show the QR + deep link,
 * poll confirm until the user taps Start in Telegram, then allow disconnect.
 * Re-running Connect (as "Reconnect") always mints a fresh code, so
 * switching Telegram accounts is one more tap, not a dead end. */
export function TelegramConnectCard() {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()

  const { data: status } = useQuery({
    queryKey: ["telegram-status"],
    queryFn: () => NotificationsService.getTelegramStatus(),
  })

  const [activeCode, setActiveCode] = useState<string | null>(null)
  const [pollStartedAt, setPollStartedAt] = useState<number | null>(null)
  const [pollTimedOut, setPollTimedOut] = useState(false)
  const [confirmError, setConfirmError] = useState<string | null>(null)

  const connectMutation = useMutation({
    mutationFn: () => NotificationsService.connectTelegram(),
    onSuccess: (data) => {
      setActiveCode(data.code)
      setPollStartedAt(Date.now())
      setPollTimedOut(false)
      setConfirmError(null)
    },
    onError: () =>
      showErrorToast("Could not start connecting Telegram. Try again."),
  })

  const confirmQuery = useQuery({
    queryKey: ["telegram-confirm", activeCode],
    queryFn: () =>
      NotificationsService.confirmTelegram({
        requestBody: { code: activeCode as string },
      }),
    enabled: activeCode !== null,
    refetchInterval: POLL_INTERVAL_MS,
  })

  // Confirmed: stop polling, refresh the status card + the preference grid
  // (its per-channel "connected" flag depends on the same address), and
  // celebrate with the captured username.
  useEffect(() => {
    if (!confirmQuery.data?.connected) return
    setActiveCode(null)
    setPollStartedAt(null)
    queryClient.invalidateQueries({ queryKey: ["telegram-status"] })
    queryClient.invalidateQueries({ queryKey: ["notification-preferences"] })
    showSuccessToast(
      confirmQuery.data.telegram_username
        ? `Connected as @${confirmQuery.data.telegram_username}.`
        : "Telegram connected.",
    )
    // The actual trigger is confirmQuery.data flipping to connected;
    // showSuccessToast is useCallback-stabilized so it can't cause a re-fire.
  }, [confirmQuery.data, queryClient, showSuccessToast])

  // A terminal failure (e.g. this Telegram already backs another account).
  // Stop polling immediately rather than letting it run out the clock into a
  // generic timeout -- more polling cannot resolve it, and the user needs to
  // know that rather than being told to just try again.
  useEffect(() => {
    const error = confirmQuery.data?.error
    if (!error) return
    setActiveCode(null)
    setPollStartedAt(null)
    setConfirmError(error)
  }, [confirmQuery.data])

  // Give up client-side after POLL_TIMEOUT_MS so the card doesn't poll
  // forever if the user never taps Start.
  useEffect(() => {
    if (pollStartedAt === null) return
    const remaining = POLL_TIMEOUT_MS - (Date.now() - pollStartedAt)
    const giveUp = () => {
      setPollTimedOut(true)
      setActiveCode(null)
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
    mutationFn: () => NotificationsService.disconnectTelegram(),
    onSuccess: () => {
      queryClient.setQueryData(["telegram-status"], {
        connected: false,
        telegram_username: null,
        delivery_failing: false,
        last_error: null,
      })
      queryClient.invalidateQueries({ queryKey: ["telegram-status"] })
      queryClient.invalidateQueries({ queryKey: ["notification-preferences"] })
      showSuccessToast("Telegram disconnected.")
    },
    onError: () => showErrorToast("Could not disconnect Telegram. Try again."),
  })

  if (!status) return null

  const connectData = connectMutation.data

  return (
    <div className="bg-card flex flex-col gap-4 rounded-lg border p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium">Telegram</p>
          <p className="text-muted-foreground text-sm">
            {status.connected
              ? `Connected as ${
                  status.telegram_username
                    ? `@${status.telegram_username}`
                    : "your account"
                }`
              : "Not connected."}
          </p>
        </div>
        <div className="flex gap-2">
          {status.connected && (
            <Button
              variant="destructive"
              onClick={() => disconnectMutation.mutate()}
              disabled={disconnectMutation.isPending}
            >
              {disconnectMutation.isPending ? "Disconnecting…" : "Disconnect"}
            </Button>
          )}
          <Button
            variant={status.connected ? "outline" : "default"}
            onClick={() => connectMutation.mutate()}
            disabled={connectMutation.isPending || activeCode !== null}
          >
            {status.connected ? "Reconnect" : "Connect Telegram"}
          </Button>
        </div>
      </div>

      {status.connected && status.delivery_failing && (
        <Alert variant="destructive">
          <AlertTriangle />
          <AlertTitle>Telegram delivery is failing</AlertTitle>
          <AlertDescription>
            {status.last_error ?? "The last message could not be delivered."}{" "}
            Try reconnecting.
          </AlertDescription>
        </Alert>
      )}

      {activeCode && connectData && (
        <div className="flex flex-col items-center gap-3 border-t pt-4 sm:flex-row sm:items-start">
          <img
            src={connectData.qr_code_data_uri}
            alt="Scan to connect Telegram"
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
              Tap Start in Telegram — this updates automatically once you do.
            </p>
          </div>
        </div>
      )}

      {confirmError && (
        <Alert variant="destructive">
          <AlertTriangle />
          <AlertTitle>Couldn't connect this Telegram account</AlertTitle>
          <AlertDescription>{confirmError}</AlertDescription>
        </Alert>
      )}

      {pollTimedOut && !confirmError && (
        <p className="text-muted-foreground text-sm">
          Didn't detect a connection — tap Reconnect to try again.
        </p>
      )}
    </div>
  )
}
