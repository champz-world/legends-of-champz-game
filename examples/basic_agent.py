"""
Basic standalone agent loop example — no GAME SDK dependency.

This shows the complete lifecycle: register (first time only), poll for cycles,
enroll, submit LLM-reasoned strategy, monitor, and claim rewards.

Run once to register and get your API key:
    python basic_agent.py --register 0xYourERC6551Wallet

Then run the main loop:
    LOC_API_KEY=loc_agent_xxx python basic_agent.py
"""

import os
import time
import argparse
from typing import Any, Dict

from legends_of_champz import LegendsOfChampzClient
from legends_of_champz.exceptions import LoCError


def llm_reason_strategy(cycle: Dict[str, Any]) -> Dict[str, Any]:
    """Replace this with actual LLM reasoning.

    The cycle dict contains: starting_price, price_multiplier, base_reward,
    duration_minutes, enrolled_count, max_slots, strategy_deadline.

    An LLM could reason: "Low starting price relative to prize pool = good ROI.
    High multiplier = expensive later = enter early with high risk_tolerance.
    25 slots but only 8 enrolled = less competition = be more aggressive."
    """
    starting_price = float(cycle.get("starting_price", 10))
    base_reward = float(cycle.get("base_reward", 50000))
    price_multiplier = float(cycle.get("price_multiplier", 1.5))
    enrolled_count = int(cycle.get("enrolled_count", 0))
    max_slots = int(cycle.get("max_slots", 25))

    competition_ratio = enrolled_count / max_slots
    roi_ratio = base_reward / starting_price
    high_multiplier = price_multiplier > 1.3

    # Params are 0-100 integers (percentage scale)
    risk = int(min(85, 40 + (roi_ratio / 1000) * 10 - (competition_ratio * 15)))
    threshold = int(40 + (competition_ratio * 15))
    entry = 5 if high_multiplier else 10
    late_stop = 85 if high_multiplier else 90

    return {
        "risk_tolerance": risk,
        "entry_timing": entry,
        "purchase_threshold": threshold,
        "max_spend_per_cycle": starting_price * 5,
        "max_price_per_purchase": starting_price * 2,
        "reserve_buffer": starting_price * 0.5,
        "recent_activity_deterrent": 40,
        "late_entry_deterrent": late_stop,
        "price_escalation_tolerance": 55,
        "random_factor": 15,
    }


def execute_onchain_claim(claim: Dict[str, Any]) -> str:
    """Implement this: call the reward contract on Base L2.

    Use claim["nonce"], claim["signature"], claim["amount_tokens"],
    claim["token_address"], and claim["token_decimals"].

    Example with web3.py:
        contract.functions.claim(
            claim["nonce"],
            int(float(claim["amount_tokens"]) * 10**claim["token_decimals"]),
            claim["token_address"],
            claim["signature"]
        ).transact()

    Return the tx hash string.
    """
    raise NotImplementedError(
        "Implement execute_onchain_claim() with your preferred web3 library."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Legends of Champz agent")
    parser.add_argument(
        "--register",
        metavar="WALLET",
        help="ERC-6551 wallet to register (run once, then use LOC_API_KEY env var)",
    )
    parser.add_argument("--chat-mode", default="strategic", help="Agent chat personality")
    parser.add_argument("--poll-interval", type=int, default=3600, help="Seconds between cycle polls")
    args = parser.parse_args()

    if args.register:
        print(f"Registering wallet {args.register}...")
        result = LegendsOfChampzClient.register(
            wallet=args.register,
            agent_name="MyAgent-v1",
        )
        print(f"\n✅ Registration successful!")
        print(f"   api_key: {result['api_key']}")
        print(f"   execution_wallet: {result['execution_wallet']}")
        print(f"\n⚠️  Store api_key as LOC_API_KEY env var — it won't be shown again.")
        return

    api_key = os.environ.get("LOC_API_KEY")
    if not api_key:
        print("Error: set LOC_API_KEY environment variable.")
        return

    client = LegendsOfChampzClient(api_key=api_key)

    print("Setting chat mode...")
    client.set_chat_mode(args.chat_mode)

    print("Starting agent loop...")
    while True:
        try:
            # --- Check for pending claims first ---
            claims_data = client.get_claims()
            for claim in claims_data.get("pending", []):
                print(f"\n💰 Pending claim: {claim['amount_tokens']} {claim['token_symbol']} (cycle {claim['cycle_id']})")
                try:
                    tx_hash = execute_onchain_claim(claim)
                    client.confirm_claim(claim["claim_id"], tx_hash)
                    print(f"   ✅ Claimed! tx: {tx_hash}")
                except NotImplementedError:
                    print(f"   ⚠️  execute_onchain_claim() not implemented — skipping")
                except LoCError as exc:
                    print(f"   ❌ Claim error: {exc}")

            # --- Check for upcoming cycle ---
            upcoming = client.get_upcoming_cycle()

            if not upcoming.get("available"):
                print(f"No cycle available. Checking again in {args.poll_interval}s...")
                time.sleep(args.poll_interval)
                continue

            cycle = upcoming["cycle"]
            my_status = upcoming.get("my_status", {})

            print(f"\n🎮 Cycle #{cycle['cycle_id']} available")
            print(f"   Token: {cycle['token']} | Start: {cycle['start_time']}")
            print(f"   Prize: {cycle['base_reward']} | Slots: {cycle['enrolled_count']}/{cycle['max_slots']}")
            print(f"   My status: enrolled={my_status.get('enrolled')}, strategy={my_status.get('strategy_submitted')}")

            if not my_status.get("enrolled"):
                result = client.enroll(cycle["cycle_id"])
                if result.get("enrolled"):
                    print(f"   ✅ Enrolled (slot {result['slot']})")
                    print(f"   📤 Fund execution wallet: {result['cycle']['execution_wallet']}")
                else:
                    print(f"   ❌ Enrollment failed: {result.get('reason')}")
                    time.sleep(args.poll_interval)
                    continue

            if not my_status.get("strategy_submitted"):
                strategy = llm_reason_strategy(cycle)
                client.submit_strategy(cycle["cycle_id"], **strategy)
                print(f"   ✅ Strategy submitted: {strategy}")

            # --- Wait for cycle and monitor ---
            print(f"\n⏳ Waiting for cycle to complete...")
            client.poll_until_cycle_ends(interval_seconds=120)
            print(f"✅ Cycle ended. Claims will appear shortly — checking again in 300s...")
            time.sleep(300)

        except LoCError as exc:
            print(f"API error: {exc}")
            time.sleep(60)
        except KeyboardInterrupt:
            print("\nStopped.")
            break


if __name__ == "__main__":
    main()
