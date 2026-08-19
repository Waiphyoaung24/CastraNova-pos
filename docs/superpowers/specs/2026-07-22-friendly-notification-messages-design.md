# Friendlier notification messages

**Date:** 2026-07-22
**Status:** Approved, ready for planning

## Problem

The four outbound notification messages read like log lines. Two of the four lead
with a raw UUID, which tells a human reading Telegram on their phone nothing:

```
Project pull 3f9a1c2e-... settled SHORT (2 line(s) short).
Project pull 3f9a1c2e-... fulfilled.
Low stock: SKU-1234 — 3 left (min 10).
Pricing override pending approval: SKU-1234 (12.5% deviation). Request 8b2c....
```

All notification channels (LINE, Viber, Telegram) have been tested end to end and
deliver correctly. This change is about the message copy, not the transport.

## Scope

Rewrite the four event messages in `_render_text`
(`backend/app/services/notify.py`) and the Telegram test message
(`backend/app/api/routes/notifications.py`) into an emoji + labeled-lines format,
and widen the `notify_*` helper payloads so the messages can name things instead
of quoting UUIDs.

### Out of scope (deferred)

**Action deep links** back into the app. The three target routes (`/pulls`,
`/pricing-overrides`, `/low-stock`) are plain list pages with no `validateSearch`
and no detail routes, so a per-record link would require frontend work on each
table. Deferred by explicit decision; revisit if the override-approval flow needs
it.

## Content decisions

**Names, but no customer.** Messages show project name/code and product
model name/SKU. The customer is deliberately kept out of the message body —
these land in personal chat apps outside the app's role-based access control,
and low-stock in particular fans out to any-role users who opted in.
`customer_id` stays in the payload for the audit log, exactly as today.

**No prices, ever.** The existing rule holds: `deviation_pct` is a percentage,
not a price, and is safe to surface. No retail price, repair price, cost, or
margin enters a message.

**Project renders as `name (code)`** to mirror the item's `model_name (sku)` —
the code is what people quote to each other, the name is what they recognise.

## Messages

Telegram messages are sent without `parse_mode`, so they are plain text. Emoji
and line breaks render; bold and italics do not.

```
⚠️ Project pull came up short
Project: Riverside Tower (PRJ-001)
Lines short: 2
```

```
✅ Project pull fulfilled
Project: Riverside Tower (PRJ-001)
```

```
📉 Low stock
Item: 12mm Copper Elbow (SKU-1234)
On hand: 3 (minimum 10)
```

```
🔔 Pricing override needs approval
Item: 12mm Copper Elbow (SKU-1234)
Deviation: 12.5%
```

Test message (`POST` test-notification route):

```
✅ CastraNova POS
Your Telegram notifications are working.
```

The labeled-line format sidesteps singular/plural agreement — `Lines short: 1`
reads fine, where `1 line(s) short` did not.

## Architecture

`_render_text` stays a pure function of `(event_type, payload)`. Same signature,
same "never push a raw payload; every event needs an explicit template" rule,
same `NotImplementedError` fallthrough for unhandled events. All new data
arrives through the payload.

The four `notify_*` helpers widen the payloads they build:

| Helper | New payload keys | Cost |
| --- | --- | --- |
| `notify_pull_short` | `project_name`, `project_code` | one `session.get(Project, …)` |
| `notify_pull_fulfilled` | `project_name`, `project_code` | one `session.get(Project, …)` |
| `notify_low_stock` | `model_name` | none — `Product` already loaded |
| `notify_override_pending` | `model_name` | none — `Product` already loaded |

`notification_log.payload` is a JSON column and is write-only — nothing in the
frontend re-renders a stored payload, and `_render_text` is only ever called at
send time. So widening the payload needs no migration and cannot break existing
log rows.

## Missing-data handling

`Project.name`, `Project.code`, `Product.model_name`, and `Product.sku` are all
non-nullable, so a field is only absent if the row itself has been deleted.
`notify_override_pending` already tolerates `product is None`; the two pull
helpers gain the same tolerance.

When a name is missing, the label line falls back to the id — `Project: 3f9a1c2e-...`
rather than `Project: None`. **No message may ever render the string `None`.**
For the two product-bearing events, both `model_name` and `sku` come from the
same `Product` row, so when it is absent the `Item:` line falls back to
`product_id` for low stock and to `override_id` for a pricing override.

`pull_id` and `override_id` no longer appear in any message body. They remain in
the payload, so the append-only audit log loses no fidelity.

## Testing

`_render_text` being pure keeps verification cheap:

- One unit test per event asserting the rendered text.
- One unit test per event asserting the id fallback when the name key is absent,
  and that `None` never appears in the output.
- Helper tests assert the new payload keys are populated.

`test_render_text_pull_fulfilled_mentions_pull_id`
(`backend/tests/services/test_notify.py`) asserts the pull id appears in the
message body. That becomes false under this change — it is updated to assert the
project name instead.

No E2E change, no frontend change, no migration.

## Risk

Low. No schema change. No behaviour change to retry policy, logging, opt-in
resolution, or token handling. No new external calls. The one real risk is a
stale test asserting the old copy, which the backend suite catches.
