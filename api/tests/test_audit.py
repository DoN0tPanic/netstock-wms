import datetime
import uuid
from decimal import Decimal

from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.users import User
from app.services.audit import write_audit


async def test_details_with_date_uuid_decimal_are_json_safe(app_db_session) -> None:
    # PATCH /units/{id} builds `details` straight from
    # `payload.model_dump(exclude_unset=True)`, which keeps native `date`
    # objects — this used to 500 on flush because the JSONB column's default
    # encoder can't serialize them.
    user = (await app_db_session.execute(select(User).limit(1))).scalar_one()
    some_uuid = uuid.uuid4()

    await write_audit(
        app_db_session,
        actor=user,
        actor_username=user.username,
        action="unit.update",
        entity_type="stock_unit",
        entity_id=str(some_uuid),
        details={
            "changed_fields": {
                "warranty_end": datetime.date(2027, 12, 31),
                "contract_ref": "CONTRACT-1",
                "reference_id": some_uuid,
                "quantity": Decimal("3.00"),
            }
        },
    )
    await app_db_session.flush()

    entry = (
        await app_db_session.execute(
            select(AuditLog).where(AuditLog.entity_id == str(some_uuid))
        )
    ).scalar_one()
    changed = entry.details["changed_fields"]
    assert changed["warranty_end"] == "2027-12-31"
    assert changed["contract_ref"] == "CONTRACT-1"
    assert changed["reference_id"] == str(some_uuid)
    assert changed["quantity"] == "3.00"


async def test_forbidden_keys_still_stripped_alongside_coercion(app_db_session) -> None:
    user = (await app_db_session.execute(select(User).limit(1))).scalar_one()

    await write_audit(
        app_db_session,
        actor=user,
        actor_username=user.username,
        action="user.update",
        entity_type="user",
        entity_id=str(uuid.uuid4()),
        details={"password": "should-never-be-stored", "full_name": "Test User"},
    )
    await app_db_session.flush()

    entry = (
        await app_db_session.execute(
            select(AuditLog).where(AuditLog.action == "user.update").order_by(AuditLog.id.desc())
        )
    ).scalars().first()
    assert "password" not in entry.details
    assert entry.details["full_name"] == "Test User"
