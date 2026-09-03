"""Unit lifecycle state machine (§5.2).

Explicit dictionary of valid transitions, never scattered `if` statements in
endpoints. Any transition not listed here is rejected with
`InvalidTransitionError` (mapped to HTTP 409 INVALID_TRANSITION).
"""

from app.exceptions import InvalidTransitionError
from app.models.enums import MovementType, UnitStatus

# Movement-driven transitions: {movement_type: {status_before: status_after}}.
MOVEMENT_TRANSITIONS: dict[MovementType, dict[UnitStatus, UnitStatus]] = {
    MovementType.issue: {
        UnitStatus.in_stock: UnitStatus.issued,
        UnitStatus.reserved: UnitStatus.issued,
    },
    MovementType.transfer: {
        # Giving a unit a location is the universal correction in this product:
        # goods never leave the archive, so whatever state a piece is in —
        # issued, in RMA, lost, reserved, or scrapped by mistake — assigning it
        # a location brings it back in stock. Every status is listed on
        # purpose: a piece that cannot be relocated is a piece the operator
        # cannot fix.
        UnitStatus.in_stock: UnitStatus.in_stock,
        UnitStatus.issued: UnitStatus.in_stock,
        UnitStatus.in_rma: UnitStatus.in_stock,
        UnitStatus.lost: UnitStatus.in_stock,
        UnitStatus.reserved: UnitStatus.in_stock,
        UnitStatus.scrapped: UnitStatus.in_stock,
    },
    MovementType.return_: {
        UnitStatus.issued: UnitStatus.in_stock,
    },
    MovementType.rma_out: {
        UnitStatus.in_stock: UnitStatus.in_rma,
    },
    MovementType.rma_in: {
        UnitStatus.in_rma: UnitStatus.in_stock,
    },
    MovementType.scrap: {
        UnitStatus.in_stock: UnitStatus.scrapped,
        UnitStatus.in_rma: UnitStatus.scrapped,
    },
    MovementType.adjustment: {
        UnitStatus.in_stock: UnitStatus.lost,
        UnitStatus.in_rma: UnitStatus.lost,
        UnitStatus.lost: UnitStatus.in_stock,
        UnitStatus.issued: UnitStatus.in_stock,
        UnitStatus.reserved: UnitStatus.in_stock,
        # Reversing a scrap arrives here (see _reverse_movement_type): without
        # this entry "Storna" on a rottamazione failed with 409, leaving a
        # mistaken scrap correctable only by relocating the piece.
        UnitStatus.scrapped: UnitStatus.in_stock,
    },
}


def apply_movement_transition(current: UnitStatus, movement_type: MovementType) -> UnitStatus:
    allowed = MOVEMENT_TRANSITIONS.get(movement_type)
    if allowed is None or current not in allowed:
        raise InvalidTransitionError(
            f"Transizione non consentita: unità in stato '{current.value}' "
            f"non può ricevere un movimento di tipo '{movement_type.value}'.",
            details={"current_status": current.value, "movement_type": movement_type.value},
        )
    return allowed[current]


def reserve(current: UnitStatus) -> UnitStatus:
    if current != UnitStatus.in_stock:
        raise InvalidTransitionError(
            f"Impossibile prenotare un'unità in stato '{current.value}': deve essere 'in_stock'.",
            details={"current_status": current.value},
        )
    return UnitStatus.reserved


def release_reservation(current: UnitStatus) -> UnitStatus:
    if current != UnitStatus.reserved:
        raise InvalidTransitionError(
            f"Impossibile liberare un'unità in stato '{current.value}': non è prenotata.",
            details={"current_status": current.value},
        )
    return UnitStatus.in_stock
