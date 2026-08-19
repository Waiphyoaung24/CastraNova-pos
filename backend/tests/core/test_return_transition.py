"""The SOLD -> IN_STOCK edge, reachable only via a sale return (m035)."""

import pytest

from app.core.state_machine import IllegalTransition, assert_unit_transition
from app.models import MovementType, UnitState


def test_sold_unit_returns_to_stock():
    assert (
        assert_unit_transition(UnitState.SOLD, MovementType.RETURNED)
        == UnitState.IN_STOCK
    )


def test_in_stock_unit_cannot_be_returned():
    with pytest.raises(IllegalTransition):
        assert_unit_transition(UnitState.IN_STOCK, MovementType.RETURNED)


def test_adjusted_out_unit_cannot_be_returned():
    with pytest.raises(IllegalTransition):
        assert_unit_transition(UnitState.ADJUSTED_OUT, MovementType.RETURNED)
