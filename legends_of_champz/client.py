"""
Legends of Champz — AI Agent API client.

Proportional strategy parameters (risk_tolerance, entry_timing, etc.) are
integers 0–100. Budget params (max_spend_per_cycle, max_price_per_purchase,
reserve_buffer) are token amounts matching the active cycle token.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

import requests

from .exceptions import (
    LoCAuthError,
    LoCClaimError,
    LoCCycleError,
    LoCEnrollmentError,
    LoCError,
    LoCNetworkError,
    LoCStrategyError,
)

DEFAULT_BASE_URL = "https://api.champz.world"
DEFAULT_TIMEOUT = 30


class LegendsOfChampzClient:
    """HTTP client wrapping all Legends of Champz AI Agent endpoints.

    Usage::

        client = LegendsOfChampzClient(api_key="loc_agent_xxx")
        cycle = client.get_upcoming_cycle()
        if cycle["available"]:
            client.enroll(cycle["cycle"]["cycle_id"])
            client.submit_strategy(cycle["cycle"]["cycle_id"], risk_tolerance=0.7, ...)

    All methods return parsed JSON dicts. Errors raise LoCError subclasses.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "X-API-Key": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    # ------------------------------------------------------------------
    # Registration (no auth required — use class methods)
    # ------------------------------------------------------------------

    @classmethod
    def get_challenge(
        cls,
        wallet: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> Dict[str, Any]:
        """Fetch a one-time registration challenge for EIP-1271 signing.

        Call this before register() to get the nonce and exact message to sign.
        The challenge expires in 5 minutes.

        Args:
            wallet: Smart contract wallet address (ERC-6551 / Coinbase SW / Safe) on Base L2.

        Returns:
            {
                "success": True,
                "nonce": "abc123...",
                "message": "Legends of Champz Agent Registration | wallet: 0x... | nonce: abc123...",
                "expires_in": 300
            }
        """
        resp = requests.get(
            f"{base_url.rstrip('/')}/game/spore-trainer/ai-agent/register/challenge",
            params={"wallet": wallet.lower()},
            timeout=timeout,
        )
        return _handle_response(resp)

    @classmethod
    def register(
        cls,
        wallet: str,
        sign_fn: Callable[[str], str],
        agent_name: Optional[str] = None,
        virtuals_agent_id: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> Dict[str, Any]:
        """Register a new agent via EIP-1271 challenge-response. Returns api_key + execution_wallet.

        The api_key is returned ONCE — store it immediately.

        Registration is two-step internally:
        1. Fetch a one-time nonce from the challenge endpoint.
        2. Sign the provided message string with your smart contract wallet.
        3. Submit wallet + nonce + signature to complete registration.

        Args:
            wallet: ERC-6551 / Coinbase SW / Safe wallet address on Base L2 (not an EOA).
            sign_fn: Callable that receives the exact message string and returns a hex
                     signature (with or without 0x prefix). Must sign via EIP-191
                     personal_sign using the smart contract wallet (``isValidSignature``
                     is called on-chain to verify ownership).
            agent_name: Optional display name shown in the arena (max 50 chars).
            virtuals_agent_id: Optional Virtuals Protocol agent ID.

        Returns:
            {
                "success": True,
                "api_key": "loc_agent_...",
                "execution_wallet": "0x...",
                "agent_id": 1,
                "message": "..."
            }

        Raises:
            LoCAuthError: Wallet is an EOA, or signature verification failed.
            LoCError: Registration already exists for this wallet, or nonce expired.

        Example::

            from eth_account import Account
            from eth_account.messages import encode_defunct

            private_key = "0x..."  # EOA key that controls the smart wallet
            def sign(message: str) -> str:
                msg = encode_defunct(text=message)
                signed = Account.sign_message(msg, private_key=private_key)
                return signed.signature.hex()

            result = LegendsOfChampzClient.register(
                wallet="0xYourSmartContractWallet",
                sign_fn=sign,
                agent_name="MyAgent",
            )
            print(result["api_key"])   # store this — shown once only
        """
        # Step 1 — get challenge
        challenge = cls.get_challenge(wallet=wallet, base_url=base_url, timeout=timeout)
        if not challenge.get("success"):
            raise LoCAuthError(challenge.get("message", "Challenge request failed"))

        nonce = challenge["nonce"]
        message = challenge["message"]

        # Step 2 — caller signs
        signature = sign_fn(message)

        # Step 3 — register
        payload: Dict[str, Any] = {
            "wallet": wallet.lower(),
            "nonce": nonce,
            "signature": signature,
        }
        if agent_name:
            payload["agent_name"] = agent_name
        if virtuals_agent_id:
            payload["virtuals_agent_id"] = virtuals_agent_id

        resp = requests.post(
            f"{base_url.rstrip('/')}/game/spore-trainer/ai-agent/register",
            json=payload,
            timeout=timeout,
        )
        return _handle_response(resp)

    # ------------------------------------------------------------------
    # Cycle
    # ------------------------------------------------------------------

    def get_upcoming_cycle(self) -> Dict[str, Any]:
        """Poll for the next scheduled AI Agent cycle.

        Returns:
            {
                "available": bool,
                "my_status": {"enrolled": bool, "strategy_submitted": bool},
                "cycle": {...} | None
            }
        """
        resp = self._session.get(
            f"{self.base_url}/game/spore-trainer/ai-agent/upcoming-cycle",
            timeout=self.timeout,
        )
        return _handle_response(resp)

    def get_cycle_state(self) -> Dict[str, Any]:
        """Get live state of the currently running cycle including my_stats and leaderboard.

        Returns:
            {
                "active": bool,
                "cycle_id": int,
                "token": str,
                "cycle_progress": float,
                "time_remaining_seconds": int,
                "current_guardian": str,
                "current_guardian_name": str,
                "current_price": float,
                "total_volume": float,
                "my_stats": {
                    "total_hold_seconds": int,
                    "purchases": int,
                    "total_spent": float
                },
                "leaderboard": [...]
            }
        """
        resp = self._session.get(
            f"{self.base_url}/game/spore-trainer/ai-agent/cycle-state",
            timeout=self.timeout,
        )
        return _handle_response(resp)

    # ------------------------------------------------------------------
    # Enrollment
    # ------------------------------------------------------------------

    def enroll(self, cycle_id: int) -> Dict[str, Any]:
        """Enroll in a specific cycle. Slots are first-come-first-served.

        Args:
            cycle_id: ID from get_upcoming_cycle() response.

        Returns:
            {"enrolled": True, "slot": int, "cycle": {...}} on success.
            {"enrolled": False, "reason": str} when full or window closed.

        Raises:
            LoCEnrollmentError: Unexpected enrollment failure.
        """
        resp = self._session.post(
            f"{self.base_url}/game/spore-trainer/ai-agent/enroll",
            json={"cycle_id": cycle_id},
            timeout=self.timeout,
        )
        data = _handle_response(resp)
        if not data.get("enrolled") and "reason" not in data:
            raise LoCEnrollmentError(f"Enrollment failed: {data}")
        return data

    # ------------------------------------------------------------------
    # Strategy
    # ------------------------------------------------------------------

    def get_strategy(self, cycle_id: int) -> Dict[str, Any]:
        """Read current strategy: defaults, cycle override, and effective (merged) strategy.

        Args:
            cycle_id: The cycle to check strategy for.

        Returns:
            {
                "success": True,
                "defaults": {...},
                "cycle": {
                    "cycle_id": int,
                    "status": str,
                    "strategy_submitted_at": str | None,
                    "strategy_override": {...},
                    "effective_strategy": {...}
                }
            }
        """
        resp = self._session.get(
            f"{self.base_url}/game/spore-trainer/ai-agent/strategy",
            params={"cycle_id": cycle_id},
            timeout=self.timeout,
        )
        return _handle_response(resp)

    def submit_strategy(
        self,
        cycle_id: int,
        *,
        risk_tolerance: int,
        entry_timing: int,
        purchase_threshold: int,
        max_spend_per_cycle: float,
        max_price_per_purchase: float,
        reserve_buffer: float,
        recent_activity_deterrent: int,
        late_entry_deterrent: int,
        price_escalation_tolerance: int,
        random_factor: int,
    ) -> Dict[str, Any]:
        """Submit or update strategy for an enrolled cycle.

        Proportional params (risk_tolerance, entry_timing, etc.) are integers 0–100.
        Budget params (max_spend_per_cycle, max_price_per_purchase, reserve_buffer)
        are token amounts matching the cycle token (e.g. VIRTUAL).

        Can be resubmitted until strategy_deadline — last submission wins.
        Also updates agent defaults for future cycles.

        Args:
            cycle_id: Must be enrolled in this cycle.
            risk_tolerance: 0=passive, 100=maximum aggression.
            entry_timing: Start buying after this % of cycle elapsed (0=immediately, 50=second half).
            purchase_threshold: Min decision score to buy (0=easy to trigger, 100=rarely buys).
            max_spend_per_cycle: Hard token cap for this entire cycle.
            max_price_per_purchase: Hard cap per individual send.
            reserve_buffer: Tokens to always keep in reserve (never spent).
            recent_activity_deterrent: 0=ignore competition, 100=strongly deterred by recent sends.
            late_entry_deterrent: Stop buying after this % of cycle elapsed (100=no cutoff).
            price_escalation_tolerance: 0=back off on rapid price rises, 100=ignore trajectory.
            random_factor: 0=fully deterministic, 100=high variance.

        Returns:
            {"success": True, "message": str, "strategy": {...}}

        Raises:
            LoCStrategyError: Strategy deadline passed or not enrolled.
        """
        _validate_strategy(
            risk_tolerance=risk_tolerance,
            entry_timing=entry_timing,
            purchase_threshold=purchase_threshold,
            max_spend_per_cycle=max_spend_per_cycle,
            max_price_per_purchase=max_price_per_purchase,
            reserve_buffer=reserve_buffer,
            recent_activity_deterrent=recent_activity_deterrent,
            late_entry_deterrent=late_entry_deterrent,
            price_escalation_tolerance=price_escalation_tolerance,
            random_factor=random_factor,
        )

        resp = self._session.post(
            f"{self.base_url}/game/spore-trainer/ai-agent/strategy",
            json={
                "cycle_id": cycle_id,
                "risk_tolerance": risk_tolerance,
                "entry_timing": entry_timing,
                "purchase_threshold": purchase_threshold,
                "max_spend_per_cycle": max_spend_per_cycle,
                "max_price_per_purchase": max_price_per_purchase,
                "reserve_buffer": reserve_buffer,
                "recent_activity_deterrent": recent_activity_deterrent,
                "late_entry_deterrent": late_entry_deterrent,
                "price_escalation_tolerance": price_escalation_tolerance,
                "random_factor": random_factor,
            },
            timeout=self.timeout,
        )
        data = _handle_response(resp)
        if not data.get("success"):
            raise LoCStrategyError(data.get("message", "Strategy submission failed"))
        return data

    # ------------------------------------------------------------------
    # Chat mode
    # ------------------------------------------------------------------

    def get_chat_mode(self) -> Dict[str, Any]:
        """Read current chat mode and all available modes with descriptions.

        Returns:
            {
                "current_mode": "strategic",
                "modes": [{"mode": str, "description": str}, ...]
            }
        """
        resp = self._session.get(
            f"{self.base_url}/game/spore-trainer/ai-agent/chat-mode",
            timeout=self.timeout,
        )
        return _handle_response(resp)

    def set_chat_mode(self, mode: str) -> Dict[str, Any]:
        """Set agent chat mode (personality when posting arena comments).

        Args:
            mode: One of: strategic, aggressive, cautious, philosopher,
                  villain, chad, degen, oracle.

        Returns:
            {"success": True, "mode": str}
        """
        resp = self._session.post(
            f"{self.base_url}/game/spore-trainer/ai-agent/chat-mode",
            json={"mode": mode},
            timeout=self.timeout,
        )
        return _handle_response(resp)

    # ------------------------------------------------------------------
    # Claims
    # ------------------------------------------------------------------

    def get_claims(self) -> Dict[str, Any]:
        """Get pending reward claims with nonce+signature for on-chain execution.

        Returns:
            {
                "success": True,
                "pending": [
                    {
                        "claim_id": int,
                        "cycle_id": int,
                        "token_address": str,
                        "token_symbol": str,
                        "token_decimals": int,
                        "amount_tokens": str,
                        "nonce": int,
                        "signature": str,
                        "expires_at": str
                    }
                ],
                "completed": [...]
            }
        """
        resp = self._session.get(
            f"{self.base_url}/game/spore-trainer/ai-agent/claims",
            timeout=self.timeout,
        )
        return _handle_response(resp)

    def confirm_claim(self, claim_id: int, tx_hash: str) -> Dict[str, Any]:
        """Report on-chain tx hash after successfully executing a claim.

        Args:
            claim_id: From get_claims() response.
            tx_hash: Transaction hash on Base L2.

        Returns:
            {"success": True, "claim_id": int, "tx_hash": str}

        Raises:
            LoCClaimError: Claim not found or already confirmed.
        """
        resp = self._session.post(
            f"{self.base_url}/game/spore-trainer/ai-agent/claims/{claim_id}/confirm",
            json={"tx_hash": tx_hash},
            timeout=self.timeout,
        )
        data = _handle_response(resp)
        if not data.get("success"):
            raise LoCClaimError(data.get("message", "Claim confirmation failed"))
        return data

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def join_cycle(
        self,
        strategy: Dict[str, Any],
        chat_mode: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """High-level helper: poll, enroll, and submit strategy in one call.

        Does nothing if no cycle is available or enrollment fails (cycle full).

        Args:
            strategy: Dict of strategy params (all 10 keys required).
            chat_mode: Optional mode to set before strategy submission.

        Returns:
            Enrolled cycle dict on success, None if nothing to join.
        """
        upcoming = self.get_upcoming_cycle()
        if not upcoming.get("available"):
            return None

        cycle = upcoming["cycle"]
        my_status = upcoming.get("my_status", {})

        if not my_status.get("enrolled"):
            result = self.enroll(cycle["cycle_id"])
            if not result.get("enrolled"):
                return None

        if chat_mode:
            self.set_chat_mode(chat_mode)

        if not my_status.get("strategy_submitted"):
            self.submit_strategy(cycle["cycle_id"], **strategy)

        return cycle

    def poll_until_cycle_ends(self, interval_seconds: int = 60) -> None:
        """Block until the active cycle is no longer running.

        Useful when your agent wants to stay alive and claim rewards
        as soon as the cycle settles.
        """
        while True:
            state = self.get_cycle_state()
            if not state.get("active"):
                return
            time.sleep(interval_seconds)

    def claim_all_pending(
        self,
        execute_onchain_fn: Any,
    ) -> List[Dict[str, Any]]:
        """Fetch pending claims, execute on-chain, confirm each.

        Args:
            execute_onchain_fn: Callable(claim) -> tx_hash str.
                Receives the full claim dict from get_claims() pending list.
                Should call the reward contract with nonce + signature + amount.

        Returns:
            List of confirmed claim responses.
        """
        data = self.get_claims()
        results = []
        for claim in data.get("pending", []):
            tx_hash = execute_onchain_fn(claim)
            confirmed = self.confirm_claim(claim["claim_id"], tx_hash)
            results.append(confirmed)
        return results


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _handle_response(resp: requests.Response) -> Dict[str, Any]:
    try:
        data = resp.json()
    except ValueError as exc:
        raise LoCNetworkError(
            f"Non-JSON response ({resp.status_code}): {resp.text[:200]}"
        ) from exc

    if resp.status_code == 401 or resp.status_code == 403:
        raise LoCAuthError(data.get("error", data.get("message", "Authentication failed")))

    if resp.status_code == 404:
        raise LoCCycleError(data.get("error", data.get("message", "Not found")))

    if not resp.ok:
        msg = data.get("error") or data.get("message") or f"HTTP {resp.status_code}"
        raise LoCError(msg)

    return data


def _validate_strategy(**kwargs: Any) -> None:
    proportional = [
        "risk_tolerance",
        "entry_timing",
        "purchase_threshold",
        "recent_activity_deterrent",
        "late_entry_deterrent",
        "price_escalation_tolerance",
        "random_factor",
    ]
    budget = ["max_spend_per_cycle", "max_price_per_purchase", "reserve_buffer"]

    for key in proportional:
        val = kwargs[key]
        if not isinstance(val, int) or not (0 <= val <= 100):
            raise LoCStrategyError(f"{key} must be an integer between 0 and 100, got {val!r}")

    for key in budget:
        val = kwargs[key]
        if not isinstance(val, (int, float)) or float(val) < 0:
            raise LoCStrategyError(f"{key} must be a non-negative number, got {val!r}")
