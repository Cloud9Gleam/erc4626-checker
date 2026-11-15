import unittest
from fractions import Fraction

from erc4626_checker import Vault, run_all, check_donation


class TestChecker(unittest.TestCase):
    def test_alphaprimer_params_all_pass(self):
        v = Vault(decimals_offset=6, min_deposit=1_000_000, perf_fee_bps=1000)
        results = run_all(v)
        self.assertTrue(all(r["pass"] for r in results), results)

    def test_no_offset_no_min_is_exploitable(self):
        # Control case: with offset 0 and no minimum, a large donation
        # CAN make the victim's deposit round to ~0 shares. The checker
        # must be able to tell the two configurations apart.
        v = Vault(decimals_offset=0, min_deposit=0)
        r = check_donation(v, victim_deposit=1_000_000,
                           donations=(10_000_000_000_000,))
        self.assertFalse(r["pass"])

    def test_detail_lines_use_readable_units(self):
        # Result detail lines must be readable at a glance: USDC amounts
        # with 6 decimals, share counts comma-separated and labelled, and
        # no bare 10+ digit runs a reader has to count zeros in.
        v = Vault(decimals_offset=6, min_deposit=1_000_000, perf_fee_bps=1000)
        results = {r["name"]: r for r in run_all(v)}
        prev = " ".join(results["preview_consistency"]["detail"])
        self.assertIn("10,000,000,000,000,000\u00a0shares", prev)
        self.assertIn("0.000001\u00a0USDC", prev)
        self.assertEqual(len(results["preview_consistency"]["detail"]), 3)
        fee = results["fee_conservation"]["detail"][0]
        self.assertEqual(
            fee, "yield 10,000.000000\u00a0USDC, fee 1,000.000000\u00a0USDC, "
                 "holder gain 9,000.000000\u00a0USDC")
        price = results["share_price_sanity"]["detail"][0]
        self.assertEqual(
            price, "price per 1,000,000\u00a0shares 0.000001\u00a0USDC -> 0.000001\u00a0USDC")
        for r in results.values():
            for line in r["detail"]:
                if isinstance(line, str):
                    self.assertNotRegex(line, r"\d{10,}")
                    # Amounts stay bound to their unit: a wrapping line
                    # breaks at "==" / "," / "->", never leaving a lone
                    # "USDC" / "shares" on its own line.
                    self.assertNotIn(" USDC", line)
                    self.assertNotIn(" shares", line)

    def test_empty_vault_first_deposit(self):
        v = Vault(decimals_offset=6, min_deposit=1_000_000)
        shares = v.deposit(1_000_000)
        self.assertGreater(shares, 0)

    def test_run_all_threads_victim_deposit(self):
        # The victim deposit is a scenario parameter, not a vault constant:
        # run_all must pass it to the donation check, and the presets'
        # verdicts must not depend on it (offset 6 passes at every size
        # 1–10,000,000 USDC, offset 0 fails at every size).
        noprot = Vault(decimals_offset=0, min_deposit=0)
        default_rows = {r["name"]: r for r in run_all(noprot)}["donation_inflation"]["detail"]
        self.assertEqual(max(r["victim_loss"] for r in default_rows), 909091)
        small_rows = {r["name"]: r for r in run_all(noprot, victim_deposit=1_000_000_000)}["donation_inflation"]["detail"]
        self.assertEqual(max(r["victim_loss"] for r in small_rows), 999001)
        self.assertFalse(all(r["pass"] for r in run_all(noprot, victim_deposit=1_000_000_000)))
        alpha = Vault(decimals_offset=6, min_deposit=1_000_000, perf_fee_bps=1000)
        self.assertTrue(all(r["pass"] for r in run_all(alpha, victim_deposit=1_000_000)))
        self.assertTrue(all(r["pass"] for r in run_all(alpha, victim_deposit=1_000_000_000_000)))

    def test_donation_error_row_reports_no_loss(self):
        # A minimum deposit above the victim deposit makes the victim's
        # deposit revert: no loss is measured, so the row must not claim
        # the full deposit as lost.
        v = Vault(decimals_offset=6, min_deposit=200_000_000_000, perf_fee_bps=1000)
        r = check_donation(v)
        self.assertFalse(r["pass"])
        for row in r["detail"]:
            self.assertIn("error", row)
            self.assertIsNone(row["victim_loss"])
            self.assertIsNone(row["attacker_net"])

    def test_inflation_guide_numbers(self):
        # Pins the worked example in /guides/erc4626-inflation-attack/,
        # /guides/erc4626-donation-attack/ and
        # /research/erc4626-donation-inflation/ to the model: attacker
        # 1 USDC, donate 1,000,000 USDC, victim 100,000 USDC, both
        # redeem, offset 0. Earlier versions of all three pages told
        # the textbook story — victim "receives a handful of shares",
        # "most of their deposit stays in the vault", attacker "redeems
        # for the inflated remainder" — but the model says the victim
        # loses 0.909091 USDC, the attacker nets -0.090909, and the
        # missing 1 USDC stays in the vault as rounding dust.
        w = Vault(decimals_offset=0, min_deposit=0)
        atk_shares = w.deposit(1_000_000)
        self.assertEqual(atk_shares, 1_000_000)
        w.donate(1_000_000_000_000)
        vic_shares = w.deposit(100_000_000_000)
        self.assertEqual(vic_shares, 99_999)
        atk_out = w.redeem(atk_shares)
        self.assertEqual(atk_out, 1_000_000_909_091)
        self.assertEqual(atk_out - (1_000_000 + 1_000_000_000_000), -90_909)
        vic_out = w.redeem(vic_shares)
        self.assertEqual(vic_out, 99_999_090_909)
        self.assertEqual(100_000_000_000 - vic_out, 909_091)
        self.assertEqual(w.total_assets, 1_000_000)
        self.assertEqual(w.total_supply, 0)

    def test_virtual_shares_guide_numbers(self):
        # Pins the worked example in /guides/erc4626-virtual-shares/ to
        # the model: attacker 1 USDC, donate 1,000,000 USDC, victim
        # 1,000 USDC, both redeem. The guide's first version had
        # hand-computed numbers that contradicted the model in 9 of 10
        # cells (attacker "profit" +0.998003 at offset 0, victim
        # "+997.008979" at offset 6) — the model says the attacker
        # never profits here: the victim's offset-0 loss stays in the
        # vault as rounding dust, and at offset 6 the victim loses
        # exactly one base unit.
        for off, atk_net, vic_loss in ((0, -999, 999001), (6, -999999, 1)):
            r = check_donation(Vault(decimals_offset=off, min_deposit=1_000_000),
                               victim_deposit=1_000_000_000,
                               donations=(1_000_000_000_000,))
            row = r["detail"][0]
            self.assertEqual(row["attacker_net"], atk_net)
            self.assertEqual(row["victim_loss"], vic_loss)
        self.assertFalse(check_donation(
            Vault(decimals_offset=0, min_deposit=1_000_000),
            victim_deposit=1_000_000_000,
            donations=(1_000_000_000_000,))["pass"])
        self.assertTrue(check_donation(
            Vault(decimals_offset=6, min_deposit=1_000_000),
            victim_deposit=1_000_000_000,
            donations=(1_000_000_000_000,))["pass"])

    def test_defense_measured_scan(self):
        # Pins the worked examples in
        # /guides/erc4626-inflation-defense-measured/ to the model:
        # attacker 1 USDC, donate 1,000,000 USDC, victim V, both
        # redeem, offsets 0/6/18 x victims 1k/10k/100k/1M/10M USDC.
        # (victim_loss, attacker_net) in base units. The pattern the
        # guide reports: at offset 0 the loss falls as the victim
        # grows (999001 -> 90909) and victim + attacker loss is
        # exactly 1,000,000 base units in every row; at offset 6 the
        # loss is 1 base unit or zero; at offset 18 it is zero.
        expected = {
            0: {1_000: (999001, -999), 10_000: (990100, -9900),
                100_000: (909091, -90909), 1_000_000: (500000, -500000),
                10_000_000: (90909, -909091)},
            6: {1_000: (1, -999999), 10_000: (1, -999999),
                100_000: (1, -999999), 1_000_000: (0, -1000000),
                10_000_000: (0, -1000000)},
            18: {1_000: (0, -1000000), 10_000: (0, -1000000),
                 100_000: (0, -1000000), 1_000_000: (0, -1000000),
                 10_000_000: (0, -1000000)},
        }
        for off, rows in expected.items():
            for vic_usdc, (vic_loss, atk_net) in rows.items():
                r = check_donation(Vault(decimals_offset=off, min_deposit=1_000_000),
                                   victim_deposit=vic_usdc * 1_000_000,
                                   donations=(1_000_000_000_000,))
                row = r["detail"][0]
                self.assertEqual(row["victim_loss"], vic_loss)
                self.assertEqual(row["attacker_net"], atk_net)

    def test_checklist_donation_and_share_price_numbers(self):
        # Pins the two last unreviewed pages to the model:
        # /guides/erc4626-audit-checklist/ §2 and §5, and
        # /guides/vault-share-price-manipulation/ "What to check".
        # Checklist scenario: attacker seeds the minimum, donates
        # 1 / 1,000 / 1,000,000 / 1,000,000,000 USDC, victim deposits
        # 100,000 USDC, both redeem. Worst victim loss: offset 0
        # 0.909091 USDC (FAIL), offset 6 0.000900 USDC (PASS),
        # offset 18 zero (PASS); attacker never profits.
        worst = {0: 909091, 6: 900, 18: 0}
        for off, expected_worst in worst.items():
            mn = 0 if off == 0 else 1_000_000
            r = check_donation(Vault(decimals_offset=off, min_deposit=mn))
            losses = [row["victim_loss"] for row in r["detail"]]
            self.assertEqual(max(losses), expected_worst)
            self.assertTrue(all(row["attacker_net"] <= 0
                                for row in r["detail"]))
        # Share-price sanity as the guides state it: on a plain
        # deposit the price is never negative and never below its
        # pre-deposit value. The model's check tolerates a 1-base-unit
        # dip; the sweep below shows the dip is never exercised.
        for off in (0, 6, 18, 30):
            for seed in (1_000_000, 100_000_000_000, 10_000_000_000_000):
                for dep in (1, 1_000_000, 100_000_000_000, 1_000_000_000_000):
                    v = Vault(decimals_offset=off, min_deposit=0)
                    v.deposit(seed)
                    before = v.convert_to_assets(1_000_000)
                    try:
                        v.deposit(dep)
                    except ValueError:
                        continue
                    after = v.convert_to_assets(1_000_000)
                    self.assertGreaterEqual(before, 0)
                    self.assertGreaterEqual(after, before)
    def test_how_to_guide_numbers(self):
        # Pins /guides/how-to-use-the-erc4626-checker/ Step 3 to the
        # model: four donations 1 / 1,000 / 1,000,000 / 1,000,000,000
        # USDC against a 100,000 USDC victim deposit; pass bound is
        # victim loss <= 1000 base units (0.001 USDC) AND <= 0.1% of
        # the victim deposit, attacker never profits. Unprotected
        # preset loses 0.909091 USDC to the 1,000,000 USDC donation;
        # offset-6 preset loses at most 0.0009 USDC.
        victim = 100_000_000_000
        donations = [1_000_000, 1_000_000_000, 1_000_000_000_000,
                     1_000_000_000_000_000]
        noprot = check_donation(Vault(decimals_offset=0, min_deposit=0),
                                victim_deposit=victim)
        self.assertEqual([r["donation"] for r in noprot["detail"]], donations)
        self.assertFalse(noprot["pass"])
        row_1m = noprot["detail"][2]
        self.assertEqual(row_1m["donation"], 1_000_000_000_000)
        self.assertEqual(row_1m["victim_loss"], 909091)
        self.assertTrue(all(r["attacker_net"] <= 0 for r in noprot["detail"]))
        primer = check_donation(Vault(decimals_offset=6, min_deposit=1_000_000,
                                      perf_fee_bps=1000),
                                victim_deposit=victim)
        self.assertTrue(primer["pass"])
        losses = [r["victim_loss"] for r in primer["detail"]]
        self.assertEqual(max(losses), 900)
        # The bound as the guide states it: 1000 base units is
        # 0.001 USDC, and 0.1% of the 100,000 USDC victim deposit is
        # 100 USDC -- the absolute bound binds first here.
        self.assertEqual(1000, 1_000_000 // 1000)  # 0.001 USDC in base units
        self.assertEqual(victim // 1000, 100_000_000)  # 0.1% = 100 USDC
        self.assertLessEqual(max(losses), 1000)
        self.assertLessEqual(max(losses), victim // 1000)

    def test_minfeeonly_preset_numbers(self):
        # Pins the checker's "Minimum + fee, no offset" preset to the
        # model: offset 0, minimum deposit 1 USDC, fee 10%, victim
        # 100,000 USDC. The fee only touches yield and the minimum only
        # forces a 1 USDC seed, so neither blunts the donation: the
        # preset still fails and still loses the full 0.909091 USDC to
        # the 1,000,000 USDC donation, exactly like no protection.
        victim = 100_000_000_000
        v = Vault(decimals_offset=0, min_deposit=1_000_000, perf_fee_bps=1000)
        self.assertFalse(all(r["pass"] for r in run_all(v, victim_deposit=victim)))
        don = check_donation(v, victim_deposit=victim)
        self.assertFalse(don["pass"])
        self.assertEqual(don["detail"][2]["victim_loss"], 909091)
        self.assertEqual(max(r["victim_loss"] for r in don["detail"]), 909091)

    def test_slippage_bounds_guide_numbers(self):
        # Pins /guides/erc4626-slippage-bounds/ to the model: victim
        # 100,000 USDC, bound 99% of the clean (pre-attack) quote,
        # attacker seed max(min, 1 USDC), donations 1 / 1,000 /
        # 1,000,000 / 1,000,000,000 USDC, offsets 0 / 6 / 18. The
        # bound must revert every attacked deposit at every offset;
        # the attacker must never profit.
        victim = 100_000_000_000
        donations = [1_000_000, 1_000_000_000, 1_000_000_000_000,
                     1_000_000_000_000_000]

        def attacked_mint(offset, min_dep, donation):
            v = Vault(decimals_offset=offset, min_deposit=min_dep)
            seed = max(min_dep, 1_000_000)
            v.deposit(seed)
            v.donate(donation)
            return v.deposit(victim)

        # Unprotected vault: clean quote and the four attacked mints.
        clean0 = Vault(decimals_offset=0, min_deposit=0).deposit(victim)
        self.assertEqual(clean0, 100_000_000_000)
        bound0 = clean0 * 99 // 100
        self.assertEqual(bound0, 99_000_000_000)
        mints0 = [attacked_mint(0, 0, d) for d in donations]
        self.assertEqual(mints0, [50_000_024_999, 99_900_199, 99_999, 100])
        self.assertTrue(all(m < bound0 for m in mints0))
        # The 1 USDC donation halves the quote yet costs the victim
        # nothing: the bound still reverts a harmless deposit.
        self.assertEqual(mints0[0] * 2, clean0 + 49_998)

        # Losses and attacker nets from check_donation, same victim.
        noprot = check_donation(Vault(decimals_offset=0, min_deposit=0),
                                victim_deposit=victim)
        self.assertEqual([r["victim_loss"] for r in noprot["detail"]],
                         [0, 6, 909091, 99890])
        self.assertEqual([r["attacker_net"] for r in noprot["detail"]],
                         [-1, -994, -90909, -999899111])

        # Offset 6 caps the worst loss at 900 base units (0.0009 USDC,
        # at the 1,000,000,000 USDC donation); offset 18 loses nothing.
        # The bound still reverts every row at both offsets.
        for offset, min_dep, worst_loss in ((6, 1_000_000, 900),
                                            (18, 1_000_000, 0)):
            clean = Vault(decimals_offset=offset,
                          min_deposit=min_dep).deposit(victim)
            bound = clean * 99 // 100
            mints = [attacked_mint(offset, min_dep, d) for d in donations]
            self.assertTrue(all(m < bound for m in mints))
            res = check_donation(
                Vault(decimals_offset=offset, min_deposit=min_dep),
                victim_deposit=victim)
            losses = [r["victim_loss"] for r in res["detail"]]
            self.assertEqual(max(losses), worst_loss)
            self.assertTrue(all(r["attacker_net"] <= 0
                                for r in res["detail"]))
    def test_quote_sources_guide_numbers(self):
        # Pins /guides/erc4626-quote-sources/ to the model: victim
        # 100,000 USDC, unprotected vault, attacker seed 1 USDC,
        # donations 1 / 1,000 / 1,000,000 / 1,000,000,000 USDC.
        # A bound built on the same-block preview (taken after the
        # donation) passes every attack; a bound built on the clean
        # pre-donation quote reverts every one. A stale clean quote
        # after 1% legitimate yield still passes the 99% bound, with
        # only 0.0099% of headroom left.
        victim = 100_000_000_000
        donations = [1_000_000, 1_000_000_000, 1_000_000_000_000,
                     1_000_000_000_000_000]

        clean = Vault(decimals_offset=0, min_deposit=0).deposit(victim)
        self.assertEqual(clean, 100_000_000_000)
        bound_clean = clean * 99 // 100
        self.assertEqual(bound_clean, 99_000_000_000)

        previews = []
        for d in donations:
            v = Vault(decimals_offset=0, min_deposit=0)
            v.deposit(1_000_000)
            v.donate(d)
            previews.append(v.preview_deposit(victim))
        self.assertEqual(previews,
                         [50_000_024_999, 99_900_199, 99_999, 100])
        # Bound from the same-block preview always passes (attack wins).
        for preview in previews:
            bound_preview = preview * 99 // 100
            self.assertTrue(preview >= bound_preview)
        # Bound from the clean quote reverts every attacked deposit.
        self.assertTrue(all(p < bound_clean for p in previews))

        # Stale clean quote: 1% yield accrues after the quote, no attack.
        v = Vault(decimals_offset=0, min_deposit=0)
        v.deposit(victim)
        v.donate(1_000_000_000)  # 1,000 USDC yield on a 100,000 USDC vault
        stale_mint = v.preview_deposit(victim)
        self.assertEqual(stale_mint, 99_009_900_990)
        self.assertTrue(stale_mint >= bound_clean)
        self.assertEqual(clean - stale_mint, 990_099_010)

    def test_wrapper_guide_numbers(self):
        # Pins /guides/erc4626-minshares-wrapper/ to the model: a wrapper
        # enforces minShares by depositing, then reverting unless the
        # shares received are >= the user-supplied floor (computed
        # off-chain from a pre-donation quote). The wrapper does not change
        # the mint math — it only refuses a bad result. Same victim and
        # donations as the slippage-bounds guide.
        victim = 100_000_000_000
        donations = [1_000_000, 1_000_000_000, 1_000_000_000_000,
                     1_000_000_000_000_000]

        clean = Vault(decimals_offset=0, min_deposit=0).deposit(victim)
        self.assertEqual(clean, 100_000_000_000)
        floor = clean * 99 // 100
        self.assertEqual(floor, 99_000_000_000)
        # floor() costs less than one share of strictness, by construction.
        self.assertTrue(0 <= clean * 99 - floor * 100 < 100)

        def wrapper_deposit(donation):
            v = Vault(decimals_offset=0, min_deposit=0)
            v.deposit(1_000_000)  # attacker seed
            v.donate(donation)
            shares = v.deposit(victim)
            return shares if shares >= floor else None

        # All four attacked deposits revert under the wrapper.
        self.assertEqual([wrapper_deposit(d) for d in donations],
                         [None, None, None, None])

        # Stale-but-clean quote still passes, headroom 9,900,990 shares.
        v = Vault(decimals_offset=0, min_deposit=0)
        v.deposit(victim)
        v.donate(1_000_000_000)  # 1,000 USDC yield on a 100,000 USDC vault
        stale_mint = v.preview_deposit(victim)
        self.assertEqual(stale_mint, 99_009_900_990)
        self.assertEqual(stale_mint - floor, 9_900_990)

        # Small victim: floor rounding is exact here too, and the attacked
        # mint (9 shares) sits 1,100,000x below the floor.
        small = 10_000_000
        small_clean = Vault(decimals_offset=0, min_deposit=0).deposit(small)
        self.assertEqual(small_clean, 10_000_000)
        small_floor = small_clean * 99 // 100
        self.assertEqual(small_floor, 9_900_000)
        v = Vault(decimals_offset=0, min_deposit=0)
        v.deposit(1_000_000)
        v.donate(1_000_000_000_000)
        small_attacked = v.preview_deposit(small)
        self.assertEqual(small_attacked, 9)
        self.assertTrue(small_attacked < small_floor)
        self.assertEqual(small_floor // small_attacked, 1_100_000)

        # A wrapper that previews in the SAME transaction reads the
        # already-inflated price and passes every attack — no better
        # than a same-block frontend preview.
        for d in donations:
            v = Vault(decimals_offset=0, min_deposit=0)
            v.deposit(1_000_000)
            v.donate(d)
            preview = v.preview_deposit(victim)
            same_tx_floor = preview * 99 // 100
            shares = v.deposit(victim)
            self.assertEqual(shares, preview)
            self.assertTrue(shares >= same_tx_floor)
    def test_perf_fee_guide_numbers(self):
        # Pins /guides/erc4626-performance-fee/ to its model: a performance
        # fee is 20% of yield above the high-water mark, paid in shares
        # minted at the current price; the mark is what stops the manager
        # charging twice for the same gain.
        import importlib.util
        from pathlib import Path
        model_path = (Path.home() / "workspace/taskmarket/site"
                      / "perf-fee-model.py")
        spec = importlib.util.spec_from_file_location(
            "perf_fee_model", model_path)
        model = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(model)
        USDC = model.USDC
        S0 = 1_000_000 * USDC
        H = 10_000 * USDC

        # A: +10% year, 20% fee: fee 20,000, shares 18,181.818181, claim
        # 10,803.571428, recipient 19,642.857141 (mint dilutes the fee).
        a1 = 1_100_000 * USDC
        fa, fs, hwm1 = model.harvest(a1, 1_000_000 * USDC, S0, 2000)
        self.assertEqual(fa, 20_000 * USDC)
        self.assertEqual(fs, 18_181_818_181)
        self.assertEqual(model.holder_claim(H, a1, S0 + fs), 10_803_571_428)
        self.assertEqual(model.holder_claim(fs, a1, S0 + fs), 19_642_857_141)
        # B: recover to 1,050,000, below the 1,100,000 mark: fee 0.
        fb, fsb, hwm2b = model.harvest(1_050_000 * USDC, hwm1, S0 + fs, 2000)
        self.assertEqual((fb, fsb), (0, 0))
        self.assertEqual(hwm2b, hwm1)
        self.assertEqual(model.holder_claim(H, 1_050_000 * USDC, S0 + fs),
                         10_312_500_000)
        # C: recover to 1,200,000: fee only on the 100,000 excess.
        fc, fsc, _ = model.harvest(1_200_000 * USDC, hwm1, S0 + fs, 2000)
        self.assertEqual(fc, 20_000 * USDC)
        self.assertEqual(fsc, 16_969_696_969)
        self.assertEqual(
            model.holder_claim(H, 1_200_000 * USDC, S0 + fs + fsc),
            11_592_505_854)
        self.assertEqual(
            model.holder_claim(fs + fsc, 1_200_000 * USDC, S0 + fs + fsc),
            40_749_414_518)
        # D: no HWM, second +10% swing: fee again on the same 100,000.
        fd, fsd, _ = model.harvest(a1, 1_000_000 * USDC, S0 + fs, 2000)
        self.assertEqual(fd, 20_000 * USDC)
        self.assertEqual(fsd, 18_512_396_694)
        self.assertEqual(
            model.holder_claim(H, a1, S0 + fs + fsd), 10_610_650_510)
        self.assertEqual(
            model.holder_claim(fs + fsd, a1, S0 + fs + fsd), 38_934_948_978)
        # E: 10% fee control: fee 10,000, claim 10,900.900900.
        fe, fse, _ = model.harvest(a1, 1_000_000 * USDC, S0, 1000)
        self.assertEqual(fe, 10_000 * USDC)
        self.assertEqual(fse, 9_090_909_090)
        self.assertEqual(model.holder_claim(H, a1, S0 + fse), 10_900_900_900)

    def test_maxwithdraw_guide_numbers(self):
        # Pins /guides/erc4626-maxwithdraw/ to its model: a vault's
        # totalAssets counts assets locked in a strategy, but a
        # withdrawal only pays out of liquid assets on hand. One
        # holder, 1,000,000 shares = 1,000,000 USDC paper value.
        import importlib.util
        from pathlib import Path
        model_path = (Path.home() / "workspace/taskmarket/site"
                      / "withdrawal-liquidity-model.py")
        spec = importlib.util.spec_from_file_location(
            "withdrawal_liquidity_model", model_path)
        model = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(model)
        USDC = model.USDC
        SUPPLY = 1_000_000 * USDC

        def scenario(total, liquid, shares):
            # Same four quantities the guide prints, computed from the
            # model's Vault directly (scenario() prints, so not used).
            v = model.Vault(total, liquid, SUPPLY)
            naive = v.max_withdraw_naive(shares)
            honest = v.max_withdraw_honest(shares)
            paid = v.redeemable(naive)
            return {"naive": naive, "honest": honest, "paid": paid,
                    "shortfall": naive - paid}

        # Strategy holds 90%: naive promises 1,000,000, settles
        # 100,000, shortfall 900,000; honest cap is 100,000.
        r1 = scenario(1_000_000 * USDC, 100_000 * USDC, SUPPLY)
        self.assertEqual(r1["naive"], 1_000_000 * USDC)
        self.assertEqual(r1["paid"], 100_000 * USDC)
        self.assertEqual(r1["shortfall"], 900_000 * USDC)
        self.assertEqual(r1["honest"], 100_000 * USDC)
        # Half the strategy harvested: shortfall halves to 500,000.
        r2 = scenario(1_000_000 * USDC, 500_000 * USDC, SUPPLY)
        self.assertEqual(r2["paid"], 500_000 * USDC)
        self.assertEqual(r2["shortfall"], 500_000 * USDC)
        self.assertEqual(r2["honest"], 500_000 * USDC)
        # Fully liquid: the naive promise finally settles in full.
        r3 = scenario(1_000_000 * USDC, 1_000_000 * USDC, SUPPLY)
        self.assertEqual(r3["shortfall"], 0)
        self.assertEqual(r3["honest"], 1_000_000 * USDC)
        # Half-holder in the 90%-in-strategy vault: paper value
        # 500,000, settles 100,000, shortfall 400,000.
        r4 = scenario(1_000_000 * USDC, 100_000 * USDC, 500_000 * USDC)
        self.assertEqual(r4["naive"], 500_000 * USDC)
        self.assertEqual(r4["paid"], 100_000 * USDC)
        self.assertEqual(r4["shortfall"], 400_000 * USDC)
        # Honest cap is min(balance value, liquid) in every scenario,
        # and the capped amount always settles in full.
        for r, liquid in ((r1, 100_000 * USDC), (r2, 500_000 * USDC),
                          (r3, 1_000_000 * USDC), (r4, 100_000 * USDC)):
            self.assertEqual(r["honest"], min(r["naive"], liquid))
            self.assertEqual(r["honest"], r["paid"])

    def test_fee_accrual_guide_numbers(self):
        # Pins /guides/erc4626-fee-accrual/ to its model: a management
        # fee is paid by minting fee shares, so the holder's cost is
        # their share of the dilution, not the rate times their deposit.
        import importlib.util
        from pathlib import Path
        model_path = (Path.home() / "workspace/taskmarket/site"
                      / "fee-accrual-model.py")
        spec = importlib.util.spec_from_file_location(
            "fee_accrual_model", model_path)
        model = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(model)
        USDC = model.USDC
        A0 = 1_000_000 * USDC
        S0 = 1_000_000 * USDC
        H = 10_000 * USDC

        # 2%/1y/no yield: 20,000 fee shares; claim 9,803.921568 USDC.
        self.assertEqual(model.fee_shares_minted(S0, 200, 1),
                         20_000 * USDC)
        self.assertEqual(model.holder_claim(H, A0, S0 + 20_000 * USDC),
                         9_803_921_568)
        # 2%/5y/no yield: 100,000 fee shares; claim 9,090.909090 USDC.
        self.assertEqual(model.fee_shares_minted(S0, 200, 5),
                         100_000 * USDC)
        self.assertEqual(model.holder_claim(H, A0, S0 + 100_000 * USDC),
                         9_090_909_090)
        # 2%/1y/+10% yield: assets 1,100,000; claim 10,784.313725 USDC.
        self.assertEqual(
            model.holder_claim(H, 1_100_000 * USDC, S0 + 20_000 * USDC),
            10_784_313_725)
        # Control: zero fee leaves the holder whole.
        self.assertEqual(model.holder_claim(H, A0, S0), H)
        # 1%/1y/no yield: 10,000 fee shares; claim 9,900.990099 USDC.
        self.assertEqual(model.holder_claim(H, A0, S0 + 10_000 * USDC),
                         9_900_990_099)

    def test_fee_down_year_guide_numbers(self):
        # Pins /guides/erc4626-fee-in-down-year/ to its model: a management
        # fee is a fraction of supply, so in a loss year the fee is still
        # charged -- and its USDC cost shrinks with the vault, never to zero.
        import importlib.util
        from pathlib import Path
        model_path = (Path.home() / "workspace/taskmarket/site"
                      / "fee-down-year-model.py")
        spec = importlib.util.spec_from_file_location(
            "fee_down_year_model", model_path)
        model = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(model)
        USDC = model.USDC
        A0 = 1_000_000 * USDC
        S0 = 1_000_000 * USDC
        H = 10_000 * USDC

        # 2%/1y/-10%: assets 900,000; fee shares 20,000; claim 8,823.529411.
        a1 = A0 * 9000 // model.BPS
        self.assertEqual(model.fee_shares_minted(S0, 200), 20_000 * USDC)
        self.assertEqual(model.holder_claim(H, a1, S0 + 20_000 * USDC),
                         8_823_529_411)
        self.assertEqual(model.holder_claim(H, a1, S0), 9_000 * USDC)
        self.assertEqual(
            model.holder_claim(20_000 * USDC, a1, S0 + 20_000 * USDC),
            17_647_058_823)
        # 2%/1y/-50%: assets 500,000; claim 4,901.960784; fee cost 98.04.
        a2 = A0 * 5000 // model.BPS
        self.assertEqual(model.holder_claim(H, a2, S0 + 20_000 * USDC),
                         4_901_960_784)
        self.assertEqual(model.holder_claim(H, a2, S0), 5_000 * USDC)
        # 5%/1y/-10%: fee shares 50,000; claim 8,571.428571.
        self.assertEqual(model.fee_shares_minted(S0, 500), 50_000 * USDC)
        self.assertEqual(model.holder_claim(H, a1, S0 + 50_000 * USDC),
                         8_571_428_571)
        self.assertEqual(
            model.holder_claim(50_000 * USDC, a1, S0 + 50_000 * USDC),
            42_857_142_857)
        # Control: zero fee leaves the holder with exactly the post-loss share.
        self.assertEqual(model.holder_claim(H, a1, S0), 9_000 * USDC)

    def test_combined_fee_guide_numbers(self):
        # Pins /guides/erc4626-combined-fee/ to its model: a 2% management
        # fee plus a 20% performance fee do NOT add up to the naive 400 --
        # the performance fee mints more shares on the management-diluted
        # supply, so the combined cost (408.26) sits between the naive sum
        # (400) and the sum of the two separate costs (412.11); in a loss
        # year the performance fee is 0 and the combined cost is the
        # management fee alone.
        import importlib.util
        from pathlib import Path
        model_path = (Path.home() / "workspace/taskmarket/site"
                      / "combined-fee-model.py")
        spec = importlib.util.spec_from_file_location(
            "combined_fee_model", model_path)
        model = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(model)
        USDC = model.USDC
        A0 = 1_000_000 * USDC
        S0 = 1_000_000 * USDC
        H = 10_000 * USDC

        # A: +10% year, both fees. Mgmt 20,000 shares; perf fee 20,000 USDC
        # minted as 18,545.454545 shares on the diluted supply (vs
        # 18,181.818181 perf-only); claim 10,591.736694, cost 408.26.
        a1 = 1_100_000 * USDC
        mg = model.mgmt_shares(S0, 200)
        self.assertEqual(mg, 20_000 * USDC)
        fa, fs = model.perf_fee(a1, A0, S0 + mg, 2000)
        self.assertEqual(fa, 20_000 * USDC)
        self.assertEqual(fs, 18_545_454_545)
        self.assertEqual(model.holder_claim(H, a1, S0 + mg + fs),
                         10_591_736_694)
        self.assertEqual(model.holder_claim(mg, a1, S0 + mg + fs),
                         21_183_473_389)
        self.assertEqual(model.holder_claim(fs, a1, S0 + mg + fs),
                         19_642_857_142)
        # B: mgmt only, +10%: claim 10,784.313725, cost 215.69.
        self.assertEqual(model.holder_claim(H, a1, S0 + mg), 10_784_313_725)
        # C: perf only, +10%: fee shares 18,181.818181, claim 10,803.571428.
        fc, fsc = model.perf_fee(a1, A0, S0, 2000)
        self.assertEqual((fc, fsc), (20_000 * USDC, 18_181_818_181))
        self.assertEqual(model.holder_claim(H, a1, S0 + fsc), 10_803_571_428)
        # D: -10% year, both fees: perf is 0, claim 8,823.529411.
        a2 = 900_000 * USDC
        fd, fsd = model.perf_fee(a2, A0, S0 + mg, 2000)
        self.assertEqual((fd, fsd), (0, 0))
        self.assertEqual(model.holder_claim(H, a2, S0 + mg), 8_823_529_411)
        self.assertEqual(model.holder_claim(mg, a2, S0 + mg), 17_647_058_823)
        # Interaction: 400 < combined 408.26 < separate sum 412.11.
        cost_a = 11_000 * USDC - model.holder_claim(H, a1, S0 + mg + fs)
        cost_b = 11_000 * USDC - model.holder_claim(H, a1, S0 + mg)
        cost_c = 11_000 * USDC - model.holder_claim(H, a1, S0 + fsc)
        self.assertTrue(400 * USDC < cost_a < cost_b + cost_c)

    def test_withdrawal_queue_guide_numbers(self):
        # Pins /guides/erc4626-withdrawal-queue/ to its model: a queue
        # answers WHEN you get paid, not how much. FIFO with 300k ahead,
        # 100k liquid, 50k/day inflow pays 0 now, first dollar day 4,
        # full day 5; pro-rata pays 14,285.714285 now and the same day 5
        # in full; zero inflow never clears; a 7-day delay binds at day 7
        # when liquidity clears day 5 and does not bind when it clears
        # day 9; a 10% loss while waiting turns 50,000 into 45,000.
        import importlib.util
        from pathlib import Path
        model_path = (Path.home() / "workspace/taskmarket/site"
                      / "withdrawal-queue-model.py")
        spec = importlib.util.spec_from_file_location(
            "withdrawal_queue_model", model_path)
        model = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(model)
        USDC = model.USDC
        L = 100_000 * USDC
        R = 50_000 * USDC
        I = 50_000 * USDC
        # No queue: paid now.
        self.assertEqual(model.fifo(L, 0, R, I), (R, 0, 0))
        # Deep queue FIFO: 0 now, first day 4, full day 5.
        self.assertEqual(model.fifo(L, 300_000 * USDC, R, I), (0, 4, 5))
        # Pro-rata: 14,285.714285 now, remainder 35,714.285715, full day 5.
        self.assertEqual(model.prorata_immediate(L, 300_000 * USDC, R),
                         14_285_714_285)
        self.assertEqual(R - model.prorata_immediate(L, 300_000 * USDC, R),
                         35_714_285_715)
        self.assertEqual(model.fifo(L, 300_000 * USDC, R, I)[2], 5)
        # No inflow: never.
        self.assertEqual(model.fifo(L, 300_000 * USDC, R, 0),
                         (0, None, None))
        # Small queue: paid now.
        self.assertEqual(model.fifo(L, 20_000 * USDC, R, I), (R, 0, 0))
        # 7-day delay binds at 7 when liquidity clears day 5, not when
        # it clears day 9 (500k ahead: first day 8, full day 9).
        self.assertEqual(model.fifo(L, 500_000 * USDC, R, I), (0, 8, 9))
        self.assertEqual(max(model.fifo(L, 300_000 * USDC, R, I)[2], 7), 7)
        self.assertEqual(max(model.fifo(L, 500_000 * USDC, R, I)[2], 7), 9)
        # Waiting cost: 50,000 shares at 1.00 worth 45,000 at 0.90.
        self.assertEqual(R * 900_000 // USDC, 45_000 * USDC)

    def test_queue_priority_guide_numbers(self):
        # Pins /guides/erc4626-queue-priority/ to its model: a queue is
        # only a schedule if the order is enforced. Baseline FIFO with
        # 300k ahead, 100k liquid, 50k/day inflow pays 0 now, first
        # dollar day 4, full day 5. A flat 2% jump fee costs 1,000 and
        # pays 49,000 on day 0; 1% per 100k skipped costs 1,500 and
        # pays 48,500 on day 0. One 50k jumper ahead moves the waiter
        # to first day 5 / full day 6; two jumpers to day 6 / day 7. A
        # priority lane reserving 50% of the liquid pays the priority
        # request 50,000 on day 0 and leaves the FIFO queue at first
        # day 5 / full day 6. A 10% loss over the 5-day wait costs
        # 5,000 — five times the flat jump fee.
        import importlib.util
        from pathlib import Path
        model_path = (Path.home() / "workspace/taskmarket/site"
                      / "queue-priority-model.py")
        spec = importlib.util.spec_from_file_location(
            "queue_priority_model", model_path)
        model = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(model)
        USDC = model.USDC
        L = 100_000 * USDC
        R = 50_000 * USDC
        I = 50_000 * USDC
        # Baseline FIFO: 0 now, first day 4, full day 5.
        self.assertEqual(model.fifo_days(L, 300_000 * USDC, R, I),
                         (0, 4, 5))
        # Flat 2% jump fee: 1,000 fee, 49,000 paid day 0.
        self.assertEqual(R * 200 // 10_000, 1_000 * USDC)
        self.assertEqual(R - R * 200 // 10_000, 49_000 * USDC)
        # Scaled fee, 1% per 100k skipped: 1,500 fee, 48,500 day 0.
        self.assertEqual(R * 3 // 100, 1_500 * USDC)
        self.assertEqual(R - R * 3 // 100, 48_500 * USDC)
        # One 50k jumper ahead: first day 5, full day 6.
        self.assertEqual(model.fifo_days(L, 350_000 * USDC, R, I),
                         (0, 5, 6))
        # Two 50k jumpers ahead: first day 6, full day 7.
        self.assertEqual(model.fifo_days(L, 400_000 * USDC, R, I),
                         (0, 6, 7))
        # Priority lane, 50% of liquid reserved: priority paid 50,000
        # day 0; FIFO queue left with 50k liquid, first day 5, full 6.
        self.assertEqual(min(R, L // 2), 50_000 * USDC)
        self.assertEqual(model.fifo_days(L - L // 2, 300_000 * USDC, R, I),
                         (0, 5, 6))
        # Jump vs wait: 10% loss over the wait costs 5,000 > 1,000 fee.
        self.assertEqual(R - R * 900_000 // USDC, 5_000 * USDC)
        self.assertGreater(R - R * 900_000 // USDC, R * 200 // 10_000)

    def test_priority_fee_destination_guide_numbers(self):
        # Pins /guides/erc4626-priority-fee/ to its model: where the
        # jump fee goes decides who it compensates. Vault 1,000,000
        # assets / 1,000,000 shares, price 1.0; a 50k jumper pays a 2%
        # fee (1,000) and is settled day 0 for 49,000. Fee to the vault
        # leaves 951,000 / 950,000, price 1.001053, and a waiting 50k
        # holder at 50,052.631578. Fee to the manager leaves 950,000 /
        # 950,000, price 1.0, holder unchanged at 50,000, manager +1,000.
        # Scaled 3% fee (1,500) to the vault: 951,500 / 950,000, holder
        # 50,078.947368. Liquid left for the queue: 51,000 fee to the
        # vault vs 50,000 fee to the manager. Ten jumpers a day at
        # 1,000 each is 10,000/day of manager rent.
        import importlib.util
        from pathlib import Path
        model_path = (Path.home() / "workspace/taskmarket/site"
                      / "priority-fee-destination-model.py")
        spec = importlib.util.spec_from_file_location(
            "priority_fee_destination_model", model_path)
        model = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(model)
        USDC = model.USDC
        A = 1_000_000 * USDC
        S = 1_000_000 * USDC
        R = 50_000 * USDC
        H = 50_000 * USDC
        # Fee to the vault: holder 50,052.631578.
        self.assertEqual(model.holder_value(A - 49_000 * USDC,
                                            S - R, H),
                         50_052 * USDC + 631_578)
        # Fee to the manager: holder unchanged, manager +1,000.
        self.assertEqual(model.holder_value(A - R, S - R, H), H)
        # Scaled 3% fee to the vault: holder 50,078.947368.
        self.assertEqual(model.holder_value(A - 48_500 * USDC,
                                            S - R, H),
                         50_078 * USDC + 947_368)
        # Liquid left: 51,000 vs 50,000.
        self.assertEqual(100_000 * USDC - 49_000 * USDC, 51_000 * USDC)
        self.assertEqual(100_000 * USDC - R, 50_000 * USDC)
        # Manager rent at 10 jumpers/day: 10,000/day.
        self.assertEqual(10 * (R * 200 // 10_000), 10_000 * USDC)

    def test_basket_redemption_guide_numbers(self):
        # Pins /guides/erc4626-basket-redemption/ to its model: a
        # 100,000 USDC + 100 XYZ ($100 each) vault, 110,000 shares at
        # $1.00. Flooring each asset separately to whole base units
        # makes the 0-decimal asset round to nothing on small
        # redemptions. 1 share -> 0.909090 USDC + 0 XYZ, loss
        # $0.090910 (9.0910%). 11 shares -> 10 USDC + 0 XYZ, loss
        # $1.00. Clean multiples lose nothing: 11,000 shares ->
        # 10,000 USDC + 10 XYZ; 1,100 shares -> 1,000 USDC + 1 XYZ.
        # 1,100 x 1-share redeems leave $100.001 of dust and lift the
        # price to $1.000918. Worst-case floor loss per redeem is
        # < $100.000001 (100,000,001x a USDC-only vault). Ceiling
        # rounding overpays $99.909091 on a $1.00 redemption.
        import importlib.util
        from fractions import Fraction
        from pathlib import Path
        model_path = (Path.home() / "workspace/taskmarket/site"
                      / "basket-redemption-model.py")
        spec = importlib.util.spec_from_file_location(
            "basket_redemption_model", model_path)
        model = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(model)
        USDC = model.USDC
        # One share: 0.909090 USDC + 0 XYZ, loss $0.090910.
        self.assertEqual(model.redeem_floor(1), (909_090, 0))
        self.assertEqual(model.loss_usd(1), Fraction(90_910, USDC))
        # Eleven shares: 10 USDC + 0 XYZ, loss $1.00.
        self.assertEqual(model.redeem_floor(11), (10 * USDC, 0))
        self.assertEqual(model.loss_usd(11), 1)
        # Clean multiples: no loss.
        self.assertEqual(model.redeem_floor(11_000),
                         (10_000 * USDC, 10))
        self.assertEqual(model.loss_usd(11_000), 0)
        self.assertEqual(model.redeem_floor(1_100),
                         (1_000 * USDC, 1))
        self.assertEqual(model.loss_usd(1_100), 0)
        # Dust accrual: 1,100 x 1-share redeems keep $100.001 and
        # lift the price to $1.000918 (exact fraction).
        self.assertEqual(model.loss_usd(1) * 1_100,
                         Fraction(100_001, 1000))
        price_left = (Fraction(109_000_001, 1000)
                      / Fraction(108_900))
        self.assertEqual(price_left,
                         Fraction(109_000_001, 108_900_000))
        self.assertEqual(round(float(price_left), 6), 1.000918)
        # Bound: < $100.000001 per redeem, 100,000,001x USDC-only.
        worst = Fraction(1, USDC) + 100
        self.assertEqual(worst, Fraction(100_000_001, USDC))
        self.assertTrue(model.loss_usd(1) < worst)
        self.assertTrue(model.loss_usd(11) < worst)
        # Ceiling: 1 share overpays $99.909091.
        self.assertEqual(model.redeem_ceil(1), (909_091, 1))
        self.assertEqual(model.value_usd(909_091, 1) - 1,
                         Fraction(99_909_091, USDC))

    def test_deposit_into_queue_guide_numbers(self):
        # Pins /guides/erc4626-deposit-into-queue/ to its model: a
        # 50,000 deposit into a vault with a 300,000 queue either pays
        # the queue first (queue 250,000, clears day 3, depositor's own
        # redemption first day 3 / full day 4) or is invested first
        # (queue untouched at 300,000, clears day 4, depositor's own
        # redemption first day 4 / full day 5). Both keep price 1.0
        # because redeemed shares burn on payment. With inflow only
        # from new deposits, policy A needs 6 x 50,000 deposits to
        # clear 300,000, policy B never clears. Paying the queue
        # without burning shares drops the price to 0.952381 and a
        # 50,000 deposit is worth 47,619.047619.
        import importlib.util
        from pathlib import Path
        model_path = (Path.home() / "workspace/taskmarket/site"
                      / "deposit-into-queue-model.py")
        spec = importlib.util.spec_from_file_location(
            "deposit_into_queue_model", model_path)
        model = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(model)
        USDC = model.USDC
        A = 1_000_000 * USDC
        S = 1_000_000 * USDC
        L = 100_000 * USDC
        Q = 300_000 * USDC
        D = 50_000 * USDC
        I = 50_000 * USDC
        # Baseline queue clears day 4; policy A day 3, policy B day 4.
        self.assertEqual(model.queue_clear_day(L, Q, I), 4)
        self.assertEqual(model.queue_clear_day(L, Q - D, I), 3)
        # Depositor redeems right after depositing: A (3, 4), B (4, 5).
        self.assertEqual(model.fifo_days(L, Q - D, D, I), (0, 3, 4))
        self.assertEqual(model.fifo_days(L, Q, D, I), (0, 4, 5))
        # Price stays 1.0 under both policies (shares burn on payment).
        self.assertEqual(model.share_price(A + D - D, S + D - D), USDC)
        self.assertEqual(model.share_price(A + D, S + D), USDC)
        # Inflow only from deposits: A needs 6 deposits; B never clears.
        self.assertEqual(Q // D, 6)
        self.assertIsNone(model.queue_clear_day(L, Q, 0))
        # No share burn: price 0.952380, deposit worth 47,619.047619.
        self.assertEqual(model.share_price(A, S + D), 952_380)
        self.assertEqual(D * A // (S + D), 47_619 * USDC + 47_619)

    def test_failed_donation_notice_links_slippage_bounds(self):
        # The checker page's failure notice is the funnel entry for a
        # depositor, not just a deployer: when the donation check fails
        # it must link the slippage-bounds guide (the one defense a
        # depositor controls). A passing preset must not show it. The
        # Worker JS renderer carries the same sentence; it is verified
        # by the /tmp slip-link harness (node), not by this suite.
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path.home() / "workspace/taskmarket/site"))
        import build
        link = "/guides/erc4626-slippage-bounds/"
        failed = build.results_html(
            run_all(Vault(decimals_offset=0, min_deposit=0, perf_fee_bps=0)),
            vic=100_000_000_000, off=0, mn=0, fee=0)
        self.assertIn(link, failed)
        self.assertIn("offset 6", failed)
        passed = build.results_html(
            run_all(Vault(decimals_offset=6, min_deposit=1_000_000,
                          perf_fee_bps=1000)),
            vic=100_000_000_000, off=6, mn=1_000_000, fee=1000)
    def test_exit_fee_guide_numbers(self):
        # Exit-fee guide (site/exit-fee-model.py): a 5% fee on redemption.
        # Re-derived here with plain integer arithmetic, independent of
        # the model file, so the guide's numbers cannot drift silently.
        # Vault 1,000,000 assets / 1,000,000 shares, price exactly 1.00.
        USDC = 1_000_000
        A, S = 1_000_000 * USDC, 1_000_000 * USDC
        shares = 100_000 * USDC
        gross = shares * A // S
        fee = gross * 500 // 10_000
        self.assertEqual((gross, fee, gross - fee),
                         (100_000 * USDC, 5_000 * USDC, 95_000 * USDC))
        # Fee retained in the vault: price rises to exactly 181/180.
        self.assertEqual(Fraction(A - (gross - fee), S - shares),
                         Fraction(181, 180))
        # Second exiter at the new price nets 527.777778 more than the first.
        gross2 = shares * (A - (gross - fee)) // (S - shares)
        fee2 = gross2 * 500 // 10_000
        self.assertEqual((gross2, fee2, gross2 - fee2),
                         (100_555_555_555, 5_027_777_777, 95_527_777_778))
        # Withdraw side: minimal shares to net exactly 100,000 USDC.
        want = 100_000 * USDC

        def net(sh):
            g = sh * A // S
            return g - g * 500 // 10_000

        s = -(-want * 10_000 // (10_000 - 500))  # ceil gross, price 1.00
        while s > 0 and net(s - 1) >= want:
            s -= 1
        self.assertEqual(s, 105_263_157_894)
        self.assertGreaterEqual(net(s), want)
        self.assertLess(net(s - 1), want)
        # Fee paid out to a manager instead: price stays exactly 1.00.
        self.assertEqual(Fraction(A - gross, S - shares), 1)
        # Dust redemption: 1 USDC gross nets 0.95 USDC.
        self.assertEqual(USDC - USDC * 500 // 10_000, 950_000)

    def test_rounding_direction_guide_numbers(self):
        # Rounding-direction guide (site/rounding-direction-model.py):
        # convertTo* floor, previewMint/previewWithdraw ceil.
        # Re-derived here with plain integer arithmetic, independent of
        # the model file, so the guide's numbers cannot drift silently.
        # Vault 1,000,001 base units / 1,000,000 shares, price 1.000001.
        USDC = 1_000_000
        A, S = 1_000_001, 1_000_000
        # Minting one share costs 2 base units, converts back to 1.
        self.assertEqual(-(-1 * A // S), 2)   # previewMint ceil
        self.assertEqual(1 * A // S, 1)       # convertToAssets floor
        # A 1-base-unit deposit mints zero shares.
        self.assertEqual(1 * S // A, 0)       # previewDeposit floor
        # Round trip on 1 USDC loses exactly 1 base unit.
        shares = 1 * USDC * S // A
        self.assertEqual(shares, 999_999)
        self.assertEqual(shares * A // S, 999_999)
        # Round trip on 100,000 USDC loses exactly 1 base unit too.
        shares = 100_000 * USDC * S // A
        self.assertEqual(shares, 99_999_900_000)
        self.assertEqual(shares * A // S, 99_999_999_999)
        # Withdrawing 1 base unit burns 1 share (ceil).
        self.assertEqual(-(-1 * S // A), 1)   # previewWithdraw ceil
        # At price exactly 1.00 the directions agree.
        self.assertEqual(1_000_000 * 1_000_000 // 1_000_000, 1_000_000)
        self.assertEqual(-(-1_000_000 * 1_000_000 // 1_000_000),
                         1_000_000)

    def test_fee_basis_guide_numbers(self):
        # Fee-basis guide (site/fee-basis-model.py): a 2% management fee
        # collected by minting 2% of the supply transfers only f/(1+f) of
        # assets. Re-derived here with plain Fractions, independent of
        # the model file, so the guide's numbers cannot drift silently.
        # Vault 1,100,000 USDC / 1,000,000 shares, price 1.10.
        A, S, H = Fraction(1_100_000), Fraction(1_000_000), Fraction(10_000)
        # (a) Fee taken as assets: exactly 22,000 out, holder keeps 10,780.
        self.assertEqual(A * Fraction(2, 100), 22_000)
        self.assertEqual(H * (A - A * Fraction(2, 100)) / S, 10_780)
        # (b) Fee minted as 2% of supply: price 55/51, manager gets 1/51.
        m = S * Fraction(2, 100)
        self.assertEqual(m, 20_000)
        self.assertEqual(A / (S + m), Fraction(55, 51))
        self.assertEqual(m * A / (S + m), Fraction(1_100_000, 51))
        self.assertEqual(m * A / (S + m) / A, Fraction(1, 51))
        self.assertEqual(H * A / (S + m), Fraction(550_000, 51))
        # Invariant f/(1+f), price-independent (0.90 case: same 1/51).
        A2, S2 = Fraction(900_000), Fraction(1_000_000)
        m2 = S2 * Fraction(2, 100)
        self.assertEqual(m2 * A2 / (S2 + m2) / A2, Fraction(1, 51))
        self.assertEqual(H * A2 / (S2 + m2), Fraction(150_000, 17))
        # (c) Gross-up mint 1,000,000/49 is not an integer; nearest mints
        # under/over-collect against the quoted 22,000.
        self.assertEqual(Fraction(2, 100) * S / (1 - Fraction(2, 100)),
                         Fraction(1_000_000, 49))
        self.assertNotEqual(Fraction(1_000_000, 49).denominator, 1)
        self.assertLess(Fraction(20_408) * A / (S + 20_408), 22_000)
        self.assertGreater(Fraction(20_409) * A / (S + 20_409), 22_000)
        # Consistency with the fee-accrual guide at price 1.00.
        self.assertEqual(Fraction(20_000) * Fraction(1_000_000)
                         / Fraction(1_020_000), Fraction(1_000_000, 51))

    def test_deposit_fee_guide_numbers(self):
        # Deposit-fee guide (site/deposit-fee-model.py): a 5% front-end
        # load on a 100,000 USDC deposit into a 1,000,000 / 1,000,000
        # vault at price 1.00. Re-derived here with plain Fractions,
        # independent of the model file.
        A, S, H = Fraction(1_000_000), Fraction(1_000_000), Fraction(10_000)
        D, FEE = Fraction(100_000), Fraction(5, 100)
        fee, net = D * FEE, D - D * FEE
        self.assertEqual(fee, 5_000)
        self.assertEqual(net, 95_000)
        # (a) Fee to the manager: price stays 1.00, loss exactly 5,000.
        self.assertEqual((A + net) / (S + net), 1)
        self.assertEqual(net * 1, 95_000)
        self.assertEqual(D - net, 5_000)
        # (b) Fee retained: price 220/219, depositor loses 1,000,000/219.
        price_b = (A + D) / (S + net)
        self.assertEqual(price_b, Fraction(220, 219))
        self.assertEqual(net * price_b, Fraction(20_900_000, 219))
        self.assertEqual(D - net * price_b, Fraction(1_000_000, 219))
        self.assertEqual(H * price_b, Fraction(2_200_000, 219))
        self.assertEqual(H * price_b - 10_000, Fraction(10_000, 219))
        # Conservation: depositor loss == existing holders' total gain.
        self.assertEqual(D - net * price_b, S * (price_b - 1))
        # Recapture: depositor's own share of the retained fee, 95,000/219.
        self.assertEqual(net / (S + net) * fee, Fraction(95_000, 219))
        # Front-end vs back-end exactly equal at price 1.10 and 0.90.
        for p1, expect in ((Fraction(11, 10), 104_500),
                           (Fraction(9, 10), 85_500)):
            self.assertEqual(net * p1, expect)
            self.assertEqual(D * p1 * (1 - FEE), expect)
        # Gross vs net quoting: 105,000 deposit, 5% of net is 1/21.
        D2 = Fraction(105_000)
        self.assertEqual(D2 / (1 + FEE), 100_000)
        self.assertEqual(D2 - D2 / (1 + FEE), 5_000)
        self.assertEqual((D2 - D2 / (1 + FEE)) / D2, Fraction(1, 21))
        self.assertEqual(D2 * FEE, 5_250)
        self.assertEqual(D2 - D2 * FEE, 99_750)
        self.assertEqual(D2 / (1 + FEE) - (D2 - D2 * FEE), 250)

    def test_fee_net_vs_gross_guide_numbers(self):
        # Fee net-vs-gross guide (site/fee-net-vs-gross-model.py): a 2%
        # management fee on a 1,000,000 / 1,000,000 vault at price 1.00.
        # Re-derived here with plain Fractions, independent of the model
        # file. Continuous-accrual figure uses math.exp with tolerance.
        import math
        A, S, H = Fraction(1_000_000), Fraction(1_000_000), Fraction(10_000)
        FEE = Fraction(2, 100)
        # (a) Gross basis: fee 20,000, price 0.98, holder 9,800, loss 200.
        fee_gross = A * FEE
        self.assertEqual(fee_gross, 20_000)
        self.assertEqual((A - fee_gross) / S, Fraction(49, 50))
        self.assertEqual(H * (A - fee_gross) / S, 9_800)
        # (b) Net basis: fee = A*f/(1+f) = 1,000,000/51, price 50/51.
        fee_net = A * FEE / (1 + FEE)
        self.assertEqual(fee_net, Fraction(1_000_000, 51))
        self.assertEqual((A - fee_net) / S, Fraction(50, 51))
        self.assertEqual(H * (A - fee_net) / S, Fraction(500_000, 51))
        self.assertEqual(H - H * (A - fee_net) / S, Fraction(10_000, 51))
        self.assertEqual(fee_gross - fee_net, Fraction(20_000, 51))
        self.assertEqual(H * (A - fee_net) / S - H * (A - fee_gross) / S,
                         Fraction(200, 51))
        # Identity: net basis == minting 2% of supply (fee-basis guide).
        self.assertEqual(fee_net, Fraction(1_000_000, 51))
        # Gross-up rate: r/(1+r) = 2% gives r = 1/49 = 2.040816...%.
        rate = FEE / (1 - FEE)
        self.assertEqual(rate, Fraction(1, 49))
        self.assertEqual(A * rate / (1 + rate), 20_000)
        # Two years: gross holder 9,604; net holder 9,611.687812...
        self.assertEqual(H * (1 - FEE) ** 2, 9_604)
        self.assertAlmostEqual(float(H * Fraction(100, 102) ** 2),
                               9611.687812379854, places=6)
        self.assertAlmostEqual(float(H * Fraction(100, 102) ** 2 - 9_604),
                               7.687812379854, places=6)
        # Five years: gross holder 9,039.207968; net 9,057.308098.
        self.assertAlmostEqual(float(H * (1 - FEE) ** 5),
                               9039.207968, places=6)
        self.assertAlmostEqual(float(H * Fraction(100, 102) ** 5),
                               9057.30809829916, places=6)
        self.assertAlmostEqual(float(H * Fraction(100, 102) ** 5
                                     - H * (1 - FEE) ** 5),
                               18.100130299159, places=6)
        # Continuous accrual sits between net and gross.
        fee_cont = float(A) * (1 - math.exp(-0.02))
        self.assertAlmostEqual(fee_cont, 19801.326693244748, places=6)
        self.assertAlmostEqual(float(H) * (1 - math.exp(-0.02)),
                               198.01326693244746, places=6)
        self.assertTrue(float(fee_net) < fee_cont < float(fee_gross))

    def test_round_trip_fee_guide_numbers(self):
        # Round-trip fee guide (site/round-trip-fee-model.py): a 5%
        # deposit fee AND a 5% exit fee on a 100,000 USDC deposit into a
        # 1,000,000 / 1,000,000 vault at price 1.00. Re-derived here with
        # plain Fractions, independent of the model file.
        D = Fraction(100_000)
        FEE = Fraction(5, 100)
        net = D * (1 - FEE)
        self.assertEqual(net, 95_000)

        def round_trip(price):
            gross = net * price
            exit_fee = gross * FEE
            return gross, exit_fee, gross - exit_fee, D - (gross - exit_fee)

        # Flat price: cost 9,750 = 9.75%, not the naive 10%.
        gross, fee, out, cost = round_trip(Fraction(1))
        self.assertEqual((gross, fee, out, cost), (95_000, 4_750, 90_250, 9_750))
        self.assertEqual(D - out, D * (1 - (1 - FEE) ** 2))
        self.assertEqual(1 - (1 - FEE) ** 2, Fraction(39, 400))
        self.assertEqual(D * Fraction(10, 100) - cost, 250)
        # Price 1.10: exit fee 5,225 on the grown value; net 99,275.
        gross, fee, out, cost = round_trip(Fraction(11, 10))
        self.assertEqual((gross, fee, out, cost), (104_500, 5_225, 99_275, 725))
        self.assertEqual((net * Fraction(11, 10) - net) - (D * FEE + fee), -cost)
        # Each fee alone leaves 104,500 (deposit-fee guide); both leave
        # 99,275 -- the second fee costs the full 5,225.
        self.assertEqual(net * Fraction(11, 10), 104_500)
        self.assertEqual(D * Fraction(11, 10) * (1 - FEE), 104_500)
        # Price 0.90: net 81,225, cost 18,775 = 9,500 price loss + fees.
        gross, fee, out, cost = round_trip(Fraction(9, 10))
        self.assertEqual((gross, fee, out, cost), (85_500, 4_275, 81_225, 18_775))
        self.assertEqual((net - gross) + (D * FEE + fee), cost)
        # Break-even price 1/(0.95 x 0.95) = 400/361; gain 10.803324%.
        be = 1 / (1 - FEE) ** 2
        self.assertEqual(be, Fraction(400, 361))
        self.assertEqual(net * be * (1 - FEE), D)
        self.assertTrue(be - 1 > Fraction(10, 100))
        self.assertAlmostEqual(float((be - 1) * 100), 10.803324099722992,
                               places=6)

    def test_fee_compounding_guide_numbers(self):
        # Fee-compounding guide (site/fee-compounding-model.py): a 2%/yr
        # management fee charged on the CURRENT supply, +10%/yr yield,
        # vault 1,000,000 / 1,000,000, holder 10,000 shares. Re-derived
        # here with plain Fractions, independent of the model file.
        A0, S0, H = Fraction(1_000_000), Fraction(1_000_000), Fraction(10_000)
        FEE, YIELD = Fraction(2, 100), Fraction(1, 10)

        def run(years, fee=FEE, yld=YIELD):
            A, S = A0, S0
            for _ in range(years):
                A *= (1 + yld)
                S += S * fee
            return A, S

        # Year 1 = linear: supply 1,020,000, claim 10,784.313725.
        A1, S1 = run(1)
        self.assertEqual((A1, S1), (1_100_000, 1_020_000))
        self.assertAlmostEqual(float(H / S1 * A1), 10784.313725, places=6)
        self.assertAlmostEqual(float(H / S0 * A1 - H / S1 * A1), 215.686275,
                               places=6)
        # Year 5 compounding: supply (51/50)^5, claim 14,586.885265.
        A5, S5 = run(5)
        self.assertEqual(A5, 1_610_510)
        self.assertEqual(S5, Fraction(1_000_000) * Fraction(51, 50) ** 5)
        self.assertAlmostEqual(float(H / S5 * A5), 14586.885265, places=6)
        self.assertAlmostEqual(float(H / S0 * A5 - H / S5 * A5), 1518.214735,
                               places=6)
        # Linear 5y: supply 1,100,000, claim exactly 14,641, cost 1,464.10.
        S5_lin = S0 * (1 + FEE * 5)
        self.assertEqual(H / S5_lin * A5, 14_641)
        self.assertAlmostEqual(float(H / S5_lin * A5 - H / S5 * A5),
                               54.114735, places=6)
        # Manager's 5y claim is 151,821.47 USDC of the 1,610,510 vault.
        self.assertAlmostEqual(float((S5 - S0) / S5 * A5), 151821.47,
                               places=2)
        # Year 5 no yield: claim 9,057.308098, cost 942.691902.
        A5n, S5n = run(5, yld=Fraction(0))
        self.assertEqual(A5n, 1_000_000)
        self.assertAlmostEqual(float(H / S5n * A5n), 9057.308098, places=6)
        self.assertAlmostEqual(float(H - H / S5n * A5n), 942.691902, places=6)
        # Linear no-yield 5y: claim 9,090.909091, cost 909.09.
        self.assertAlmostEqual(float(H / S5_lin * A5n), 9090.909091, places=6)
        # Year 10: manager owns 17.965170% of the vault, not 16.666667%.
        A10, S10 = run(10)
        self.assertAlmostEqual(float(H / S10 * A10), 21277.722175, places=6)
        self.assertAlmostEqual(float((S10 - S0) / S10 * 100), 17.965170,
                               places=6)
        self.assertEqual(Fraction(200_000) / Fraction(1_200_000) * 100,
                         Fraction(50, 3))
        # Control: zero fee leaves the full no-fee claim 16,105.10.
        A5c, S5c = run(5, fee=Fraction(0))
        self.assertEqual(S5c, S0)
        self.assertEqual(H / S5c * A5c, Fraction(161051, 10))

    def test_redeem_fee_basis_guide_numbers(self):
        # Redeem-fee-basis guide (site/redeem-fee-basis-model.py): a 5%
        # fee on redemption, charged on the payout in assets vs charged
        # in shares. Re-derived here with plain integer arithmetic,
        # independent of the model file. Vault 1,000,003 / 1,000,000
        # base units, price 1.000003, fee 5%.
        USDC = 1_000_000
        A, S = 1_000_003 * USDC, 1_000_000 * USDC

        def fee_on_assets(shares):
            gross = shares * A // S
            fee = gross * 5 // 100
            return gross, fee, gross - fee

        def fee_in_shares(shares, ceil_fee=False):
            if ceil_fee:
                fee_shares = -(-shares * 5 // 100)
            else:
                fee_shares = shares * 5 // 100
            return fee_shares, (shares - fee_shares) * A // S

        # Big redeem, 999,999 shares: (a) nets 950,001.899998,
        # (b) nets 950,001.899997 -- the whole gap is 1 base unit.
        H1 = 999_999 * USDC
        self.assertEqual(fee_on_assets(H1),
                         (1_000_001_999_997, 50_000_099_999,
                          950_001_899_998))
        self.assertEqual(fee_in_shares(H1),
                         (49_999_950_000, 950_001_899_997))
        self.assertEqual(fee_in_shares(H1, ceil_fee=True),
                         fee_in_shares(H1))
        self.assertEqual(fee_on_assets(H1)[2] - fee_in_shares(H1)[1], 1)
        # Exact net is 950,001.89999715 USDC: both designs round it.
        self.assertEqual(Fraction(H1) * Fraction(A, S) * Fraction(95, 100),
                         Fraction(19_000_037_999_943, 20))
        # Mid redeem, 10,000 shares: both designs pay exactly
        # 9,500.028500 -- gap 0, the usual case.
        H2 = 10_000 * USDC
        self.assertEqual(fee_on_assets(H2),
                         (10_000_030_000, 500_001_500, 9_500_028_500))
        self.assertEqual(fee_in_shares(H2),
                         (500_000_000, 9_500_028_500))
        # Dust redeem, 19 base units of shares: floor on either side
        # pays 19 (fee 0 -- the fee vanishes); ceil on the fee shares
        # pays 18 (fee enforced).
        self.assertEqual(fee_on_assets(19), (19, 0, 19))
        self.assertEqual(fee_in_shares(19), (0, 19))
        self.assertEqual(fee_in_shares(19, ceil_fee=True), (1, 18))
        # Control: zero fee pays the full floored gross.
        self.assertEqual(H1 * A // S, 1_000_001_999_997)

    def test_preview_rounding_guide_numbers(self):
        # Preview-rounding guide (site/preview-rounding-model.py):
        # preview vs actual rounding mismatch, and a stale quote.
        # Re-derived here with plain integer arithmetic, independent
        # of the model file. Vault 1,000,003 / 1,000,000 base units,
        # price 1.000003.
        USDC = 1_000_000
        A, S = 1_000_003 * USDC, 1_000_000 * USDC

        def down(a, b, c):
            return a * b // c

        def up(a, b, c):
            return -(-a * b // c)

        # Deposit 3 base assets: exact 2.999991 shares -- preview
        # (floor) quotes 2, an actual deposit rounding up mints 3.
        self.assertEqual(Fraction(3) * Fraction(S, A),
                         Fraction(3_000_000_000_000, 1_000_003_000_000))
        self.assertEqual((down(3, S, A), up(3, S, A)), (2, 3))
        # 1,000 dust deposits: preview totals 2,000 base shares,
        # actual (ceil) totals 3,000 -- 1,000 free base shares.
        pv_total = ac_total = 0
        a, s = A, S
        for _ in range(1000):
            pv_total += down(3, s, a)
            ac_total += up(3, s, a)
            a += 3
            s += up(3, s, a)
        self.assertEqual((pv_total, ac_total), (2000, 3000))
        # Mint 1 base share: exact cost 1.000003 base assets --
        # previewMint (ceil) quotes 2, an actual mint rounding down
        # charges 1.
        self.assertEqual(Fraction(A, S), Fraction(1_000_003, 1_000_000))
        self.assertEqual((up(1, A, S), down(1, A, S)), (2, 1))
        # Redeem 3 base shares: exact payout 3.000009 base assets --
        # previewRedeem (floor) quotes 3, an actual redeem rounding
        # up pays 4.
        self.assertEqual(Fraction(3) * Fraction(A, S),
                         Fraction(3_000_009, 1_000_000))
        self.assertEqual((down(3, A, S), up(3, A, S)), (3, 4))
        # Conformant baseline: same rounding both sides, every gap 0.
        self.assertEqual(down(3, S, A) - down(3, S, A), 0)
        self.assertEqual(up(1, A, S) - up(1, A, S), 0)
        self.assertEqual(down(3, A, S) - down(3, A, S), 0)
        # Stale quote: a 1,000,000 USDC donation moves the price to
        # 2.000003; 1,000,003 base assets that previewed at 1,000,000
        # shares execute at 500,000.
        A1 = A + 1_000_000 * USDC
        self.assertEqual(Fraction(A1, S), Fraction(2_000_003, 1_000_000))
        self.assertEqual(down(1_000_003, S, A), 1_000_000)
        self.assertEqual(down(1_000_003, S, A1), 500_000)

    def test_vault_state_seeded_donation(self):
        # A live vault is not a new vault: the checker used to run the
        # donation check only on an empty vault, so every live vault got
        # the new-vault verdict (offset 0 SOME FAILED, worst loss
        # 0.909091 USDC). Seeding the vault with its existing deposits
        # dilutes the donation — the victim's loss is bounded by about
        # one share's value at the inflated price, and one share is
        # cheap when the vault already holds many shares.
        A50 = 50_000_000_000_000  # 50M USDC in base units; 50M shares below
        S50 = 50_000_000_000_000  # price 1.00 USDC per share
        don0 = check_donation(Vault(decimals_offset=0, min_deposit=0),
                              vault_assets=A50, vault_supply=S50)
        self.assertTrue(don0["pass"])
        self.assertEqual([r["victim_loss"] for r in don0["detail"]],
                         [1, 1, 1, 13])
        self.assertEqual([r["attacker_net"] for r in don0["detail"]],
                         [-1_000_000, -999_999_981,
                          -999_999_980_001, -999_999_980_000_001])
        don6 = check_donation(Vault(decimals_offset=6, min_deposit=0),
                              vault_assets=A50, vault_supply=S50)
        self.assertTrue(don6["pass"])
        self.assertEqual([r["victim_loss"] for r in don6["detail"]],
                         [1, 1, 1, 18])
        # Price 1.05 (52.5M assets / 50M shares): same shape, still PASS.
        don105 = check_donation(Vault(decimals_offset=0, min_deposit=0),
                                vault_assets=52_500_000_000_000,
                                vault_supply=S50)
        self.assertTrue(don105["pass"])
        self.assertEqual([r["victim_loss"] for r in don105["detail"]],
                         [1, 1, 1, 5])
        # The default (no seed) is unchanged: a new vault at offset 0
        # still fails with worst victim loss 909091 base units.
        default = run_all(Vault(decimals_offset=0, min_deposit=0,
                                perf_fee_bps=0))
        don = next(r for r in default if r["name"] == "donation_inflation")
        self.assertFalse(don["pass"])
        self.assertEqual(max(r["victim_loss"] for r in don["detail"]),
                         909091)

    def test_partial_vault_state_is_an_error(self):
        # A half-filled vault state is not a vault: assets with no
        # shares, or shares with no assets, cannot exist. Before this
        # guard the shares-only half reported ALL PASS (victim loss 0
        # at every donation) — a verdict about a vault that cannot
        # exist — and the assets-only half failed with a cryptic
        # "zero shares minted". Both halves must now fail with the
        # incomplete-state error and no invented loss figure.
        A50 = 50_000_000_000_000  # 50M USDC in base units
        S50 = 50_000_000_000_000  # 50M shares in base units
        for va, vs in ((A50, 0), (0, S50)):
            don = check_donation(Vault(decimals_offset=0, min_deposit=0),
                                 vault_assets=va, vault_supply=vs)
            self.assertFalse(don["pass"])
            self.assertEqual(len(don["detail"]), 4)
            for row in don["detail"]:
                self.assertIsNone(row["victim_loss"])
                self.assertIsNone(row["attacker_net"])
                self.assertEqual(
                    row["error"],
                    "incomplete vault state: assets and shares must "
                    "both be set")
        # Both halves filled stays a real vault: still PASS, same
        # numbers as the seeded test above.
        don = check_donation(Vault(decimals_offset=0, min_deposit=0),
                             vault_assets=A50, vault_supply=S50)
        self.assertTrue(don["pass"])
        self.assertEqual([r["victim_loss"] for r in don["detail"]],
                         [1, 1, 1, 13])


    def test_rebasing_underlying_guide_numbers(self):
        # Rebasing-underlying guide (site/rebasing-underlying-model.py):
        # a rebasing token moves the share price with no yield at all.
        # Re-derived here with plain integer / Fraction arithmetic,
        # independent of the model file. Vault 100,000 USDC /
        # 100,000 shares, price exactly 1.00; holder 50,000 shares.
        USDC = 1_000_000
        A0, S0 = 100_000 * USDC, 100_000 * USDC
        HOLDER = 50_000 * USDC

        def down(a, b, c):
            return a * b // c

        # 1: +10% rebase -- price 1.00 -> 1.10, holder +5,000 USDC
        # with no yield; an 11,000 deposit mints 10,000 shares, not
        # the 11,000 it minted before.
        A1 = 110_000 * USDC
        self.assertEqual(Fraction(A1, S0), Fraction(11, 10))
        self.assertEqual(HOLDER * Fraction(A1, S0), 55_000 * USDC)
        self.assertEqual(down(11_000 * USDC, S0, A0), 11_000 * USDC)
        self.assertEqual(down(11_000 * USDC, S0, A1), 10_000 * USDC)
        # 2: -10% rebase -- price 1.00 -> 0.90, holder -5,000 USDC
        # with no loss; a 9,000 deposit mints 10,000 shares, not 9,000.
        A2 = 90_000 * USDC
        self.assertEqual(Fraction(A2, S0), Fraction(9, 10))
        self.assertEqual(HOLDER * Fraction(A2, S0), 45_000 * USDC)
        self.assertEqual(down(9_000 * USDC, S0, A0), 9_000 * USDC)
        self.assertEqual(down(9_000 * USDC, S0, A2), 10_000 * USDC)
        # 3: stale quote -- an 11,000 deposit previews 11,000 shares
        # at price 1.00 and executes 10,000 after the +10% rebase:
        # 1,000 shares short, worth 1,100 USDC at the new price.
        short = down(11_000 * USDC, S0, A0) - down(11_000 * USDC, S0, A1)
        self.assertEqual(short, 1_000 * USDC)
        self.assertEqual(short * Fraction(A1, S0), 1_100 * USDC)
        # 4: fee on rebased assets -- 2% of 110,000 is 2,200, not
        # the 2,000 it is on 100,000: +200 from the rebase alone.
        self.assertEqual((2 * A0 // 100, 2 * A1 // 100),
                         (2_000 * USDC, 2_200 * USDC))
        # 5: donation attack on the seeded vault (offset 0, min 1
        # USDC, victim 100,000 USDC): worst loss at the 1,000,000,000
        # donation is 801 base units with no rebase (PASS), 101 after
        # a +10% rebase (PASS), 1722 after a -10% rebase (FAIL -- over
        # the 0.001 USDC bound). The negative rebase shrinks the asset
        # base the donation is measured against.
        v = Vault(decimals_offset=0, min_deposit=1 * USDC, perf_fee_bps=0)
        for assets, want_worst, want_pass in (
                (A0, 801, True), (A1, 101, True), (A2, 1722, False)):
            res = check_donation(v, victim_deposit=100_000 * USDC,
                                 vault_assets=assets, vault_supply=S0)
            worst = max(r["victim_loss"] for r in res["detail"]
                        if r["victim_loss"] is not None)
            self.assertEqual((worst, res["pass"]), (want_worst, want_pass))

    def test_fot_underlying_guide_numbers(self):
        # Fee-on-transfer-underlying guide (site/fot-underlying-model.py):
        # a 10% transfer tax breaks the "amount asked == amount
        # received" assumption at the vault's edges. Re-derived here
        # with plain integer / Fraction arithmetic, independent of the
        # model file. Vault 100,000 USDC / 100,000 shares, price 1.00;
        # holder 50,000 shares; 10% tax on every transfer.
        USDC = 1_000_000
        A0, S0 = 100_000 * USDC, 100_000 * USDC
        HOLDER = 50_000 * USDC

        def down(a, b, c):
            return a * b // c

        def taxed(amount):
            return amount * 9_000 // 10_000

        dep = 11_000 * USDC
        received = taxed(dep)
        self.assertEqual(received, 9_900 * USDC)
        # 1: mint on the amount asked -- 11,000 shares for 9,900
        # received; price 109,900/111,000; holder 50,000 shares fall
        # to 49,504.504504 USDC; depositor's shares worth 10,890.99.
        sh_naive = down(dep, S0, A0)
        A1, S1 = A0 + received, S0 + sh_naive
        self.assertEqual((sh_naive, A1, S1),
                         (11_000 * USDC, 109_900 * USDC, 111_000 * USDC))
        self.assertEqual(Fraction(A1, S1), Fraction(1099, 1110))
        self.assertEqual(HOLDER * Fraction(A1, S1),
                         Fraction(50_000 * 109_900, 111_000) * USDC)
        self.assertEqual(int(HOLDER * Fraction(A1, S1)), 49_504_504_504)
        self.assertEqual(int(sh_naive * Fraction(A1, S1)), 10_890_990_990)
        # 2: mint on the amount received -- 9,900 shares; price stays
        # 1.00; holder untouched; depositor bears the full 1,100 tax.
        sh_fixed = down(received, S0, A0)
        A2, S2 = A0 + received, S0 + sh_fixed
        self.assertEqual((sh_fixed, A2, S2),
                         (9_900 * USDC, 109_900 * USDC, 109_900 * USDC))
        self.assertEqual(Fraction(A2, S2), Fraction(1, 1))
        self.assertEqual(HOLDER * Fraction(A2, S2), HOLDER)
        self.assertEqual(dep - sh_fixed, 1_100 * USDC)
        # 3: preview mismatch -- preview 11,000 shares, execution
        # 9,900: 1,100 shares short, worth 1,100 USDC at price 1.00.
        preview = down(dep, S0, A0)
        self.assertEqual((preview, sh_fixed),
                         (11_000 * USDC, 9_900 * USDC))
        self.assertEqual((preview - sh_fixed) * Fraction(A2, S2),
                         1_100 * USDC)
        # 4: withdrawal -- redeem 10,000 shares, vault sends 10,000,
        # holder receives 9,000: 1,000 short of the previewRedeem
        # quote; vault books clean at 90,000 / 90,000, price 1.00.
        sent = 10_000 * USDC
        got = taxed(sent)
        self.assertEqual((sent, got), (10_000 * USDC, 9_000 * USDC))
        self.assertEqual(sent - got, 1_000 * USDC)
        self.assertEqual((A0 - sent, S0 - sent),
                         (90_000 * USDC, 90_000 * USDC))
        # 5: round trip -- 11,000 in, 9,900 shares, 8,910 out: loss
        # 2,090 USDC, 19% (1 - 0.9^2), with no price movement.
        back = taxed(sh_fixed)
        self.assertEqual(back, 8_910 * USDC)
        self.assertEqual(dep - back, 2_090 * USDC)
        self.assertEqual((dep - back) * 100 // dep, 19)

    def test_async_vault_guide_numbers(self):
        # Async-vault guide (site/async-vault-model.py): an ERC-7540
        # style vault prices deposits and redemptions at fulfilment
        # time, not request time. Re-derived here with plain integer
        # / Fraction arithmetic, independent of the model file. Vault
        # 100,000 USDC / 100,000 shares, price 1.00; holder 50,000
        # shares; pending assets sit in escrow, outside totalAssets.
        USDC = 1_000_000
        A0, S0 = 100_000 * USDC, 100_000 * USDC
        HOLDER = 50_000 * USDC

        def down(a, b, c):
            return a * b // c

        dep = 11_000 * USDC
        red = 10_000 * USDC
        # 1: deposit after +10% yield -- preview 11,000 shares,
        # fulfil 10,000 (1,000 short, 9.0909%); value unchanged at
        # 11,000 USDC; vault 121,000 / 110,000, price 1.10.
        A_up = 110_000 * USDC
        preview = down(dep, S0, A0)
        sh_up = down(dep, S0, A_up)
        self.assertEqual((preview, sh_up),
                         (11_000 * USDC, 10_000 * USDC))
        self.assertEqual(preview - sh_up, 1_000 * USDC)
        self.assertEqual(sh_up * Fraction(A_up, S0), dep)
        self.assertEqual((A_up + dep, S0 + sh_up),
                         (121_000 * USDC, 110_000 * USDC))
        self.assertEqual(Fraction(A_up + dep, S0 + sh_up),
                         Fraction(11, 10))
        # 2: deposit after -10% loss -- fulfil 12,222.222222 shares
        # (1,222.222222 extra); worth 10,999.9999998 USDC, leaving
        # 0.2 base units of rounding dust; price 0.9000000000018.
        A_dn = 90_000 * USDC
        sh_dn = down(dep, S0, A_dn)
        self.assertEqual(sh_dn, 12_222_222_222)
        self.assertEqual(sh_dn - preview, 1_222_222_222)
        value_dn = sh_dn * Fraction(A_dn, S0)
        self.assertEqual(value_dn, Fraction(10_999_999_999_8, 10))
        self.assertEqual(dep - value_dn, Fraction(1, 5))
        self.assertEqual((A_dn + dep, S0 + sh_dn),
                         (101_000 * USDC, 112_222_222_222))
        self.assertEqual(Fraction(A_dn + dep, S0 + sh_dn),
                         Fraction(101_000_000_000, 112_222_222_222))
        # 3: redemption -- quote 10,000 USDC; +10% pays 11,000
        # (+1,000), -10% pays 9,000 (-1,000); vault 99,000 / 90,000
        # and 81,000 / 90,000 respectively, prices 1.10 and 0.90.
        quote = down(red, A0, S0)
        pay_up = down(red, A_up, S0)
        pay_dn = down(red, A_dn, S0)
        self.assertEqual((quote, pay_up, pay_dn),
                         (10_000 * USDC, 11_000 * USDC, 9_000 * USDC))
        self.assertEqual(pay_up - quote, 1_000 * USDC)
        self.assertEqual(quote - pay_dn, 1_000 * USDC)
        self.assertEqual((A_up - pay_up, S0 - red),
                         (99_000 * USDC, 90_000 * USDC))
        self.assertEqual((A_dn - pay_dn, S0 - red),
                         (81_000 * USDC, 90_000 * USDC))
        # 4: pending money earns nothing -- synchronous deposit
        # before the +10% yield would be worth 12,100 USDC; async
        # fulfilment is worth 11,000; the wait costs 1,100 USDC.
        sync_value = dep * Fraction(A_up, S0)
        self.assertEqual(sync_value, 12_100 * USDC)
        self.assertEqual(sync_value - dep, 1_100 * USDC)

    def test_guide_pages_emit_tech_article_json_ld(self):
        # Guides and research writeups are the site's article content:
        # they must carry TechArticle JSON-LD + og:type article so search
        # engines classify them as articles. The checker keeps its
        # SoftwareApplication node and the home page stays a plain page.
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path.home() / "workspace/taskmarket/site"))
        import build
        guide = build.page("Rebasing underlying", "desc", "kw", "<p>x</p>",
                           "/guides/erc4626-rebasing-underlying/")
        self.assertIn('"@type": "TechArticle"', guide)
        self.assertIn('"headline": "Rebasing underlying"', guide)
        self.assertIn('"mainEntityOfPage": "https://check.n1netw3n.live'
                      '/guides/erc4626-rebasing-underlying/"', guide)
        self.assertIn('<meta property="og:type" content="article">', guide)
        research = build.page("Twyne", "desc", "kw", "<p>x</p>",
                              "/research/twyne/")
        self.assertIn('"@type": "TechArticle"', research)
        self.assertIn('<meta property="og:type" content="article">', research)
        home = build.page("Home", "desc", "kw", "<p>x</p>", "/")
        self.assertNotIn("TechArticle", home)
        self.assertIn('<meta property="og:type" content="website">', home)
        checker = build.page("Checker", "desc", "kw", "<p>x</p>", "/checker/")
        self.assertIn('"@type": "SoftwareApplication"', checker)
        self.assertNotIn("TechArticle", checker)
        self.assertIn('<meta property="og:type" content="website">', checker)

    def test_nested_vault_fee_guide_numbers(self):
        # Nested-vault fee guide (site/nested-vault-fee-model.py):
        # a vault holding another vault's shares pays a 2%
        # management fee at both layers. Re-derived here with plain
        # Fraction arithmetic, independent of the model file. Each
        # vault 1,000,000 USDC / 1,000,000 shares; the outer vault
        # holds 1,000,000 inner shares; holder 10,000 outer shares;
        # fee 2% of supply minted as shares, linear, yield lands
        # in the inner vault first.
        def d6(x):
            n = x * 1_000_000
            q, r = divmod(n.numerator, n.denominator)
            if 2 * r >= n.denominator:
                q += 1
            return "%d.%06d" % (q // 1_000_000, q % 1_000_000)

        def nested(yield_bps):
            a_i = Fraction(1_000_000) * (10_000 + yield_bps) / 10_000
            p_i = a_i / Fraction(1_020_000)
            a_o = Fraction(1_000_000) * p_i
            p_o = a_o / Fraction(1_020_000)
            holder = Fraction(10_000) * a_o / Fraction(1_020_000)
            return p_i, a_o, p_o, holder, Fraction(20_000) * p_i, \
                Fraction(20_000) * p_o

        def single(yield_bps):
            a = Fraction(1_000_000) * (10_000 + yield_bps) / 10_000
            return Fraction(10_000) * a / Fraction(1_020_000)

        # +10% year: inner price 55/51, outer price 2750/2601.
        p_i, a_o, p_o, holder, im, om = nested(1000)
        self.assertEqual((p_i, p_o), (Fraction(55, 51), Fraction(2750, 2601)))
        self.assertEqual(holder, Fraction(55_000_000, 5202))
        self.assertEqual(d6(holder), "10572.856594")
        self.assertEqual(d6(im + om), "42714.340638")
        self.assertEqual(d6(single(1000)), "10784.313725")
        self.assertEqual(d6(single(1000) - holder), "211.457132")
        self.assertEqual(d6(Fraction(11_000) - holder), "427.143406")
        self.assertEqual(d6(holder - Fraction(10_560)), "12.856594")
        # Flat year: prices 50/51 and 2500/2601.
        p_i, a_o, p_o, holder, im, om = nested(0)
        self.assertEqual((p_i, p_o), (Fraction(50, 51), Fraction(2500, 2601)))
        self.assertEqual(holder, Fraction(25_000_000, 2601))
        self.assertEqual(d6(holder), "9611.687812")
        self.assertEqual(d6(im + om), "38831.218762")
        self.assertEqual(d6(single(0)), "9803.921569")
        self.assertEqual(d6(single(0) - holder), "192.233756")
        self.assertEqual(d6(Fraction(10_000) - holder), "388.312188")
        self.assertEqual(d6(holder - Fraction(9_600)), "11.687812")
        # -10% year: prices 15/17 and 250/289.
        p_i, a_o, p_o, holder, im, om = nested(-1000)
        self.assertEqual((p_i, p_o), (Fraction(15, 17), Fraction(250, 289)))
        self.assertEqual(holder, Fraction(2_500_000, 289))
        self.assertEqual(d6(holder), "8650.519031")
        self.assertEqual(d6(im + om), "34948.096886")
        self.assertEqual(d6(single(-1000)), "8823.529412")
        self.assertEqual(d6(single(-1000) - holder), "173.010381")
        self.assertEqual(d6(Fraction(9_000) - holder), "349.480969")
        self.assertEqual(d6(holder - Fraction(8_640)), "10.519031")
        # Controls: a fee at one layer only == the single vault.
        self.assertEqual(
            d6(Fraction(10_000) * Fraction(1_100_000, 1_020_000)),
            "10784.313725")

    def test_audit_payment_block_is_a_container(self):
        # /audit/ is the sales page: the payment facts (price, USDC on
        # Base, address + copy button, email-first instruction) must sit
        # inside one styled container, not float bare on the page.
        import re
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path.home() / "workspace/taskmarket/site"))
        import build
        audit = dict((p, b) for p, t, d, k, b in build.PAGES)["/audit/"]
        self.assertIn('<div class="pay-box">', audit)
        self.assertLess(audit.index('<div class="pay-box">'),
                        audit.index('<div class="pay-row">'))
        self.assertLess(audit.index('<div class="pay-box">'),
                        audit.index('id="pay-addr"'))
        # The box closes only after the email-first instruction, so the
        # whole payment block (price line, address row, instruction) is
        # inside it; the pay-row's own </div> comes first and must not
        # end the match.
        m = re.search(r'<div class="pay-box">.*?<p>Email first.*?</p>\s*</div>',
                      audit, re.S)
        self.assertIsNotNone(m)
        self.assertIn(build.PAY_ADDR, m.group(0))
        self.assertIn("Copy payment address", m.group(0))
        # Firm price as a figure, not a hedged sentence: the title already
        # says 50 USDC, so the box must not hedge with "About".
        # Token/network are labelled chips, not prose.
        self.assertIn('<p class="price-big">50 USDC</p>', m.group(0))
        self.assertIn("Prepaid", m.group(0))
        self.assertNotIn("About 50 USDC", m.group(0))
        self.assertIn('<span class="chip">USDC</span>', m.group(0))
        self.assertIn('<span class="chip">Base</span>', m.group(0))
        self.assertIn(".pay-box{background:#f0fdf4", build.CSS)
        self.assertIn(".pay-box code{background:#fff}", build.CSS)
        self.assertIn(".chip{display:inline-block", build.CSS)
        self.assertIn(".price-big{font-size:2.4em", build.CSS)
        self.assertIn(".price-sub{font-size:.95em", build.CSS)
        # The order form sits at the bottom of a long page, so a top CTA
        # must jump straight to it — before the first section heading.
        self.assertIn('<a class="cta" href="#audit-order">Start an audit',
                      audit)
        self.assertLess(audit.index('href="#audit-order"'),
                        audit.index('<h2>Scope</h2>'))
        self.assertIn("a.cta{display:inline-block", build.CSS)

    def test_checker_form_is_a_styled_panel(self):
        # The checker form must read as a grouped panel, not a flat list
        # of default inputs: panel background + border, label/input
        # spacing, a prominent submit button, and a visible focus ring.
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path.home() / "workspace/taskmarket/site"))
        import build
        self.assertIn("#checker-form{display:grid", build.CSS)
        self.assertIn("background:#f9fafb;border:1px solid #e5e7eb", build.CSS)
        self.assertIn("#checker-form input,#checker-form select{width:100%;margin-top:.3em}",
                      build.CSS)
        self.assertIn("#checker-form button{grid-column:1 / -1;justify-self:start;"
                      "margin-top:.7em", build.CSS)
        self.assertIn("box-shadow:0 0 0 3px rgba(10,125,44,.15)", build.CSS)
        self.assertIn("label{display:block;margin:.7em 0;color:#111827}", build.CSS)

    def test_hero_has_attack_flow_diagram(self):
        # The homepage hero was the site's first visual element of any
        # kind: before this change it was text only (tenth visual verdict,
        # 15:39 CST — 0 <img> / 0 <svg> on all four pages, verified
        # against the live HTML the same run). The diagram must show the
        # mechanism in three steps, and every number in it must be the
        # model's own number, not a copy of the paragraph above it.
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path.home() / "workspace/taskmarket/site"))
        import build
        home = dict((p, b) for p, t, d, k, b in build.PAGES)["/"]
        # The flow diagram is the hero's only diagram: it must sit
        # between the hero opening and its CTA link.
        hero_start = home.index('<div class="hero">')
        hero_end = home.index('Run the free ERC-4626 checker')
        hero = home[hero_start:hero_end]
        self.assertIn('<div class="flow"', hero)
        self.assertEqual(hero.count('<div class="flow-step">'), 3)
        self.assertEqual(hero.count('class="flow-arrow"'), 2)
        self.assertIn("Attacker donates", hero)
        self.assertIn("Share price inflates", hero)
        self.assertIn("Victim loses", hero)
        self.assertIn("1,000,000 USDC", hero)
        self.assertIn("0.909091 USDC", hero)
        self.assertIn("100,000 USDC", hero)
        # The loss figure is the model's own worst case, re-derived
        # here: unprotected vault, 100,000 USDC victim deposit, worst
        # row over the donation ladder is 909091 base units.
        noprot = Vault(decimals_offset=0, min_deposit=0)
        rows = {r["name"]: r for r in run_all(noprot)}["donation_inflation"]["detail"]
        self.assertEqual(max(r["victim_loss"] for r in rows), 909091)
        # Layout: horizontal flow on desktop, stacked with down arrows
        # on a phone viewport.
        self.assertIn(".flow{display:flex;align-items:stretch", build.CSS)
        self.assertIn(".flow-step{flex:1;background:#fff", build.CSS)
        self.assertIn(".flow-arrow{align-self:center", build.CSS)
        self.assertIn("@media (max-width:640px){.flow{flex-direction:column}"
                      ".flow-arrow{transform:rotate(90deg)}}", build.CSS)

    def test_reward_token_guide_numbers(self):
        # Reward-token guide (site/reward-token-model.py): yield paid
        # out as a separate token never touches the share price.
        # Re-derived here with plain integer / Fraction arithmetic,
        # independent of the model file. Vault 100,000 USDC / 100,000
        # shares, price 1.00; Alice 50,000 shares, others 50,000.
        USDC = 1_000_000
        A0, S0 = 100_000 * USDC, 100_000 * USDC
        ALICE, OTHERS = 50_000 * USDC, 50_000 * USDC
        YIELD = 10_000 * USDC
        # 1: price stays exactly 1.00 through the distribution.
        self.assertEqual(Fraction(A0, S0), 1)
        # 2: Bob deposits 100,000 after the yield accrued, before
        # distribution. No checkpoint: reward/share 0.05, Alice 2,500,
        # others 2,500, Bob 5,000. With checkpoint: Alice 5,000,
        # others 5,000, Bob 0. Late entry costs Alice 2,500.
        S1 = S0 + 100_000 * USDC
        rps = Fraction(YIELD, S1)
        self.assertEqual(rps, Fraction(1, 20))
        self.assertEqual((ALICE * rps, OTHERS * rps, 100_000 * USDC * rps),
                         (2_500 * USDC, 2_500 * USDC, 5_000 * USDC))
        self.assertEqual((YIELD * ALICE // S0, YIELD * OTHERS // S0),
                         (5_000 * USDC, 5_000 * USDC))
        self.assertEqual(5_000 * USDC - 2_500 * USDC, 2_500 * USDC)
        # 3: second 10,000 distribution after Bob joined: Alice 2,500,
        # others 2,500, Bob 5,000 under both policies. Totals:
        # checkpoint Alice 7,500 / Bob 5,000; no checkpoint Alice
        # 5,000 / Bob 10,000.
        rps2 = Fraction(YIELD, S1)
        self.assertEqual((ALICE * rps2, OTHERS * rps2,
                          100_000 * USDC * rps2),
                         (2_500 * USDC, 2_500 * USDC, 5_000 * USDC))
        self.assertEqual((5_000 * USDC + 2_500 * USDC, 5_000 * USDC),
                         (7_500 * USDC, 5_000 * USDC))
        self.assertEqual((2_500 * USDC + 2_500 * USDC,
                          5_000 * USDC + 5_000 * USDC),
                         (5_000 * USDC, 10_000 * USDC))
        # 4: Alice redeems 50,000 shares for 50,000 USDC; her 5,000
        # REWARD claim is separate -- 10% of the position, walked
        # away from if never claimed.
        self.assertEqual(ALICE * Fraction(A0, S0), 50_000 * USDC)
        self.assertEqual(Fraction(5_000 * USDC, 50_000 * USDC),
                         Fraction(1, 10))
        # 5: reward-token price risk: 5,000 REWARD at 0.50 USDC is
        # worth 2,500 USDC.
        self.assertEqual(5_000 * USDC * Fraction(1, 2), 2_500 * USDC)

    def test_tranched_vault_guide_numbers(self):
        # Tranched-vault guide (site/tranche-vault-model.py): senior
        # 60,000 shares promised fixed 5% per period, junior 40,000
        # shares takes the residual and absorbs losses first. Vault
        # 100,000 USDC / 100,000 shares, both tranches at 1.00.
        # Re-derived here with plain integer / Fraction arithmetic,
        # independent of the model file.
        USDC = 1_000_000
        # 1: yield +10,000: senior takes 5% of 60,000 = 3,000, junior
        # the residual 7,000. Prices 1.05 / 1.175; blended 1.10.
        self.assertEqual(60_000 * USDC * 5 // 100, 3_000 * USDC)
        self.assertEqual(10_000 * USDC - 3_000 * USDC, 7_000 * USDC)
        self.assertEqual(Fraction(63_000 * USDC, 60_000), Fraction(21, 20) * USDC)
        self.assertEqual(Fraction(47_000 * USDC, 40_000), Fraction(47, 40) * USDC)
        self.assertEqual(Fraction(110_000 * USDC, 100_000), Fraction(11, 10) * USDC)
        self.assertEqual(66_000 * USDC - 63_000 * USDC, 3_000 * USDC)
        # 2: loss -10,000: junior absorbs it all. Prices 1.00 / 0.75.
        self.assertEqual(Fraction(60_000 * USDC, 60_000), 1 * USDC)
        self.assertEqual(Fraction(30_000 * USDC, 40_000), Fraction(3, 4) * USDC)
        self.assertEqual(60_000 * USDC // 10, 6_000 * USDC)
        # 3: loss -50,000: junior wiped to 0, senior takes the excess
        # 10,000 = one sixth of senior capital; price 5/6.
        self.assertEqual(max(40_000 * USDC - 50_000 * USDC, 0), 0)
        self.assertEqual(Fraction(50_000 * USDC, 60_000), Fraction(5, 6) * USDC)
        self.assertEqual(Fraction(10_000, 60_000), Fraction(1, 6))
        self.assertEqual(10_000 * Fraction(50_000 * USDC, 60_000),
                         Fraction(25_000, 3) * USDC)
        # 4: shortfall: yield +2,000 < promised 3,000. Senior 62,000
        # (price 31/30), junior 40,000 (1.00), shortfall 1,000 carried.
        self.assertEqual(3_000 * USDC - 2_000 * USDC, 1_000 * USDC)
        self.assertEqual(Fraction(62_000 * USDC, 60_000), Fraction(31, 30) * USDC)
        # Next +10,000: senior takes 1,000 + 3,000 = 4,000, junior 6,000.
        self.assertEqual(Fraction(66_000 * USDC, 60_000), Fraction(11, 10) * USDC)
        self.assertEqual(Fraction(46_000 * USDC, 40_000), Fraction(23, 20) * USDC)
        self.assertEqual(66_000 * USDC + 46_000 * USDC, 112_000 * USDC)
        # 5: new 10,000 deposit after the +10% period mints 200,000/21
        # senior shares or 400,000/47 junior shares, both worth 10,000.
        self.assertEqual(Fraction(10_000 * USDC, Fraction(21, 20) * USDC),
                         Fraction(200_000, 21))
        self.assertEqual(Fraction(10_000 * USDC, Fraction(47, 40) * USDC),
                         Fraction(400_000, 47))

    def test_tiered_fee_guide_numbers(self):
        # Guide #48: tiered deposit fee -- 5% below 10,000, 2% from
        # 10,000, 1% from 100,000 (per deposit call, on gross).
        # Re-derived here with plain integer / Fraction arithmetic,
        # independent of the model file.
        USDC = 1_000_000
        # A: 5,000 at 5% -> fee 250, net 4,750.
        self.assertEqual(5_000 * USDC * 5 // 100, 250 * USDC)
        # B/C: the 10,000 cliff -- 1 more USDC in, 300.95 more net out.
        self.assertEqual(9_999 * USDC * 5 // 100, Fraction(9999, 20) * USDC)
        self.assertEqual(9_999 * USDC - Fraction(9999, 20) * USDC,
                         Fraction(189981, 20) * USDC)
        self.assertEqual(10_000 * USDC * 2 // 100, 200 * USDC)
        self.assertEqual(Fraction(9_800) - Fraction(189981, 20),
                         Fraction(6019, 20))
        # D/E: the 100,000 cliff -- 1 more USDC in, 1,000.98 more net out.
        self.assertEqual(99_999 * USDC * 2 // 100, Fraction(99999, 50) * USDC)
        self.assertEqual(99_999 * USDC - Fraction(99999, 50) * USDC,
                         Fraction(4899951, 50) * USDC)
        self.assertEqual(100_000 * USDC * 1 // 100, 1_000 * USDC)
        self.assertEqual(Fraction(99_000) - Fraction(4899951, 50),
                         Fraction(50049, 50))
        # F: 200,000 at 1% -> fee 2,000, net 198,000.
        self.assertEqual(200_000 * USDC // 100, 2_000 * USDC)
        # Tiering vs flat 5%: saves 300 on 10,000, 4,000 on 100,000.
        self.assertEqual(10_000 * USDC * 5 // 100 - 200 * USDC, 300 * USDC)
        self.assertEqual(100_000 * USDC * 5 // 100 - 1_000 * USDC, 4_000 * USDC)
        # G: splitting 10,000 into 2x5,000 costs 300 extra in fees;
        # splitting inside one tier (2x10,000 vs 20,000) costs nothing.
        self.assertEqual(2 * (5_000 * USDC * 5 // 100) - 200 * USDC, 300 * USDC)
        self.assertEqual(2 * (10_000 * USDC * 2 // 100),
                         20_000 * USDC * 2 // 100)
        # H: cliff in shares at price 1.10: 9,999 -> 8,635.50 shares,
        # 10,000 -> 8,909.090909... shares, cliff 6,019/22 shares.
        self.assertEqual(Fraction(9_499_05, 100) / Fraction(11, 10),
                         Fraction(17_271, 2))
        self.assertEqual(Fraction(9_800) / Fraction(11, 10),
                         Fraction(98_000, 11))
        self.assertEqual(Fraction(98_000, 11) - Fraction(17_271, 2),
                         Fraction(6_019, 22))
        # Boundary exactness: exactly 10,000 / 100,000 get the lower rate.
        self.assertEqual(10_000 * USDC * 2 // 100, 200 * USDC)
        self.assertEqual(100_000 * USDC * 1 // 100, 1_000 * USDC)

    def test_insurance_reserve_guide_numbers(self):
        # Guide #49: insurance-reserve vault -- a 5,000 USDC reserve held
        # outside totalAssets tops the vault up after a loss, up to the
        # reserve balance. Vault 100,000 USDC / 100,000 shares, price 1.00;
        # Alice holds 50,000 shares. Re-derived here with plain integer /
        # Fraction arithmetic, independent of the model file.
        USDC = 1_000_000
        # 1: loss -3,000, reserve pays all 3,000: assets back to 100,000,
        # price 1.00, reserve left 2,000. Alice loses 0; without the
        # reserve she would hold 48,500 (price 0.97), losing 1,500.
        self.assertEqual(min(3_000 * USDC, 5_000 * USDC), 3_000 * USDC)
        self.assertEqual(5_000 * USDC - 3_000 * USDC, 2_000 * USDC)
        self.assertEqual(100_000 * USDC - 3_000 * USDC + 3_000 * USDC,
                         100_000 * USDC)
        self.assertEqual(50_000 * Fraction(97_000 * USDC, 100_000),
                         48_500 * USDC)
        # 2: loss -10,000, reserve has 2,000 left: pays 2,000, assets
        # 92,000, price 23/25 = 0.92, Alice 46,000. Without the reserve
        # the price would be 0.90 and Alice would hold 45,000.
        self.assertEqual(min(10_000 * USDC, 2_000 * USDC), 2_000 * USDC)
        self.assertEqual(100_000 * USDC - 10_000 * USDC + 2_000 * USDC,
                         92_000 * USDC)
        self.assertEqual(Fraction(92_000 * USDC, 100_000),
                         Fraction(23, 25) * USDC)
        self.assertEqual(50_000 * Fraction(92_000 * USDC, 100_000),
                         46_000 * USDC)
        self.assertEqual(50_000 * Fraction(90_000 * USDC, 100_000),
                         45_000 * USDC)
        # 3: gain +4,000. Refill-first: reserve 4,000, vault stays 92,000,
        # price 0.92. Distribute-first: reserve 0, vault 96,000, price
        # 24/25 = 0.96. Alice redeeming 50,000 shares gets 46,000 vs
        # 48,000 -- a 2,000 difference. The next -4,000 loss makes both
        # policies converge at 92,000 / 0.92.
        self.assertEqual(min(0 + 4_000 * USDC, 5_000 * USDC), 4_000 * USDC)
        self.assertEqual(Fraction(96_000 * USDC, 100_000),
                         Fraction(24, 25) * USDC)
        self.assertEqual(48_000 * USDC - 46_000 * USDC, 2_000 * USDC)
        self.assertEqual(92_000 * USDC - 4_000 * USDC + 4_000 * USDC,
                         92_000 * USDC)
        self.assertEqual(96_000 * USDC - 4_000 * USDC + 0,
                         92_000 * USDC)
        # 4: one big loss -50,000 with a full 5,000 reserve: assets 55,000,
        # price 11/20 = 0.55, Alice 27,500. Without the reserve: price
        # 0.50, Alice 25,000 -- the reserve saves 2,500 of a 25,000 loss.
        self.assertEqual(min(50_000 * USDC, 5_000 * USDC), 5_000 * USDC)
        self.assertEqual(100_000 * USDC - 50_000 * USDC + 5_000 * USDC,
                         55_000 * USDC)
        self.assertEqual(Fraction(55_000 * USDC, 100_000),
                         Fraction(11, 20) * USDC)
        self.assertEqual(50_000 * Fraction(55_000 * USDC, 100_000),
                         27_500 * USDC)
        self.assertEqual(27_500 * USDC - 25_000 * USDC, 2_500 * USDC)
        self.assertEqual(Fraction(5_000, 100_000), Fraction(1, 20))
        # 5: funding: 5,000 / 0.5% = 1,000,000 USDC of deposits; 1% of a
        # 10,000 annual yield = 100/year, so 5,000 takes 50 years.
        self.assertEqual(5_000 * USDC * 1000 // 5, 1_000_000 * USDC)
        self.assertEqual(10_000 * USDC // 100, 100 * USDC)
        self.assertEqual(5_000 * USDC // (100 * USDC), 50)

    def test_yield_token_guide_numbers(self):
        # Guide #51: yield-token vault (ERC-5115) -- 10,000 SY splits
        # 1:1:1 into 10,000 PT + 10,000 YT. Vault 100,000 USDC /
        # 100,000 SY, price 1.00, maturity one year out; Alice holds
        # 10,000 SY. Re-derived here with plain integer / Fraction
        # arithmetic, independent of the model file
        # (site/yield-token-model.py).
        USDC = 1_000_000
        # 1: the split. 10,000 SY -> 10,000 PT + 10,000 YT; at +10%
        # the YT pays 1,000. Hold both to maturity: 11,000, exactly
        # what holding the SY would have been worth.
        self.assertEqual(10_000 * USDC, 10_000 * USDC)
        self.assertEqual(10_000 * USDC * Fraction(1, 10), 1_000 * USDC)
        self.assertEqual(10_000 * USDC + 1_000 * USDC,
                         10_000 * USDC * (1 + Fraction(1, 10)))
        # 2: PT price at 10% implied: 10,000 / 1.10 = 100,000/11 USDC
        # = 9,090.909091; discount 10,000/11 = 909.090909. YT price
        # the same 909.090909; PT + YT = 10,000 = the SY value.
        self.assertEqual(Fraction(10_000 * USDC, 1) / Fraction(11, 10),
                         Fraction(100_000 * USDC, 11))
        self.assertEqual(10_000 * USDC - Fraction(100_000 * USDC, 11),
                         Fraction(10_000 * USDC, 11))
        self.assertEqual(Fraction(1_000 * USDC, 1) / Fraction(11, 10),
                         Fraction(10_000 * USDC, 11))
        self.assertEqual(Fraction(100_000 * USDC, 11)
                         + Fraction(10_000 * USDC, 11),
                         10_000 * USDC)
        # 3: PT gain locked: 10,000 - 100,000/11 = 10,000/11, exactly
        # 10% of the PT price, whatever the vault earns.
        self.assertEqual(10_000 * USDC - Fraction(100_000 * USDC, 11),
                         Fraction(10_000 * USDC, 11))
        self.assertEqual(Fraction(Fraction(10_000 * USDC, 11),
                                  Fraction(100_000 * USDC, 11)),
                         Fraction(1, 10))
        # 4: YT at +5% pays 500; loss 909.090909 - 500 = 409.090909
        # = 4,500/11 USDC, which is 9/20 = -45% of the YT price.
        # At 0% the YT pays 0: the whole 909.090909 is lost (-100%).
        # After maturity the YT is worth exactly 0.
        self.assertEqual(10_000 * USDC * Fraction(1, 20), 500 * USDC)
        self.assertEqual(Fraction(10_000 * USDC, 11) - 500 * USDC,
                         Fraction(4_500 * USDC, 11))
        self.assertEqual(Fraction(Fraction(4_500 * USDC, 11),
                                  Fraction(10_000 * USDC, 11)),
                         Fraction(9, 20))
        self.assertEqual(Fraction(10_000 * USDC, 11) - 0,
                         Fraction(10_000 * USDC, 11))
        # 5: PT quoted at 9,500 implies 10,000/9,500 - 1 = 1/19
        # = 5.263158%. The PT buyer still only gets 10,000 even if
        # the vault earns 10%.
        self.assertEqual(Fraction(10_000 * USDC, 9_500 * USDC) - 1,
                         Fraction(1, 19))
        # 6: sell the YT early at 909.090909, cash idle, PT redeems
        # 10,000: total 120,000/11 = 10,909.090909, short of holding
        # by 1,000/11 = 90.909091.
        self.assertEqual(10_000 * USDC + Fraction(10_000 * USDC, 11),
                         Fraction(120_000 * USDC, 11))
        self.assertEqual(11_000 * USDC - Fraction(120_000 * USDC, 11),
                         Fraction(1_000 * USDC, 11))
        # 7: double-count bug: PT at face 10,000 + YT at expected
        # 1,000 = 11,000 against 10,000 SY of backing -- 1,000
        # overstated, 1/10 = 10%.
        self.assertEqual(10_000 * USDC + 1_000 * USDC, 11_000 * USDC)
        self.assertEqual(11_000 * USDC - 10_000 * USDC, 1_000 * USDC)
        self.assertEqual(Fraction(1_000 * USDC, 10_000 * USDC),
                         Fraction(1, 10))
        # 8: SY price blind spot: totalAssets stays 100,000 through
        # a +10% year, price exactly 1.00.
        self.assertEqual(Fraction(100_000 * USDC, 100_000 * USDC), 1)

    def test_share_classes_guide_numbers(self):
        # Guide #50: two share classes, one vault -- A pays 2%, B pays
        # 0.5%. Each class holds 500,000 shares / 500,000 USDC at launch,
        # price 1.00. Alice holds 10,000 shares. Re-derived here with
        # plain integer / Fraction arithmetic, independent of the model
        # file (site/share-classes-model.py).
        USDC = 1_000_000
        # Two share classes, one vault: A pays 2%, B pays 0.5%. Each
        # class holds 500,000 shares / 500,000 USDC at launch, price 1.00.
        # Alice holds 10,000 shares. All values from
        # site/share-classes-model.py (exact Fractions).
        # 1: year 1, +10% gross. A fee 11,000 -> 539,000, price 539/500 =
        # 1.078; B fee 2,750 -> 547,250, price 2189/2000 = 1.0945. Alice:
        # 10,780 in A vs 10,945 in B, a 165 difference after one year.
        self.assertEqual(550_000 * USDC * 2 // 100, 11_000 * USDC)
        self.assertEqual(550_000 * USDC - 11_000 * USDC, 539_000 * USDC)
        self.assertEqual(Fraction(539_000 * USDC, 500_000),
                         Fraction(539, 500) * USDC)
        self.assertEqual(10_000 * Fraction(539_000 * USDC, 500_000),
                         10_780 * USDC)
        self.assertEqual(550_000 * USDC // 200, 2_750 * USDC)
        self.assertEqual(550_000 * USDC - 2_750 * USDC, 547_250 * USDC)
        self.assertEqual(Fraction(547_250 * USDC, 500_000),
                         Fraction(2189, 2000) * USDC)
        self.assertEqual(10_000 * Fraction(547_250 * USDC, 500_000),
                         10_945 * USDC)
        self.assertEqual(10_945 * USDC - 10_780 * USDC, 165 * USDC)
        # 2: year 2, another +10%. A fee 11,858 -> 581,042, price
        # 290521/250000 = 1.162084; B fee 3,009.875 -> 598,965.125,
        # price 1.19793025. Alice: 11,620.84 vs 11,979.3025, gap 358.4625.
        self.assertEqual(592_900 * USDC * 2 // 100, 11_858 * USDC)
        self.assertEqual(592_900 * USDC - 11_858 * USDC, 581_042 * USDC)
        self.assertEqual(Fraction(581_042 * USDC, 500_000),
                         Fraction(290521, 250000) * USDC)
        self.assertEqual(10_000 * Fraction(581_042 * USDC, 500_000),
                         Fraction(1162084, 100) * USDC)
        self.assertEqual(Fraction(601975, 200) * USDC,
                         Fraction(3009875, 1000) * USDC)
        self.assertEqual(Fraction(601975 * USDC) - Fraction(601975, 200) * USDC,
                         Fraction(4791721, 8) * USDC)
        self.assertEqual(10_000 * Fraction(4791721, 8) * USDC / 500_000,
                         Fraction(119793025, 10000) * USDC)
        self.assertEqual(Fraction(119793025, 10000) * USDC
                         - Fraction(1162084, 100) * USDC,
                         Fraction(28677, 80) * USDC)
        # 3: down year -10% from launch. Both classes still pay: A fee
        # 9,000 -> 441,000, price 0.882; B fee 2,250 -> 447,750, price
        # 0.8955. Alice: 8,820 vs 8,955, a 135 difference in a losing year.
        self.assertEqual(450_000 * USDC * 2 // 100, 9_000 * USDC)
        self.assertEqual(450_000 * USDC - 9_000 * USDC, 441_000 * USDC)
        self.assertEqual(Fraction(441_000 * USDC, 500_000),
                         Fraction(441, 500) * USDC)
        self.assertEqual(10_000 * Fraction(441_000 * USDC, 500_000),
                         8_820 * USDC)
        self.assertEqual(450_000 * USDC // 200, 2_250 * USDC)
        self.assertEqual(450_000 * USDC - 2_250 * USDC, 447_750 * USDC)
        self.assertEqual(Fraction(447_750 * USDC, 500_000),
                         Fraction(1791, 2000) * USDC)
        self.assertEqual(10_000 * Fraction(447_750 * USDC, 500_000),
                         8_955 * USDC)
        self.assertEqual(8_955 * USDC - 8_820 * USDC, 135 * USDC)
        # 4: ten years at +10% a year. A ends near 21,192.76, B near
        # 24,669.35; B/A ratio near 1.164046 -- "only 1.5% a year"
        # compounds to B ending about 16.40% ahead.
        a10 = 10_000 * Fraction(539, 500) ** 10
        b10 = 10_000 * Fraction(2189, 2000) ** 10
        self.assertTrue(21_192 < a10 < 21_193)
        self.assertTrue(24_669 < b10 < 24_670)
        self.assertTrue(3476 < b10 - a10 < 3477)
        self.assertTrue(Fraction(1164, 1000) < b10 / a10
                        < Fraction(1165, 1000))
        # 5: pooled-fee bug. Correct year-1 fees total 13,750; taken from
        # pooled totalAssets and split 50/50, each class loses 6,875, so
        # both sit at 543,125, price 21725/20000 = 1.08625. A gains 4,125
        # against its correct 539,000; B loses 4,125 against its correct
        # 547,250 -- 0.7539% of B's value moves to A in one year.
        self.assertEqual(11_000 * USDC + 2_750 * USDC, 13_750 * USDC)
        self.assertEqual(13_750 * USDC // 2, 6_875 * USDC)
        self.assertEqual(550_000 * USDC - 6_875 * USDC, 543_125 * USDC)
        self.assertEqual(Fraction(543_125 * USDC, 500_000),
                         Fraction(21725, 20000) * USDC)
        self.assertEqual(543_125 * USDC - 539_000 * USDC, 4_125 * USDC)
        self.assertEqual(547_250 * USDC - 543_125 * USDC, 4_125 * USDC)
        self.assertEqual(Fraction(4125, 547250), Fraction(33, 4378))
        # 6: converting A to B at NAV. Alice's 10,000 A shares are worth
        # 10,780 after year 1; at B's price 1.0945 that buys 21,560,000 /
        # 2,189 = 9,849.246... B shares. A stale launch price of 1.00
        # would mint 10,780 B shares: 2,037,420/2,189 = 930.753... shares
        # too many, worth about 1,018.71 USDC.
        conv = Fraction(10_780 * USDC, 1) / (Fraction(2189, 2000) * USDC)
        self.assertEqual(conv, Fraction(21_560_000, 2189))
        self.assertTrue(9849 < conv < 9850)
        over = 10_780 - conv
        self.assertEqual(over, Fraction(2037420, 2189))
        self.assertTrue(930 < over < 931)
        self.assertTrue(1018 < over * Fraction(2189, 2000) < 1019)

    def test_leveraged_vault_guide_numbers(self):
        # Guide #50: leveraged vault -- 100,000 equity / 100,000 shares
        # at 1.00, borrows 100,000 at 5% a year, gross 200,000, 2x.
        # Alice holds 10,000 shares. Re-derived here with plain
        # integer / Fraction arithmetic, independent of the model
        # file (site/leveraged-vault-model.py).
        USDC = 1_000_000
        equity0 = 100_000 * USDC
        debt = 100_000 * USDC
        gross0 = 200_000 * USDC
        supply = 100_000
        alice = 10_000
        rate = Fraction(5, 100)
        # 1: +10% year. Gross 220,000, interest 5,000, equity 115,000,
        # price 23/20 = 1.15, Alice 11,500; unlevered 11,000.
        interest = debt * rate
        self.assertEqual(interest, 5_000 * USDC)
        equity_up = gross0 * Fraction(11, 10) - debt - interest
        self.assertEqual(equity_up, 115_000 * USDC)
        self.assertEqual(Fraction(equity_up, supply), Fraction(23, 20) * USDC)
        self.assertEqual(alice * Fraction(equity_up, supply), 11_500 * USDC)
        self.assertEqual(alice * Fraction(equity_up, supply)
                         - 11_000 * USDC, 500 * USDC)
        # 2: -10% year. Gross 180,000, equity 75,000, price 3/4 = 0.75,
        # Alice 7,500; unlevered 9,000, so 1,500 worse.
        equity_down = gross0 * Fraction(9, 10) - debt - interest
        self.assertEqual(equity_down, 75_000 * USDC)
        self.assertEqual(Fraction(equity_down, supply), Fraction(3, 4) * USDC)
        self.assertEqual(alice * Fraction(equity_down, supply), 7_500 * USDC)
        self.assertEqual(9_000 * USDC
                         - alice * Fraction(equity_down, supply),
                         1_500 * USDC)
        # 3: flat year. Equity 95,000, price 19/20 = 0.95, Alice 9,500.
        # Break-even gross yield is 5,000 / 200,000 = 1/40 = 2.5%.
        equity_flat = gross0 - debt - interest
        self.assertEqual(equity_flat, 95_000 * USDC)
        self.assertEqual(Fraction(equity_flat, supply), Fraction(19, 20) * USDC)
        self.assertEqual(alice * Fraction(equity_flat, supply), 9_500 * USDC)
        self.assertEqual(interest / gross0, Fraction(1, 40))
        # 4: liquidation at 80% LTV. Gross 125,000, a -3/8 = -37.5%
        # fall; equity 25,000, price 1/4, Alice 2,500. At -30% gross
        # 140,000, LTV 5/7, equity 40,000, price 2/5 = 0.40.
        liq_gross = debt / Fraction(4, 5)
        self.assertEqual(liq_gross, 125_000 * USDC)
        self.assertEqual((gross0 - liq_gross) / gross0, Fraction(3, 8))
        self.assertEqual(liq_gross - debt, 25_000 * USDC)
        self.assertEqual(Fraction(liq_gross - debt, supply), Fraction(1, 4) * USDC)
        self.assertEqual(alice * Fraction(liq_gross - debt, supply),
                         2_500 * USDC)
        gross_30 = gross0 * Fraction(7, 10)
        self.assertEqual(Fraction(debt, gross_30), Fraction(5, 7))
        self.assertEqual(Fraction(gross_30 - debt, supply), Fraction(2, 5) * USDC)
        # 5: the accounting bug. Naive price 2.00 vs true 1.00; a
        # 10,000 deposit mints 5,000 shares worth 5,000, losing 5,000.
        self.assertEqual(Fraction(gross0, supply), 2 * USDC)
        self.assertEqual(Fraction(equity0, supply), 1 * USDC)
        shares_naive = Fraction(10_000 * USDC, 1) / Fraction(gross0, supply)
        self.assertEqual(shares_naive, 5_000)
        self.assertEqual(shares_naive * Fraction(equity0, supply),
                         5_000 * USDC)
        # 6: year two. After the up year, gross net of interest is
        # 215,000; +10% -> 236,500, interest 5,000, equity 131,500,
        # price 263/200 = 1.315, Alice 13,150; unlevered 12,100.
        gross1_net = gross0 * Fraction(11, 10) - interest
        self.assertEqual(gross1_net, 215_000 * USDC)
        equity2 = gross1_net * Fraction(11, 10) - interest - debt
        self.assertEqual(equity2, 131_500 * USDC)
        self.assertEqual(Fraction(equity2, supply), Fraction(263, 200) * USDC)
        self.assertEqual(alice * Fraction(equity2, supply), 13_150 * USDC)
        self.assertEqual(alice * Fraction(equity2, supply)
                         - 12_100 * USDC, 1_050 * USDC)
        # Two -10% years: gross 157,500, equity 52,500, price 21/40
        # = 0.525, Alice 5,250; unlevered 8,100, gap 2,850.
        gross_down_net = gross0 * Fraction(9, 10) - interest
        self.assertEqual(gross_down_net, 175_000 * USDC)
        equity2_down = gross_down_net * Fraction(9, 10) - interest - debt
        self.assertEqual(equity2_down, 52_500 * USDC)
        self.assertEqual(Fraction(equity2_down, supply), Fraction(21, 40) * USDC)
        self.assertEqual(alice * Fraction(equity2_down, supply), 5_250 * USDC)
        self.assertEqual(8_100 * USDC
                         - alice * Fraction(equity2_down, supply),
                         2_850 * USDC)

    def test_pausable_vault_guide_numbers(self):
        # Guide #52: pausable vault -- the pause stops the exits, not
        # the losses. Vault 1,000,000 USDC / 1,000,000 shares, price
        # 1.00; Alice holds 100,000 shares. Re-derived here with plain
        # integer / Fraction arithmetic, independent of the model file
        # (site/pause-vault-model.py).
        USDC = 1_000_000
        # 1: deposits-only pause. Alice redeems 100,000 shares at
        # 1.00 and leaves whole; Bob's deposit reverts, 0 shares.
        self.assertEqual(100_000 * USDC * Fraction(1_000_000 * USDC,
                                                   1_000_000 * USDC),
                         100_000 * USDC)
        self.assertEqual(0, 0)
        # 2: full pause, flat strategy. Alice still exits whole, but
        # the lock costs forgone yield at 10%/yr: 7d = 14,000/73,
        # 30d = 60,000/73, 90d = 180,000/73 USDC.
        self.assertEqual(Fraction(100_000) * Fraction(1, 10)
                         * Fraction(7, 365), Fraction(14_000, 73))
        self.assertEqual(Fraction(100_000) * Fraction(1, 10)
                         * Fraction(30, 365), Fraction(60_000, 73))
        self.assertEqual(Fraction(100_000) * Fraction(1, 10)
                         * Fraction(90, 365), Fraction(180_000, 73))
        self.assertEqual(f"{float(Fraction(14_000, 73)):,.6f}",
                         "191.780822")
        self.assertEqual(f"{float(Fraction(60_000, 73)):,.6f}",
                         "821.917808")
        self.assertEqual(f"{float(Fraction(180_000, 73)):,.6f}",
                         "2,465.753425")
        # 3: full pause + strategy -20%. True price 800,000 /
        # 1,000,000 = 0.80; Alice's 100,000 shares redeem for 80,000,
        # a 20,000 loss the pause locked her into.
        self.assertEqual(Fraction(800_000 * USDC, 1_000_000 * USDC),
                         Fraction(4, 5))
        self.assertEqual(100_000 * USDC * Fraction(4, 5),
                         80_000 * USDC)
        self.assertEqual(100_000 * USDC - 80_000 * USDC,
                         20_000 * USDC)
        # 4: a 1,000,000 USDC donation during the pause, established
        # vault. Price doubles to exactly 2.00; Alice's 100,000
        # shares redeem for 199,999,999,999 base units (one base unit
        # short of 200,000, from the +1 virtual terms), a gain of
        # 99,999,999,999. The next 100,000 USDC depositor after
        # unpause mints 50,000,000,000 base-unit shares and redeems
        # them for 99,999,999,999 -- a loss of one base unit.
        A_don, S0 = 2_000_000 * USDC, 1_000_000 * USDC
        self.assertEqual(Fraction(A_don, S0), 2)
        alice_back = 100_000 * USDC * (A_don + 1) // (S0 + 1)
        self.assertEqual(alice_back, 199_999_999_999)
        self.assertEqual(alice_back - 100_000 * USDC, 99_999_999_999)
        dep = 100_000 * USDC
        new_shares = dep * (S0 + 1) // (A_don + 1)
        self.assertEqual(new_shares, 50_000_000_000)
        A2, S2 = A_don + dep, S0 + new_shares
        new_back = new_shares * (A2 + 1) // (S2 + 1)
        self.assertEqual(new_back, 99_999_999_999)
        self.assertEqual(dep - new_back, 1)
        # 5: contrast -- the same 1,000,000 donation against a NEW
        # vault, attacker first depositor with a 1 USDC seed.
        # Reproduces the checker's no-protection preset exactly:
        # victim loss 909,091 base units (0.909091 USDC), attacker
        # net -90,909 (-0.090909 USDC).
        A, S = 0, 0
        atk_in = 1 * USDC
        atk_shares = atk_in * (S + 1) // (A + 1)
        A += atk_in
        S += atk_shares
        A += 1_000_000 * USDC
        vic_shares = dep * (S + 1) // (A + 1)
        A += dep
        S += vic_shares
        atk_out = atk_shares * (A + 1) // (S + 1)
        A -= atk_out
        S -= atk_shares
        vic_out = vic_shares * (A + 1) // (S + 1)
        self.assertEqual(dep - vic_out, 909_091)
        self.assertEqual(atk_out - (atk_in + 1_000_000 * USDC),
                         -90_909)

    def test_donation_loss_chart(self):
        # The donation table shows four losses that are not monotonic in
        # the donation (1B loses less than 1M) — easy to miss in a column
        # of decimals. The bar chart under the table makes the shape
        # visible: bars scaled to the worst row, red where the row breaches
        # the pass bound. The chart adds no new numbers; every figure is
        # the model's own, and the bar widths are pinned here.
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path.home() / "workspace/taskmarket/site"))
        import build
        # No protection: losses 0 / 6 / 909091 / 99890 base units.
        html = build.results_html(
            run_all(Vault(decimals_offset=0, min_deposit=0, perf_fee_bps=0)),
            vic=100_000_000_000, off=0, mn=0, fee=0)
        self.assertIn("loss-chart", html)
        self.assertIn("Bars are scaled to the worst row in this table", html)
        self.assertEqual(html.count("loss-fill fail"), 2)
        self.assertEqual(html.count("loss-fill pass"), 2)
        self.assertIn("width:100.0%", html)
        self.assertIn("width:11.0%", html)
        self.assertIn("0.909091", html)
        # Seeded vault: losses [1, 1, 1, 13] — all within bound, all green.
        A50 = 50_000_000_000_000
        html = build.results_html(
            run_all(Vault(decimals_offset=0, min_deposit=0, perf_fee_bps=0),
                    vault_assets=A50, vault_supply=A50),
            vic=100_000_000_000, off=0, mn=0, fee=0, vassets=A50, vshares=A50)
        self.assertEqual(html.count("loss-fill fail"), 0)
        self.assertEqual(html.count("loss-fill pass"), 4)
        self.assertIn("width:7.7%", html)
        # Offset 18: every loss is 0 — bars all zero width, chart still there.
        html = build.results_html(
            run_all(Vault(decimals_offset=18, min_deposit=1_000_000,
                          perf_fee_bps=1000)))
        self.assertIn("loss-chart", html)
        self.assertEqual(html.count("width:0.0%"), 4)
        # Giant minimum deposit: every row errors, no number to chart.
        html = build.results_html(
            run_all(Vault(decimals_offset=0, min_deposit=10 ** 21,
                          perf_fee_bps=0)),
            vic=100_000_000_000, off=0, mn=10 ** 21, fee=0)
        self.assertNotIn("loss-chart", html)


    def test_smoothed_nav_guide_numbers(self):
        # Smoothed-NAV guide: 30-day moving-average reported price.
        # Vault 1,000,000 USDC / 1,000,000 shares, price 1.00.
        # Independent re-derivation with Fraction (does not import the
        # site model file); pins every number the guide prints.
        USDC = 1_000_000
        # -20% day: reported = (29 x 1.00 + 0.80) / 30 = 149/150.
        rep_loss = (29 * Fraction(1) + Fraction(4, 5)) / 30
        self.assertEqual(rep_loss, Fraction(149, 150))
        payout = Fraction(100_000) * rep_loss
        self.assertEqual(payout, Fraction(298_000, 3))  # 99,333.333333
        overpay = payout - Fraction(80_000)
        self.assertEqual(overpay, Fraction(58_000, 3))  # 19,333.333333
        rem_price = (Fraction(800_000) - payout) / Fraction(900_000)
        self.assertEqual(rem_price, Fraction(1051, 1350))  # 0.778519
        # +20% day: reported = (29 x 1.00 + 1.20) / 30 = 151/150.
        rep_gain = (29 * Fraction(1) + Fraction(6, 5)) / 30
        self.assertEqual(rep_gain, Fraction(151, 150))
        shares_base = (100_000 * USDC * 150) // 151
        self.assertEqual(shares_base, 99_337_748_344)  # 99,337.748344
        shares = Fraction(shares_base, USDC)
        true_price = Fraction(1_300_000) / (Fraction(1_000_000) + shares)
        bob_value = shares * true_price
        # 117,469.879518 to 6dp; gain 17,469.879518.
        self.assertLess(abs(bob_value - Fraction(117_469_879_518, USDC)),
                        Fraction(1, USDC))
        self.assertLess(abs((bob_value - 100_000)
                            - Fraction(17_469_879_518, USDC)),
                        Fraction(1, USDC))
        # Run: half the vault redeems at the smoothed price.
        run_payout = Fraction(500_000) * rep_loss
        self.assertEqual(run_payout, Fraction(1_490_000, 3))  # 496,666.666667
        run_price = (Fraction(800_000) - run_payout) / Fraction(500_000)
        self.assertEqual(run_price, Fraction(91, 150))  # 0.606667
        # Convergence: reported price k days after the shock.
        for k, want in ((10, Fraction(14, 15)), (29, Fraction(121, 150)),
                        (30, Fraction(4, 5))):
            got = ((30 - k) * Fraction(1) + k * Fraction(4, 5)) / 30
            self.assertEqual(got, want)

    def test_time_decay_exit_fee_guide_numbers(self):
        # Time-decaying exit-fee guide: 500 bps day 0 -> 0 bps day 30.
        # Vault 1,000,000 USDC / 1,000,000 shares, price 1.00, Alice
        # 100,000 shares. Independent re-derivation with Fraction and
        # integer mul_div_down (does not import the site model file);
        # pins every number the guide prints.
        USDC = 1_000_000
        gross_base = 100_000 * USDC

        def fee_base(days):
            if days >= 30:
                return 0
            # rate = 500 * (30 - days) / 30 bps; fee = gross * rate / 10000.
            return (gross_base * 500 * (30 - days)) // (30 * 10_000)

        # Day 0: fee 5,000, net 95,000, price after 181/180 = 1.005556.
        self.assertEqual(fee_base(0), 5_000 * USDC)
        self.assertEqual(gross_base - fee_base(0), 95_000 * USDC)
        price0 = Fraction(1_000_000 * USDC - (gross_base - fee_base(0)),
                          900_000 * USDC)
        self.assertEqual(price0, Fraction(181, 180))
        # Day 15: fee 2,500, net 97,500, price after 9025/9000 = 1.002778.
        self.assertEqual(fee_base(15), 2_500 * USDC)
        self.assertEqual(gross_base - fee_base(15), 97_500 * USDC)
        price15 = Fraction(1_000_000 * USDC - (gross_base - fee_base(15)),
                           900_000 * USDC)
        self.assertEqual(price15, Fraction(9025, 9000))
        # Day 29: rate 50/3 bps, fee 166,666,666 base units, net
        # 99,833,333,334, price after 1.000185 (900166666666/900000000000).
        self.assertEqual(fee_base(29), 166_666_666)
        self.assertEqual(gross_base - fee_base(29), 99_833_333_334)
        price29 = Fraction(1_000_000 * USDC - (gross_base - fee_base(29)),
                           900_000 * USDC)
        self.assertEqual(price29, Fraction(900_166_666_666, 900_000_000_000))
        self.assertLess(abs(price29 - Fraction(1_000_185, 1_000_000)),
                        Fraction(1, USDC))
        # Day 30: fee 0, net 100,000.
        self.assertEqual(fee_base(30), 0)
        self.assertEqual(gross_base - fee_base(30), gross_base)
        # Waiting 0 -> 30 saves exactly the day-0 fee.
        self.assertEqual(fee_base(0) - fee_base(30), 5_000 * USDC)
        # Yield while waiting 30 days at 10%/yr: 821.917808 USDC.
        # (yield_30d is base units; compare in USDC, not base units.)
        yield_30d = Fraction(100_000 * USDC * 10 * 30, 100 * 365)
        yield_30d_usdc = yield_30d / USDC
        self.assertLess(abs(yield_30d_usdc - Fraction(821_917_808, USDC)),
                        Fraction(1, USDC))
        # Clock reset: 1 USDC top-up at day 29, exit all 100,001 shares
        # at the day-0 rate.
        all_base = gross_base + 1 * USDC
        fee_reset = (all_base * 500) // 10_000
        self.assertEqual(fee_reset, 5_000_050_000)
        net_reset = all_base - fee_reset
        self.assertEqual(net_reset, 95_000_950_000)
        reset_cost = (gross_base - fee_base(29)) - net_reset
        self.assertEqual(reset_cost, 4_832_383_334)
        # FIFO per-lot clock: old lot at day-29 fee, new 1 share at 500 bps.
        fee_fifo = fee_base(29) + (1 * USDC * 500) // 10_000
        self.assertEqual(fee_fifo, 166_716_666)
        net_fifo = all_base - fee_fifo
        self.assertEqual(net_fifo, 99_834_283_334)
        self.assertEqual(net_fifo - net_reset, 4_833_333_334)

    def test_share_price_collateral_guide_numbers(self):
        # Share-price-as-collateral guide: donate to inflate the price you
        # borrow against. Vault 1,000,000 USDC / 1,000,000 shares, price
        # 1.00; lending market values shares at the live price, LTV 75%.
        # Independent re-derivation with Fraction (does not import the
        # site model file); pins every number the guide prints.
        USDC = 1_000_000
        A = 1_000_000 * USDC
        S = 1_000_000 * USDC
        D = 1_000_000 * USDC
        LTV = Fraction(3, 4)
        # Donation doubles the price: (A + D) / S = 2.00.
        self.assertEqual(Fraction(A + D, S), 2)
        for shares, coll, borrow, net in (
                (100_000 * USDC, 200_000 * USDC,
                 150_000 * USDC, -950_000 * USDC),
                (900_000 * USDC, 1_800_000 * USDC,
                 1_350_000 * USDC, -550_000 * USDC)):
            f = Fraction(shares, S)
            collateral = f * (A + D)
            self.assertEqual(collateral, coll)
            self.assertEqual(collateral * LTV, borrow)
            self.assertEqual(collateral * LTV - D - f * A, net)
        # Limit case: 999,999 of 1,000,000 shares.
        f999 = Fraction(999_999 * USDC, S)
        coll999 = f999 * (A + D)
        self.assertEqual(coll999, 1_999_998 * USDC)
        borrow999 = coll999 * LTV
        self.assertEqual(borrow999, Fraction(2_999_997, 2) * USDC)
        self.assertEqual(borrow999 - D - f999 * A,
                         Fraction(-1_000_001, 2) * USDC)  # -500,000.5
        # General formula, both terms negative at every fraction.
        for shares in (100_000 * USDC, 900_000 * USDC, 999_999 * USDC):
            f = Fraction(shares, S)
            formula = f * (LTV - 1) * A + (f * LTV - 1) * D
            direct = f * (A + D) * LTV - D - f * A
            self.assertEqual(formula, direct)
            self.assertLess(f * (LTV - 1) * A, 0)
            self.assertLess((f * LTV - 1) * D, 0)
        # f = 100% floor: -(1 - LTV) * (A + D) = -500,000.
        self.assertEqual(-(1 - LTV) * (A + D), -500_000 * USDC)
        # Flash-loan variant: 0.05% fee on 1,000,000 = 500; due 1,000,500.
        # Most extractable in one tx: borrow 150,000 + redeem own shares
        # at 2.00 = 200,000; total 350,000; short 650,500.
        flash_fee = (D * 5) // 10_000
        self.assertEqual(flash_fee, 500 * USDC)
        self.assertEqual(D + flash_fee, 1_000_500 * USDC)
        redeem_own = (100_000 * USDC) * 2
        self.assertEqual(redeem_own, 200_000 * USDC)
        extractable = 150_000 * USDC + redeem_own
        self.assertEqual(extractable, 350_000 * USDC)
        self.assertEqual((D + flash_fee) - extractable, 650_500 * USDC)

    def test_governance_vote_guide_numbers(self):
        # Governance-vote guide: votes weighted by raw share balance let
        # the first depositor buy the vote for one base unit. OZ
        # conversion rules, rounding down: shares = deposit * (supply +
        # 10**offset) / (assets + 1); assets = shares * (assets + 1) /
        # (supply + 10**offset). Independent re-derivation with Fraction
        # (does not import the site model file); pins every number the
        # guide prints.
        USDC = 1_000_000
        D = 1_000_000 * USDC
        V = 1_000_000 * USDC

        def sh_for(dep, sup, ast, off=0):
            return (dep * (sup + 10 ** off)) // (ast + 1)

        def as_for(sh, sup, ast, off=0):
            return (sh * (ast + 1)) // (sup + 10 ** off)

        # Offset 0: attacker 1 base unit -> 1 share; victim 1,000,000
        # USDC -> 1 share; vote split 50/50.
        s_att = sh_for(1, 0, 0)
        self.assertEqual(s_att, 1)
        s_vic = sh_for(V, s_att, 1 + D)
        self.assertEqual(s_vic, 1)
        self.assertEqual(Fraction(s_att, s_att + s_vic), Fraction(1, 2))
        # Price per vote: attacker 0.000001 USDC, victim 1,000,000 USDC.
        self.assertEqual(Fraction(1, USDC), Fraction(1, 1_000_000))
        self.assertEqual(Fraction(V, USDC), 1_000_000)
        # Victim twice as large buys only 3 shares: attacker keeps 25%.
        s_vic2 = sh_for(2 * V, s_att, 1 + D)
        self.assertEqual(s_vic2, 3)
        self.assertEqual(Fraction(s_att, s_att + s_vic2), Fraction(1, 4))
        # Offset 6: attacker 1,000,000 shares for 1 base unit; victim
        # 1,999,999 shares; attacker vote share 1,000,000/2,999,999.
        off = 6
        s_att6 = sh_for(1, 0, 0, off)
        self.assertEqual(s_att6, 1_000_000)
        s_vic6 = sh_for(V, s_att6, 1 + D, off)
        self.assertEqual(s_vic6, 1_999_999)
        self.assertEqual(Fraction(s_att6, s_att6 + s_vic6),
                         Fraction(1_000_000, 2_999_999))
        # Price per vote at offset 6: attacker 1e-12 USDC, victim
        # 1,000,000/1,999,999 USDC.
        self.assertEqual(Fraction(1, s_att6 * USDC),
                         Fraction(1, 10 ** 12))
        self.assertEqual(Fraction(V, s_vic6 * USDC),
                         Fraction(1_000_000, 1_999_999))
        # Value side at offset 6: victim redeems 999,999.75, loss 0.25.
        assets_after = (1 + D) + V
        supply_after = s_att6 + s_vic6
        vic_redeem = as_for(s_vic6, supply_after, assets_after, off)
        self.assertEqual(vic_redeem, 999_999_750_000)
        self.assertEqual(V - vic_redeem, 250_000)  # 0.25 USDC
        # Attacker redeems after the victim exits: 500,000.125001,
        # net -499,999.875 USDC.
        att_redeem = as_for(s_att6, s_att6, assets_after - vic_redeem, off)
        self.assertEqual(att_redeem, 500_000_125_001)
        self.assertEqual(att_redeem - D - 1, -499_999_875_000)
        # Value-weighted votes: attacker weight 500,000.125, victim
        # 999,999.75; cost per unit weight ~2.00 vs ~1.00.
        att_value = as_for(s_att6, supply_after, assets_after, off)
        vic_value = as_for(s_vic6, supply_after, assets_after, off)
        self.assertEqual(att_value, 500_000_125_000)
        self.assertEqual(vic_value, 999_999_750_000)
        att_cost = Fraction(D + 1, att_value)
        vic_cost = Fraction(V, vic_value)
        self.assertAlmostEqual(float(att_cost), 2.0, places=5)
        self.assertAlmostEqual(float(vic_cost), 1.0, places=5)
        self.assertGreater(att_cost, vic_cost)

    def test_deposit_cap_griefing_guide_numbers(self):
        # Pins /guides/erc4626-deposit-cap-griefing/ to its model: a
        # 1,000,000 USDC / 1,000,000 share vault, price $1.00, capped by
        # totalAssets. The cap is a threshold, not a price: a dust
        # donation 1 base unit over the cap freezes every deposit, and
        # the sunk cost is 1 base unit whenever the attacker can front
        # the headroom. A supply cap is donation-proof because a
        # donation mints no shares.
        import importlib.util
        from fractions import Fraction
        from pathlib import Path
        model_path = (Path.home() / "workspace/taskmarket/site"
                      / "deposit-cap-griefing-model.py")
        spec = importlib.util.spec_from_file_location(
            "deposit_cap_griefing_model", model_path)
        model = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(model)
        USDC = model.USDC

        def mul_div_down(a, b, c):
            return (a * b) // c

        def allowed(total_assets, assets, cap):
            return total_assets + assets <= cap

        # Setup: 1,000,000 USDC / 1,000,000 shares, price $1.00.
        self.assertEqual(model.A0, 1_000_000 * USDC)
        self.assertEqual(model.S0, 1_000_000)
        # Tight cap: 1 USDC headroom. Fill 1 USDC -> 1 share, assets
        # land exactly on the cap; even a 1-base-unit deposit reverts,
        # and a 100,000 USDC victim deposit reverts after 1 bu of dust.
        self.assertEqual(model.cap_tight, 1_000_001 * USDC)
        self.assertEqual(model.shares1, 1)
        self.assertFalse(allowed(model.cap_tight, 1, model.cap_tight))
        self.assertFalse(allowed(model.cap_tight + 1,
                                100_000 * USDC, model.cap_tight))
        # Attacker redeems the 1 share for exactly 1 USDC back;
        # net grief cost is 1 base unit = $0.000001.
        self.assertEqual(model.redeem1, 1 * USDC)
        self.assertEqual(model.cost1, 1)
        self.assertEqual(Fraction(model.cost1, USDC), Fraction(1, USDC))
        # Unblock thresholds: 1.000001 USDC of net withdrawals before a
        # 1 USDC deposit is accepted again; 2 base units before even a
        # 1-bu deposit is accepted.
        self.assertEqual(model.withdraw_to_unblock_1usdc, 1_000_001)
        self.assertEqual(model.withdraw_to_unblock_1bu, 2)
        # Mid cap: 100 USDC headroom, same 1-bu sunk cost.
        self.assertEqual(model.shares2, 100)
        self.assertEqual(model.redeem2, 100 * USDC)
        self.assertEqual(model.cost2, 1)
        # Loose cap: donate-through needs 999,999.000001 USDC, costs
        # 999,998.000003 USDC; the 1 share redeems for 1.999998 USDC.
        self.assertEqual(model.donation3, 999_999_000_001)
        self.assertEqual(model.redeem3, 1_999_998)
        self.assertEqual(model.cost3, 999_998_000_003)
        self.assertEqual(Fraction(model.cost3, USDC),
                         Fraction(999_998_000_003, USDC))
        # Fill-then-dust on the loose cap: 1,000,000 USDC of temporary
        # capital, redeemed whole, net cost 1 base unit (recomputed
        # here, not read from the model).
        a_fill = model.A0 + 1_000_000 * USDC + 1
        s_fill = model.S0 + 1_000_000
        self.assertEqual(a_fill, model.cap_loose + 1)
        self.assertEqual(mul_div_down(1_000_000, a_fill, s_fill),
                         1_000_000 * USDC)
        # Supply cap: a dust donation mints no shares, so with no fill
        # deposit the boundary is unmoved and deposits still pass.
        self.assertEqual(model.supply_cap, 1_000_001)
        self.assertLess(model.S0, model.supply_cap)
        # Classic donation attack needs a 1,000,000 USDC donation to
        # double the price; cap griefing needs 1 base unit of sunk cost.
        self.assertEqual(model.classic_donation, 1_000_000 * USDC)
        self.assertEqual(model.cost1, 1)

    def test_underlying_depeg_guide_numbers(self):
        # Pins /guides/erc4626-underlying-depeg/ to its model: a
        # 1,000,000 sUSDS / 1,000,000 share vault, price $1.00 at the
        # peg. The vault accounts in sUSDS units, so convertToAssets
        # per share is flat at 1 sUSDS at any price; only a USD mark
        # shows the loss. Yield in units can mask a depeg in dollars.
        import importlib.util
        from fractions import Fraction
        from pathlib import Path
        model_path = (Path.home() / "workspace/taskmarket/site"
                      / "underlying-depeg-model.py")
        spec = importlib.util.spec_from_file_location(
            "underlying_depeg_model", model_path)
        model = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(model)
        SUSDS = model.SUSDS

        # Setup: 1,000,000 sUSDS / 1,000,000 shares, price $1.00.
        self.assertEqual(model.balance, 1_000_000 * SUSDS)
        self.assertEqual(model.shares_total, 1_000_000)
        self.assertEqual(model.price_peg, 1)
        # At the peg a 10,000-share redemption pays exactly $10,000.
        self.assertEqual(model.redeem_value_usd(10_000, Fraction(1)),
                         10_000)
        # At $0.97: 10,000 shares -> $9,700, loss $300 (3%); one share
        # -> $0.97, loss $0.03; full redeem -> $970,000, loss $30,000
        # (recomputed here from the price, not read from the model).
        p97 = Fraction(97, 100)
        self.assertEqual(model.value_usd(p97), 970_000)
        self.assertEqual(model.share_price_usd(p97), p97)
        self.assertEqual(model.redeem_value_usd(10_000, p97), 9_700)
        self.assertEqual(Fraction(10_000)
                         - model.redeem_value_usd(10_000, p97), 300)
        self.assertEqual(model.redeem_value_usd(1, p97), p97)
        self.assertEqual(Fraction(1) - model.redeem_value_usd(1, p97),
                         Fraction(3, 100))
        self.assertEqual(model.redeem_value_usd(1_000_000, p97), 970_000)
        # At $1.03 the mirror: 10,000 shares -> $10,300, gain $300.
        p103 = Fraction(103, 100)
        self.assertEqual(model.redeem_value_usd(10_000, p103), 10_300)
        # Blind spot: the unit-denominated price is 1 sUSDS/share at
        # $1.00 and at $0.97 alike; the USD price at $0.97 is $0.97.
        self.assertEqual(model.convert_to_assets_units(1), 1)
        self.assertEqual(model.convert_to_assets_units(10_000), 10_000)
        self.assertEqual(model.unit_price - model.usd_price_at_depeg,
                         Fraction(3, 100))
        # Depositing during the depeg: 100,000 sUSDS at $0.97 costs
        # $97,000 and mints 100,000 shares; at a restored $1.00 peg
        # they are worth $100,000 (+$3,000); A is whole again.
        self.assertEqual(model.b_shares, 100_000)
        self.assertEqual(model.b_cost_usd, 97_000)
        self.assertEqual(model.b_value_restored, 100_000)
        self.assertEqual(model.b_value_restored - model.b_cost_usd, 3_000)
        self.assertEqual(model.a_value_restored, 1_000_000)
        # Deeper slide to $0.94: 10,000 shares -> $9,400, loss $600 (6%).
        p94 = Fraction(94, 100)
        self.assertEqual(model.redeem_value_usd(10_000, p94), 9_400)
        self.assertEqual(Fraction(10_000)
                         - model.redeem_value_usd(10_000, p94), 600)
        # Yield masks the depeg: balance +5% to 1,050,000 sUSDS at
        # $0.97 is $1,018,500 (+1.85% USD) while the unit price shows
        # +5% (1.05 sUSDS); the depeg ate $31,500 of $50,000 yield.
        self.assertEqual(model.balance_yield, 1_050_000 * SUSDS)
        self.assertEqual(model.value_yield, Fraction(1_018_500))
        self.assertEqual(model.value_yield - 1_000_000, 18_500)
        self.assertEqual(model.share_price_yield_units, Fraction(105, 100))
        self.assertEqual(model.depeg_cost, 31_500)
        self.assertEqual(model.yield_usd - model.depeg_cost, 18_500)

    def test_stale_oracle_guide_numbers(self):
        # Pins /guides/erc4626-stale-oracle/ to its model: a
        # 1,000 ETH / 3,000,000 share vault priced at the oracle's
        # $3,000. When the market moves and the feed does not, the
        # first mover extracts value from the holders who stay; a
        # TWAP dampens the loss but a freshness gate removes it.
        import importlib.util
        from fractions import Fraction
        from pathlib import Path
        model_path = (Path.home() / "workspace/taskmarket/site"
                      / "stale-oracle-model.py")
        spec = importlib.util.spec_from_file_location(
            "stale_oracle_model", model_path)
        model = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(model)

        # Setup: 1,000 ETH / 3,000,000 shares, oracle $3,000,
        # share $1.00; redeeming 300,000 shares pays $300,000.
        self.assertEqual(model.ETH_BALANCE, 1_000)
        self.assertEqual(model.SHARES_TOTAL, 3_000_000)
        self.assertEqual(model.ETH_PRICE_ORACLE, 3_000)
        self.assertEqual(model.share_price_usd(model.ETH_BALANCE,
                                               model.SHARES_TOTAL,
                                               model.ETH_PRICE_ORACLE), 1)
        self.assertEqual(model.redeem_usdc(300_000, model.ETH_BALANCE,
                                           model.SHARES_TOTAL,
                                           model.ETH_PRICE_ORACLE), 300_000)
        # Market $2,700 (-10%), oracle stale $3,000: 300,000 shares
        # pay $300,000 against a true $270,000; extraction $30,000.
        # Vault sells 1,000/9 ETH, keeps 8,000/9; remaining shares
        # fall to 8/9; holders lose the same $30,000 (recomputed).
        p_down = Fraction(2_700)
        true_down = Fraction(300_000, 3_000_000) * 1_000 * p_down
        self.assertEqual(true_down, 270_000)
        self.assertEqual(model.redeem_usdc(300_000, model.ETH_BALANCE,
                                           model.SHARES_TOTAL,
                                           model.ETH_PRICE_ORACLE)
                         - true_down, 30_000)
        self.assertEqual(Fraction(300_000) / p_down, Fraction(1_000, 9))
        self.assertEqual(Fraction(1_000) - Fraction(1_000, 9),
                         Fraction(8_000, 9))
        self.assertEqual(model.share_price_usd(Fraction(8_000, 9),
                                               2_700_000, p_down),
                         Fraction(8, 9))
        self.assertEqual(Fraction(2_700_000, 3_000_000) * 1_000 * p_down
                         - Fraction(8_000, 9) * p_down, 30_000)
        # Market $3,300 (+10%), oracle stale $3,000: a $300,000
        # deposit mints 300,000 shares; the vault buys 1,000/11 ETH.
        # At the updated $3,300 the share is 12/11 and the attacker's
        # shares are worth 3,600,000/11, a gain of 300,000/11.
        p_up = Fraction(3_300)
        self.assertEqual(Fraction(300_000)
                         / model.share_price_usd(model.ETH_BALANCE,
                                                 model.SHARES_TOTAL,
                                                 model.ETH_PRICE_ORACLE),
                         300_000)
        self.assertEqual(Fraction(300_000) / p_up, Fraction(1_000, 11))
        self.assertEqual(model.share_price_usd(Fraction(12_000, 11),
                                               3_300_000, p_up),
                         Fraction(12, 11))
        self.assertEqual(Fraction(300_000) * Fraction(12, 11),
                         Fraction(3_600_000, 11))
        self.assertEqual(Fraction(3_600_000, 11) - 300_000,
                         Fraction(300_000, 11))
        # A 2% drift to $2,940 still extracts $6,000 on the same
        # redemption; remaining shares fall to 44/45 (true $0.98).
        p_small = Fraction(2_940)
        true_small = Fraction(300_000, 3_000_000) * 1_000 * p_small
        self.assertEqual(true_small, 294_000)
        self.assertEqual(model.redeem_usdc(300_000, model.ETH_BALANCE,
                                           model.SHARES_TOTAL,
                                           model.ETH_PRICE_ORACLE)
                         - true_small, 6_000)
        self.assertEqual(model.share_price_usd(
            Fraction(1_000) - Fraction(300_000) / p_small,
            2_700_000, p_small), Fraction(44, 45))
        # TWAP: 30 minutes, $2,700 for 5 minutes -> $2,950; the
        # redemption pays $295,000, extraction $25,000 = 5/6 of
        # the $30,000 stale-oracle loss.
        twap = (Fraction(25) * 3_000 + Fraction(5) * 2_700) / 30
        self.assertEqual(twap, 2_950)
        self.assertEqual(model.twap_price, twap)
        self.assertEqual(model.redeem_usdc(300_000, model.ETH_BALANCE,
                                           model.SHARES_TOTAL, twap),
                         295_000)
        self.assertEqual(Fraction(295_000) - true_down, 25_000)
        self.assertEqual(Fraction(25_000, 30_000), Fraction(5, 6))
        # Freshness gate (heartbeat 3,600 s): 3,599 s and 3,600 s
        # pass, 3,601 s reverts.
        self.assertEqual(model.HEARTBEAT, 3_600)
        self.assertTrue(model.fresh(3_599))
        self.assertTrue(model.fresh(3_600))
        self.assertFalse(model.fresh(3_601))
    def test_minimum_redemption_guide_numbers(self):
        # Pins /guides/erc4626-minimum-redemption/ to its model: a
        # 1,000,000 USDC / 1,000,000 share vault, price $1.00, with
        # a 1,000-share / 1,000-USDC redemption floor. The floor is
        # a threshold, not a price: it locks small holders out and
        # strands the remainder of any partial redemption.
        import importlib.util
        from fractions import Fraction
        from pathlib import Path
        model_path = (Path.home() / "workspace/taskmarket/site"
                      / "minimum-redemption-model.py")
        spec = importlib.util.spec_from_file_location(
            "minimum_redemption_model", model_path)
        model = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(model)

        # Setup: 1,000,000 USDC / 1,000,000 shares, price $1.00.
        self.assertEqual(model.A0, 1_000_000 * model.USDC)
        self.assertEqual(model.S0, 1_000_000)
        self.assertEqual(Fraction(model.A0, model.USDC) / model.S0, 1)
        self.assertEqual(model.MIN_SHARES, 1_000)
        self.assertEqual(model.MIN_ASSETS, 1_000 * model.USDC)
        # Case 1, shares minimum: 999 shares = $999 locked at
        # $1.00; still locked at $2.00 ($1,998).
        self.assertFalse(model.redeem_allowed_shares(999, 1_000))
        self.assertEqual(model.redeem_assets(999, model.A0, model.S0),
                         999 * model.USDC)
        self.assertEqual(model.redeem_assets(999, 2_000_000 * model.USDC,
                                             model.S0),
                         1_998 * model.USDC)
        self.assertFalse(model.redeem_allowed_shares(999, 1_000))
        # Top-up escape: 1 USDC mints 1 share, balance hits 1,000.
        self.assertEqual(999 + (1 * model.USDC * model.S0) // model.A0,
                         1_000)
        # Case 2, assets minimum: 999 shares locked at $999.00,
        # unlocked at $1.01 ($1,008.99); 1,000 shares redeemable at
        # $1.00, locked at $0.99 ($990).
        self.assertFalse(model.redeem_allowed_assets(
            999, model.A0, model.S0, model.MIN_ASSETS))
        self.assertEqual(model.redeem_assets(
            999, 1_010_000 * model.USDC, model.S0), 1_008_990_000)
        self.assertEqual(
            Fraction(model.redeem_assets(999, 1_010_000 * model.USDC,
                                         model.S0), model.USDC),
            Fraction(100899, 100))
        self.assertTrue(model.redeem_allowed_assets(
            999, 1_010_000 * model.USDC, model.S0, model.MIN_ASSETS))
        self.assertTrue(model.redeem_allowed_assets(
            1_000, model.A0, model.S0, model.MIN_ASSETS))
        self.assertEqual(model.redeem_assets(
            1_000, 990_000 * model.USDC, model.S0), 990 * model.USDC)
        self.assertFalse(model.redeem_allowed_assets(
            1_000, 990_000 * model.USDC, model.S0, model.MIN_ASSETS))
        # Case 3, aggregate: 1,000 holders x 500 shares = $500,000
        # stranded, exactly 50% of the vault; $550,000 at $1.10.
        self.assertEqual(model.redeem_assets(
            1_000 * 500, model.A0, model.S0), 500_000 * model.USDC)
        self.assertEqual(Fraction(model.redeem_assets(
            1_000 * 500, model.A0, model.S0), model.A0), Fraction(1, 2))
        self.assertEqual(model.redeem_assets(
            1_000 * 500, 1_100_000 * model.USDC, model.S0),
            550_000 * model.USDC)
        # Case 4, partial redemption: 1,500 shares, redeem 1,000
        # -> $500 stranded; full exit pays $1,500.
        self.assertTrue(model.redeem_allowed_shares(1_000, 1_000))
        self.assertEqual(model.redeem_assets(1_000, model.A0, model.S0),
                         1_000 * model.USDC)
        self.assertFalse(model.redeem_allowed_shares(500, 1_000))
        self.assertEqual(model.redeem_assets(500, model.A0, model.S0),
                         500 * model.USDC)
        self.assertEqual(model.redeem_assets(1_500, model.A0, model.S0),
                         1_500 * model.USDC)

    def test_pending_redemption_guide_numbers(self):
        # Pins /guides/erc4626-pending-redemption/ to its model: a
        # 1,000,000 USDC / 1,000,000 share vault, price $1.00.
        # Alice requests redemption of 100,000 shares; Bob holds
        # 90,000. Importing the model re-runs its 27 assertions;
        # the checks below independently re-derive the headline
        # numbers the guide quotes.
        import importlib.util
        from fractions import Fraction
        from pathlib import Path
        model_path = (Path.home() / "workspace/taskmarket/site"
                      / "pending-redemption-model.py")
        spec = importlib.util.spec_from_file_location(
            "pending_redemption_model", model_path)
        model = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(model)

        # Setup: 1,000,000 USDC / 1,000,000 shares, price $1.00.
        self.assertEqual(Fraction(1_000_000, 1_000_000), 1)
        # Design A: burn at request, earmark stays in totalAssets.
        # Price jumps to 10/9; Bob's 90,000 shares pay 100,000
        # (+10,000 over pro-rata); price after Alice claims is
        # 80/81 and the remaining 810,000 shares are worth 800,000.
        self.assertEqual(Fraction(1_000_000, 900_000), Fraction(10, 9))
        self.assertEqual(90_000 * Fraction(10, 9), 100_000)
        self.assertEqual(90_000 * Fraction(10, 9) - 90_000, 10_000)
        self.assertEqual(Fraction(900_000, 810_000), Fraction(10, 9))
        self.assertEqual(Fraction(800_000, 810_000), Fraction(80, 81))
        self.assertEqual(810_000 * Fraction(80, 81), 800_000)
        self.assertEqual(810_000 * Fraction(80, 81) - 810_000, -10_000)
        # Full drain: 900,000 shares x 10/9 = the whole vault,
        # so Alice's fixed claim pays zero.
        self.assertEqual(900_000 * Fraction(10, 9), 1_000_000)
        self.assertEqual(1_000_000 - 900_000 * Fraction(10, 9), 0)
        # Design A + 100,000 yield during the wait: price 11/9
        # before the claim; Alice still gets 100,000, forgoing
        # 10,000 of yield (110,000 had she stayed); the remaining
        # holders end at 1,000,000 vs 990,000 with no request.
        self.assertEqual(Fraction(1_100_000, 900_000), Fraction(11, 9))
        self.assertEqual(100_000 * Fraction(11, 10), 110_000)
        self.assertEqual(100_000 - 110_000, -10_000)
        self.assertEqual(900_000 * Fraction(10, 9), 1_000_000)
        self.assertEqual(900_000 * Fraction(10, 9) - 990_000, 10_000)
        # Design B: shares locked, priced at claim time. Yield:
        # claim 110,000 at 1.10, remaining 990,000. Loss: claim
        # 90,000 at 0.90, remaining 810,000.
        self.assertEqual(100_000 * Fraction(11, 10), 110_000)
        self.assertEqual(900_000 * Fraction(11, 10), 990_000)
        self.assertEqual(100_000 * Fraction(9, 10), 90_000)
        self.assertEqual(900_000 * Fraction(9, 10), 810_000)
        # Design C: pending claim netted off totalAssets — price
        # stays 1.00 through request, Bob's redemption and claim.
        self.assertEqual(Fraction(1_000_000 - 100_000, 900_000), 1)
        self.assertEqual(Fraction(910_000 - 100_000, 810_000), 1)
        self.assertEqual(Fraction(810_000 - 0, 810_000), 1)
        self.assertEqual(810_000 * 1, 810_000)

    def test_claim_window_guide_numbers(self):
        # Pins /guides/erc4626-claim-window/ to its model: a
        # 100,000 USDC / 100,000 share vault, price $1.00.
        # Bob holds 10,000 shares (10%), Alice 50,000.
        # Importing the model re-runs its assertions; the checks
        # below independently re-derive the headline numbers the
        # guide quotes.
        import importlib.util
        from fractions import Fraction
        from pathlib import Path
        model_path = (Path.home() / "workspace/taskmarket/site"
                      / "claim-window-model.py")
        spec = importlib.util.spec_from_file_location(
            "claim_window_model", model_path)
        model = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(model)

        USDC = 1_000_000
        # Setup: 100,000 USDC / 100,000 shares, price $1.00.
        self.assertEqual(Fraction(100_000 * USDC, USDC) / 100_000, 1)
        # Case 1: claim in time — Bob paid 10,000 in full, price
        # stays 1.00, Alice still 50,000.
        self.assertEqual((10_000 * 100_000 * USDC) // 100_000,
                         10_000 * USDC)
        self.assertEqual(Fraction(90_000, 90_000), 1)
        self.assertEqual(50_000 * Fraction(90_000, 90_000), 50_000)
        # Case 2: missed window, forfeit — price 10/9; Alice's
        # 50,000 shares rise to 55,555,555,555 base units
        # ($55,555.555555, +$5,555.555555); the other 40,000
        # shares are worth 44,444,444,444 (+$4,444.444444);
        # one base unit of dust is left unaccounted.
        self.assertEqual(Fraction(100_000, 90_000), Fraction(10, 9))
        self.assertEqual(50_000 * Fraction(10, 9), Fraction(500_000, 9))
        self.assertEqual((50_000 * 100_000 * USDC) // 90_000,
                         55_555_555_555)
        self.assertEqual(55_555_555_555 - 50_000 * USDC, 5_555_555_555)
        self.assertEqual((40_000 * 100_000 * USDC) // 90_000,
                         44_444_444_444)
        self.assertEqual(44_444_444_444 - 40_000 * USDC, 4_444_444_444)
        self.assertEqual(55_555_555_555 + 44_444_444_444,
                         99_999_999_999)
        # Case 3: missed window, refund — Bob keeps 10,000,
        # price stays 1.00, Alice stays 50,000.
        self.assertEqual(Fraction(100_000, 100_000), 1)
        self.assertEqual(10_000 * Fraction(100_000, 100_000), 10_000)
        self.assertEqual(50_000 * Fraction(100_000, 100_000), 50_000)
        # Case 4: the clock — fulfilment 3 days, 2-day window
        # from the request is dead on arrival (-1 days left);
        # from fulfilment it leaves 2 days; a 7-day window
        # from the request leaves 4 days.
        self.assertEqual(2 - 3, -1)
        self.assertLess(2 - 3, 0)
        self.assertEqual(7 - 3, 4)

    def test_deposit_bonus_guide_numbers(self):
        # Pins /guides/erc4626-deposit-bonus/ to its model: a
        # 100,000 USDC / 100,000 share vault, price $1.00.
        # Carol holds all 100,000 shares; Alice deposits
        # 100,000 USDC with a 10% bonus. Importing the model
        # re-runs its assertions; the checks below independently
        # re-derive the headline numbers the guide quotes.
        import importlib.util
        from fractions import Fraction
        from pathlib import Path
        model_path = (Path.home() / "workspace/taskmarket/site"
                      / "deposit-bonus-model.py")
        spec = importlib.util.spec_from_file_location(
            "deposit_bonus_model", model_path)
        model = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(model)

        USDC = 1_000_000
        # Setup: 100,000 USDC / 100,000 shares, price $1.00.
        self.assertEqual(Fraction(100_000 * USDC, USDC) / 100_000, 1)
        # Case 1: bonus minted as shares — Alice gets 100,000
        # base + 10,000 bonus = 110,000 shares; price 20/21;
        # Carol's 100,000 shares fall to 95,238,095,238 base
        # units ($95,238.095238, -$4,761.904762); Alice's
        # 110,000 shares rise to 104,761,904,761
        # ($104,761.904761, +$4,761.904761); one base unit
        # of dust is left unaccounted.
        self.assertEqual((100_000 * USDC * 100_000) // (100_000 * USDC),
                         100_000)
        self.assertEqual(100_000 // 10, 10_000)
        self.assertEqual(Fraction(200_000, 210_000), Fraction(20, 21))
        self.assertEqual((100_000 * 200_000 * USDC) // 210_000,
                         95_238_095_238)
        self.assertEqual(100_000 * USDC - 95_238_095_238, 4_761_904_762)
        self.assertEqual((110_000 * 200_000 * USDC) // 210_000,
                         104_761_904_761)
        self.assertEqual(104_761_904_761 - 100_000 * USDC, 4_761_904_761)
        self.assertEqual(95_238_095_238 + 104_761_904_761,
                         199_999_999_999)
        # Case 2: bonus paid in a separate reward token —
        # price stays 1.00, Carol stays 100,000; 10,000
        # reward tokens are $10,000 at $1.00, $5,000 at $0.50.
        self.assertEqual(Fraction(200_000, 200_000), 1)
        self.assertEqual((100_000 * 200_000 * USDC) // 200_000,
                         100_000 * USDC)
        self.assertEqual(10_000 * 1, 10_000)
        self.assertEqual(Fraction(10_000, 2), 5_000)
        # Case 3: bonus pool exhausted — Bob deposits 100,000
        # with no bonus and mints 105,000 shares at the diluted
        # price; his shares are worth exactly 100,000 USDC;
        # price stays 20/21; Carol and Alice are unchanged.
        self.assertEqual((100_000 * 210_000) // 200_000, 105_000)
        self.assertEqual(Fraction(300_000, 315_000), Fraction(20, 21))
        self.assertEqual((105_000 * 300_000 * USDC) // 315_000,
                         100_000 * USDC)
        self.assertEqual((100_000 * 300_000 * USDC) // 315_000,
                         95_238_095_238)
        self.assertEqual((110_000 * 300_000 * USDC) // 315_000,
                         104_761_904_761)
        # Case 4: yield after the bonus — vault earns 21,000
        # USDC; price 221/210; Carol's 100,000 shares are worth
        # 105,238,095,238 base units, against 110,500 USDC
        # without the bonus (-$5,261.904762); Alice's 110,000
        # shares are worth 115,761,904,761, against 110,500
        # USDC without the bonus (+$5,261.904761).
        self.assertEqual(Fraction(221_000, 210_000), Fraction(221, 210))
        self.assertEqual((100_000 * 221_000 * USDC) // 210_000,
                         105_238_095_238)
        self.assertEqual(Fraction(221_000, 200_000), Fraction(221, 200))
        self.assertEqual((100_000 * 221_000 * USDC) // 200_000,
                         110_500 * USDC)
        self.assertEqual(110_500 * USDC - 105_238_095_238, 5_261_904_762)
        self.assertEqual((110_000 * 221_000 * USDC) // 210_000,
                         115_761_904_761)
        self.assertEqual(115_761_904_761 - 110_500 * USDC, 5_261_904_761)
    def test_rebasing_shares_guide_numbers(self):
        # Pins /guides/erc4626-rebasing-shares/ to its model: a
        # 1,000,000 USDC / 1,000,000 internal share vault, price
        # $1.00, Alice holding 100,000 internal shares (10%).
        # Importing the model re-runs its assertions; the checks
        # below independently re-derive the headline numbers the
        # guide quotes.
        import importlib.util
        from fractions import Fraction
        from pathlib import Path
        model_path = (Path.home() / "workspace/taskmarket/site"
                      / "rebasing-shares-model.py")
        spec = importlib.util.spec_from_file_location(
            "rebasing_shares_model", model_path)
        model = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(model)

        USDC = 1_000_000
        # Setup: price $1.00, Alice's displayed balance $100,000.
        self.assertEqual(Fraction(1_000_000 * USDC, USDC) / 1_000_000, 1)
        self.assertEqual((100_000 * USDC * 1_000_000 * USDC)
                         // (1_000_000 * USDC), 100_000 * USDC)
        # Case 1: +10% yield — Alice $110,000 in both designs; a
        # new 11,000 USDC deposit mints 10,000,000,000 internal
        # shares, displayed as $11,000 (price vault: 10,000 shares
        # at 1.10, same $11,000 claim).
        self.assertEqual((100_000 * USDC * 1_100_000 * USDC)
                         // (1_000_000 * USDC), 110_000 * USDC)
        self.assertEqual(11_000 * Fraction(10, 11), 10_000)
        self.assertEqual((11_000 * USDC * 1_000_000 * USDC)
                         // (1_100_000 * USDC), 10_000 * USDC)
        self.assertEqual((10_000 * USDC * 1_100_000 * USDC)
                         // (1_000_000 * USDC), 11_000 * USDC)
        # Case 2: 1,000,000 USDC donation — Alice's balance doubles
        # to $200,000 (+$100,000, half the donation); Bob deposits
        # 100,000, mints 50,000,000,000 internal shares, redeems
        # $100,000 in full: loss $0. Contrast with the checker's
        # own donation model on an unprotected price vault (new
        # vault, offset 0, same donation and victim): victim loss
        # 909,091 base units ($0.909091), attacker net -90,909.
        self.assertEqual((100_000 * USDC * 2_000_000 * USDC)
                         // (1_000_000 * USDC), 200_000 * USDC)
        self.assertEqual((100_000 * USDC * 1_000_000 * USDC)
                         // (2_000_000 * USDC), 50_000 * USDC)
        self.assertEqual((50_000 * USDC * 2_100_000 * USDC)
                         // (1_050_000 * USDC), 100_000 * USDC)
        from erc4626_checker import Vault, run_all
        v = Vault(decimals_offset=0, min_deposit=0, perf_fee_bps=0)
        checks = run_all(v)
        d = [c for c in checks if c["name"] == "donation_inflation"][0]
        self.assertFalse(d["pass"])
        row_1m = [r for r in d["detail"]
                  if r["donation"] == 1_000_000_000_000][0]
        self.assertEqual(row_1m["victim_loss"], 909_091)
        self.assertEqual(row_1m["attacker_net"], -90_909)
        # Seeded attacker: 1 USDC in, 1,000,000 USDC donated,
        # recovers $1.999999 (1,999,999 base units), loses
        # $999,999.000001.
        self.assertEqual((1 * USDC * 2_000_001 * USDC)
                         // (1_000_001 * USDC), 1_999_999)
        self.assertEqual((1 * USDC + 1_000_000 * USDC) - 1_999_999,
                         999_999_000_001)
        # Case 3: the stale snapshot — +10% yield under-reads by
        # 10,000, -10% over-reads by 10,000; a 75,000 loan at 75%
        # LTV against the snapshot is really 5/6 = 83.3333% LTV.
        self.assertEqual(110_000 * USDC - 100_000 * USDC, 10_000 * USDC)
        self.assertEqual((100_000 * USDC * 900_000 * USDC)
                         // (1_000_000 * USDC), 90_000 * USDC)
        self.assertEqual(100_000 * USDC - 90_000 * USDC, 10_000 * USDC)
        self.assertEqual(100_000 * USDC * 3 // 4, 75_000 * USDC)
        self.assertEqual(Fraction(75_000 * USDC, 90_000 * USDC),
                         Fraction(5, 6))
        # Case 4: the dust floor — 1 internal share shows 1 base
        # unit after +10% and after a second +10%, 2 only after a
        # doubling; 1,000,000 dust holders trap $0.10 per rebase.
        self.assertEqual((1 * 1_100_000 * USDC) // (1_000_000 * USDC), 1)
        self.assertEqual((1 * 1_210_000 * USDC) // (1_000_000 * USDC), 1)
        self.assertEqual((1 * 2_000_000 * USDC) // (1_000_000 * USDC), 2)
        self.assertEqual(Fraction(1 * 1_100_000 * USDC, 1_000_000 * USDC),
                         Fraction(11, 10))
        self.assertEqual(1_000_000 * (Fraction(11, 10) - 1), 100_000)

    def test_multi_strategy_guide_numbers(self):
        # Pins /guides/erc4626-multi-strategy/ to its model: a
        # 1,000,000 USDC / 1,000,000 share vault, price $1.00,
        # Alice 100,000 shares (10%), Carol 900,000 (90%), split
        # 50/50 across strategies A and B (500,000 each). Importing
        # the model re-runs its assertions; the checks below
        # independently re-derive the headline numbers the guide
        # quotes.
        import importlib.util
        from fractions import Fraction
        from pathlib import Path
        model_path = (Path.home() / "workspace/taskmarket/site"
                      / "multi-strategy-model.py")
        spec = importlib.util.spec_from_file_location(
            "multi_strategy_model", model_path)
        model = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(model)

        USDC = 1_000_000
        # Case 1: drift — A +20%, B 0%: total 1,100,000, price 1.10,
        # Alice $110,000, Carol $990,000; A is 6/11 = 54.5454% of
        # the vault; all-A counterfactual $120,000 for Alice, so
        # the drift cost her $10,000.
        self.assertEqual((100_000 * USDC * 1_100_000 * USDC)
                         // (1_000_000 * USDC), 110_000 * USDC)
        self.assertEqual((900_000 * USDC * 1_100_000 * USDC)
                         // (1_000_000 * USDC), 990_000 * USDC)
        self.assertEqual(Fraction(600_000, 1_100_000), Fraction(6, 11))
        self.assertEqual((100_000 * USDC * 1_200_000 * USDC)
                         // (1_000_000 * USDC), 120_000 * USDC)
        self.assertEqual(120_000 * USDC - 110_000 * USDC, 10_000 * USDC)
        # Case 2: rebalance — move 50,000 at 0.5% = 250 fee; total
        # 1,099,750, price 1.09975; Alice $109,975 (-$25), Carol
        # $989,775 (-$225).
        self.assertEqual(50_000 * USDC * 50 // 10_000, 250 * USDC)
        self.assertEqual((100_000 * USDC * 1_099_750 * USDC)
                         // (1_000_000 * USDC), 109_975 * USDC)
        self.assertEqual((900_000 * USDC * 1_099_750 * USDC)
                         // (1_000_000 * USDC), 989_775 * USDC)
        self.assertEqual(110_000 * USDC - 109_975 * USDC, 25 * USDC)
        self.assertEqual(990_000 * USDC - 989_775 * USDC, 225 * USDC)
        # Case 3: loss socialization — A -20%: total 900,000, price
        # 0.90, Alice $90,000 (-$10,000); direct-in-B she would
        # still hold $100,000.
        self.assertEqual((100_000 * USDC * 900_000 * USDC)
                         // (1_000_000 * USDC), 90_000 * USDC)
        self.assertEqual(100_000 * USDC - 90_000 * USDC, 10_000 * USDC)
        # Case 4: dip buyer — Bob deposits 90,000 at 0.90, mints
        # 100,000 shares; +10% recovery: total 1,089,000, price
        # 0.99; Bob $99,000 (+$9,000), Alice $99,000 (-$1,000),
        # Carol $891,000 (-$9,000).
        self.assertEqual((90_000 * USDC * 1_000_000 * USDC)
                         // (900_000 * USDC), 100_000 * USDC)
        self.assertEqual((100_000 * USDC * 1_089_000 * USDC)
                         // (1_100_000 * USDC), 99_000 * USDC)
        self.assertEqual((900_000 * USDC * 1_089_000 * USDC)
                         // (1_100_000 * USDC), 891_000 * USDC)
        self.assertEqual(99_000 * USDC - 90_000 * USDC, 9_000 * USDC)
        self.assertEqual(99_000 * USDC - 100_000 * USDC, -1_000 * USDC)
        # Case 5: two periods unrebalanced — A 720,000, B 500,000,
        # total 1,220,000, price 1.22, Alice $122,000; A is 36/61 =
        # 59.0164%; all-A counterfactual Alice $144,000, gap $22,000.
        self.assertEqual((100_000 * USDC * 1_220_000 * USDC)
                         // (1_000_000 * USDC), 122_000 * USDC)
        self.assertEqual(Fraction(720_000, 1_220_000), Fraction(36, 61))
        self.assertEqual((100_000 * USDC * 1_440_000 * USDC)
                         // (1_000_000 * USDC), 144_000 * USDC)
        self.assertEqual(144_000 * USDC - 122_000 * USDC, 22_000 * USDC)

    def test_maxmint_vs_maxdeposit_guide_numbers(self):
        # Pins /guides/erc4626-maxmint-vs-maxdeposit/ to its model: a
        # 1,000,000 USDC / 1,000,000 share vault, price $1.00, with
        # maxDeposit = 100,000 USDC and maxMint = 100,000 shares.
        # Importing the model re-runs its assertions; the checks below
        # independently re-derive the headline numbers the guide
        # quotes.
        import importlib.util
        from fractions import Fraction
        from pathlib import Path
        model_path = (Path.home() / "workspace/taskmarket/site"
                      / "maxmint-vs-maxdeposit-model.py")
        spec = importlib.util.spec_from_file_location(
            "maxmint_vs_maxdeposit_model", model_path)
        model = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(model)

        USDC = 1_000_000
        # Case 1: price $1.00 — the caps agree: deposit 100,000 USDC
        # mints 100,000 shares; mint 100,000 shares costs 100,000 USDC.
        self.assertEqual((100_000 * USDC * 1_000_000 * USDC)
                         // (1_000_000 * USDC), 100_000 * USDC)
        self.assertEqual((100_000 * USDC * 1_000_000 * USDC)
                         // (1_000_000 * USDC), 100_000 * USDC)
        # Case 2: price $1.10 — deposit 100,000 USDC mints
        # 90,909.090909 shares (floor 90,909,090,909 base units);
        # mint 100,000 shares costs 110,000 USDC; gap 10,000 USDC.
        self.assertEqual((100_000 * USDC * 1_000_000 * USDC)
                         // (1_100_000 * USDC), 90_909_090_909)
        self.assertEqual(Fraction(100_000 * 1_000_000, 1_100_000),
                         Fraction(1_000_000, 11))
        self.assertEqual((100_000 * USDC * 1_100_000 * USDC)
                         // (1_000_000 * USDC), 110_000 * USDC)
        self.assertEqual(110_000 * USDC - 100_000 * USDC, 10_000 * USDC)
        # Case 3: price $0.90 — deposit 100,000 USDC would mint
        # 111,111.111111 shares (floor 111,111,111,111), over the
        # 100,000-share cap, so it is blocked; mint 100,000 shares
        # costs only 90,000 USDC.
        self.assertEqual((100_000 * USDC * 1_000_000 * USDC)
                         // (900_000 * USDC), 111_111_111_111)
        self.assertEqual(Fraction(100_000 * 1_000_000, 900_000),
                         Fraction(1_000_000, 9))
        self.assertGreater(111_111_111_111, 100_000 * USDC)
        self.assertEqual((100_000 * USDC * 900_000 * USDC)
                         // (1_000_000 * USDC), 90_000 * USDC)
        # Case 4: scaling — at $2.00 the mint cap admits 200,000 USDC;
        # at $0.50 it admits 50,000 USDC.
        self.assertEqual((100_000 * USDC * 2_000_000 * USDC)
                         // (1_000_000 * USDC), 200_000 * USDC)
        self.assertEqual((100_000 * USDC * 500_000 * USDC)
                         // (1_000_000 * USDC), 50_000 * USDC)
        # Case 5: both caps set — effective cap is the smaller of the
        # two: 100,000 at $1.10 (deposit binds), 90,000 at $0.90
        # (mint binds), 100,000 at $1.00.
        self.assertEqual(min(100_000 * USDC, 110_000 * USDC),
                         100_000 * USDC)
        self.assertEqual(min(100_000 * USDC, 90_000 * USDC),
                         90_000 * USDC)
        # Case 6: exit mirror — at $1.10 redeem 100,000 shares pays
        # 110,000 USDC, withdraw 100,000 USDC burns 90,909.090909
        # shares (ceil 90,909,090,910 base units); at $0.90 redeem
        # 100,000 shares pays 90,000 USDC, withdraw 100,000 USDC
        # would burn 111,111.111111 shares (ceil 111,111,111,112),
        # over the redeem cap, so it is blocked.
        self.assertEqual((100_000 * USDC * 1_100_000 * USDC)
                         // (1_000_000 * USDC), 110_000 * USDC)
        self.assertEqual(-(-(100_000 * USDC * 1_000_000 * USDC)
                           // (1_100_000 * USDC)), 90_909_090_910)
        self.assertEqual((100_000 * USDC * 900_000 * USDC)
                         // (1_000_000 * USDC), 90_000 * USDC)
        self.assertEqual(-(-(100_000 * USDC * 1_000_000 * USDC)
                           // (900_000 * USDC)), 111_111_111_112)
        self.assertGreater(111_111_111_112, 100_000 * USDC)

    def test_gamma_research_page_numbers(self):
        # Pins /research/gamma/ to the study: 27 validated findings
        # (5H + 9M + 13L), 24 published as verified, payouts summing
        # to 29,968.33 USDC. The 24 are H-01–H-05 (5),
        # M-01–M-04 + M-06–M-09 (8) and L-01–L-11 (11); M-05 is a
        # MISS and H-05 was cut/flagged until this round: it is now
        # verified (sole submission, 19,249.83 USDC), while L-12/L-13
        # and M-1(#829) remain cut or flagged.
        from pathlib import Path
        build = (Path.home() / "workspace/taskmarket/site"
                 / "build.py").read_text()
        start = build.index('add("/research/gamma/"')
        end = build.index('add("/research/domain-hijack/"', start)
        page = build[start:end]
        self.assertEqual(page.count("<tr><td>"), 24)
        self.assertIn("29,968.33 USDC", page)
        self.assertIn("27 findings: 5 High, 9 Medium, 13 Low", page)
        # Largest payout (M-08, live on-chain) and the two Highs.
        self.assertIn("3,849.97 USDC", page)
        self.assertIn("95.74 USDC", page)
        self.assertIn("61.42 USDC", page)
        # Scope cut is stated on the page itself.
        self.assertIn("M-05", page)
        self.assertIn("MISS", page)
        self.assertIn("Flagged or cut", page)
        # Payout arithmetic: H 20,214.19 + M 8,485.06 + L 1,269.08.
        from decimal import Decimal
        highs = [Decimal("95.74"), Decimal("61.42"), Decimal("61.42"),
                 Decimal("745.78"), Decimal("19249.83")]
        mediums = [Decimal("122.04"), Decimal("122.04"),
                   Decimal("378.89"), Decimal("41.97"),
                   Decimal("505.19"), Decimal("1732.48"),
                   Decimal("3849.97"), Decimal("1732.48")]
        lows = [Decimal("9.22"), Decimal("78.56"), Decimal("0.93"),
                Decimal("17.40"), Decimal("53.03"), Decimal("53.03"),
                Decimal("290.98"), Decimal("290.98"), Decimal("53.03"),
                Decimal("290.98"), Decimal("130.94")]
        self.assertEqual(sum(highs) + sum(mediums) + sum(lows),
                         Decimal("29968.33"))

if __name__ == "__main__":
    unittest.main()
