from app.models import (
    AdjustmentTarget,
    Channel,
    CustomerType,
    LineState,
    MovementType,
    OverrideState,
    ProjectPullState,
    TrackingMode,
    UnitState,
    UserRole,
)


def test_user_roles():
    assert {r.value for r in UserRole} == {"BKK_ADMIN", "YGN_STAFF"}


def test_tracking_modes():
    assert {m.value for m in TrackingMode} == {"SERIALIZED", "QUANTITY"}


def test_channels():
    assert {c.value for c in Channel} == {"SALE", "MAINTENANCE", "PROJECT"}


def test_unit_states_terminal_set():
    assert UnitState.ADJUSTED_OUT.value == "ADJUSTED_OUT"
    assert {s.value for s in UnitState} >= {
        "RECEIVED",
        "IN_STOCK",
        "SOLD",
        "MAINTENANCE_OUT",
        "PROJECT_OUT",
        "ADJUSTED_OUT",
    }


def test_movement_types():
    assert {m.value for m in MovementType} == {
        "RECEIVED",
        "SOLD",
        "MAINTENANCE_OUT",
        "PROJECT_OUT",
        "ADJUSTED_OUT",
        "RETURNED",
    }


def test_project_pull_states():
    assert {s.value for s in ProjectPullState} == {
        "PENDING",
        "FULFILLED",
        "SHORT",
        "CANCELLED",
    }


def test_line_states():
    assert {s.value for s in LineState} == {
        "PENDING",
        "FULFILLED",
        "SHORT",
        "CANCELLED",
    }


def test_override_states():
    assert {s.value for s in OverrideState} == {
        "AUTO_APPROVED",
        "PENDING",
        "APPROVED",
        "REJECTED",
    }


def test_adjustment_targets():
    assert {t.value for t in AdjustmentTarget} == {"UNIT", "QUANTITY"}


def test_customer_types():
    assert {t.value for t in CustomerType} == {"DEALER", "END_CUSTOMER"}
