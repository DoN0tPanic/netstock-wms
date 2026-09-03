from dataclasses import dataclass

from app.api.v1.dashboard import get_dashboard
from app.models.enums import UserRole


@dataclass
class _FakeUser:
    role: UserRole


async def test_dashboard_returns_all_expected_sections(app_db_session) -> None:
    result = await get_dashboard(db=app_db_session, user=_FakeUser(role=UserRole.admin))

    assert isinstance(result.total_by_category, list)
    assert isinstance(result.below_reorder, list)
    assert isinstance(result.open_delivery_notes, int)
    assert isinstance(result.recent_movements, list)
    assert len(result.recent_movements) <= 20
    assert isinstance(result.expiring_warranties, list)
    assert isinstance(result.reconciliation_errors, int)
    assert isinstance(result.reconciliation_error_rows, list)


async def test_dashboard_hides_reconciliation_rows_for_non_admin(app_db_session) -> None:
    viewer_result = await get_dashboard(db=app_db_session, user=_FakeUser(role=UserRole.viewer))
    operator_result = await get_dashboard(
        db=app_db_session, user=_FakeUser(role=UserRole.operator)
    )

    assert viewer_result.reconciliation_error_rows == []
    assert viewer_result.reconciliation_errors == 0
    assert operator_result.reconciliation_error_rows == []
    assert operator_result.reconciliation_errors == 0
