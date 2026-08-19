"""Which notification events a given role is eligible to receive.

This policy is the single source of truth behind the self-service preference
grid. It must agree with the recipient queries in ``app.services.notify``: a
grid that offers a staff user a checkbox for an admin-only event would persist
``enabled=True`` and then silently never deliver — worse than showing nothing.
"""

import pytest

from app.models import (
    ADMIN_ONLY_EVENTS,
    ALL_ROLE_EVENTS,
    NotificationChannel,
    NotificationEvent,
    User,
    UserRole,
    channel_connected,
    eligible_events,
)


def _user(role: UserRole) -> User:
    return User(email="x@example.test", hashed_password="x", role=role)


def test_every_event_is_classified() -> None:
    """Adding a NotificationEvent must force a deliberate choice about who can
    receive it, rather than defaulting into (or out of) the grid silently."""
    assert ADMIN_ONLY_EVENTS | ALL_ROLE_EVENTS == set(NotificationEvent)


def test_no_event_is_both_admin_only_and_all_role() -> None:
    assert not (ADMIN_ONLY_EVENTS & ALL_ROLE_EVENTS)


def test_admin_is_eligible_for_every_event() -> None:
    assert eligible_events(_user(UserRole.BKK_ADMIN)) == set(NotificationEvent)


def test_non_admin_role_gets_only_all_role_events() -> None:
    assert eligible_events(_user(UserRole.YGN_STAFF)) == ALL_ROLE_EVENTS


def test_low_stock_is_open_to_staff() -> None:
    # notify_low_stock has no role filter, so staff must be offered it.
    assert NotificationEvent.LOW_STOCK in eligible_events(_user(UserRole.YGN_STAFF))


@pytest.mark.parametrize(
    "event",
    [
        NotificationEvent.PULL_SHORT,
        NotificationEvent.PULL_FULFILLED,
        NotificationEvent.OVERRIDE_PENDING,
        NotificationEvent.SYNC_REVIEW_PENDING,
    ],
)
def test_admin_only_events_are_hidden_from_staff(event: NotificationEvent) -> None:
    # These producers query User.role == BKK_ADMIN, so a staff checkbox for
    # them could never deliver.
    assert event not in eligible_events(_user(UserRole.YGN_STAFF))


def test_sync_review_pending_is_admin_only() -> None:
    # The queue's list/resolve routes are get_admin-gated, so a staff
    # recipient could be told about something they cannot open.
    assert NotificationEvent.SYNC_REVIEW_PENDING in ADMIN_ONLY_EVENTS


def test_eligibility_keys_off_role_not_superuser_flag() -> None:
    """Regression guard for the is_admin / role divergence documented in
    notes.md: deps.is_admin treats any superuser as admin, but the notify
    producers query role strictly. A superuser left at the default staff role
    must NOT be offered admin-only events, or the grid would promise sends that
    never arrive."""
    superuser_with_staff_role = User(
        email="su@example.test",
        hashed_password="x",
        role=UserRole.YGN_STAFF,
        is_superuser=True,
    )
    assert eligible_events(superuser_with_staff_role) == ALL_ROLE_EVENTS


# --- channel_connected --------------------------------------------------------
#
# Whether a checkbox can ever actually deliver, independent of whether the
# user has opted into that event -- a preference row is meaningless to enable
# if notify() has no address to send to.


def test_channel_disconnected_by_default() -> None:
    user = _user(UserRole.YGN_STAFF)
    assert channel_connected(user, NotificationChannel.LINE) is False
    assert channel_connected(user, NotificationChannel.VIBER) is False
    assert channel_connected(user, NotificationChannel.TELEGRAM) is False


def test_channel_connected_when_address_set() -> None:
    user = _user(UserRole.YGN_STAFF)
    user.telegram_chat_id = "847392015"
    assert channel_connected(user, NotificationChannel.TELEGRAM) is True
    # Setting one channel's address must not affect the others.
    assert channel_connected(user, NotificationChannel.LINE) is False


def test_channel_connected_is_total_over_the_enum() -> None:
    """VIBER remains a legal enum member (historical notificationlog rows carry
    it) but has no address attribute. channel_connected must answer False for
    every member, never raise -- a channel we cannot address is by definition
    not connected."""
    user = _user(UserRole.YGN_STAFF)
    for channel in NotificationChannel:
        assert channel_connected(user, channel) is False


def test_channel_connected_treats_blank_string_as_disconnected() -> None:
    user = _user(UserRole.YGN_STAFF)
    user.line_user_id = ""
    assert channel_connected(user, NotificationChannel.LINE) is False
