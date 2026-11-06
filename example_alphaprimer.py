"""Worked example: AlphaPrimer parameters, as audited 2026-11-03.

AlphaPrimerVault (Arbitrum, USDC 6 decimals, pin ace0f1dd):
  - _decimalsOffset() = 6  -> virtual shares 1,000,000, virtual assets 1
  - MIN_DEPOSIT = 1e6 (1 USDC)
  - perf fee 10% (1000 bps), management fee 1%/yr (100 bps)
This script does NOT touch the chain: it runs the checker against a
model vault carrying exactly those parameters. The 2026-11-03 forge
audit of the real contract was a clean negative (donation attacks
net-loss at every scale, fee conservation within 0.001 USDC); this
example reproduces the same shape of result with exact integers.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from erc4626_checker import Vault, run_all

if __name__ == "__main__":
    vault = Vault(decimals_offset=6, min_deposit=1_000_000,
                  perf_fee_bps=1000, mgmt_fee_bps_per_year=100)
    results = run_all(vault)
    for r in results:
        print(f"[{'PASS' if r['pass'] else 'FAIL'}] {r['name']}: {r['detail']}")
    print("ALL PASS" if all(r["pass"] for r in results) else "SOME FAILED")
    print(json.dumps(results, indent=2, default=str))
