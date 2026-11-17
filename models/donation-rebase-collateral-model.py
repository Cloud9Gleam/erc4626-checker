#!/usr/bin/env python3
"""A donation meets a stale collateral oracle -- and fails to bite.

Neither the donation-attack guide nor the rebase-collateral guide
answers this one alone. The rebase-collateral guide shows a -20%
rebase pushing a loan to 100% LTV while the oracle still says
$1.00. A donation also moves the price -- it doubles it here --
so the natural question is whether a donation plus a stale oracle
opens the same wedge. It does not, and the reason is structural:
a rebase moves the price with no deposit and no share burn, while
a donation is asset-backed (the inflated price is real while the
donation sits in the vault) and pro-rata redemption cannot move
the price at all. The borrower who draws against the inflated
price stays collateralised through every exit that follows.

Setup: vault holds a rebasing underlying, 1,000,000 USDC
(6 decimals), 1,000,000 shares, price $1.00. Alice holds 100,000
shares (10%); the other holders hold 900,000. Lending market:
collateral factor 80%, oracle price updated weekly -- stale
between updates. Attacker seeds 1 base unit (classic seed), then
donates 1,000,000 USDC. All arithmetic is exact (integers /
fractions.Fraction); base units are integers. No new numbers are
invented -- every figure below is computed here.

Run: python3 donation-rebase-collateral-model.py
"""

from fractions import Fraction

USDC = 1_000_000  # base units per USDC

A0 = 1_000_000 * USDC           # 1,000,000 USDC in base units
S0 = 1_000_000 * USDC           # 1,000,000 shares
assert Fraction(A0, S0) == 1   # $1.00 per share

ALICE = 100_000 * USDC          # Alice's shares: 10% of the vault
OTHERS = 900_000 * USDC         # the other holders: 90%
CF = Fraction(4, 5)             # collateral factor 80%


def price(total_assets, total_supply):
    return Fraction(total_assets, total_supply)


def capacity(shares, oracle_price):
    """Max borrow in base units, floored to whole base units."""
    v = shares * oracle_price * CF
    return v.numerator // v.denominator


# --- case 1: donation doubles the price; oracle follows ------------------
# Attacker seeds 1 base unit, then donates 1,000,000 USDC. Assets
# 2,000,000,000,001, supply 1,000,000,000,001, price a hair under
# $2.00. The oracle updates to it, so Alice's capacity is 80% of
# her inflated $200,000 claim: $159,999.999999, not $80,000.
seed = 1
A1 = A0 + seed
S1 = S0 + seed
DON = 1_000_000 * USDC
A2 = A1 + DON
p2 = price(A2, S1)
assert p2 == Fraction(2_000_000_000_001, 1_000_000_000_001)
assert ALICE * p2 == Fraction(200_000_000_000_100_000_000_000, 1_000_000_000_001)  # ~$199,999.9999999
cap2 = capacity(ALICE, p2)
assert cap2 == 159_999_999_999  # $159,999.999999
assert Fraction(cap2, 1) / (ALICE * p2) == Fraction(53_333_333_333_053_333_333_333, 66_666_666_666_700_000_000_000)  # ~80% LTV

# --- case 2: every other holder exits at the inflated price --------------
# The other 90% redeem all 900,000 shares at $2.00 and take
# $1,799,999.999999 out. Assets fall to $200,000,000,002 and supply
# to 100,000,000,001 -- but the price is the SAME fraction as
# before, because redemption burns shares pro-rata. Alice's
# 100,000 shares are still worth $199,999.9999999, her $159,999.999999
# loan is still ~80% LTV. The donation cannot be borrowed against
# and then pulled out from under the loan: whoever exits takes
# their own pro-rata share and leaves the price untouched.
out_others = OTHERS * p2
assert out_others == Fraction(1_800_000_000_000_900_000_000_000, 1_000_000_000_001)  # ~$1,799,999.999999
A3 = Fraction(A2, 1) - out_others
S3 = S1 - OTHERS
assert A3 / S3 == p2  # price unchanged by pro-rata redemption
assert ALICE * (A3 / S3) == ALICE * p2
assert Fraction(cap2, 1) / (ALICE * (A3 / S3)) == Fraction(53_333_333_333_053_333_333_333, 66_666_666_666_700_000_000_000)

# --- case 3: the attacker exits too, and still loses everything ----------
# The attacker's 1 seed share redeems for ~$0.000002 (2 base units
# at the $2.00 price) against a $1,000,001.000001 outlay: net
# -$999,999.999999. Seeding first does not save the attack here
# either -- the seed is one trillionth of the supply, so the
# donation pays back about one trillionth of itself. And the price
# does not move on their exit.
att_out = seed * p2
assert att_out == Fraction(2_000_000_000_001, 1_000_000_000_001)  # ~$2.00
attacker_net = att_out - (seed + DON)
assert attacker_net == Fraction(-1_000_000_000_000_000_000_000_000, 1_000_000_000_001)  # ~-$999,999.999999

# --- case 4: the contrast -- a -20% rebase DOES open the wedge -----------
# Same vault, no donation: Alice borrows the $80,000 max at the
# $1.00 oracle. A -20% rebase (slashing) drops the true price to
# $0.80 while the oracle still says $1.00: her shares are worth
# exactly the debt, LTV 100% (rebase-collateral case 4). The
# rebase moves the price with no deposit and no share burn, so
# the collateral thins under a loan that cannot be re-priced.
# The donation moves the price only by adding real assets, and
# every exit that could remove them is pro-rata -- so the wedge
# never opens. Donation risk and rebase risk are not the same
# risk, even though both move the same price.
assets4 = A0 * 4 // 5
assert price(assets4, S0) == Fraction(4, 5)
assert ALICE * price(assets4, S0) == 80_000 * USDC
assert Fraction(80_000 * USDC, 1) / (ALICE * price(assets4, S0)) == 1


def usd(base_units):
    """Display helper: base units -> dollars with 6 decimals (display only)."""
    return f"{base_units / USDC:,.6f}"


print("ALL ASSERTIONS PASS")
print(f"donation 1,000,000 USDC: price ${float(p2):.6f}; Alice borrows "
      f"${usd(cap2)} at ~80% LTV")
print(f"other holders exit at the inflated price: ${usd(out_others)} out; "
      f"price unchanged, Alice still worth ${usd(ALICE * p2)}, LTV unchanged")
print(f"attacker exits: recovers ${usd(att_out)} on $1,000,001.000001 "
      f"outlay, net ${usd(attacker_net)}")
print(f"contrast: -20% rebase at stale $1.00 oracle puts the same "
      f"$80,000 loan at 100% LTV -- the donation never does")
