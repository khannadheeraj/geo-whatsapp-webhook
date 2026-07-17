from typing import Any, Dict, Optional


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        field_errors: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.field_errors = field_errors or {}


class AuthenticationError(ApiError):
    def __init__(self, code: str = "AUTHENTICATION_REQUIRED", message: str = "Authentication is required.") -> None:
        super().__init__(401, code, message)


class AuthorizationError(ApiError):
    def __init__(self, code: str = "FORBIDDEN", message: str = "You are not permitted to perform this action.") -> None:
        super().__init__(403, code, message)


class ConflictError(ApiError):
    def __init__(
        self,
        code: str,
        message: str,
        field_errors: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(409, code, message, field_errors)


class NotFoundError(ApiError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(404, code, message)


class GoneError(ApiError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(410, code, message)


class PayloadTooLargeError(ApiError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(413, code, message)


class ValidationApiError(ApiError):
    def __init__(self, code: str, message: str, field_errors: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(422, code, message, field_errors)


class WebhookSignatureError(ApiError):
    def __init__(self) -> None:
        super().__init__(401, "WEBHOOK_SIGNATURE_INVALID", "Webhook signature validation failed.")
