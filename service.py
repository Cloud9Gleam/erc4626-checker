#!/usr/bin/env python3
"""ERC-4626 checker as a live web service (stdlib only).

Serves the exact-integer model from erc4626_checker.py — the SAME code as
the repo, not a port, no chain reads. Runs on 127.0.0.1:8765 behind a
Cloudflare Tunnel (check.n1netw3n.live).

GET /            HTML UI: form (decimals offset, min deposit, perf fee)
                 + the 5 checks, PASS/FAIL with numbers.
GET /api/check   JSON: ?preset=alphaprimer|noprot|offset18
                 or ?offset=N&min_usdc=X&fee_bps=N
"""
import html as htmllib
import json
import sys
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parent))
from erc4626_checker import Vault, run_all

HOST, PORT = "127.0.0.1", 8765
USDC = 1_000_000

PRESETS = {
    "alphaprimer": ("AlphaPrimer — offset 6, min 1 USDC, fee 10%", 6, 1_000_000, 1000),
    "noprot": ("No protection — offset 0, no minimum, no fee", 0, 0, 0),
    "offset18": ("Offset 18 — offset 18, min 1 USDC, fee 10%", 18, 1_000_000, 1000),
}


def parse_params(qs):
    preset = (qs.get("preset") or ["alphaprimer"])[0]
    if preset in PRESETS and not any(k in qs for k in ("offset", "min_usdc", "fee_bps")):
        _, off, mn, fee = PRESETS[preset]
        return off, mn, fee, preset

    def _int(name, default, lo, hi):
        try:
            v = int(qs.get(name, [default])[0])
        except (ValueError, TypeError):
            v = default
        return max(lo, min(hi, v))

    off = _int("offset", 6, 0, 30)
    fee = _int("fee_bps", 1000, 0, 10000)
    try:
        mn = int(Decimal(str(qs.get("min_usdc", ["1"])[0])) * USDC)
    except (InvalidOperation, ValueError):
        mn = 1_000_000
    mn = max(0, min(mn, 10 ** 15))
    return off, mn, fee, preset if preset in PRESETS else "custom"


def run_checks(off, mn, fee):
    v = Vault(decimals_offset=off, min_deposit=mn, perf_fee_bps=fee)
    return run_all(v)


def usdc(base):
    if base is None:
        return "—"
    return f"{base / USDC:.6f}"


def results_html(results):
    all_pass = all(r["pass"] for r in results)
    parts = [f"<h2>Result: {'ALL PASS' if all_pass else 'SOME FAILED'}</h2>"]
    for r in results:
        badge = "PASS" if r["pass"] else "FAIL"
        cls = "pass" if r["pass"] else "fail"
        parts.append(f"<h3><span class='{cls}'>{badge}</span> {htmllib.escape(r['name'])}</h3>")
        if r["name"] == "donation_inflation":
            parts.append("<table><tr><th>Donation (USDC)</th><th>Victim loss (USDC)</th>"
                         "<th>Attacker net (USDC)</th><th></th></tr>")
            for row in r["detail"]:
                err = f"<td>{htmllib.escape(str(row.get('error', '')))}</td>" if row.get("error") else "<td></td>"
                parts.append(f"<tr><td>{usdc(row['donation'])}</td>"
                             f"<td>{usdc(row['victim_loss'])}</td>"
                             f"<td>{usdc(row['attacker_net'])}</td>{err}</tr>")
            parts.append("</table>")
            parts.append("<p>Pass bound: attacker never profits, victim loss ≤ 0.001 USDC "
                         "and ≤ 0.1% of the victim deposit (100,000 USDC).</p>")
        else:
            for line in r["detail"]:
                parts.append(f"<p>{htmllib.escape(str(line))}</p>")
    return "\n".join(parts)


def page(off, mn, fee, preset, results):
    opts = "".join(
        f"<option value='{k}'{' selected' if k == preset else ''}>{htmllib.escape(label)}</option>"
        for k, (label, *_rest) in PRESETS.items())
    body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>ERC-4626 checker — donation-inflation model</title>
<style>body{{font-family:system-ui,sans-serif;max-width:760px;margin:2em auto;padding:0 1em;line-height:1.5}}
.pass{{color:#0a7d2c;font-weight:bold}}.fail{{color:#c00;font-weight:bold}}
.notice{{background:#fff8e1;border:1px solid #e6c200;padding:.8em}}
table{{border-collapse:collapse}}td,th{{border:1px solid #ccc;padding:.3em .6em;text-align:right}}
label{{display:block;margin:.5em 0}}input,select{{font-size:1em}}</style></head>
<body>
<h1>ERC-4626 accounting checker</h1>
<div class="notice"><strong>What this is:</strong> an exact-integer <em>model</em> of ERC-4626
accounting (OpenZeppelin math with a decimals offset). It does <strong>not</strong> read any
chain, connect any wallet, or check a live vault. Amounts are USDC at 6 decimals.
Source: <a href="https://github.com/Cloud9Gleam/erc4626-checker">github.com/Cloud9Gleam/erc4626-checker</a>.</div>
<form method="get">
<label>Preset <select name="preset">{opts}</select></label>
<label>Decimals offset <input name="offset" type="number" min="0" max="30" value="{off}"></label>
<label>Minimum deposit (USDC) <input name="min_usdc" type="text" value="{mn / USDC:g}"></label>
<label>Performance fee (bps) <input name="fee_bps" type="number" min="0" max="10000" value="{fee}"></label>
<button type="submit">Run checks</button>
</form>
<p>Parameters: offset={off}, min deposit={mn} base units ({mn / USDC:g} USDC), fee={fee} bps.
Victim deposit in the donation check: 100,000 USDC. Donations tested: 1 / 1,000 / 1,000,000 / 1,000,000,000 USDC.</p>
{results_html(results)}
<p><a href="/api/check?preset={htmllib.escape(preset)}&offset={off}&min_usdc={mn / USDC:g}&fee_bps={fee}">JSON API for these parameters</a></p>
</body></html>"""
    return body


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep logs quiet
        pass

    def _send(self, code, body, ctype):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if u.path == "/api/check":
            off, mn, fee, preset = parse_params(qs)
            results = run_checks(off, mn, fee)
            payload = {"params": {"decimals_offset": off, "min_deposit_base_units": mn,
                                  "min_deposit_usdc": mn / USDC, "perf_fee_bps": fee,
                                  "preset": preset},
                       "all_pass": all(r["pass"] for r in results),
                       "results": results,
                       "model_notice": "Exact-integer model only. Not a chain read; no wallet."}
            self._send(200, json.dumps(payload, default=str), "application/json")
        elif u.path in ("/", "/index.html"):
            off, mn, fee, preset = parse_params(qs)
            results = run_checks(off, mn, fee)
            self._send(200, page(off, mn, fee, preset, results), "text/html; charset=utf-8")
        else:
            self._send(404, "not found", "text/plain")


if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
