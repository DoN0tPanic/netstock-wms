from typing import Any


class AppError(Exception):
    """Domain error mapped to the uniform error envelope of §6.1."""

    status_code: int = 400
    code: str = "APP_ERROR"

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class InsufficientStockError(AppError):
    status_code = 409
    code = "INSUFFICIENT_STOCK"


class InvalidTransitionError(AppError):
    status_code = 409
    code = "INVALID_TRANSITION"


class DuplicateSerialError(AppError):
    status_code = 409
    code = "DUPLICATE_SERIAL"


class ConfirmationRequiredError(AppError):
    status_code = 409
    code = "CONFIRMATION_REQUIRED"


class AlreadyReversedError(AppError):
    status_code = 409
    code = "ALREADY_REVERSED"


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class ConflictAppError(AppError):
    """Operazione legittima ma non adesso: qualcosa di incompatibile è in corso."""

    status_code = 409
    code = "CONFLICT"


class ValidationAppError(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"


class UnauthorizedError(AppError):
    status_code = 401
    code = "UNAUTHORIZED"


class ForbiddenError(AppError):
    status_code = 403
    code = "FORBIDDEN"


class LockedOutError(AppError):
    status_code = 423
    code = "ACCOUNT_LOCKED"


class RateLimitedError(AppError):
    status_code = 429
    code = "RATE_LIMITED"
