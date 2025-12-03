"""Custom exceptions for liq-sim."""


class LookAheadBiasError(ValueError):
    """Raised when an order attempts to use information from the current/future bar."""


class IneligibleOrderError(ValueError):
    """Raised when an order is not eligible for execution due to delay constraints."""
