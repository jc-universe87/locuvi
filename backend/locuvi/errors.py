"""Domain errors carrying a stable i18n code; the frontend translates the code."""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    status_code = 400

    def __init__(self, code: str, message: str, **params: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.params = params

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "params": self.params}


class NotFound(DomainError):
    status_code = 404


class Conflict(DomainError):
    status_code = 409


class ValidationFailed(DomainError):
    status_code = 422

    def __init__(self, problems: list[dict[str, Any]]) -> None:
        super().__init__(
            "invoice.preflight_failed",
            "The invoice cannot be issued yet: " + "; ".join(p["message"] for p in problems),
            problems=problems,
        )
