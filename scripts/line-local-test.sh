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
# public URL + a real phone prove those.
#
# Dependencies: bash, curl, openssl, sed, grep. Deliberately NOT python --
# on Windows `python` is often a pyenv shim that WSL cannot execute, and this
# script has to run the same in WSL, Git Bash and macOS.
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

for tool in curl openssl sed grep; do
  command -v "$tool" >/dev/null 2>&1 || { echo "missing required tool: $tool" >&2; exit 1; }
done

email=$(grep -E '^FIRST_SUPERUSER=' "$ENV_FILE" | cut -d= -f2- | tr -d '\r')
password=$(grep -E '^FIRST_SUPERUSER_PASSWORD=' "$ENV_FILE" | cut -d= -f2- | tr -d '\r')
secret=$(grep -E '^LINE_CHANNEL_SECRET=' "$ENV_FILE" | cut -d= -f2- | tr -d '\r')
# Your real LINE userId, if you have one.
#
# This script binds a SYNTHETIC userId to the superuser in order to stand in
# for LINE. That silently clobbers a real binding: the card still reads
# "Connected", but it is connected to an account that does not exist, so live
# alerts go nowhere. The full run is worse -- it ends on `unfollow`, which
# clears the binding entirely.
#
# Set LINE_TEST_USER_ID in .env and the script puts the real one back when it
# finishes, through the app's own connect+webhook path.
real_user_id=$(grep -E '^LINE_TEST_USER_ID=' "$ENV_FILE" | cut -d= -f2- | tr -d '\r' || true)

if [ -z "$secret" ]; then
  echo "LINE_CHANNEL_SECRET is not set in $ENV_FILE" >&2
  exit 1
fi

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
fail() { printf '\033[31mFAIL: %s\033[0m\n' "$*" >&2; exit 1; }
ok()   { printf '\033[32m  ok\033[0m %s\n' "$*"; }

# A LINE userId is opaque; any stable unique string stands in for one.
LINE_USER_ID="Ulocaltest$(date +%s)"

# Every response field read here is a flat top-level string or bool, so a
# regex is sufficient and keeps the dependency list to coreutils.
json_str() {  # $1 = key; reads JSON on stdin
  sed -E "s/.*\"$1\" *: *\"([^\"]*)\".*/\1/"
}

sign() {  # $1 = raw body -> base64(HMAC-SHA256(secret, body))
  printf '%s' "$1" | openssl dgst -sha256 -hmac "$secret" -binary | openssl base64 -A
}

post_webhook() {  # $1 = raw JSON body; echoes the HTTP status
  curl -s -o /dev/null -w '%{http_code}' \
    -X POST "$API/api/v1/notifications/line/webhook" \
    -H "Content-Type: application/json" \
    -H "x-line-signature: $(sign "$1")" \
    --data-raw "$1"
}

login() {
  curl -s -X POST "$API/api/v1/login/access-token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    --data-urlencode "username=$email" --data-urlencode "password=$password" \
    | json_str access_token
}

is_connected() {  # $1 = bearer token -> True/False
  # Objects in this array are flat, so [^}]* safely scopes the match to one row.
  if curl -s "$API/api/v1/notifications/preferences" -H "Authorization: Bearer $1" \
      | grep -o '{[^}]*"channel":"LINE"[^}]*}' | grep -q '"channel_connected":true'; then
    echo True
  else
    echo False
  fi
}

message_event() {  # $1 = text
  printf '{"destination":"Uoa","events":[{"type":"message","replyToken":"local-reply-token","source":{"type":"user","userId":"%s"},"message":{"type":"text","text":"%s"}}]}' \
    "$LINE_USER_ID" "$1"
}

restore_real_binding() {
  # Rebind through the app's own connect+webhook path rather than SQL, so the
  # restore exercises the same code the real flow uses.
  [ -n "${real_user_id:-}" ] || return 0
  local tok code body
  tok=$(login) || return 0
  [ -n "$tok" ] || return 0
  curl -s -o /dev/null -X DELETE "$API/api/v1/notifications/line/disconnect"     -H "Authorization: Bearer $tok"
  code=$(curl -s -X POST "$API/api/v1/notifications/line/connect"     -H "Authorization: Bearer $tok" | json_str code)
  [ -n "$code" ] || return 0
  body=$(printf '{"destination":"Uoa","events":[{"type":"message","replyToken":"restore","source":{"type":"user","userId":"%s"},"message":{"type":"text","text":"%s"}}]}' "$real_user_id" "$code")
  post_webhook "$body" >/dev/null
  ok "restored the real LINE binding ($real_user_id)"
}

# --- single-code mode -------------------------------------------------------

if [ $# -ge 1 ]; then
  say "Delivering code $1 as LINE would"
  token=$(login); [ -n "$token" ] || fail "could not log in to $API"

  # Start from a known-disconnected state, or "is it connected afterwards?"
  # answers True from a previous run and proves nothing about this delivery.
  if [ "$(is_connected "$token")" = "True" ]; then
    curl -s -o /dev/null -X DELETE "$API/api/v1/notifications/line/disconnect" \
      -H "Authorization: Bearer $token"
    ok "was already connected -- disconnected first so the result is meaningful"
  fi

  status=$(post_webhook "$(message_event "$1")")
  [ "$status" = "200" ] || fail "webhook returned $status, expected 200"
  # A 200 proves nothing on its own: the webhook answers 200 for an unknown,
  # expired or already-consumed code too, deliberately, so that LINE never
  # disables it. The binding is the only real evidence.
  [ "$(is_connected "$token")" = "True" ] \
    || fail "webhook accepted the request but nothing bound -- the code was unknown, expired (10 min TTL) or already used. Click Connect LINE again for a fresh one."
  ok "bound -- the open browser tab should flip to Connected within ~3s"
  restore_real_binding
  exit 0
fi

# --- full run ---------------------------------------------------------------

say "1. Log in as $email"
token=$(login)
[ -n "$token" ] || fail "could not log in to $API"
ok "got a token"

say "2. Mint a connect code (what the Connect LINE button does)"
connect=$(curl -s -X POST "$API/api/v1/notifications/line/connect" \
  -H "Authorization: Bearer $token")
code=$(printf '%s' "$connect" | json_str code)
deep=$(printf '%s' "$connect" | json_str deep_link)
qr=$(printf '%s' "$connect" | json_str qr_code_data_uri | cut -c1-30)
[ ${#code} -eq 32 ] || fail "code is ${#code} chars, expected 32 -- response was: $connect"
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
status=$(post_webhook "$(message_event "$code")")
[ "$status" = "200" ] || fail "webhook returned $status, expected 200"
ok "200"

say "5. The preference grid now reports LINE connected"
[ "$(is_connected "$token")" = "True" ] || fail "grid still reports LINE disconnected"
ok "channel_connected = true  <- this is what flips the card in the UI"

say "6. Replaying the same code binds nothing (single use)"
curl -s -o /dev/null -X DELETE "$API/api/v1/notifications/line/disconnect" \
  -H "Authorization: Bearer $token"
status=$(post_webhook "$(message_event "$code")")
[ "$status" = "200" ] || fail "replay returned $status, expected 200"
[ "$(is_connected "$token")" = "False" ] \
  || fail "a consumed code rebound -- single use is broken"
ok "200, ignored, nothing rebound -- LINE redelivers, so this path is routine"

say "7. unfollow unbinds (user blocked the Official Account)"
# Step 6 deliberately left us disconnected, so rebind with a fresh code first.
fresh=$(curl -s -X POST "$API/api/v1/notifications/line/connect" \
  -H "Authorization: Bearer $token" | json_str code)
post_webhook "$(message_event "$fresh")" >/dev/null
[ "$(is_connected "$token")" = "True" ] || fail "could not rebind for the unfollow check"
unfollow=$(printf '{"events":[{"type":"unfollow","source":{"type":"user","userId":"%s"}}]}' "$LINE_USER_ID")
status=$(post_webhook "$unfollow")
[ "$status" = "200" ] || fail "unfollow returned $status, expected 200"
[ "$(is_connected "$token")" = "False" ] || fail "still connected after unfollow"
ok "back to Not connected"

# Step 7 deliberately ends unbound, which would leave a real account
# disconnected and live alerts going nowhere. Put it back.
restore_real_binding

printf '\n\033[32mAll local checks passed.\033[0m\n'
printf 'Not covered: LINE reaching your webhook, and the phone deep link.\n'
