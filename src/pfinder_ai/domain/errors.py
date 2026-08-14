"""Structured exceptions that may safely cross application boundaries."""

from collections.abc import Mapping
from typing import Any

from pfinder_ai.domain.enums import ErrorKind


class PfinderAIError(Exception):
    """Base exception with retry semantics and non-sensitive context.

    Adapters should translate vendor exceptions into this hierarchy. The
    ``context`` mapping must contain identifiers or summaries only; raw logs,
    credentials, and customer data must never be attached to an exception.
    """

    def __init__(
        self,
        message: str,
        *,
        kind: ErrorKind,
        retryable: bool = False,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable
        self.context = dict(context or {})


class InvalidInvestigationInputError(PfinderAIError):
    """Raised when required user input is missing or inconsistent."""

    def __init__(self, message: str, *, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(
            message,
            kind=ErrorKind.INVALID_INPUT,
            retryable=False,
            context=context,
        )


class ProviderError(PfinderAIError):
    """Normalized failure returned by an external provider adapter."""


class StructuredOutputError(PfinderAIError):
    """Raised when a model response cannot be parsed into its declared schema."""

    def __init__(self, message: str, *, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(
            message,
            kind=ErrorKind.INVALID_RESPONSE,
            retryable=True,
            context=context,
        )


class BudgetExceededError(PfinderAIError):
    """Raised when an investigation reaches a configured execution budget."""

    def __init__(self, message: str, *, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(
            message,
            kind=ErrorKind.BUDGET_EXCEEDED,
            retryable=False,
            context=context,
        )

