import pytest

from app.exceptions import InvalidTransitionError
from app.models.enums import MovementType, UnitStatus
from app.services.state_machine import (
    apply_movement_transition,
    release_reservation,
    reserve,
)


@pytest.mark.parametrize(
    ("current", "movement", "expected"),
    [
        (UnitStatus.in_stock, MovementType.issue, UnitStatus.issued),
        (UnitStatus.reserved, MovementType.issue, UnitStatus.issued),
        (UnitStatus.in_stock, MovementType.transfer, UnitStatus.in_stock),
        (UnitStatus.issued, MovementType.transfer, UnitStatus.in_stock),
        (UnitStatus.in_rma, MovementType.transfer, UnitStatus.in_stock),
        (UnitStatus.lost, MovementType.transfer, UnitStatus.in_stock),
        (UnitStatus.scrapped, MovementType.transfer, UnitStatus.in_stock),
        (UnitStatus.reserved, MovementType.transfer, UnitStatus.in_stock),
        (UnitStatus.issued, MovementType.return_, UnitStatus.in_stock),
        (UnitStatus.in_stock, MovementType.rma_out, UnitStatus.in_rma),
        (UnitStatus.in_rma, MovementType.rma_in, UnitStatus.in_stock),
        (UnitStatus.in_stock, MovementType.scrap, UnitStatus.scrapped),
        (UnitStatus.in_rma, MovementType.scrap, UnitStatus.scrapped),
        (UnitStatus.in_stock, MovementType.adjustment, UnitStatus.lost),
        (UnitStatus.lost, MovementType.adjustment, UnitStatus.in_stock),
        # Reversing a scrap routes through adjustment (see
        # movements._reverse_movement_type): it must undo the rottamazione.
        (UnitStatus.scrapped, MovementType.adjustment, UnitStatus.in_stock),
    ],
)
def test_valid_transitions(
    current: UnitStatus, movement: MovementType, expected: UnitStatus
) -> None:
    assert apply_movement_transition(current, movement) == expected


@pytest.mark.parametrize(
    ("current", "movement"),
    [
        (UnitStatus.issued, MovementType.issue),
        (UnitStatus.scrapped, MovementType.issue),
        (UnitStatus.in_stock, MovementType.rma_in),
        (UnitStatus.in_stock, MovementType.return_),
        (UnitStatus.scrapped, MovementType.scrap),
    ],
)
def test_invalid_transitions_raise(current: UnitStatus, movement: MovementType) -> None:
    with pytest.raises(InvalidTransitionError):
        apply_movement_transition(current, movement)


def test_reserve_requires_in_stock() -> None:
    assert reserve(UnitStatus.in_stock) == UnitStatus.reserved
    with pytest.raises(InvalidTransitionError):
        reserve(UnitStatus.issued)


def test_release_reservation_requires_reserved() -> None:
    assert release_reservation(UnitStatus.reserved) == UnitStatus.in_stock
    with pytest.raises(InvalidTransitionError):
        release_reservation(UnitStatus.in_stock)
