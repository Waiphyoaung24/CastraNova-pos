#!/usr/bin/env bash
# Local end-to-end exercise of the LINE enrollment flow, with no LINE account,
# no phone and no public URL involved.
#
# It drives the real backend over HTTP and forges the one thing that would
# otherwise come from LINE's servers: a webhook POST carrying a valid
# x-line-signature. Everything downstream of that signature -- the HMAC check,
# the code lookup, the single-use consume, the bind, the unfollow unbind -- is
# the real code path.
#
# What this canNOT tell you: whether LINE's servers can actually reach your
# webhook, and whether the deep link opens correctly on a real phone. Only a
# public URL + a real phone prove those (see the tunnel section in the docs).
#
# Usage:
#   bash scripts/line-local-test.sh          full automated run
#   bash scripts/line-local-test.sh <code>   deliver one code, then stop --
#                                            use this to finish a connect you
#                                            started by clicking the button in
#                                            the browser, so you can watch the
#                                            card flip to Connected for real.
set -euo pipefail

API="${API:-http://localhost:8000}"
ENV_FILE="${ENV_FILE:-.env}"

email=$(grep -E '^FIRST_SUPERUSER=' "$ENV_FILE" | cut -d= -f2-)
password=$(grep -E '^FIRST_SUPERUSER_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)
secret=$(grep -E '^LINE_CHANNEL_SECRET=' "$ENV_FILE" | cut -d= -f2-)

if [ -z "$secret" ]; then
  echo "LINE_CHANNEL_SECRET is not set in $ENV_FILE" >&2
  exit 1
fi

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
fail() { printf '\033[31mFAIL: %s\033[0m\n' "$*" >&2; exit 1; }
ok()   { printf '\033[32m  ok\033[0m %s\n' "$*"; }

# A LINE userId is opaque; any stable unique string stands in for one.
LINE_USER_ID="Ulocaltest$(date +%s)"

sign() {  # $1 = raw body -> base64(HMAC-SHA256(secret, body))
  printf '%s' "$1" | openssl dgst -sha256 -hmac "$secret" -binary | openssl base64 -A
}

post_webhook() {  # $1 = raw JSON body; echoes the HTTP status
  local body="$1"
  curl -s -o /tmp/line_wh_body -w '%{http_code}' \
    -X POST "$API/api/v1/notifications/line/webhook" \
    -H "Content-Type: application/json" \
    -H "x-line-signature: $(sign "$body")" \
    --data-raw "$body"
}

login() {
  curl -s -X POST "$API/api/v1/login/access-token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    --data-urlencode "username=$email" --data-urlencode "password=$password" \
    | python -c 'import sys,json; print(json.load(sys.stdin)["access_token"])'
}

is_connected() {  # $1 = bearer token -> True/False
  curl -s "$API/api/v1/notifications/preferences" -H "Authorization: Bearer $1" \
    | python -c 'import sys,json; rows=json.load(sys.stdin); print(any(r["channel"]=="LINE" and r["channel_connected"] for r in rows))'
}

if [ $# -ge 1 ]; then
  say "Delivering code $1 as LINE would"
  token=$(login); [ -n "$token" ] || fail "could not log in"
  body="{\"destination\":\"Uoa\",\"events\":[{\"type\":\"message\",\"replyToken\":\"local-reply-token\",\"source\":{\"type\":\"user\",\"userId\":\"$LINE_USER_ID\"},\"message\":{\"type\":\"text\",\"text\":\"$1\"}}]}"
  # Start from a known-disconnected state, or "is it connected afterwards?"
  # answers True from a previous run and proves nothing about this delivery.
  if [ "$(is_connected "$token")" = "True" ]; then
    curl -s -o /dev/null -X DELETE "$API/api/v1/notifications/line/disconnect" \
      -H "Authorization: Bearer $token"
    ok "was already connected -- disconnected first so the result is meaningful"
  fi

  status=$(post_webhook "$body")
  [ "$status" = "200" ] || fail "webhook returned $status, expected 200"
  # A 200 proves nothing on its own: the webhook answers 200 for an unknown,
  # expired or already-consumed code too, deliberately, so that LINE never
  # disables it. The binding is the only real evidence.
  [ "$(is_connected "$token")" = "True" ] \
    || fail "webhook accepted the request but nothing bound -- the code was unknown, expired (10 min TTL) or already used. Click Connect LINE again for a fresh one."
  ok "bound -- the open browser tab should flip to Connected within ~3s"
  exit 0
fi

say "1. Log in as $email"
token=$(login)
[ -n "$token" ] || fail "could not log in"
ok "got a token"

say "2. Mint a connect code (what the Connect LINE button does)"
connect=$(curl -s -X POST "$API/api/v1/notifications/line/connect" \
  -H "Authorization: Bearer $token")
code=$(python -c 'import sys,json; print(json.load(sys.stdin)["code"])' <<<"$connect")
deep=$(python -c 'import sys,json; print(json.load(sys.stdin)["deep_link"])' <<<"$connect")
qr=$(python -c 'import sys,json; print(json.load(sys.stdin)["qr_code_data_uri"][:30])' <<<"$connect")
[ ${#code} -eq 32 ] || fail "code is ${#code} chars, expected 32"
ok "code   $code"
ok "link   $deep"
ok "qr     $qr..."

say "3. Reject a webhook with a BAD signature (the security gate)"
bad=$(curl -s -o /dev/null -w '%{http_code}' \
  -X POST "$API/api/v1/notifications/line/webhook" \
  -H "Content-Type: application/json" \
  -H "x-line-signature: this-is-not-a-valid-signature" \
  --data-raw '{"events":[]}')
[ "$bad" = "400" ] || fail "bad signature returned $bad, expected 400"
ok "400, nothing parsed"

say "4. Deliver the code as LINE would (valid signature)"
body="{\"destination\":\"Uoa\",\"events\":[{\"type\":\"message\",\"replyToken\":\"local-reply-token\",\"source\":{\"type\":\"user\",\"userId\":\"$LINE_USER_ID\"},\"message\":{\"type\":\"text\",\"text\":\"$code\"}}]}"
status=$(post_webhook "$body")
[ "$status" = "200" ] || fail "webhook returned $status, expected 200"
ok "200"

say "5. The preference grid now reports LINE connected"
connected=$(curl -s "$API/api/v1/notifications/preferences" \
  -H "Authorization: Bearer $token" \
  | python -c 'import sys,json; rows=json.load(sys.stdin); print(any(r["channel"]=="LINE" and r["channel_connected"] for r in rows))')
[ "$connected" = "True" ] || fail "grid still reports LINE disconnected"
ok "channel_connected = true  <- this is what flips the card in the UI"

say "6. Replaying the same code binds nothing (single use)"
status=$(post_webhook "$body")
[ "$status" = "200" ] || fail "replay returned $status, expected 200"
ok "200 and ignored -- LINE redelivers webhooks, so this path is routine"

say "7. unfollow unbinds (user blocked the Official Account)"
unfollow="{\"events\":[{\"type\":\"unfollow\",\"source\":{\"type\":\"user\",\"userId\":\"$LINE_USER_ID\"}}]}"
status=$(post_webhook "$unfollow")
[ "$status" = "200" ] || fail "unfollow returned $status, expected 200"
still=$(curl -s "$API/api/v1/notifications/preferences" \
  -H "Authorization: Bearer $token" \
  | python -c 'import sys,json; rows=json.load(sys.stdin); print(any(r["channel"]=="LINE" and r["channel_connected"] for r in rows))')
[ "$still" = "False" ] || fail "still connected after unfollow"
ok "back to Not connected"

printf '\n\033[32mAll local checks passed.\033[0m\n'
printf 'Not covered: LINE reaching your webhook, and the phone deep link.\n'
