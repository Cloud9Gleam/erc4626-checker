"""CLI entry point for the ERC-4626 accounting checker.

Run the six exact-integer checks against a vault model described by
its parameters, and exit non-zero when any check fails, so CI can gate
on it:

    python3 check_vault.py --offset 6 --min-deposit-usdc 1 \
        --perf-fee-bps 1000 --mgmt-fee-bps-per-year 100

Amounts are USDC (6 decimals); commas are accepted ("1,000,000").
The model is the same one the hosted checker runs
(https://check.n1netw3n.live/checker/): it checks the accounting
rules, not a deployed contract's live state.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from erc4626_checker import Vault, run_all


def _usdc(text: str) -> int:
    """USDC amount (e.g. '1,000.5') -> base units (int)."""
    return int(round(float(text.replace(",", "").replace("_", "")) * 1_000_000))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="ERC-4626 accounting checks")
    p.add_argument("--offset", type=int, default=0,
                   help="decimals offset (virtual shares = 10**offset)")
    p.add_argument("--min-deposit-usdc", default="0",
                   help="minimum deposit in USDC (default 0)")
    p.add_argument("--victim-deposit-usdc", default="100000",
                   help="victim deposit in the donation scenario, USDC")
    p.add_argument("--perf-fee-bps", type=int, default=0)
    p.add_argument("--mgmt-fee-bps-per-year", type=int, default=0)
    args = p.parse_args(argv)

    vault = Vault(decimals_offset=args.offset,
                  min_deposit=_usdc(args.min_deposit_usdc),
                  perf_fee_bps=args.perf_fee_bps,
                  mgmt_fee_bps_per_year=args.mgmt_fee_bps_per_year)
    results = run_all(vault, victim_deposit=_usdc(args.victim_deposit_usdc))
    for r in results:
        print(f"[{'PASS' if r['pass'] else 'FAIL'}] {r['name']}: {r['detail']}")
    ok = all(r["pass"] for r in results)
    print("ALL PASS" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
