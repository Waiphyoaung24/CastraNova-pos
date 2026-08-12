"""Send a REAL low-stock LINE message to a real phone, from localhost.

Outbound sends do not need a public URL -- send_line calls api.line.me, which
is an outbound HTTPS request. Only the inbound webhook needs to be reachable
from the internet. So the whole notification path can be proven locally, as
long as you can supply a genuine LINE userId.

Getting that userId without a webhook: LINE Developers Console -> your channel
-> Basic settings -> "Your user ID". That is the channel owner's own userId,
scoped to the channel's provider, which is exactly what push needs.

Prerequisites, all of which this script checks and reports on:
  1. LINE_CHANNEL_ACCESS_TOKEN set in .env (long-lived), backend restarted.
  2. You have added the Official Account as a friend on your phone. LINE
     refuses to push to a user who never added the bot.

Usage (from the repo root):
    docker compose exec -T backend python scripts/line_low_stock_test.py <YOUR_LINE_USER_ID>

It binds that userId to the superuser, enables the LOW_STOCK/LINE preference,
forces one product below its threshold, and calls the real notify_low_stock
dispatcher. It then prints the append-only NotificationLog rows it produced --
which is the same record a weekly admin review would read.

Local test aid. It mutates dev data (one product's min stock level) and prints
what it changed so you can put it back.
"""

import sys

from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.core.db import engine
from app.models import (
    NotificationChannel,
    NotificationEvent,
    NotificationPreference,
    NotificationStatus,
    Product,
    User,
)
from app.services import notify

GREEN, RED, YELLOW, BOLD, OFF = "\033[32m", "\033[31m", "\033[33m", "\033[1m", "\033[0m"


def die(msg: str) -> None:
    print(f"{RED}FAIL:{OFF} {msg}")
    sys.exit(1)


def main() -> None:
    if len(sys.argv) < 2:
        die(
            "pass your LINE userId as the first argument.\n"
            "  Find it at: LINE Developers Console -> your channel\n"
            "              -> Basic settings -> 'Your user ID' (starts with U)"
        )
    line_user_id = sys.argv[1].strip()
    if not line_user_id.startswith("U"):
        print(
            f"{YELLOW}warning:{OFF} a LINE userId normally starts with 'U'. "
            f"Got {line_user_id!r} -- continuing anyway."
        )

    if not settings.LINE_CHANNEL_ACCESS_TOKEN:
        die(
            "LINE_CHANNEL_ACCESS_TOKEN is unset, so no push can be sent.\n"
            "  Issue a long-lived token: LINE Developers Console -> your channel\n"
            "  -> Messaging API tab -> 'Channel access token (long-lived)'.\n"
            "  Put it in .env, then: docker compose up -d --force-recreate backend"
        )

    with Session(engine) as session:
        user = session.exec(
            select(User).where(User.email == settings.FIRST_SUPERUSER)
        ).first()
        if user is None:
            die(f"no user {settings.FIRST_SUPERUSER}; run app.initial_data first")

        print(f"\n{BOLD}1. Bind your real LINE account to {user.email}{OFF}")
        incumbent = session.exec(
            select(User).where(
                User.line_user_id == line_user_id, User.id != user.id
            )
        ).first()
        if incumbent is not None:
            die(
                f"that LINE userId is already bound to {incumbent.email}. "
                "line_user_id is UNIQUE by design so two staff cannot cross-feed "
                "each other's alerts."
            )
        user.line_user_id = line_user_id
        session.add(user)
        session.commit()
        print(f"{GREEN}  ok{OFF} bound")

        print(f"\n{BOLD}2. Opt in to LOW_STOCK over LINE{OFF}")
        pref = session.exec(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user.id,
                NotificationPreference.channel == NotificationChannel.LINE,
                NotificationPreference.event_type == NotificationEvent.LOW_STOCK,
            )
        ).first()
        if pref is None:
            pref = NotificationPreference(
                user_id=user.id,
                channel=NotificationChannel.LINE,
                event_type=NotificationEvent.LOW_STOCK,
                enabled=True,
            )
        pref.enabled = True
        session.add(pref)
        session.commit()
        print(f"{GREEN}  ok{OFF} enabled")

        print(f"\n{BOLD}3. Force a product below its threshold{OFF}")
        product = session.exec(select(Product)).first()
        if product is None:
            die("no products in the database; run `python -m app.seed_demo`")
        on_hand = crud._on_hand(session, product)
        original = product.default_min_stock_level
        # notify_low_stock re-checks on_hand < threshold at dispatch, so the
        # threshold has to genuinely exceed stock or it will (correctly) send
        # nothing.
        product.default_min_stock_level = on_hand + 10
        session.add(product)
        session.commit()
        print(
            f"{GREEN}  ok{OFF} {product.sku} on_hand={on_hand} "
            f"min_stock_level {original} -> {product.default_min_stock_level}"
        )

        print(f"\n{BOLD}4. Run the real low-stock dispatcher{OFF}")
        logs = notify.notify_low_stock(session=session, product_ids=[product.id])

        line_logs = [
            lg for lg in logs if lg.channel == NotificationChannel.LINE
        ]
        if not line_logs:
            die(
                "the dispatcher produced no LINE log row at all -- the "
                "preference or the recipient query did not match."
            )
        for lg in line_logs:
            if lg.status == NotificationStatus.SENT:
                print(
                    f"{GREEN}  SENT{OFF} after {lg.attempts} attempt(s) "
                    "-- check your phone"
                )
            else:
                print(f"{RED}  {lg.status.value}{OFF} after {lg.attempts} attempt(s)")
                print(f"       {lg.last_error}")

        print(f"\n{BOLD}5. Restore the threshold{OFF}")
        product.default_min_stock_level = original
        session.add(product)
        session.commit()
        print(f"{GREEN}  ok{OFF} {product.sku} min_stock_level back to {original}")

        sent = any(lg.status == NotificationStatus.SENT for lg in line_logs)
        if sent:
            print(f"\n{GREEN}{BOLD}LINE reported the message as accepted.{OFF}")
            print(
                "Caveat worth knowing: LINE returns 200 even when the recipient\n"
                "has blocked or never added the Official Account, so SENT means\n"
                "'LINE accepted it', not 'it appeared on a phone'. If nothing\n"
                "arrives, add the Official Account as a friend and re-run."
            )
        else:
            print(f"\n{RED}{BOLD}Not delivered -- see the error above.{OFF}")
            sys.exit(1)


if __name__ == "__main__":
    main()
