# Friendlier Notification Messages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the four outbound notification messages into an emoji + labeled-lines format that names projects and products instead of quoting UUIDs.

**Architecture:** `_render_text` stays a pure function of `(event_type, payload)` — all new data reaches it through the payload, which the four `notify_*` helpers build. Three small render helpers (`_clean`, `_field`, `_describe`) guarantee no message ever renders the string `None` when a referenced row has been deleted. No schema change, no migration, no frontend change.

**Tech Stack:** Python 3.12, FastAPI, SQLModel, pytest.

**Spec:** `docs/superpowers/specs/2026-07-22-friendly-notification-messages-design.md`

## Global Constraints

- Messages are sent without `parse_mode` — **plain text only**. Emoji and `\n` render; bold/italic markup does not. Never add markdown or HTML to a message body.
- **No prices, ever.** `deviation_pct` is a percentage and is safe to surface. No retail price, repair price, cost, margin, revenue, or budget may enter a message or a payload.
- **No customer in a message body.** `customer_id` stays in the payload for the audit log; the customer name never enters the rendered text.
- **No message may ever render the string `None`.**
- `pull_id` and `override_id` no longer appear in any message body. They remain in the payload.
- `_render_text` keeps its exact signature `(*, event_type: NotificationEvent, payload: dict[str, Any]) -> str` and keeps raising `NotImplementedError` for any event without an explicit template.
- Project renders as `name (code)`; product renders as `model_name (sku)`.
- Run all commands from the `backend/` directory.

---

### Task 1: Rewrite the four message templates

The pure-render half of the change. `_render_text` reads payload keys that
Task 2 will start populating — until then the new keys are simply absent and
the fallbacks fire, so this task is independently correct and testable.

**Files:**
- Modify: `backend/app/services/notify.py:329-351` (`_render_text`)
- Test: `backend/tests/services/test_notify.py`

**Interfaces:**
- Consumes: `NotificationEvent` (from `app.models`), already imported in `notify.py`.
- Produces:
  - `_clean(value: Any) -> str`
  - `_field(*candidates: Any) -> str`
  - `_describe(name: Any, code: Any, fallback: Any) -> str`
  - `_render_text(*, event_type: NotificationEvent, payload: dict[str, Any]) -> str` (signature unchanged)
  - Payload keys the templates read: `project_name`, `project_code`, `project_id`, `short_line_count`, `model_name`, `sku`, `product_id`, `on_hand`, `min_stock_level`, `deviation_pct`, `override_id`. Task 2 populates the first two and `model_name`.

- [ ] **Step 1: Delete the obsolete test**

`test_render_text_pull_fulfilled_mentions_pull_id` at
`backend/tests/services/test_notify.py:821-827` asserts the pull id appears in
the message body. The spec removes ids from message bodies, so this assertion
becomes false by design. Delete the whole function — Step 2 replaces it with a
project-name assertion.

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/services/test_notify.py`:

```python
# --- message copy (2026-07-22 friendlier messages) ----------------------------


def test_render_text_pull_short_is_labeled_lines() -> None:
    text = notify._render_text(
        event_type=NotificationEvent.PULL_SHORT,
        payload={
            "pull_id": "the-pull-id",
            "project_id": "the-project-id",
            "project_name": "Riverside Tower",
            "project_code": "PRJ-001",
            "short_line_count": 2,
        },
    )
    assert text == (
        "⚠️ Project pull came up short\n"
        "Project: Riverside Tower (PRJ-001)\n"
        "Lines short: 2"
    )
    # ids are payload-only now
    assert "the-pull-id" not in text


def test_render_text_pull_fulfilled_names_the_project() -> None:
    text = notify._render_text(
        event_type=NotificationEvent.PULL_FULFILLED,
        payload={
            "pull_id": "the-pull-id",
            "project_id": "the-project-id",
            "project_name": "Riverside Tower",
            "project_code": "PRJ-001",
        },
    )
    assert text == (
        "✅ Project pull fulfilled\nProject: Riverside Tower (PRJ-001)"
    )
    assert "the-pull-id" not in text


def test_render_text_low_stock_names_the_product() -> None:
    text = notify._render_text(
        event_type=NotificationEvent.LOW_STOCK,
        payload={
            "product_id": "the-product-id",
            "sku": "SKU-1234",
            "model_name": "12mm Copper Elbow",
            "on_hand": 3,
            "min_stock_level": 10,
        },
    )
    assert text == (
        "📉 Low stock\n"
        "Item: 12mm Copper Elbow (SKU-1234)\n"
        "On hand: 3 (minimum 10)"
    )


def test_render_text_override_pending_names_the_product() -> None:
    text = notify._render_text(
        event_type=NotificationEvent.OVERRIDE_PENDING,
        payload={
            "override_id": "the-override-id",
            "sku": "SKU-1234",
            "model_name": "12mm Copper Elbow",
            "deviation_pct": "12.5",
        },
    )
    assert text == (
        "🔔 Pricing override needs approval\n"
        "Item: 12mm Copper Elbow (SKU-1234)\n"
        "Deviation: 12.5%"
    )
    assert "the-override-id" not in text


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        (
            NotificationEvent.PULL_SHORT,
            {"project_id": "the-project-id", "short_line_count": 2},
        ),
        (NotificationEvent.PULL_FULFILLED, {"project_id": "the-project-id"}),
        (
            NotificationEvent.LOW_STOCK,
            {"product_id": "the-product-id", "on_hand": 3, "min_stock_level": 10},
        ),
        (
            NotificationEvent.OVERRIDE_PENDING,
            {"override_id": "the-override-id", "deviation_pct": "12.5"},
        ),
    ],
)
def test_render_text_falls_back_to_id_when_row_is_gone(
    event_type: NotificationEvent, payload: dict[str, object]
) -> None:
    """A deleted Project/Product leaves the name keys absent. The label must
    degrade to the id and must never render the string "None"."""
    text = notify._render_text(event_type=event_type, payload=payload)
    assert "None" not in text
    assert "unknown" not in text
    fallback = payload.get("project_id") or payload.get("product_id") or payload.get(
        "override_id"
    )
    assert str(fallback) in text


def test_render_text_never_renders_none_for_missing_quantities() -> None:
    """Every key absent — the last line of defence against "None" reaching a
    user's phone."""
    for event_type in (
        NotificationEvent.PULL_SHORT,
        NotificationEvent.PULL_FULFILLED,
        NotificationEvent.LOW_STOCK,
        NotificationEvent.OVERRIDE_PENDING,
    ):
        text = notify._render_text(event_type=event_type, payload={})
        assert "None" not in text


def test_render_text_still_rejects_an_unknown_event() -> None:
    """Every new event must add an explicit, safe template — never a raw dump."""
    with pytest.raises(NotImplementedError):
        notify._render_text(
            event_type="not-an-event",  # type: ignore[arg-type]
            payload={"retail_price_thb": "999.00"},
        )
```

- [ ] **Step 3: Run the tests to verify they fail**

Run:

```bash
pytest tests/services/test_notify.py -k "render_text" -v
```

Expected: the new tests FAIL on the message text (`AssertionError` comparing the
old one-line copy against the new labeled-lines copy).
`test_render_text_still_rejects_an_unknown_event` will already PASS — the
existing `NotImplementedError` fallthrough covers it. That is fine; it is a
regression guard, not a driver.

- [ ] **Step 4: Write the implementation**

Replace `_render_text` in `backend/app/services/notify.py` (currently lines
329-351) with the helpers plus the new templates:

```python
def _clean(value: Any) -> str:
    """A payload value as display text; None and blank strings become ""."""
    return "" if value is None else str(value).strip()


def _field(*candidates: Any) -> str:
    """The first candidate carrying display text, else "unknown". This is what
    guarantees a message never renders the string "None"."""
    for candidate in candidates:
        text = _clean(candidate)
        if text:
            return text
    return "unknown"


def _describe(name: Any, code: Any, fallback: Any) -> str:
    """"name (code)", degrading to whichever one is present, then to an id.

    A row named in a payload can be deleted between the send and the render,
    so every label needs a floor.
    """
    label, extra = _clean(name), _clean(code)
    if label and extra:
        return f"{label} ({extra})"
    return _field(label, extra, fallback)


def _render_text(*, event_type: NotificationEvent, payload: dict[str, Any]) -> str:
    """Render one plain-text message. Sent without parse_mode, so emoji and
    newlines render but markup does not.

    Ids are payload-only: they stay in the append-only log for audit, but a
    UUID means nothing to someone reading this on their phone.
    """
    if event_type == NotificationEvent.PULL_SHORT:
        project = _describe(
            payload.get("project_name"),
            payload.get("project_code"),
            payload.get("project_id"),
        )
        return (
            "⚠️ Project pull came up short\n"
            f"Project: {project}\n"
            f"Lines short: {_field(payload.get('short_line_count'))}"
        )
    if event_type == NotificationEvent.PULL_FULFILLED:
        project = _describe(
            payload.get("project_name"),
            payload.get("project_code"),
            payload.get("project_id"),
        )
        return f"✅ Project pull fulfilled\nProject: {project}"
    if event_type == NotificationEvent.LOW_STOCK:
        item = _describe(
            payload.get("model_name"),
            payload.get("sku"),
            payload.get("product_id"),
        )
        return (
            "📉 Low stock\n"
            f"Item: {item}\n"
            f"On hand: {_field(payload.get('on_hand'))} "
            f"(minimum {_field(payload.get('min_stock_level'))})"
        )
    if event_type == NotificationEvent.OVERRIDE_PENDING:
        # deviation_pct is a percentage, not a raw price — safe to surface.
        item = _describe(
            payload.get("model_name"),
            payload.get("sku"),
            payload.get("override_id"),
        )
        return (
            "🔔 Pricing override needs approval\n"
            f"Item: {item}\n"
            f"Deviation: {_field(payload.get('deviation_pct'))}%"
        )
    # Never push a raw payload (may carry financial fields). Each new event must
    # add an explicit, safe template here.
    raise NotImplementedError(f"No render template for {event_type!r}")
```

Copy all four emoji verbatim from this plan into both the source and the tests
rather than retyping them. The warning sign in particular is two code points —
U+26A0 followed by the U+FE0F variation selector — and without the selector some
clients render it as monochrome text instead of an emoji. `notify.py` already
contains non-ASCII (em dashes), so literal emoji in the source are fine.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
pytest tests/services/test_notify.py -v
```

Expected: PASS, including the pre-existing notify tests (none of the others
assert on message copy).

`test_render_text_never_renders_none_for_missing_quantities` passes an empty
payload, so every label falls through to `"unknown"` — that is intended. The
`assert "unknown" not in text` in
`test_render_text_falls_back_to_id_when_row_is_gone` is the tighter check: when
an id *is* present it must be used rather than the `"unknown"` floor.

- [ ] **Step 6: Lint and type-check**

```bash
ruff check app/services/notify.py tests/services/test_notify.py
ruff format --check app/services/notify.py tests/services/test_notify.py
mypy app/services/notify.py
```

Expected: all clean. If `ruff format --check` objects, run `ruff format` on the
two files and re-run.

- [ ] **Step 7: Commit**

```bash
git add app/services/notify.py tests/services/test_notify.py
git commit -m "feat(notify): rewrite message templates as labeled lines

Replace the four one-line notification messages with an emoji +
labeled-lines format. Ids drop out of message bodies (they stay in the
payload for the audit log) in favour of project and product names, which
Task 2 starts populating.

Add _clean/_field/_describe so a deleted Project or Product degrades to
its id rather than rendering the string \"None\"."
```

---

### Task 2: Populate names into the notify payloads

**Files:**
- Modify: `backend/app/services/notify.py` — the `from app.models import (...)` block (add `Project`), `notify_pull_short`, `notify_pull_fulfilled`, `notify_low_stock`, `notify_override_pending`
- Test: `backend/tests/services/test_notify.py`

**Interfaces:**
- Consumes: `_render_text` and its payload keys from Task 1.
- Produces: payloads carrying `project_name` + `project_code` (both pull events) and `model_name` (low stock, override pending). No signature changes — all four helpers keep `(*, session: Session, ...) -> list[NotificationLog]`.

- [ ] **Step 1: Write the failing tests**

Two existing tests already build a project named `"P"`; extend them rather than
duplicating their fixture setup.

In `test_notify_pull_short_targets_bkk_admins_with_pref`
(`backend/tests/services/test_notify.py:746`), after the existing final
assertion `assert sample.payload["pull_id"] == str(pull.id)`, add:

```python
    assert sample.payload["project_name"] == project.name
    assert sample.payload["project_code"] == project.code
```

In `test_notify_pull_fulfilled_targets_bkk_admins_with_pref`
(`backend/tests/services/test_notify.py:830`), after
`assert sample.payload["pull_id"] == str(pull.id)` and before the
`assert_no_financial_keys` call, add:

```python
    assert sample.payload["project_name"] == project.name
    assert sample.payload["project_code"] == project.code
```

Then append two new tests for the product-bearing events:

```python
def test_notify_low_stock_payload_carries_model_name(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import crud
    from app.models import ProductCreate, TrackingMode

    monkeypatch.setattr(notify, "_post", lambda *a, **k: _resp(200))
    admin = _make_user(db, role=UserRole.BKK_ADMIN)
    _opt_in(db, admin, NotificationChannel.LINE, NotificationEvent.LOW_STOCK)

    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"NS-{uuid.uuid4().hex[:8]}",
            model_name="12mm Copper Elbow",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="10.00",
            repair_price_thb="2.00",
            default_min_stock_level=10,
        ),
    )

    logs = notify.notify_low_stock(session=db, product_ids=[product.id])
    sample = next(log for log in logs if log.target_user_id == admin.id)
    assert sample.payload["model_name"] == "12mm Copper Elbow"
    assert sample.payload["sku"] == product.sku
    assert_no_financial_keys(sample.payload)


def test_notify_override_pending_payload_carries_model_name(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import crud
    from app.models import (
        OverrideState,
        OverrideTargetKind,
        PricingOverrideRequest,
        ProductCreate,
        TrackingMode,
    )

    monkeypatch.setattr(notify, "_post", lambda *a, **k: _resp(200))
    admin = _make_user(db, role=UserRole.BKK_ADMIN)
    _opt_in(db, admin, NotificationChannel.LINE, NotificationEvent.OVERRIDE_PENDING)

    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"NS-{uuid.uuid4().hex[:8]}",
            model_name="12mm Copper Elbow",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="10.00",
            repair_price_thb="2.00",
        ),
    )
    override = PricingOverrideRequest(
        target_kind=OverrideTargetKind.SALE_LINE,
        product_id=product.id,
        default_price_thb=Decimal("10.00"),
        requested_price_thb=Decimal("8.75"),
        deviation_pct=Decimal("12.5"),
        reason="customer discount",
        state=OverrideState.PENDING,
        created_by_user_id=admin.id,
    )
    db.add(override)
    db.commit()
    db.refresh(override)

    logs = notify.notify_override_pending(session=db, override=override)
    sample = next(log for log in logs if log.target_user_id == admin.id)
    assert sample.payload["model_name"] == "12mm Copper Elbow"
    assert sample.payload["sku"] == product.sku
    assert_no_financial_keys(sample.payload)
```

**Before running:** confirm `Decimal`, `uuid`, and `assert_no_financial_keys`
are already imported at the top of `test_notify.py`; add any that are missing.
(`assert_no_financial_keys` comes from `tests.utils.utils` and is already used
by `test_notify_pull_fulfilled_targets_bkk_admins_with_pref`.)

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/services/test_notify.py -k "payload_carries or targets_bkk_admins" -v
```

Expected: FAIL with `KeyError: 'project_name'` and `KeyError: 'model_name'`.

- [ ] **Step 3: Add `Project` to the models import**

In `backend/app/services/notify.py`, the `from app.models import (...)` block
(lines 32-45) is alphabetised. Insert `Project,` between `Product,` and
`ProjectPull,`:

```python
from app.models import (
    LineState,
    NotificationChannel,
    NotificationEvent,
    NotificationLog,
    NotificationPreference,
    NotificationStatus,
    PricingOverrideRequest,
    Product,
    Project,
    ProjectPull,
    ProjectPullLine,
    User,
    UserRole,
)
```

- [ ] **Step 4: Widen the two pull payloads**

In `notify_pull_short`, replace the `payload` assignment with:

```python
    project = session.get(Project, pull.project_id)
    payload: dict[str, Any] = {
        "pull_id": str(pull.id),
        "project_id": str(pull.project_id),
        "project_name": project.name if project else None,
        "project_code": project.code if project else None,
        "customer_id": str(pull.customer_id),
        "short_line_count": short_line_count,
    }
```

In `notify_pull_fulfilled`, replace the `payload` assignment with:

```python
    project = session.get(Project, pull.project_id)
    payload: dict[str, Any] = {
        "pull_id": str(pull.id),
        "project_id": str(pull.project_id),
        "project_name": project.name if project else None,
        "project_code": project.code if project else None,
        "customer_id": str(pull.customer_id),
    }
```

`customer_id` stays in the payload for the audit log and is deliberately never
rendered — see the spec's content decisions.

- [ ] **Step 5: Widen the two product payloads**

In `notify_low_stock`, the `Product` is already loaded. Add `model_name` to the
payload dict:

```python
        payload: dict[str, Any] = {
            "product_id": str(product.id),
            "sku": product.sku,
            "model_name": product.model_name,
            "on_hand": on_hand,
            "min_stock_level": threshold,
        }
```

In `notify_override_pending`, the `Product` is already loaded and may be `None`.
Add `model_name` alongside the existing `sku`:

```python
    payload: dict[str, Any] = {
        "override_id": str(override.id),
        "sku": product.sku if product else None,
        "model_name": product.model_name if product else None,
        "deviation_pct": str(override.deviation_pct),
    }
```

- [ ] **Step 6: Run the full notify suite**

```bash
pytest tests/services/test_notify.py -v
```

Expected: PASS.

- [ ] **Step 7: Lint and type-check**

```bash
ruff check app/services/notify.py tests/services/test_notify.py
ruff format --check app/services/notify.py tests/services/test_notify.py
mypy app/services/notify.py
```

Expected: all clean.

- [ ] **Step 8: Commit**

```bash
git add app/services/notify.py tests/services/test_notify.py
git commit -m "feat(notify): carry project and product names in payloads

Load the Project in the two pull helpers and add project_name/project_code;
add model_name to the low-stock and override-pending payloads (the Product
is already loaded in both). This is what lets the new templates name things
instead of quoting UUIDs.

notification_log.payload is a write-only JSON column, so no migration and
no risk to existing rows."
```

---

### Task 3: Friendlier Telegram test message

**Files:**
- Modify: `backend/app/api/routes/notifications.py:135`
- Test: `backend/tests/api/routes/test_telegram_connect.py`

**Interfaces:**
- Consumes: `notify.send_telegram_test(*, to: str, text: str) -> tuple[bool, str | None]` — unchanged.
- Produces: nothing consumed by later tasks. This is the final task.

- [ ] **Step 1: Write the failing test**

No test currently asserts the test-message copy. The route's tests live in
`backend/tests/api/routes/test_telegram_connect.py` under the
`# --- test message ---` heading (around line 405), which already provides a
`user_and_headers` fixture and an autouse `_no_sleep` fixture.

Append this after `test_test_message_succeeds_when_connected`. It captures the
outgoing text at the `_post` seam, matching how the neighbouring tests
monkeypatch:

```python
def test_test_message_copy_is_friendly(
    client: TestClient,
    db: Session,
    user_and_headers: tuple[User, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The probe a user sees after clicking "Send test" should read like a
    confirmation, not a log line."""
    user, headers = user_and_headers
    user.telegram_chat_id = f"T-{uuid.uuid4().hex[:10]}"
    db.add(user)
    db.commit()
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "test-token")

    sent: dict[str, Any] = {}

    def _capture(url: str, *, headers: dict[str, str], json: dict[str, Any]):
        sent.update(json)
        return _resp(200, {"ok": True})

    monkeypatch.setattr(notify, "_post", _capture)

    r = client.post(f"{PREFIX}/notifications/telegram/test", headers=headers)
    assert r.status_code == 200, r.text
    assert sent["text"] == (
        "✅ CastraNova POS\nYour Telegram notifications are working."
    )
```

`uuid`, `Any`, `settings`, `notify`, `PREFIX`, `User`, and `_resp` are all
already imported in this file.

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/api/routes/test_telegram_connect.py -k copy_is_friendly -v
```

Expected: FAIL, `AssertionError` comparing
`"CastraNova POS: this is a test notification."` against the new copy.

- [ ] **Step 3: Update the message**

In `backend/app/api/routes/notifications.py`, change the `text` argument at
line 135:

```python
    ok, detail = notify.send_telegram_test(
        to=current_user.telegram_chat_id,
        text="✅ CastraNova POS\nYour Telegram notifications are working.",
    )
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/api/routes/test_telegram_connect.py -v
```

Expected: PASS.

- [ ] **Step 5: Run the whole backend suite**

```bash
bash scripts/test.sh
```

Expected: the known baseline of **3 failed / 654 passed** (plus the tests added
by this plan, all passing). Those three failures pre-date this branch and are
not regressions — do not chase them. If any *fourth* test fails, it is yours:
stop and fix it.

- [ ] **Step 6: Lint and type-check the full change**

```bash
ruff check app tests
ruff format --check app tests
mypy app
```

Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add app/api/routes/notifications.py tests/api/routes/test_telegram_connect.py
git commit -m "feat(notify): friendlier Telegram test message

Match the labeled-lines style of the event messages, and read as a
confirmation rather than a log line."
```

---

## Verification

The change is backend-only. To confirm end to end, with the dev stack running
(`docker compose watch`), connect Telegram on the notifications page and click
"Send test" — the message should arrive as two lines with a leading check mark.

Event messages are best verified through their unit tests; triggering a real
low-stock or override-pending push requires arranging stock state and is not
worth the setup for a copy change.

## Out of scope

Action deep links back into the app — deferred by explicit decision, recorded in
the spec. Do not add links to any message in this plan.
