# ERC-4626 accounting checker — v0.1 (one check family)

A runnable check, not a report sample. Stdlib-only Python, exact
integer arithmetic (like Solidity), no chain access, no spend.

## What it checks

1. **Rounding directions** — deposit/redeem favour the vault, mint/withdraw
   favour the vault's other side, per EIP-4626 / OpenZeppelin.
2. **Donation / first-depositor inflation** — attacker deposits, donates
   directly to the vault, victim deposits, both redeem. PASS = attacker
   never profits and victim loss stays <= 1000 base units (0.001 USDC
   at 6 decimals, the bound the 2026-11-03 audit observed).
3. **Preview consistency** — `preview*()` equals the executed amount.
4. **Fee conservation** — yield = holder gain + fee accrued, to 1 unit.
5. **Share-price sanity** — price never negative, never drops on deposit.

## Run it

```sh
python3 example_alphaprimer.py   # worked example, AlphaPrimer parameters
python3 -m unittest test_checker -v
```

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
  (2026-11-03 low-cost ideas writeup). A paid check pack, if any,
  is a separate later decision — no payment address is published here.
- Kill line (from that writeup): 30 days after publishing + posting,
  zero stars, zero downloads, zero tips, zero inbound -> shelve.
- Not published yet: publishing to the spare GitHub account and the
  tip-address choice are the two remaining decisions, not smuggled in.
