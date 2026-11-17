#!/usr/bin/env python3
"""Epoch pro-rata redemption -- exact-integer model for a future guide.

Named source (read 2026-11-17, this run): Centrifuge pools.
- Epoch batching + per-user max claimable amounts: Centrifuge docs,
  "Investment Request Lifecycle" (deepwiki mirror of the official
  docs, crawled 2026-11-03): requests are grouped into epochs,
  ShareClassManager stores `maxDepositClaims()` / `maxRedeemClaims()`,
  the Assessor "validates investment constraints (max supply,
  redemption limits)". Five stages: Pending -> Approved (cannot
  cancel) -> Issued/Revoked at the calculated price -> Fulfilled
  (vault notified, maxClaims = what the user can claim) -> Claimed.
- The pro-rata rule itself: Ark Funds help center (a Centrifuge
  issuer fund): "Up to 5% of the fund's total assets can be redeemed
  every quarter. If cumulative redemption requests are over 5% of
  total fund assets, investors would receive a pro-rata portion of
  their requested amount, depending on the redemption demand of
  other investors."

Question: when an epoch's redemption cap binds and the epoch fills
requests PRO-RATA instead of first-come-first-served, who gains, who
loses, and what does integer division leave behind?

State variables (rule (k)):
- Keyed mappings: requests[user] (shares requested this epoch),
  filled[user] (assets paid this epoch), rolled[user] (unfilled
  shares carried to the next epoch).
- Cumulative variables: totalRequested (shares), totalFilled
  (assets), epochAvailable (assets the cap releases this epoch).
- Privileged-address variables: cap set by the manager / Assessor
  (here: 5% of total assets per epoch), share price set by the
  manager at epoch close (here: exactly 1.00 throughout -- no loss,
  no donation, so the cap alone is the only thing being varied).

Pre-build check against the neighbours (all read 2026-11-17):
- withdrawal-cap-model.py: a cap as a binary allow/deny on one call
  or one block. No partial fill, no pro-rata, no roll-forward.
- queue-priority-model.py / withdrawal-queue-model.py: FIFO order
  (or pay-to-jump it). Fill is all-or-nothing by position; a small
  early requester is paid in full before a big late one gets a cent.
- async-cancel-model.py scenario 5: mentions pro-rata in ONE line
  ("first nine paid in full, tenth gets 0; pro-rata: each 9,000")
  for a LOSS-driven shortfall with ten EQUAL requests -- no cap,
  no unequal requests, no integer dust, no roll-forward, no
  comparison of who gains vs FCFS. This model is the cap-driven,
  unequal-request, dust-and-roll-forward version of that line.
- queue-loss-model.py: loss recognised while queued; request-price
  vs claim-price. No cap, no pro-rata split of a fixed pot.
- donation-async-vault-model.py: price taken at fulfilment time.
  Here the price is 1.00 at every step on purpose -- the wedge is
  the ALLOCATION rule, not the price.

Headline results (all pinned by the scenarios below):
- Pro-rata is NOT neutral vs FCFS: with a 50,000 cap and requests
  10k / 10k / 80k, FCFS pays the two small requesters in full
  (10,000 each) and the big one 30,000; pro-rata pays 5,000 / 5,000
  / 40,000 -- it moves 10,000 from the small early requesters to
  the large late one. "Fair share" rewards the biggest request.
- Integer dust is real and stays with the vault: three equal 7,000
  requests against 10,000 available fill 3,333.333333 each, floored
  to 3,333,333,333 base units; 1 base unit (0.000001 USDC) is never
  allocated to anyone.
- Rolled requests have NO seniority: an unfilled remainder competes
  in the next epoch on equal terms with a brand-new request, so a
  new 50,000 request halves a rolled 5,000 remainder to 2,500.
  A FIFO queue preserves seniority; pro-rata destroys it.
- Dilution has no profiteer: inflating total demand shrinks
  everyone else's fraction, but the diluter's own fill is the same
  fraction of a bigger request -- and approved requests cannot be
  cancelled (Centrifuge: "Request cannot be cancelled"), so the
  diluter cannot take the fraction back. Delay for all, profit
  for none.

Model: exact integers, USDC 6 decimals, base units. Price 1.00
throughout; fill_i = requests[i] * available // totalRequested.

Run: python3 epoch-prorata-redemption-model.py
Status: numbers verified 2026-11-17 21:17 run (this file); guide page,
test def and build integration completed 2026-11-17 ~21:19-21:27 run
(self-innovation): guide add() + /guides/ index <li> + hero 152->155
in build.py, 2 test defs in erc4626-checker/test_checker.py, all green.
"""
USDC = 1_000_000


def prorata_fill(requests, available):
    """Return (fills, dust). fills[i] = req_i * available // total."""
    total = sum(requests)
    if total == 0:
        return [0] * len(requests), available
    fills = [r * available // total for r in requests]
    return fills, available - sum(fills)


def fcfs_fill(requests, available):
    """First-come-first-served, for comparison. Returns fills."""
    fills, left = [], available
    for r in requests:
        f = min(r, left)
        fills.append(f)
        left -= f
    return fills


def main():
    A = 1_000_000 * USDC   # vault assets; S = 1,000,000 shares, price 1.00
    CAP = 50_000 * USDC    # 5% of total assets per epoch (Ark Funds rule)

    # --- 1. Even split: cap binds, pro-rata fills exactly ---------
    req1 = [30_000 * USDC, 20_000 * USDC, 10_000 * USDC, 40_000 * USDC]
    fills1, dust1 = prorata_fill(req1, CAP)
    print("1. requests 30k/20k/10k/40k, cap 50k -> fills",
          [f // USDC for f in fills1], "dust", dust1)
    print(f"   unfilled rolls forward: "
          f"{(sum(req1) - sum(fills1)) // USDC:,} USDC")

    # --- 2. Integer dust: three equal requests, indivisible pot ----
    req2 = [7_000 * USDC] * 3
    avail2 = 10_000 * USDC
    fills2, dust2 = prorata_fill(req2, avail2)
    print(f"2. requests 7k x3, available 10k -> each "
          f"{fills2[0]} base units ({fills2[0] / USDC:.6f} USDC), "
          f"sum {sum(fills2)}, dust {dust2} base unit")

    # --- 3. Pro-rata vs FCFS: who gains ----------------------------
    req3 = [10_000 * USDC, 10_000 * USDC, 80_000 * USDC]
    fills3, _ = prorata_fill(req3, CAP)
    fcfs3 = fcfs_fill(req3, CAP)
    print("3. requests 10k/10k/80k, cap 50k:")
    print(f"   pro-rata fills (USDC): {[f // USDC for f in fills3]}")
    print(f"   FCFS fills (USDC):     {[f // USDC for f in fcfs3]}")
    print(f"   pro-rata moves "
          f"{(fcfs3[0] - fills3[0]) // USDC:,} USDC from Alice, "
          f"{(fcfs3[1] - fills3[1]) // USDC:,} USDC from Bob, to Eve "
          f"+{(fills3[2] - fcfs3[2]) // USDC:,} USDC")

    # --- 4. Roll-forward has no seniority --------------------------
    rolled = [r - f for r, f in zip(req3, fills3)]  # 5k/5k/40k
    frank = 50_000 * USDC                          # brand-new request
    req4 = rolled + [frank]
    fills4, _ = prorata_fill(req4, CAP)
    print(f"4. epoch 2: rolled 5k/5k/40k + new 50k, cap 50k -> fills "
          f"(USDC) {[f // USDC for f in fills4]}")
    print(f"   Alice's rolled 5k fills only {fills4[0] // USDC} USDC -- "
          f"a new request halved it; no seniority")

    # --- 5. No new requests next epoch: roll clears in full --------
    fills5, _ = prorata_fill(rolled, CAP)
    print(f"5. epoch 2 with no new requests: rolled fills "
          f"(USDC) {[f // USDC for f in fills5]} in full")

    # Exact assertions.
    # 1: 30k/20k/10k/40k of 100k, cap 50k -> halves, no dust.
    assert fills1 == [15_000 * USDC, 10_000 * USDC,
                      5_000 * USDC, 20_000 * USDC]
    assert dust1 == 0
    assert sum(req1) - sum(fills1) == 50_000 * USDC
    # 2: 7,000 * 10,000 // 21,000 floors to 3,333,333,333; dust 1.
    assert fills2 == [3_333_333_333] * 3
    assert sum(fills2) == 9_999_999_999
    assert dust2 == 1
    # 3: pro-rata 5k/5k/40k vs FCFS 10k/10k/30k.
    assert fills3 == [5_000 * USDC, 5_000 * USDC, 40_000 * USDC]
    assert fcfs3 == [10_000 * USDC, 10_000 * USDC, 30_000 * USDC]
    assert (fcfs3[0] - fills3[0]) == 5_000 * USDC
    assert (fills3[2] - fcfs3[2]) == 10_000 * USDC
    # 4: rolled 5k/5k/40k + new 50k = 100k demand, cap 50k -> halves.
    assert fills4 == [2_500 * USDC, 2_500 * USDC,
                      20_000 * USDC, 25_000 * USDC]
    assert sum(fills4) == CAP
    # 5: rolled alone clears in full (50k demand, 50k cap).
    assert fills5 == rolled
    print("ALL ASSERTIONS PASS")


if __name__ == "__main__":
    main()
