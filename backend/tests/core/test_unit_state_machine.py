import pytest

from app.core.state_machine import IllegalTransition, assert_unit_transition
from app.models import MovementType as M
from app.models import UnitState as S

# Every legal (current_state, event) -> next_state pair (spec §4.4).
LEGAL = [
    (S.RECEIVED, M.RECEIVED, S.IN_STOCK),  # receive
    (S.IN_STOCK, M.SOLD, S.SOLD),
    (S.IN_STOCK, M.MAINTENANCE_OUT, S.MAINTENANCE_OUT),
    (S.IN_STOCK, M.PROJECT_OUT, S.PROJECT_OUT),
    (S.IN_STOCK, M.ADJUSTED_OUT, S.ADJUSTED_OUT),
]

_LEGAL_KEYS = {(frm, mv) for frm, mv, _ in LEGAL}
# Exhaustive complement: every (state, event) pair that is NOT legal must raise.
ILLEGAL = [
    (frm, mv)
    for frm in S
    for mv in M
    if (frm, mv) not in _LEGAL_KEYS
]


@pytest.mark.parametrize("frm,mv,to", LEGAL)
def test_legal_transitions(frm: S, mv: M, to: S) -> None:
    assert assert_unit_transition(frm, mv) == to


@pytest.mark.parametrize("frm,mv", ILLEGAL)
def test_illegal_transitions_raise(frm: S, mv: M) -> None:
    with pytest.raises(IllegalTransition):
        assert_unit_transition(frm, mv)
