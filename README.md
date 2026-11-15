# ERC-4626 accounting checker — v0.1 (one check family)

Try it live, no install: https://check.n1netw3n.live/checker/ — the same six checks, in your browser.

A runnable check, not a report sample. Stdlib-only Python, exact
integer arithmetic (like Solidity), no chain access, no spend.

## What it checks

1. **Rounding directions** — deposit/redeem favour the vault, mint/withdraw
   favour the vault's other side, per EIP-4626 / OpenZeppelin.
2. **Donation / first-depositor inflation** — attacker deposits, donates
   directly to the vault, victim deposits, both redeem. PASS = attacker
   never profits and victim loss stays <= 1000 base units (0.001 USDC
   at 6 decimals, the bound the 2026-11-03 audit observed).
3. **Minimum viable deposit** — the smallest deposit that mints at least
   one share at the vault's live price. Deposit rounds down, so below a
   threshold a deposit mints zero shares. PASS = a 1 USDC deposit mints
   at least one share after the vault's own minimum-deposit floor.
4. **Preview consistency** — `preview*()` equals the executed amount.
5. **Fee conservation** — yield = holder gain + fee accrued, to 1 unit.
6. **Share-price sanity** — price never negative, never drops on deposit.

## Run it

```sh
python3 example_alphaprimer.py   # worked example, AlphaPrimer parameters
python3 -m unittest test_checker -v
```

## Use in CI

Gate a vault's parameters on every push — the action runs the same
six checks and fails the step when any check fails:

```yaml
- uses: Cloud9Gleam/erc4626-checker@main
  with:
    decimals-offset: 6
    min-deposit-usdc: 1
    perf-fee-bps: 1000
    mgmt-fee-bps-per-year: 100
```

Or run the CLI directly (no GitHub Actions needed):

```sh
python3 check_vault.py --offset 6 --min-deposit-usdc 1 \
    --perf-fee-bps 1000 --mgmt-fee-bps-per-year 100
# exit 0 = ALL PASS, exit 1 = SOME FAILED
```

Try it in the browser instead: https://check.n1netw3n.live/checker/

## Guides

90 worked ERC-4626 accounting guides, each with exact-integer
numbers — donation and first-depositor attacks, fee mechanics,
rounding, preview drift, empty-vault reseeds:
https://check.n1netw3n.live/guides/

## Worked example

AlphaPrimerVault parameters (audited 2026-11-03, clean negative):
decimals offset 6, minimum deposit 1 USDC, 10% performance fee,
1%/yr management fee. The offset — virtual shares 1,000,000 against
virtual assets 1 — is what bounds the donation attack, not the minimum
alone. The control test proves the distinction: offset 0 + no minimum
fails the donation check, offset 6 + minimum passes it.

## Honest limits

- Model only: it checks the accounting rules, not a deployed contract's
  live state, permissions, oracle, or strategy code.
- No verified buyer. This is the free core of ranked idea #1
  (2026-11-03 low-cost ideas writeup). The paid option is a human
  review of a live vault — the vault micro-audit, up to 15 files,
  50 USDC prepaid, written report in 72 hours — offered on the
  hosted site, not in this repo: https://check.n1netw3n.live/audit/
- Kill line (from that writeup): published 2026-11-06; 30 days after
  publishing + posting, zero stars, zero downloads, zero tips, zero
  inbound -> shelve (2026-12-06).
