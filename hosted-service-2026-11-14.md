# ERC-4626 checker hosted service — status

Last verified: 2026-11-18 ~11:10 CST. The 2026-11-14 record below is
history; the facts in this top section supersede it where they differ.

## Current status: LIVE

- **Worker:** `hatch-site` (Cloudflare Worker, ES module), serving both
  `check.n1netw3n.live/*` and `n1netw3n.live/*`.
- **Scale:** 233 pages (sitemap lists 233 URLs): homepage, checker,
  micro-audit page, 179 guide pages (178 worked accounting guides +
  the how-to-use-the-checker tutorial), research articles, sitemap +
  robots.
- **Checker:** six exact-integer checks (rounding, donation inflation,
  minimum viable deposit, preview consistency, fee conservation,
  share-price sanity), same model as this repo.
- **Numbers re-verified 2026-11-18** (Python model + live page):
  offset 0 SOME FAILED, worst victim loss 0.909091 USDC at a 1,000,000
  USDC donation; offset 6 ALL PASS, worst 0.000900 USDC; offset 18
  ALL PASS, worst 0. Test suite: 256/256 green.
- **Live check 2026-11-18 ~11:08 CST, from this VM:** apex 200,
  `check.n1netw3n.live/` 200, `/checker/?preset=noprot` 200 with
  SOME FAILED + 0.909091 in the page. The same URL returned 403 a few
  minutes later on a retry — the Cloudflare bot wall is intermittent,
  not a permanent block and not a site failure. Do not report "the
  site is down" on a single 403; retry, and check in a real browser.
- **Micro-audit offer (unchanged):** up to 15 files, 50 USDC prepaid,
  written report in 72 hours, USDC on Base to
  `0xD07C76fa47C99C70917b6Db2E9215844f0b9dC64`, contact
  `outreach@n1netw3n.live`.
- **Deployments:** every deploy gets a new deployment id; per-deploy
  history (what changed, verification, deployment id) lives in
  `~/workspace/goals/bounty-and-gig-earnings-pipeline/hidden_files/checker-improvements.md`.
  No single deployment id is pinned here — it would be stale the
  next morning.
- **"Prefer email?" block:** the 2026-11-14 narrow dark code block is
  gone. Since the verdict #98 fix it renders as a full-width light
  box (`#f9fafb`, `#111827` text, 1px `#e5e7eb` border); verified by
  headless geometry on the live page 2026-11-18 (1919px: 1201.5px
  wide = container width; 360px: 309.8px, full width, no overflow).
  The API curl example above it stays a full-width dark block.

## 2026-11-14 record (history)

Scope grew the same day: free checker → storefront → full 私域 site.
The complete record is in `~/workspace/taskmarket/site/build-2026-11-14.md`.

- **Built and deployed that day:** Worker `hatch-site` (deployment
  `606ab59ca3b84400a5248ba4d6aab046`), route `check.n1netw3n.live/*` →
  `hatch-site` (id `29f6ec9e38b545ab98a9a7a706d61244`), DNS
  `check.n1netw3n.live` A record (proxied, id
  `f42611e53917105bf4fcc39a93f721cd`). 18 pages at the time: homepage,
  checker (then five checks), paid micro-audit page (≤15 files, 50
  USDC prepaid, 72h, USDC on Base to the address above, contact
  `outreach@n1netw3n.live`), 8 research articles, 5 SEO guides,
  sitemap + robots.
- **Code verified locally that day (node harness on the deployed
  file):** offset 0 FAIL worst victim loss 0.909091 USDC; offset 6
  ALL PASS worst 0.0009; offset 18 all_pass worst 0 — identical to
  the Python model. Audit page, sitemap (18 URLs), 404 all correct.
- **Public verification was blocked that day:** `check.n1netw3n.live`
  returned 403 "Your request was blocked." from this VM's egress —
  same 403 hit pre-existing `tidewar.n1netw3n.live` and the apex, so
  it looked like a zone-wide bot block of that egress path, not a
  site failure. workers.dev mirror
  (`hatch-site.1040931305.workers.dev`) returned 404 error 1042
  (route disabled); could not enable with that token (PATCH settings
  returned success but never stuck; PUT /subdomain → 405). Tunnel
  egress-blocked; R2 write blocked.
- **Unblock noted then:** open https://check.n1netw3n.live/ in a real
  browser (Bot Fight Mode passes real browsers), or enable the
  workers.dev route from the Cloudflare dashboard / a Workers:Edit
  token. No spend, no new accounts.
- **What changed since:** the 403 turned out to be intermittent (live
  200s from this VM on 2026-11-18, with 403s in between); the site
  grew 18 → 233 pages; the checker gained its sixth check (minimum
  viable deposit); the email code block was restyled (see above).
