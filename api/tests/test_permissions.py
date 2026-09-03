from dataclasses import dataclass

import pytest

from app.deps import require_role
from app.exceptions import ForbiddenError
from app.models.enums import UserRole


@dataclass
class _FakeUser:
    role: UserRole


@pytest.mark.parametrize(
    ("user_role", "minimum_role", "allowed"),
    [
        (UserRole.viewer, UserRole.viewer, True),
        (UserRole.viewer, UserRole.operator, False),
        (UserRole.viewer, UserRole.admin, False),
        (UserRole.operator, UserRole.viewer, True),
        (UserRole.operator, UserRole.operator, True),
        (UserRole.operator, UserRole.admin, False),
        (UserRole.admin, UserRole.viewer, True),
        (UserRole.admin, UserRole.operator, True),
        (UserRole.admin, UserRole.admin, True),
    ],
)
async def test_require_role(user_role: UserRole, minimum_role: UserRole, allowed: bool) -> None:
    dependency = require_role(minimum_role)
    user = _FakeUser(role=user_role)

    if allowed:
        result = await dependency(user)  # type: ignore[arg-type]
        assert result is user
    else:
        with pytest.raises(ForbiddenError):
            await dependency(user)  # type: ignore[arg-type]
