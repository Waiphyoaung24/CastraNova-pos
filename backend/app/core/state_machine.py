"""Server-enforced unit state machine (spec §4.4).

Pure functions only — no DB access. Every ``unit_movement`` insert must pass
through ``assert_unit_transition`` so illegal lifecycle moves are rejected
before any row is written.
"""

from app.models import MovementType, UnitState


class IllegalTransition(Exception):
    """Raised when a (current_state, event) pair is not a legal transition."""


# (current_state, event) -> next_state. Exactly the edges in spec §4.4.
_TABLE: dict[tuple[UnitState, MovementType], UnitState] = {
    (UnitState.RECEIVED, MovementType.RECEIVED): UnitState.IN_STOCK,
    (UnitState.IN_STOCK, MovementType.SOLD): UnitState.SOLD,
    (UnitState.IN_STOCK, MovementType.MAINTENANCE_OUT): UnitState.MAINTENANCE_OUT,
    (UnitState.IN_STOCK, MovementType.PROJECT_OUT): UnitState.PROJECT_OUT,
    (UnitState.IN_STOCK, MovementType.ADJUSTED_OUT): UnitState.ADJUSTED_OUT,
}


def assert_unit_transition(current: UnitState, event: MovementType) -> UnitState:
    """Return the resulting state for a legal transition, else raise.

    Raises:
        IllegalTransition: if ``(current, event)`` is not a legal edge.
    """
    try:
        return _TABLE[(current, event)]
    except KeyError:
        raise IllegalTransition(f"{current.value} -[{event.value}]-> illegal") from None
