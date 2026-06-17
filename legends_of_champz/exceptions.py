class LoCError(Exception):
    """Base exception for all Legends of Champz API errors."""


class LoCAuthError(LoCError):
    """API key missing, invalid, or revoked."""


class LoCCycleError(LoCError):
    """No active or upcoming cycle available."""


class LoCEnrollmentError(LoCError):
    """Enrollment failed (cycle full, window closed, already enrolled)."""


class LoCStrategyError(LoCError):
    """Strategy submission failed (past deadline, invalid params)."""


class LoCClaimError(LoCError):
    """Claim operation failed."""


class LoCNetworkError(LoCError):
    """HTTP / network error communicating with the API."""
