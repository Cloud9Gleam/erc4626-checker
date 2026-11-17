#!/usr/bin/env python3
"""Donation x operator allowance -- exact-integer model for a future guide.

Named source (this run, 2026-11-17): the donation x operator-allowance
wedge. The operator-allowance guide already says the quiet part -- an
approval is denominated in SHARES, and "a price move changes how much
VALUE an approval carries, without anyone touching the approval" -- but
no model on this site has ever made a DONATION the price mover, or the
donor and the operator the same party. That is the wedge: an approval
granted when the price was $1.00, a donation that lifts the price to
$1.10, and an operator who spends the stale approval to take the
donation's gift off the owner's shares.

Question: when a donation inflates the share price, who keeps the gift
that lands on an approved owner's shares -- the owner, or the operator
holding a stale share-denominated approval?

State variables (rule (k)):
- Keyed mappings: balances[holder] (shares), allowance[owner][spender]
  (shares the operator may move).
- Cumulative variables: totalSupply (shares), totalAssets (USDC, 6dp).
- Privileged-address variables: the operator (spender) address that
  may redeem someone else's shares up to the allowance; the owner
  address that sets or revokes the allowance (approve/revoke are the
  only writes to it).

Pre-build check against the neighbours (all read 2026-11-17):
- operator-allowance-model.py: donation 0 mentions. It proves the
  approval is share-denominated and that a price rise changes the
  value an approval carries, but it never donates, never makes the
  donor the operator, and never prices the theft.
- donation-performance-fee-model.py / donation-hurdle-rate-fee-model.py:
  donations triggering FEES. An allowance is not a fee: no value is
  taken by the vault, the operator takes the owner's shares.
- donation-governance-vote-model.py: a donation buying VOTES. Votes
  are influence; an allowance is custody of someone else's shares.
- donation-bridge-shares-model.py: unbacked shares minted by a bridge.
  Here every share is backed; the wedge is the approval, not the mint.
- per-address-cap-model.py / maxdeposit-cap-model.py: caps on what an
  address may DEPOSIT. An allowance caps what an operator may MOVE
  of someone else's shares -- the opposite direction.
- queue-priority-model.py / withdrawal-queue-model.py: donation 0
  mentions; order of exit, not custody of another's shares.

Headline results (all pinned by the scenarios below):
- A stale approval is the theft vector: Alice approves the operator
  100,000 shares at $1.00 (intending at most $100,000 of value to
  move); Mallory donates 100,000, the price rises to $1.10, and the
  operator redeems Alice's 100,000 shares for 109,999.999999 USDC --
  $9,999.999999 more than the value Alice ever approved, and
  Mallory nets +9,999.999999 on a 100,000 donation. The donation's
  gift to Alice ($10,000 on her shares) is taken, not kept.
- The approval, not the donation, decides who keeps the gift: with
  no approval the same donation is a pure gift -- Alice keeps
  100,000 shares worth 109,999.999999, Carol keeps 989,999.999999,
  Mallory keeps nothing.
- An asset-denominated allowance closes it: capped at 100,000 USDC
  of VALUE, the operator can move only 90,909.090909 shares
  (99,999.999999 USDC); Alice keeps 9,090.909091 shares worth
  exactly 10,000.000000, and Mallory nets -0.000001 on the donation.
- Timing is the whole defence in the other direction: an approval
  granted AFTER the donation moves the same 109,999.999999, but
  that is exactly the value approved at approval time -- no
  surprise. A revoke after the donation also closes it: the
  operator moves 0 and Alice keeps the full gift.

Model: exact integers, USDC 6 decimals, base units. Built directly
on the checker's own Vault (erc4626_checker.py) for every
conversion -- the vault's price formula is the same one the checker
verifies. Allowance bookkeeping is the OpenZeppelin ERC-4626 rule,
implemented here in the open: redeem on someone else's behalf spends
an allowance counted in SHARES.

Run: python3 donation-operator-allowance-model.py
Status: numbers verified 2026-11-17 21:39 run (this file); guide page,
test defs and build integration closed 2026-11-17 ~21:59 run
(guide /guides/erc4626-donation-operator-allowance/, tests 218/218).
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                "..", "erc4626-checker"))
import erc4626_checker as ec

USDC = 1_000_000


def fmt(usdc_base):
    return f"{usdc_base / USDC:,.6f} USDC"


class Allowance:
    """OZ allowance bookkeeping, shares-denominated.

    approve sets the allowance. spend checks it and decreases it.
    """

    def __init__(self):
        self.book = {}

    def approve(self, owner, spender, amount):
        self.book[(owner, spender)] = amount

    def get(self, owner, spender):
        return self.book.get((owner, spender), 0)

    def spend(self, owner, spender, shares):
        allowed = self.get(owner, spender)
        assert shares <= allowed, (
            f"allowance {allowed} < {shares} shares requested")
        self.book[(owner, spender)] = allowed - shares


def fresh_vault():
    """Vault 1,000,000 / 1,000,000 @ $1.00: Alice 100,000 shares,
    Carol 900,000 shares. Returns (vault, alice_shares, carol_shares).
    """
    v = ec.Vault(total_assets=0, total_supply=0, decimals_offset=0)
    alice = v.deposit(100_000 * USDC)
    carol = v.deposit(900_000 * USDC)
    assert (alice, carol) == (100_000 * USDC, 900_000 * USDC)
    assert (v.total_assets, v.total_supply) == (
        1_000_000 * USDC, 1_000_000 * USDC)
    return v, alice, carol


def check(cond, msg):
    assert cond, msg


def main():
    print("== S1: baseline, no donation, operator spends the approval ==")
    v, alice, carol = fresh_vault()
    allow = Allowance()
    allow.approve("alice", "mallory", 100_000 * USDC)
    allow.spend("alice", "mallory", alice)
    out = v.redeem(alice)
    print(f"operator redeems Alice 100,000 sh -> {fmt(out)}")
    check(out == 100_000 * USDC, f"S1 out {out}")
    check(v.convert_to_assets(carol) == 900_000 * USDC, "S1 carol")
    check((v.total_assets, v.total_supply) == (
        900_000 * USDC, 900_000 * USDC), "S1 vault")

    print("== S2: wedge -- donation first, then the stale approval ==")
    v, alice, carol = fresh_vault()
    allow = Allowance()
    # Approved at $1.00: Alice intends at most $100,000 of value to move.
    allow.approve("alice", "mallory", 100_000 * USDC)
    v.donate(100_000 * USDC)  # Mallory donates; price $1.00 -> $1.10.
    check(v.total_assets == 1_100_000 * USDC, "S2 assets")
    allow.spend("alice", "mallory", alice)
    out = v.redeem(alice)
    print(f"operator redeems Alice 100,000 sh -> {fmt(out)}")
    check(out == 109_999_999_999, f"S2 out {out}")
    mallory_net = out - 100_000 * USDC
    print(f"Mallory donated 100,000, extracted {fmt(out)}, "
          f"net {fmt(mallory_net)}")
    check(mallory_net == 9_999_999_999, f"S2 net {mallory_net}")
    check(v.convert_to_assets(carol) == 990_000 * USDC,
          "S2 carol keeps her 90,000 gift")
    check((v.total_assets, v.total_supply) == (
        990_000_000_001, 900_000 * USDC), "S2 vault")
    print("Alice's 10,000 gift on her shares was taken, not kept; "
          "Carol keeps her 90,000.")

    print("== S3: defence -- asset-denominated allowance (100,000 USDC) ==")
    v, alice, carol = fresh_vault()
    v.donate(100_000 * USDC)  # price $1.10.
    # Value-capped: the operator may move at most 100,000 USDC of value.
    max_shares = v.convert_to_shares(100_000 * USDC)
    print(f"max shares for 100,000 value at $1.10: {fmt(max_shares)}")
    check(max_shares == 90_909_090_909, f"S3 max shares {max_shares}")
    out = v.redeem(max_shares)
    print(f"operator redeems {fmt(max_shares)} -> {fmt(out)}")
    check(out == 99_999_999_999, f"S3 out {out}")
    kept = alice - max_shares
    kept_value = v.convert_to_assets(kept)
    print(f"Alice keeps {fmt(kept)} worth {fmt(kept_value)}")
    check(kept == 9_090_909_091, f"S3 kept shares {kept}")
    check(kept_value == 10_000 * USDC, f"S3 kept value {kept_value}")
    check(out - 100_000 * USDC == -1, "S3 mallory nets -1 base unit")

    print("== S4: control -- same donation, NO approval ==")
    v, alice, carol = fresh_vault()
    allow = Allowance()
    v.donate(100_000 * USDC)
    try:
        allow.spend("alice", "mallory", alice)
        raise AssertionError("S4: spend without approval must fail")
    except AssertionError as e:
        if "allowance 0" not in str(e):
            raise
    print("operator redeem blocked: allowance 0")
    check(v.convert_to_assets(alice) == 109_999_999_999, "S4 alice")
    check(v.convert_to_assets(carol) == 989_999_999_999, "S4 carol")
    check(v.convert_to_assets(alice) + v.convert_to_assets(carol)
          == 1_100_000 * USDC - 2, "S4 conservation, 2 base units dust")

    print("== S5: approval granted AFTER the donation ==")
    v, alice, carol = fresh_vault()
    v.donate(100_000 * USDC)  # price $1.10 first.
    allow = Allowance()
    # Alice approves 100,000 shares KNOWING the price is $1.10.
    approved_value = v.convert_to_assets(100_000 * USDC)
    allow.approve("alice", "mallory", 100_000 * USDC)
    allow.spend("alice", "mallory", alice)
    out = v.redeem(alice)
    print(f"operator redeems Alice 100,000 sh -> {fmt(out)}; "
          f"value approved at approval time {fmt(approved_value)}")
    check(out == approved_value == 109_999_999_999, "S5 no surprise")
    check(out - 100_000 * USDC == 9_999_999_999,
          "S5 same amount as S2, different intent")

    print("== S6: defence -- Alice revokes after the donation ==")
    v, alice, carol = fresh_vault()
    allow = Allowance()
    allow.approve("alice", "mallory", 100_000 * USDC)
    v.donate(100_000 * USDC)
    allow.approve("alice", "mallory", 0)  # revoke.
    try:
        allow.spend("alice", "mallory", alice)
        raise AssertionError("S6: spend after revoke must fail")
    except AssertionError as e:
        if "allowance 0" not in str(e):
            raise
    print("operator redeem blocked: allowance revoked to 0")
    check(v.convert_to_assets(alice) == 109_999_999_999, "S6 alice")
    check(v.convert_to_assets(carol) == 989_999_999_999, "S6 carol")
    check(allow.get("alice", "mallory") == 0, "S6 allowance 0")

    print("\nALL ASSERTIONS PASS")


if __name__ == "__main__":
    main()
