"""Single-feature ERC-4626 accounting checker (stdlib only, exact integers).

Checks one vault model, not a live chain:
  1. rounding directions -- deposit/mint/redeem/withdraw follow EIP-4626
     (deposit and redeem round in the vault's favour, mint and withdraw
     round against the caller, as OpenZeppelin implements them)
  2. donation / first-depositor inflation -- an attacker who deposits,
     donates directly to the vault, then redeems must not profit, and a
     later victim's loss must stay bounded by rounding + virtual offset
  3. preview consistency -- preview*() must equal the executed amount
  4. fee conservation -- yield in = holder assets out + fee accrued, to
     within 1 base unit
  5. share-price sanity -- share price never goes negative and never
     drops below its pre-deposit value on a plain deposit

The model mirrors OpenZeppelin ERC4626Upgradeable with a decimals
offset: virtual shares = 10**decimals_offset, virtual assets = 1.
That offset (not a minimum deposit alone) is what bounds the
inflation attack. All arithmetic is integer, like Solidity.
"""

from __future__ import annotations

from dataclasses import dataclass


def _mul_div_down(a: int, b: int, c: int) -> int:
    return (a * b) // c


def _mul_div_up(a: int, b: int, c: int) -> int:
    return -((-a * b) // c)


def _fmt_usdc(n: int) -> str:
    """Base units (USDC, 6 decimals) as a readable amount: '10,000.000000'."""
    neg = n < 0
    a = -n if neg else n
    return ("-" if neg else "") + f"{a // 1_000_000:,}.{a % 1_000_000:06d}"


def _fmt_int(n: int) -> str:
    """Plain integer with thousand separators: '10,000,000,000,000,000'."""
    return f"{n:,}"


# Non-breaking space between a formatted amount and its unit, so a
# wrapping detail line breaks at "==" / "," / "->" instead of leaving a
# lone "USDC" / "shares" on its own line (narrow card, mobile width).
NBSP = "\u00a0"


@dataclass
class Vault:
    """Minimal ERC-4626 state machine. Amounts are base units."""

    total_supply: int = 0
    total_assets: int = 0
    decimals_offset: int = 0
    min_deposit: int = 0
    perf_fee_bps: int = 0
    mgmt_fee_bps_per_year: int = 0
    accrued_fees: int = 0

    @property
    def virtual_shares(self) -> int:
        return 10 ** self.decimals_offset

    @property
    def virtual_assets(self) -> int:
        return 1

    def convert_to_shares(self, assets: int, round_up: bool = False) -> int:
        f = _mul_div_up if round_up else _mul_div_down
        return f(assets, self.total_supply + self.virtual_shares,
                 self.total_assets + self.virtual_assets)

    def convert_to_assets(self, shares: int, round_up: bool = False) -> int:
        f = _mul_div_up if round_up else _mul_div_down
        return f(shares, self.total_assets + self.virtual_assets,
                 self.total_supply + self.virtual_shares)

    # EIP-4626 previews (OZ rounding)
    def preview_deposit(self, assets: int) -> int:
        return self.convert_to_shares(assets, round_up=False)

    def preview_mint(self, shares: int) -> int:
        return self.convert_to_assets(shares, round_up=True)

    def preview_withdraw(self, assets: int) -> int:
        return self.convert_to_shares(assets, round_up=True)

    def preview_redeem(self, shares: int) -> int:
        return self.convert_to_assets(shares, round_up=False)

    def deposit(self, assets: int) -> int:
        if assets < self.min_deposit:
            raise ValueError("below minimum deposit")
        shares = self.preview_deposit(assets)
        if shares == 0:
            raise ValueError("zero shares minted")
        self.total_assets += assets
        self.total_supply += shares
        return shares

    def mint(self, shares: int) -> int:
        assets = self.preview_mint(shares)
        if assets < self.min_deposit:
            raise ValueError("below minimum deposit")
        self.total_assets += assets
        self.total_supply += shares
        return assets

    def withdraw(self, assets: int) -> int:
        shares = self.preview_withdraw(assets)
        if shares > self.total_supply:
            raise ValueError("insufficient shares")
        self.total_assets -= assets
        self.total_supply -= shares
        return shares

    def redeem(self, shares: int) -> int:
        assets = self.preview_redeem(shares)
        self.total_assets -= assets
        self.total_supply -= shares
        return assets

    def donate(self, assets: int) -> None:
        """Direct transfer to the vault: assets up, shares unchanged."""
        self.total_assets += assets

    def accrue_yield_and_perf_fee(self, yield_amount: int) -> int:
        """Add yield, take perf fee on it. Returns the fee accrued."""
        fee = yield_amount * self.perf_fee_bps // 10_000
        self.total_assets += yield_amount
        self.accrued_fees += fee
        return fee


def _fresh(**kw) -> Vault:
    return Vault(**kw)


def check_rounding(v: Vault, amounts=(1_000_000, 100_000_000, 10_000_000_000)) -> dict:
    """Deposit mints floor, mint charges ceil, redeem pays floor,
    withdraw burns ceil -- each within 1 unit of the exact ratio."""
    errs = []
    for a in amounts:
        w = _fresh(decimals_offset=v.decimals_offset, min_deposit=0)
        w.deposit(10_000_000_000)  # seed so price is ~1:1, not empty-vault edge
        num = a * (w.total_supply + w.virtual_shares)
        den = w.total_assets + w.virtual_assets
        # exact-integer floor check: preview*den <= num < (preview+1)*den
        dep = w.preview_deposit(a)
        if not (dep * den <= num < (dep + 1) * den):
            errs.append(f"deposit rounding off for {a}")
        # withdraw must burn at least the exact share count (ceil)
        wd = w.preview_withdraw(a)
        if not ((wd - 1) * den < num <= wd * den):
            errs.append(f"withdraw rounding off for {a}")
        if w.preview_redeem(w.preview_deposit(a)) > a:
            errs.append(f"redeem overpays for {a}")
    return {"name": "rounding", "pass": not errs, "detail": errs or ["floor/ceil directions hold"]}


def check_donation(v: Vault, victim_deposit: int = 100_000_000_000,
                   donations=(1_000_000, 1_000_000_000, 1_000_000_000_000,
                              1_000_000_000_000_000),
                   vault_assets: int = 0, vault_supply: int = 0) -> dict:
    """Attacker deposits min, donates D, victim deposits, both redeem.
    PASS = attacker never profits and victim loss <= 1000 base units
    (0.001 USDC at 6 decimals -- the bound the 2026-11-03 AlphaPrimer
    forge audit observed: victim loss at most 0.000999 USDC at every
    donation scale) and <= 0.1% of the victim deposit.

    vault_assets / vault_supply seed the vault with the deposits already
    in it before the attack (0 / 0 = a new vault, the default). Existing
    deposits dilute the donation: the victim's loss is bounded by about
    one share's value at the inflated price, and one share is cheap when
    the vault already holds many shares. A live 50M USDC vault at offset 0
    therefore passes the same bound a new vault fails — the protection
    there is the existing deposits, not the offset, and a drained vault
    behaves like a new one again.

    A half-filled state is not a vault: assets with no shares, or
    shares with no assets, cannot exist — the first is a vault that
    issued nothing for its deposits, the second is shares worth
    nothing. Running the attack on either anyway would report a
    verdict about a vault that cannot exist (shares-only used to
    report ALL PASS). Refuse the check instead of inventing one."""
    if (vault_assets == 0) != (vault_supply == 0):
        err = "incomplete vault state: assets and shares must both be set"
        rows = [{"donation": d, "attacker_net": None, "victim_loss": None,
                 "error": err} for d in donations]
        return {"name": "donation_inflation", "pass": False, "detail": rows}
    rows = []
    ok = True
    for d in donations:
        w = _fresh(total_assets=vault_assets, total_supply=vault_supply,
                   decimals_offset=v.decimals_offset, min_deposit=v.min_deposit)
        atk_in = max(v.min_deposit, 1_000_000)
        try:
            atk_shares = w.deposit(atk_in)
            w.donate(d)
            vic_shares = w.deposit(victim_deposit)
        except ValueError as e:
            # The victim's deposit reverts (below minimum, or mints zero
            # shares), so no loss is measured: the funds never enter the
            # vault. Record no loss figure rather than inventing one.
            rows.append({"donation": d, "attacker_net": None,
                         "victim_loss": None, "error": str(e)})
            ok = False
            continue
        atk_out = w.redeem(atk_shares)
        vic_out = w.redeem(vic_shares)
        # Attacker cost is deposit PLUS donation: redeeming your own
        # donation back is not profit.
        atk_net = atk_out - (atk_in + d)
        vic_loss = victim_deposit - vic_out
        rows.append({"donation": d, "attacker_net": atk_net, "victim_loss": vic_loss})
        if atk_net > 0 or vic_loss > 1000 or vic_loss > victim_deposit // 1000:
            ok = False
    return {"name": "donation_inflation", "pass": ok, "detail": rows}


def check_preview_consistency(v: Vault) -> dict:
    w = _fresh(decimals_offset=v.decimals_offset, min_deposit=0)
    w.deposit(50_000_000_000)
    dep = w.preview_deposit(10_000_000_000)
    got = w.deposit(10_000_000_000)
    mint_assets = w.preview_mint(1_000_000)
    paid = w.mint(1_000_000)
    red = w.preview_redeem(1_000_000)
    out = w.redeem(1_000_000)
    ok = dep == got and mint_assets == paid and red == out
    # dep/got are shares; mint/paid/red/out are base-unit assets. Label
    # each, or the reader cannot tell which number is which unit. One
    # line per operation: a single comma-joined line wraps with the final
    # "USDC" orphaned alone on its own line, so each amount is bound to
    # its unit with a non-breaking space and wraps land on "==" instead.
    return {"name": "preview_consistency", "pass": ok,
            "detail": [f"deposit {_fmt_int(dep)}{NBSP}shares == {_fmt_int(got)}{NBSP}shares",
                       f"mint {_fmt_usdc(mint_assets)}{NBSP}USDC == {_fmt_usdc(paid)}{NBSP}USDC",
                       f"redeem {_fmt_usdc(red)}{NBSP}USDC == {_fmt_usdc(out)}{NBSP}USDC"]}


def check_fee_conservation(v: Vault) -> dict:
    w = _fresh(decimals_offset=v.decimals_offset, min_deposit=0,
               perf_fee_bps=v.perf_fee_bps)
    w.deposit(100_000_000_000)
    before = w.total_assets
    fee = w.accrue_yield_and_perf_fee(10_000_000_000)
    # yield in == (assets growth) + fee is exact here by construction;
    # the check is that holders keep assets-fee, not assets+fee.
    holder_gain = (w.total_assets - before) - fee
    ok = holder_gain == 10_000_000_000 - fee and fee == 10_000_000_000 * v.perf_fee_bps // 10_000
    return {"name": "fee_conservation", "pass": ok,
            "detail": [f"yield {_fmt_usdc(10_000_000_000)}{NBSP}USDC, fee {_fmt_usdc(fee)}{NBSP}USDC, "
                       f"holder gain {_fmt_usdc(holder_gain)}{NBSP}USDC"]}


def check_share_price_sanity(v: Vault) -> dict:
    w = _fresh(decimals_offset=v.decimals_offset, min_deposit=0)
    w.deposit(100_000_000_000)
    price_before = w.convert_to_assets(1_000_000)
    w.deposit(100_000_000_000)
    price_after = w.convert_to_assets(1_000_000)
    ok = price_before >= 0 and price_after >= price_before - 1
    return {"name": "share_price_sanity", "pass": ok,
            "detail": [f"price per 1,000,000{NBSP}shares {_fmt_usdc(price_before)}{NBSP}USDC -> "
                       f"{_fmt_usdc(price_after)}{NBSP}USDC"]}


def run_all(v: Vault, victim_deposit: int = 100_000_000_000,
            vault_assets: int = 0, vault_supply: int = 0) -> list[dict]:
    """Run all five checks. victim_deposit is the donation-check scenario
    size (base units, default 100,000 USDC): the vault a user is testing
    may expect much smaller or larger typical deposits than the default.
    vault_assets / vault_supply are the deposits already in the vault
    before the attack (base units / shares, default 0 = a new vault);
    only the donation check uses them."""
    return [check_rounding(v),
            check_donation(v, victim_deposit=victim_deposit,
                           vault_assets=vault_assets, vault_supply=vault_supply),
            check_preview_consistency(v),
            check_fee_conservation(v), check_share_price_sanity(v)]
