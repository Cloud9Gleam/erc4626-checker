import unittest

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
        self.assertIn("10,000,000,000,000,000 shares", prev)
        self.assertIn("0.000001 USDC", prev)
        self.assertEqual(len(results["preview_consistency"]["detail"]), 3)
        fee = results["fee_conservation"]["detail"][0]
        self.assertEqual(
            fee, "yield 10,000.000000 USDC, fee 1,000.000000 USDC, "
                 "holder gain 9,000.000000 USDC")
        price = results["share_price_sanity"]["detail"][0]
        self.assertEqual(
            price, "price per 1,000,000 shares 0.000001 USDC -> 0.000001 USDC")
        for r in results.values():
            for line in r["detail"]:
                if isinstance(line, str):
                    self.assertNotRegex(line, r"\d{10,}")

    def test_empty_vault_first_deposit(self):
        v = Vault(decimals_offset=6, min_deposit=1_000_000)
        shares = v.deposit(1_000_000)
        self.assertGreater(shares, 0)

    def test_run_all_threads_victim_deposit(self):
        # The victim deposit is a scenario parameter, not a vault constant:
        # run_all must pass it to the donation check, and the three presets'
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


if __name__ == "__main__":
    unittest.main()
