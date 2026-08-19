#!/usr/bin/env bash
# Show the most recent notification attempts, newest first.
#
# notificationlog is append-only (m021), so this is the audit trail: one row
# per (recipient, channel) per event, including the failures. It is the first
# thing to check when an alert "didn't arrive" -- it distinguishes "never
# dispatched" from "dispatched and rejected" from "accepted by LINE".
#
# Reading it:
#   SENT    LINE accepted the message. Note this is not proof a human saw it --
#           LINE returns success even for a recipient who blocked the account.
#   FAILED  see last_error. "recipient id not set (not enrolled)" is normal and
#           expected for any user who opted in but never connected the channel.
#   no row  the event never fired at all. For LOW_STOCK that means no stock was
#           consumed across the threshold -- editing a minimum stock level or
#           making a stock adjustment does not trigger it (only sales, project
#           pull fulfils and service ticket closes do).
#
# Usage:
#   bash scripts/notif-log.sh            last 10, all events
#   bash scripts/notif-log.sh LOW_STOCK  filter to one event type
#   bash scripts/notif-log.sh LOW_STOCK 30
set -euo pipefail

EVENT="${1:-}"
LIMIT="${2:-10}"

where=""
if [ -n "$EVENT" ]; then
  # Guard the interpolation: this value lands in SQL.
  case "$EVENT" in
    LOW_STOCK|PULL_SHORT|PULL_FULFILLED|OVERRIDE_PENDING|SYNC_REVIEW_PENDING) ;;
    *) echo "unknown event type: $EVENT" >&2; exit 1 ;;
  esac
  where="WHERE l.event_type = '$EVENT'"
fi
case "$LIMIT" in
  ''|*[!0-9]*) echo "limit must be a number" >&2; exit 1 ;;
esac

docker compose exec -T db psql -U postgres -d app -c "
SELECT to_char(l.created_at, 'HH24:MI:SS') AS at,
       u.email,
       l.channel,
       l.event_type,
       l.status,
       COALESCE(l.payload->>'sku', '') AS sku,
       COALESCE(l.payload->>'on_hand', '') AS on_hand,
       COALESCE(l.payload->>'min_stock_level', '') AS min,
       COALESCE(l.last_error, '') AS error
FROM notificationlog l
LEFT JOIN \"user\" u ON u.id = l.target_user_id
$where
ORDER BY l.created_at DESC
LIMIT $LIMIT;" 2>/dev/null | grep -v '^time='
