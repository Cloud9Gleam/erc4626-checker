#!/usr/bin/env python3
"""Donation x withdrawal-cap numbers for the guide
\"ERC-4626 donation x withdrawal cap -- the gift that doubles
what the cap lets out\".

Exact-integer model (USDC, 6 decimals, base units), same mul_div_down
convention as the other site models. Setup, straight from the guide:
a vault of 1,110,000 USDC and 1,110,000 shares at $1.00 -- Alice
holds 1,000,000 shares, a whale holds 100,000, an attacker holds
10,000 -- and the cap is 10,000 shares per epoch. The attacker
donates 1,110,000 USDC, exactly the pre-donation totalAssets, so
the price doubles to $2.00 exactly.

Pre-build check against the neighbours (all read 2026-11-17):
- withdrawal-cap-model.py: the cap alone, a DIFFERENT scenario --
  1,000,000 vault, 100,000 donation, 50,000 per-tx/per-block cap,
  S1-S5. It does model donations, but none of its numbers is the
  guide's 1,110,000 / $2.00 / 10,000-share-per-epoch setup. This
  file is the dedicated model for the guide's own setup; it does
  not duplicate the neighbour, it pins the numbers the neighbour
  never computed.
- maxdeposit-cap: the deposit-side twin. A deposit cap does not
  stop the donation attack (the attacker deposits the minimum).
  This model is the EXIT side, and the question is different: the
  cap still counts shares while the price moves, so the dollars
  per capped share double.
- withdrawal-liquidity: maxWithdraw as a LIQUIDITY VIEW, no cap
  anywhere; the limit there is cash on hand, not a policy limit.
- donation-liquidity: donation + illiquidity, again a view, not
  a cap; the cap question is never asked there.

Headline results (all pinned by the scenarios below):
- Control, no donation: 10,000 shares per epoch is $10,000 per
  epoch; the attacker exits in 1 epoch for 10,000, the whale's
  100,000 shares take 10 epochs and drain $100,000 (S1).
- Donation first: price exactly $2.00; the same 10,000-share cap
  now lets $20,000 out per epoch; the attacker exits in 1 epoch
  for 20,000, the whale drains $200,000 over the same 10 epochs
  (S2). The cap never changed; the dollars under it doubled.
- The donor still loses $1,100,000: 10,000 in + 1,110,000
  donated - 20,000 out (S3). The leak is a rate effect (a
  griefing lever on forced liquidation), not a profit.
- An asset-denominated cap of $10,000 per epoch holds exactly:
  the attacker needs 2 epochs (5,000 shares per epoch at $2.00)
  and the whale 20 epochs at $10,000 per epoch (S4). Only a
  share-denominated cap is donation-sensitive.

Run: python3 donation-withdrawal-cap-model.py
"""
USDC = 1_000_000


def mul_div_down(a, b, c):
    return (a * b) // c


class Vault:
    """ERC-4626 vault with a per-epoch withdrawal cap switch.

    redeem pays shares * totalAssets // totalSupply (floored).
    redeem_share_cap enforces a share-denominated per-epoch cap:
    one epoch's redemptions may not exceed cap_shares shares.
    redeem_asset_cap enforces an asset-denominated per-epoch cap:
    one epoch's payouts may not exceed cap_assets base units.
    next_epoch() resets both per-epoch budgets.
    """

    def __init__(self, assets, supply):
        self.assets = assets
        self.supply = supply
        self.epoch_spent_shares = 0
        self.epoch_spent_assets = 0

    def price(self):
        return mul_div_down(self.assets, USDC, self.supply)

    def donate(self, amount):
        self.assets += amount

    def redeem(self, shares):
        assert shares <= self.supply
        out = mul_div_down(shares, self.assets, self.supply)
        self.assets -= out
        self.supply -= shares
        return out

    def redeem_share_cap(self, shares, cap_shares):
        if self.epoch_spent_shares + shares > cap_shares:
            raise ValueError("exceeds per-epoch share cap")
        self.epoch_spent_shares += shares
        return self.redeem(shares)

    def redeem_asset_cap(self, shares, cap_assets):
        out = mul_div_down(shares, self.assets, self.supply)
        if self.epoch_spent_assets + out > cap_assets:
            raise ValueError("exceeds per-epoch asset cap")
        self.epoch_spent_assets += out
        return self.redeem(shares)

    def next_epoch(self):
        self.epoch_spent_shares = 0
        self.epoch_spent_assets = 0


def fmt(usdc_base):
    return f"{usdc_base / USDC:,.6f} USDC"


if __name__ == "__main__":
    VAULT = 1_110_000 * USDC
    CAP_SHARES = 10_000 * USDC
    CAP_ASSETS = 10_000 * USDC

    # S1: control -- no donation, price $1.00, cap does what it says.
    v = Vault(VAULT, VAULT)
    assert v.price() == USDC  # $1.00
    a1 = v.redeem_share_cap(10_000 * USDC, CAP_SHARES)
    assert a1 == 10_000 * USDC  # attacker, 1 epoch, $10,000
    v.next_epoch()
    whale1 = 0
    for _ in range(10):
        whale1 += v.redeem_share_cap(10_000 * USDC, CAP_SHARES)
        v.next_epoch()
    assert whale1 == 100_000 * USDC  # whale, 10 epochs, $100,000
    assert v.assets == 1_000_000 * USDC and v.supply == 1_000_000 * USDC
    print(f"S1 control:        price $1.00; attacker 1 epoch "
          f"{fmt(a1)}, whale 10 epochs {fmt(whale1)}; "
          f"cap = $10,000/epoch as written")

    # S2: donation first -- price exactly $2.00, same share cap,
    # double the dollars per epoch, same epoch count.
    v = Vault(VAULT, VAULT)
    v.donate(1_110_000 * USDC)
    assert v.price() == 2 * USDC  # $2.00 exactly
    a2 = v.redeem_share_cap(10_000 * USDC, CAP_SHARES)
    assert a2 == 20_000 * USDC  # attacker, 1 epoch, $20,000
    v.next_epoch()
    whale2 = 0
    for _ in range(10):
        whale2 += v.redeem_share_cap(10_000 * USDC, CAP_SHARES)
        v.next_epoch()
    assert whale2 == 200_000 * USDC  # whale, 10 epochs, $200,000
    assert v.assets == 2_000_000 * USDC and v.supply == 1_000_000 * USDC
    print(f"S2 donation:       price $2.00; attacker 1 epoch "
          f"{fmt(a2)}, whale 10 epochs {fmt(whale2)}; "
          f"cap still 10,000 shares, dollars doubled")

    # S3: the donor's P&L -- 10,000 in + 1,110,000 donated
    # - 20,000 out = -1,100,000. Rate effect, not theft.
    donor_pnl = a2 - 10_000 * USDC - 1_110_000 * USDC
    assert donor_pnl == -1_100_000 * USDC
    print(f"S3 donor P&L:      10,000 in + 1,110,000 donated - "
          f"20,000 out = {fmt(donor_pnl)}; donation buys outflow "
          f"rate, not profit")

    # S4: asset-denominated cap $10,000/epoch holds exactly.
    # At $2.00 the attacker exits 5,000 shares per epoch, so 2
    # epochs; the whale drains $200,000 at $10,000/epoch, 20 epochs.
    v = Vault(VAULT, VAULT)
    v.donate(1_110_000 * USDC)
    assert v.price() == 2 * USDC
    a4 = 0
    a4 += v.redeem_asset_cap(5_000 * USDC, CAP_ASSETS)
    assert a4 == 10_000 * USDC  # epoch 1: 5,000 shares = $10,000
    v.next_epoch()
    a4 += v.redeem_asset_cap(5_000 * USDC, CAP_ASSETS)
    assert a4 == 20_000 * USDC  # epoch 2: attacker fully out
    v.next_epoch()
    whale4 = 0
    for _ in range(20):
        whale4 += v.redeem_asset_cap(5_000 * USDC, CAP_ASSETS)
        v.next_epoch()
    assert whale4 == 200_000 * USDC  # whale, 20 epochs, $10,000 each
    print(f"S4 asset cap:      $10,000/epoch holds; attacker 2 "
          f"epochs (5,000 shares each), whale 20 epochs "
          f"{fmt(whale4)}; dollar bound unchanged by the donation")
