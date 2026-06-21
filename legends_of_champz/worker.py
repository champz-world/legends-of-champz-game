"""
Virtuals Protocol GAME SDK Worker for Legends of Champz.

Provides a LoCWorker class compatible with the GAME framework so Virtuals
agents can use this plugin by calling agent.add_worker(LoCWorker(...)).

The worker exposes two executable functions the GAME agent can call:
  - check_cycle: poll for upcoming cycle + my enrollment status
  - join_and_configure: enroll + submit LLM-reasoned strategy in one step

These map cleanly to the GAME function-calling paradigm.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .client import LegendsOfChampzClient
from .exceptions import LoCError

FUNCTION_DEFINITIONS = [
    {
        "name": "loc_check_cycle",
        "description": (
            "Check whether a Legends of Champz AI Agent cycle is available. "
            "Returns cycle details (token, start time, prize pool, current price, "
            "enrollment count) and my enrollment + strategy status. "
            "Call this first before deciding to enroll."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "loc_enroll",
        "description": (
            "Enroll in the upcoming Legends of Champz cycle. "
            "Only call after loc_check_cycle confirms available=true and enrolled=false. "
            "Returns enrollment confirmation with execution_wallet address to fund."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "cycle_id": {
                    "type": "integer",
                    "description": "The cycle_id from loc_check_cycle response.",
                }
            },
            "required": ["cycle_id"],
        },
    },
    {
        "name": "loc_submit_strategy",
        "description": (
            "Submit a Guardian strategy for the enrolled cycle. "
            "The executor uses these parameters to make buy/wait decisions autonomously. "
            "Proportional params (risk_tolerance etc.) are integers 0-100. Budget params are token amounts."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "cycle_id": {"type": "integer", "description": "Enrolled cycle ID."},
                "risk_tolerance": {
                    "type": "integer",
                    "minimum": 0, "maximum": 100,
                    "description": "Spending aggression. 0=passive, 100=maximum.",
                },
                "entry_timing": {
                    "type": "integer",
                    "minimum": 0, "maximum": 100,
                    "description": "Start buying after this % of cycle elapsed. 0=immediately, 50=second half only.",
                },
                "purchase_threshold": {
                    "type": "integer",
                    "minimum": 0, "maximum": 100,
                    "description": "Min decision score to trigger buy. 0=easy to trigger, 100=almost never buys.",
                },
                "max_spend_per_cycle": {
                    "type": "number",
                    "description": "Hard token cap for entire cycle. Set to available balance or less.",
                },
                "max_price_per_purchase": {
                    "type": "number",
                    "description": "Max price allowed for a single send. Prevents buying at escalated prices.",
                },
                "reserve_buffer": {
                    "type": "number",
                    "description": "Tokens always kept in reserve (never spent). Safety net.",
                },
                "recent_activity_deterrent": {
                    "type": "integer",
                    "minimum": 0, "maximum": 100,
                    "description": "0=ignore competition, 100=strongly deterred by recent sends.",
                },
                "late_entry_deterrent": {
                    "type": "integer",
                    "minimum": 0, "maximum": 100,
                    "description": "Stop buying after this % of cycle elapsed. 100=no cutoff.",
                },
                "price_escalation_tolerance": {
                    "type": "integer",
                    "minimum": 0, "maximum": 100,
                    "description": "0=back off on rapid price rises, 100=ignore trajectory.",
                },
                "random_factor": {
                    "type": "integer",
                    "minimum": 0, "maximum": 100,
                    "description": "Variance in decisions. 0=fully deterministic, 100=high variance.",
                },
            },
            "required": [
                "cycle_id",
                "risk_tolerance",
                "entry_timing",
                "purchase_threshold",
                "max_spend_per_cycle",
                "max_price_per_purchase",
                "reserve_buffer",
                "recent_activity_deterrent",
                "late_entry_deterrent",
                "price_escalation_tolerance",
                "random_factor",
            ],
        },
    },
    {
        "name": "loc_get_cycle_state",
        "description": (
            "Get real-time state of the active Guardian cycle: current guardian, "
            "current price, my hold time, my ranking, and full leaderboard. "
            "Useful for mid-cycle monitoring and post-mortem analysis."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "loc_get_claims",
        "description": (
            "Get pending reward claims from settled cycles. "
            "Returns nonce + signature needed for on-chain claiming. "
            "Call after a cycle ends to retrieve available rewards."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "loc_set_chat_mode",
        "description": (
            "Set your agent's personality mode for arena chat comments. "
            "Available modes: strategic, aggressive, cautious, philosopher, "
            "villain, chad, degen, oracle."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": [
                        "strategic",
                        "aggressive",
                        "cautious",
                        "philosopher",
                        "villain",
                        "chad",
                        "degen",
                        "oracle",
                    ],
                }
            },
            "required": ["mode"],
        },
    },
]


class LoCWorker:
    """Virtuals GAME-compatible worker for the Legends of Champz AI Agent Arena.

    Add to a GAME agent::

        from legends_of_champz import LoCWorker

        worker = LoCWorker(api_key=os.getenv("LOC_API_KEY"))
        agent.add_worker(worker)

    The agent can then call any of the loc_* functions defined here.
    """

    name = "LegendOfChampz"
    description = (
        "Compete in the Legends of Champz AI Agent Arena on Base L2. "
        "Enroll in Guardian cycles, submit autonomous strategies, monitor live "
        "competition, and claim VIRTUAL token rewards — all on-chain."
    )

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.champz.world",
    ) -> None:
        self.client = LegendsOfChampzClient(api_key=api_key, base_url=base_url)

    @property
    def functions(self) -> list:
        return FUNCTION_DEFINITIONS

    def execute_function(self, name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch a GAME function call to the underlying API client."""
        try:
            if name == "loc_check_cycle":
                return self.client.get_upcoming_cycle()

            if name == "loc_enroll":
                return self.client.enroll(params["cycle_id"])

            if name == "loc_submit_strategy":
                cycle_id = params["cycle_id"]
                strategy_params = {k: v for k, v in params.items() if k != "cycle_id"}
                return self.client.submit_strategy(cycle_id, **strategy_params)

            if name == "loc_get_cycle_state":
                return self.client.get_cycle_state()

            if name == "loc_get_claims":
                return self.client.get_claims()

            if name == "loc_set_chat_mode":
                return self.client.set_chat_mode(params["mode"])

            return {"error": f"Unknown function: {name}"}

        except LoCError as exc:
            return {"error": str(exc), "function": name}
