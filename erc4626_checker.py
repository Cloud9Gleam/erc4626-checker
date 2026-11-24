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

    def __post_init__(self):
        # A negative or non-integer offset makes virtual_shares a
        # float (10 ** -1 == 0.1), and the checks then die inside the
        # formatters with a ValueError that says nothing about the
        # cause (checker-improvement #209: offset -1, 1.5 and True
        # all crashed cryptically). Fail here, at construction, with
        # the cause named. Only the offset is guarded: the other
        # fields are validated by the callers that accept them
        # (Worker/service clamp offset to [0, 30] and fee to
        # [0, 10000]; the CLI rejects out-of-range input), and a
        # negative victim deposit already runs honestly (#204).
        if isinstance(self.decimals_offset, bool) or not isinstance(
                self.decimals_offset, int):
            raise TypeError(
                "decimals_offset must be an integer, got %r"
                % (self.decimals_offset,))
        if self.decimals_offset < 0:
            raise ValueError(
                "decimals_offset must be >= 0, got %r"
                % (self.decimals_offset,))

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
    # its unit with a non-breaking space. When preview and execution
    # agree (the normal case) each amount is stated once — the old
    # "X == X" form repeated a 16-digit number and wrapped to five
    # lines on a 360px screen. When they disagree the full "X == Y"
    # form is kept, because the two numbers are the evidence.
    def _ident(op, a, b, unit):
        if a == b:
            return f"{op} preview matches execution: {a}{NBSP}{unit}"
        return f"{op} {a}{NBSP}{unit} == {b}{NBSP}{unit}"
    return {"name": "preview_consistency", "pass": ok,
            "detail": [_ident("deposit", _fmt_int(dep), _fmt_int(got), "shares"),
                       _ident("mint", _fmt_usdc(mint_assets), _fmt_usdc(paid), "USDC"),
                       _ident("redeem", _fmt_usdc(red), _fmt_usdc(out), "USDC")]}


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
    buys_before = w.preview_deposit(1_000_000)
    w.deposit(100_000_000_000)
    price_after = w.convert_to_assets(1_000_000)
    buys_after = w.preview_deposit(1_000_000)
    ok = price_before >= 0 and price_after >= price_before - 1
    # Same rule as preview consistency: when the price is unchanged
    # across the second deposit, state the number once; the "X -> Y"
    # form is kept when the two differ, because the difference is the
    # evidence. (Equal deposits keep the assets/shares ratio exact, so
    # the equal case is the normal one through run_all.)
    # The price is stated as shares per USDC, not USDC per million
    # shares: a vault developer thinks in what 1 USDC buys, and the
    # old unit read 0.000001 USDC at offset 6 and 0.000000 USDC at
    # offset 18 — a zero price that looks broken (visual verdict
    # #174, 2026-11-24). preview_deposit is exact, so the buys
    # number is the same price inverted, not a new measurement.
    # The verdict still follows the asset-price probe above, with
    # its 1-base-unit tolerance; the display follows buys.
    price = (f"1{NBSP}USDC buys {_fmt_int(buys_before)}{NBSP}shares (unchanged)"
             if buys_before == buys_after else
             f"1{NBSP}USDC buys {_fmt_int(buys_before)}{NBSP}shares -> "
             f"{_fmt_int(buys_after)}{NBSP}shares")
    return {"name": "share_price_sanity", "pass": ok,
            "detail": [price]}


def check_minimum_viable_deposit(v: Vault, vault_assets: int = 0,
                                 vault_supply: int = 0) -> dict:
    """Smallest deposit that mints at least one share, at the vault's
    live price. Deposit rounds down, so below a threshold a deposit
    mints zero shares: at $1,000 a share a 1 USDC deposit buys nothing,
    and the rounding-errors guide measured the same trap as a
    1-base-unit deposit minting zero shares. PASS = a 1 USDC deposit
    mints at least one share after the vault's own minimum-deposit
    floor. The closed form is exact: shares = floor(a * S' / A')
    with S' = supply + virtual shares and A' = assets + virtual
    assets, so shares >= 1 exactly when a >= ceil(A' / S'). A
    decimals offset raises S' and shrinks the threshold.

    vault_assets / vault_supply seed the vault with the deposits
    already in it (base units / shares, default 0 = a new vault).
    A half-filled state needs no refusal here, unlike the donation
    check: assets with no shares is a donated-to empty vault, and
    the preview math is still defined there."""
    w = _fresh(total_assets=vault_assets, total_supply=vault_supply,
               decimals_offset=v.decimals_offset, min_deposit=v.min_deposit)
    s_prime = w.total_supply + w.virtual_shares
    a_prime = w.total_assets + w.virtual_assets
    # ceil(A' / S') in exact integers.
    min_assets = -(-a_prime // s_prime)
    one_usdc_mints = w.preview_deposit(1_000_000)
    effective = max(v.min_deposit, min_assets)
    ok = effective <= 1_000_000
    detail = [f"1{NBSP}USDC mints {_fmt_int(one_usdc_mints)}{NBSP}shares",
              f"smallest deposit minting 1 share: {_fmt_usdc(min_assets)}{NBSP}USDC"]
    if min_assets > 1:
        detail.append(f"largest zero-share deposit: {_fmt_usdc(min_assets - 1)}{NBSP}USDC")
    else:
        detail.append("no zero-share deposit: 1 base unit mints 1 share")
    if v.min_deposit > min_assets:
        # When the floor binds, effective == the floor, so the amount
        # is stated once — the old form repeated it ("floor X binds:
        # effective minimum X") for no information.
        detail.append(f"min-deposit floor binds: effective minimum {_fmt_usdc(effective)}{NBSP}USDC")
    return {"name": "minimum_viable_deposit", "pass": ok, "detail": detail}


def run_all(v: Vault, victim_deposit: int = 100_000_000_000,
            vault_assets: int = 0, vault_supply: int = 0) -> list[dict]:
    """Run all six checks. victim_deposit is the donation-check scenario
    size (base units, default 100,000 USDC): the vault a user is testing
    may expect much smaller or larger typical deposits than the default.
    vault_assets / vault_supply are the deposits already in the vault
    before the attack (base units / shares, default 0 = a new vault);
    only the donation and minimum-viable-deposit checks use them."""
    return [check_rounding(v),
            check_donation(v, victim_deposit=victim_deposit,
                           vault_assets=vault_assets, vault_supply=vault_supply),
            check_minimum_viable_deposit(v, vault_assets=vault_assets,
                                         vault_supply=vault_supply),
            check_preview_consistency(v),
            check_fee_conservation(v), check_share_price_sanity(v)]
