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

Seeded vaults: assets already in the vault dilute the donation, so a
live 50M USDC vault at offset 0 passes the donation check a new vault
fails. Give both vault-state flags, or leave both at 0 (a new vault):

    python3 check_vault.py --offset 0 --vault-assets-usdc 50000000 \
        --vault-shares 50000000000000
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from erc4626_checker import Vault, run_all


def _usdc(text: str) -> int:
    """USDC amount (e.g. '1,000.5') -> base units (int)."""
    return int(round(float(text.replace(",", "").replace("_", "")) * 1_000_000))


def _shares(text: str) -> int:
    """Raw share count (e.g. '50,000,000,000,000') -> int.

    Shares are exact integers and can exceed float precision (an
    18-decimal vault holds ~1e25 raw shares), so parse as int, never
    through float.
    """
    return int(text.replace(",", "").replace("_", "").strip())


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="ERC-4626 accounting checks")
    p.add_argument("--offset", type=int, default=0,
                   help="decimals offset (virtual shares = 10**offset)")
    p.add_argument("--min-deposit-usdc", default="0",
                   help="minimum deposit in USDC (default 0)")
    p.add_argument("--victim-deposit-usdc", default="100000",
                   help="victim deposit in the donation scenario, USDC")
    p.add_argument("--vault-assets-usdc", default="0",
                   help="assets already in the vault before the attack, USDC "
                        "(default 0 = a new vault)")
    p.add_argument("--vault-shares", default="0",
                   help="shares already in the vault before the attack, raw "
                        "count (default 0). Give both vault-state flags, or "
                        "leave both at 0; only the donation and "
                        "minimum-viable-deposit checks use them")
    p.add_argument("--perf-fee-bps", type=int, default=0)
    p.add_argument("--mgmt-fee-bps-per-year", type=int, default=0)
    args = p.parse_args(argv)

    try:
        min_deposit = _usdc(args.min_deposit_usdc)
        victim_deposit = _usdc(args.victim_deposit_usdc)
        vault_assets = _usdc(args.vault_assets_usdc)
        vault_supply = _shares(args.vault_shares)
    except ValueError as e:
        p.error(f"bad amount: {e}")
    if vault_assets < 0 or vault_supply < 0:
        p.error("vault assets and shares must not be negative")
    if (vault_assets == 0) != (vault_supply == 0):
        # Half a state is not a vault: the donation check would refuse
        # it ("incomplete vault state") while the minimum-viable-deposit
        # check would still compute a verdict against it (assets-only
        # reads as a donated-to empty vault, shares-only as shares
        # worth nothing) — one input, two answers. Refuse up front so
        # a forgotten flag can never produce a mixed verdict.
        p.error("give both --vault-assets-usdc and --vault-shares, or "
                "neither: a vault state needs assets and shares together")

    vault = Vault(decimals_offset=args.offset,
                  min_deposit=min_deposit,
                  perf_fee_bps=args.perf_fee_bps,
                  mgmt_fee_bps_per_year=args.mgmt_fee_bps_per_year)
    results = run_all(vault, victim_deposit=victim_deposit,
                      vault_assets=vault_assets, vault_supply=vault_supply)
    for r in results:
        print(f"[{'PASS' if r['pass'] else 'FAIL'}] {r['name']}: {r['detail']}")
    ok = all(r["pass"] for r in results)
    print("ALL PASS" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
