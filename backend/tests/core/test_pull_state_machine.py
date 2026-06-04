import pytest

from app.core.state_machine import IllegalTransition, assert_pull_transition
from app.models import ProjectPullState as P

# Every legal (current_state, target_state) pair (spec §4.5).
LEGAL = [
    (P.PENDING, P.FULFILLED),
    (P.PENDING, P.SHORT),
    (P.PENDING, P.CANCELLED),
    (P.SHORT, P.CANCELLED),
]

_LEGAL_KEYS = {(frm, to) for frm, to in LEGAL}
# Exhaustive complement: every other (state, target) pair must raise.
ILLEGAL = [
    (frm, to)
    for frm in P
    for to in P
    if (frm, to) not in _LEGAL_KEYS
]


@pytest.mark.parametrize("frm,to", LEGAL)
def test_legal_pull_transitions(frm: P, to: P) -> None:
    assert assert_pull_transition(frm, to) == to


@pytest.mark.parametrize("frm,to", ILLEGAL)
def test_illegal_pull_transitions_raise(frm: P, to: P) -> None:
    with pytest.raises(IllegalTransition):
        assert_pull_transition(frm, to)
