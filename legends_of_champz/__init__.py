"""Legends of Champz — AI Agent Arena SDK."""

from .client import LegendsOfChampzClient
from .exceptions import (
    LoCAuthError,
    LoCClaimError,
    LoCCycleError,
    LoCEnrollmentError,
    LoCError,
    LoCNetworkError,
    LoCStrategyError,
    LoCWithdrawError,
)
from .worker import LoCWorker

__version__ = "0.3.2"

__all__ = [
    "LegendsOfChampzClient",
    "LoCWorker",
    "LoCError",
    "LoCAuthError",
    "LoCCycleError",
    "LoCEnrollmentError",
    "LoCStrategyError",
    "LoCClaimError",
    "LoCNetworkError",
    "LoCWithdrawError",
]
