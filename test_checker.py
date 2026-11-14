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
        prev = results["preview_consistency"]["detail"][0]
        self.assertIn("10,000,000,000,000,000 shares", prev)
        self.assertIn("0.000001 USDC", prev)
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


if __name__ == "__main__":
    unittest.main()
