"""Polymarket CTF (Conditional Token Framework) merge/redeem.

After buying a complete set of outcome tokens, we can immediately
merge them back into USDC collateral WITHOUT waiting for the
market to resolve. This is what makes arb capital-efficient.

CTF contract on Polygon:
  0x4D97DCd97eC945f40cF65F87097ACe5EA0476045

Key methods:
  - mergePositions(collateral, parentCollectionId, conditionId, partition, amount)
    → combines a complete set of outcome tokens back to collateral
  - redeemPositions(collateral, parentCollectionId, conditionId, indexSets)
    → claims winnings after resolution

For arb, mergePositions is what we want:
  - Buy YES + NO (or all NegRisk YES) → complete set
  - Call mergePositions → receive USDC immediately
  - Profit = USDC received - USDC paid
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Polygon mainnet addresses
CTF_CONTRACT = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
USDC_CONTRACT = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
NEG_RISK_ADAPTER = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"


def _get_web3():
    """Lazy-load web3 client."""
    try:
        from web3 import Web3
        rpc_url = os.environ.get("POLYGON_RPC", "https://polygon-rpc.com")
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        return w3
    except ImportError:
        logger.warning("web3 not installed. Run: pip install web3")
        return None


async def merge_complete_set(
    condition_id: str,
    amount: int,  # shares * 1e6 (USDC has 6 decimals)
    *,
    neg_risk: bool = False,
    private_key: Optional[str] = None,
) -> bool:
    """Merge a complete set of outcome tokens into USDC.

    For a binary market (YES/NO):
      - Holds 1 YES + 1 NO of the same conditionId
      - mergePositions combines them → 1 USDC

    For NegRisk (multi-outcome):
      - Holds 1 YES on each outcome market
      - Use NegRiskAdapter.mergePositions

    Args:
        condition_id: the market's condition ID
        amount: number of complete sets to merge (in wei, 6 decimals)
        neg_risk: True for NegRisk multi-outcome events
        private_key: wallet private key (defaults to env var)

    Returns:
        True on success, False otherwise.
    """
    if private_key is None:
        private_key = os.environ.get("POLY_PRIVATE_KEY", "")
    if not private_key:
        logger.error("POLY_PRIVATE_KEY not set")
        return False

    w3 = _get_web3()
    if w3 is None:
        return False

    account = w3.eth.account.from_key(private_key)
    sender = account.address

    # Select contract and ABI
    contract_address = NEG_RISK_ADAPTER if neg_risk else CTF_CONTRACT
    abi = _NEG_RISK_ABI if neg_risk else _CTF_ABI

    contract = w3.eth.contract(address=contract_address, abi=abi)

    try:
        if neg_risk:
            # NegRiskAdapter.mergePositions(conditionId, amount)
            tx = contract.functions.mergePositions(
                condition_id,
                amount,
            ).build_transaction({
                "from": sender,
                "nonce": w3.eth.get_transaction_count(sender),
                "gas": 300_000,
                "gasPrice": w3.eth.gas_price,
            })
        else:
            # CTF.mergePositions(collateral, parentCollectionId, conditionId, partition, amount)
            partition = [1, 2]  # binary partition: YES=1, NO=2
            tx = contract.functions.mergePositions(
                USDC_CONTRACT,
                "0x" + "00" * 32,  # empty parent collection
                condition_id,
                partition,
                amount,
            ).build_transaction({
                "from": sender,
                "nonce": w3.eth.get_transaction_count(sender),
                "gas": 300_000,
                "gasPrice": w3.eth.gas_price,
            })

        signed = w3.eth.account.sign_transaction(tx, private_key)
        tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

        if receipt.status == 1:
            logger.info("MERGE success: tx=%s", tx_hash.hex())
            return True
        else:
            logger.error("MERGE failed: tx=%s", tx_hash.hex())
            return False
    except Exception as e:
        logger.error("Merge exception: %s", e)
        return False


# Minimal ABIs for merge functions

_CTF_ABI = [{
    "inputs": [
        {"name": "collateralToken", "type": "address"},
        {"name": "parentCollectionId", "type": "bytes32"},
        {"name": "conditionId", "type": "bytes32"},
        {"name": "partition", "type": "uint256[]"},
        {"name": "amount", "type": "uint256"},
    ],
    "name": "mergePositions",
    "outputs": [],
    "stateMutability": "nonpayable",
    "type": "function",
}]

_NEG_RISK_ABI = [{
    "inputs": [
        {"name": "conditionId", "type": "bytes32"},
        {"name": "amount", "type": "uint256"},
    ],
    "name": "mergePositions",
    "outputs": [],
    "stateMutability": "nonpayable",
    "type": "function",
}]
