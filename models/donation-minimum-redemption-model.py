#!/usr/bin/env python3
"""Donation attack against an ERC-4626 minimum-redemption floor.

A vault enforces a minimum redemption size (redeem() reverts unless
shares >= MIN_SHARES). The floor's stated job is dust protection:
it stops wallets churning the vault with sub-cent redemptions and
keeps the share ledger from fragmenting into unspendable crumbs.

What no existing model covers is the donation interaction: the
classic donation attack inflates the share price, so a fixed-size
deposit buys FEWER shares. A victim who deposits after the donation
can land UNDER the share floor -- their whole deposit is then
locked, not merely diluted. The loss is binary (redeem reverts)
until the victim tops up past the floor, and the top-up itself is
eaten by the same rounding that created the shortfall.

Key contrast: a minimum denominated in SHARES is donation-sensitive
(the floor is fixed while the price moves); a minimum denominated
in ASSETS is not (the victim's shares are still worth nearly what
they deposited). The fix is to denominate the floor in assets, or
to measure it against the pre-donation price.

Setup: USDC, 6 decimals, base units; exact integers / Fraction.
Attacker seeds 1,000 USDC (1,000 shares at $1.00), donates
1,000,000 USDC, victim deposits 100,000 USDC. Minimum redemption
is 100 shares. All figures below are computed here, nothing is
invented.

Run: python3 donation-minimum-redemption-model.py
"""

from fractions import Fraction

USDC = 1_000_000  # base units per USDC


def mul_div_down(a, b, c):
    return (a * b) // c


class Vault:
    def __init__(self, min_shares):
        self.min_shares = min_shares
        self.total_assets = 0
        self.supply = 0

    def deposit(self, assets):
        # Shares are whole units: 1 share per whole USDC at $1.00.
        # First deposit mints assets // USDC shares; later deposits use
        # the vault price (assets in base units, supply in shares).
        shares = assets // USDC if self.supply == 0 else mul_div_down(
            assets, self.supply, self.total_assets)
        self.total_assets += assets
        self.supply += shares
        return shares

    def redeem(self, shares):
        """Returns assets, or None if the redemption is below the floor."""
        if shares < self.min_shares:
            return None
        assets = mul_div_down(shares, self.total_assets, self.supply)
        self.total_assets -= assets
        self.supply -= shares
        return assets

    def price(self):
        return Fraction(self.total_assets, self.supply)


def fmt(bu):
    return f"{Fraction(bu, USDC):,.6f} USDC"


if __name__ == "__main__":
    MIN_SHARES = 100

    # S1. Baseline, no donation: the floor never binds a real deposit.
    v = Vault(MIN_SHARES)
    assert v.deposit(1_000_000 * USDC) == 1_000_000
    assert v.deposit(100_000 * USDC) == 100_000
    out = v.redeem(100_000)
    assert out == 100_000 * USDC
    print("S1. No donation, price $1.00: victim deposits 100,000 USDC, "
          "gets 100,000 shares, redeems 100,000 USDC — floor never binds.")

    # S2. Donation inflates the price; the victim lands under the floor.
    v = Vault(MIN_SHARES)
    assert v.deposit(1_000 * USDC) == 1_000          # attacker seeds
    v.total_assets += 1_000_000 * USDC               # attacker donates
    assert v.price() == 1001 * USDC, v.price()
    vic_shares = v.deposit(100_000 * USDC)
    assert vic_shares == 99, vic_shares              # 99.90 floored
    assert v.redeem(vic_shares) is None              # 99 < 100: LOCKED
    print(f"S2. Donation 1,000,000 USDC, price $1,001.00: victim deposits "
          f"100,000 USDC, gets {vic_shares} shares — redeem reverts, "
          f"100,000 USDC locked under the 100-share floor.")

    # S3. Top-up escape: a second deposit gets the victim over the floor,
    # but the same rounding eats part of it.
    top_shares = v.deposit(100_000 * USDC)
    assert top_shares == 99, top_shares              # 99.81 floored
    total_shares = vic_shares + top_shares
    assert total_shares == 198
    out = v.redeem(total_shares)
    assert out is not None
    # Independent re-derivation: 198 shares of a 1,201,000 USDC / 1,198
    # share vault, floored.
    expect = Fraction(198 * 1_201_000 * USDC, 1_198)
    assert out == int(expect), (out, expect)
    assert out == 198_495_826_377, out
    loss = 200_000 * USDC - out
    assert loss == 1_504_173_623, loss
    # Attacker after the victim's redemption: they own the whole
    # remaining vault -- 1,002,504.173623, exactly the victim's loss,
    # to the base unit. The redemption's floor dust (0.2955 base
    # units) stays in the vault, so it goes to the attacker. (The
    # guide previously quoted 1,002,504.173622 -- the truncated
    # pre-redemption share value -- and called the loss "the
    # attacker's gain, less one base unit": both wrong.)
    assert v.total_assets == 1_002_504_173_623, v.total_assets
    assert v.supply == 1_000
    assert loss == v.total_assets - 1_001_000 * USDC
    print(f"S3. Victim tops up another 100,000 USDC (99 more shares, "
          f"198 total), redeems {fmt(out)} — loss "
          f"{fmt(loss)} on 200,000 USDC in, mostly the attacker's "
          f"extraction plus 2 shares of floor rounding.")

    # S4. Attacker exits first: the price collapses, the victim is STILL
    # locked, and the escape top-up itself mints 0 shares.
    v = Vault(MIN_SHARES)
    assert v.deposit(1_000 * USDC) == 1_000          # attacker seeds
    v.total_assets += 1_000_000 * USDC               # attacker donates
    vic_shares = v.deposit(100_000 * USDC)
    assert vic_shares == 99
    atk_out = v.redeem(1_000)                        # attacker exits first
    # Independent re-derivation: 1,000 shares of a 1,101,000 USDC /
    # 1,099 share vault, floored.
    assert atk_out == int(Fraction(1_000 * 1_101_000 * USDC, 1_099))
    assert atk_out == 1_001_819_836_214, atk_out      # 1,001,819.836214 USDC
    assert v.total_assets == 99_180_163_786
    assert v.supply == 99
    assert v.redeem(vic_shares) is None              # still 99 < 100
    assert v.price() == Fraction(99_180_163_786, 99)
    # Escape top-up of 1,000 USDC mints 0 shares (0.99 floored) — the
    # rounding floor eats the whole top-up.
    assert v.deposit(1_000 * USDC) == 0
    # 2,000 USDC mints exactly 1 share; 100 shares unlocks the vault.
    assert v.deposit(2_000 * USDC) == 1
    out = v.redeem(100)
    assert out == 102_180_163_786, out
    loss = 103_000 * USDC - out
    assert loss == 819_836_214, loss
    print(f"S4. Attacker exits first with {fmt(atk_out)}; price falls "
          f"back to ~$1,001.82/share, victim still locked at 99 shares. "
          f"A 1,000 USDC top-up mints 0 shares; 2,000 USDC mints 1. "
          f"Victim redeems {fmt(out)} on 103,000 USDC in — loss "
          f"{fmt(loss)}.")

    # S5. Asset-denominated minimum: the same attack does not lock anyone.
    v = Vault(MIN_SHARES)
    assert v.deposit(1_000 * USDC) == 1_000
    v.total_assets += 1_000_000 * USDC
    vic_shares = v.deposit(100_000 * USDC)
    assert vic_shares == 99
    # 99 shares are worth 99 * 1,101,000 / 1,099 USDC — far above a
    # 100 USDC asset floor, so redemption is allowed.
    worth = Fraction(vic_shares * v.total_assets, v.supply)
    assert worth == Fraction(99 * 1_101_000 * USDC, 1_099)
    assert worth > 100 * USDC
    print(f"S5. Asset-denominated floor (min redeem 100 USDC): the "
          f"victim's 99 shares are worth {fmt(int(worth))} — redemption "
          f"allowed. Only a SHARE-denominated floor is donation-sensitive.")

    print("ALL ASSERTIONS PASS")
