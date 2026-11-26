"""Build the ETF screener into ``<workspace>/screener/``, or check the fund-facts dataset.

    python -m etf_screener build [--workspace workspace] [--tsx-export FILE] [--limit N] [--symbols A.TO,B.TO]
    python -m etf_screener check-data

``build`` writes ``screener/dataset.json``, ``screener/gaps.md`` and, only when the dataset checks and the page gate
both pass, ``screener/site/index.html``. A failing build exits 1 and removes any earlier page, so the folder never
holds a page that would not pass today. Prices come from Alpha Vantage with your key (``ALPHAVANTAGE_API_KEY``).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import alphavantage, dataset, facts, funds, gate, page

DEFAULT_WORKSPACE = Path("workspace")


def build(workspace: Path = DEFAULT_WORKSPACE, facts_file: Path | str = facts.DATA_FILE,
          tsx_export: Path | None = None, limit: int | None = None, symbols: list[str] | None = None,
          include_all: bool = False, offline: bool = False, client: alphavantage.Client | None = None,
          interval: str = "auto") -> tuple[int, Path, list[str]]:
    out = Path(workspace) / "screener"
    page_path = out / "site" / "index.html"
    if page_path.exists():
        page_path.unlink()
    rows = facts.load(facts_file)
    bad = facts.check(rows)
    if bad:
        raise facts.FactsError(f"{len(bad)} problem(s) in the fund facts, first: {bad[0]} (run check-data)")
    exports = facts.read_tsx_export(tsx_export) if tsx_export else None
    universe = funds.eligible(rows, exports, include_all)
    if symbols:
        wanted = {s.strip().upper() for s in symbols}
        universe = [f for f in universe if f["symbol"] in wanted]
    if limit:
        universe = universe[:limit]
    tickers = [f["symbol"] for f in universe]
    client = client or alphavantage.Client(Path(workspace), offline=offline, sleep=12.0, interval=interval)
    series, failed = client.fetch_all(tickers)
    for line in client.errors:
        print(line)
    print(f"Prices: {len(series)} of {len(tickers)} funds, {client.active} adjusted closes ({client.calls} live "
          "call(s) to Alpha Vantage, the rest from the cache)")
    built = [funds.fund_row(f, series.get(f["symbol"]), (exports or {}).get(f["symbol"]), client.active)
             for f in universe]
    for line in dataset.quarantine(built):
        print(f"  {line}")
    as_of = max((r["last_close"] for r in built if r.get("last_close")), default=dataset.today())
    data = dataset.payload(built, as_of, with_export=exports is not None, interval=client.active)
    findings = dataset.check(built, len(tickers), failed, previous=dataset.previous_count(out))
    if not findings:
        html = page.render(data)
        findings = gate.check(html)
        if not findings:
            page_path.parent.mkdir(parents=True, exist_ok=True)
            page_path.write_text(html, encoding="utf-8")
    dataset.write(out, data, findings, failed)
    return (1 if findings else 0), page_path, findings


def check_data(facts_file: Path | str = facts.DATA_FILE) -> int:
    rows = facts.load(facts_file)
    findings = facts.check(rows)
    with_mer = sum(1 for r in rows if r["mer_pct"] is not None)
    fee = sum(1 for r in rows if r["mer_pct"] is None and r["mgmt_fee_pct"] is not None)
    print(f"{len(rows)} funds: {with_mer} with the issuer's MER, {fee} with the management fee only, "
          f"{len(rows) - with_mer - fee} with neither")
    for f in findings[:50]:
        print(" -", f)
    print("check-data: " + ("FAIL" if findings else "PASS"))
    return 1 if findings else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="etf_screener", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="build the screener page")
    b.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE,
                   help="where the price cache and the output go (default: ./workspace, never committed)")
    b.add_argument("--facts", type=Path, default=facts.DATA_FILE, help="the fund-facts CSV (default: data/)")
    b.add_argument("--tsx-export", type=Path, help="your downloaded TSX ETF screener export (CSV or XLSX)")
    b.add_argument("--limit", type=int, help="the first N funds only (a trial)")
    b.add_argument("--symbols", help="only these funds, comma-separated (XIU.TO,ZAG.TO)")
    b.add_argument("--include-all", action="store_true", help="keep leveraged, inverse and single-stock funds")
    b.add_argument("--offline", action="store_true", help="use cached prices only")
    b.add_argument("--interval", choices=("auto", "daily", "weekly"), default="auto",
                   help="daily adjusted closes (a premium plan) or weekly (the free key); auto asks for daily and "
                        "falls back to weekly when the plan refuses")
    c = sub.add_parser("check-data", help="check the fund-facts CSV")
    c.add_argument("--facts", type=Path, default=facts.DATA_FILE)
    a = p.parse_args(argv)
    if a.command == "check-data":
        return check_data(a.facts)
    try:
        code, page_path, findings = build(a.workspace, a.facts, a.tsx_export, a.limit,
                                          a.symbols.split(",") if a.symbols else None, a.include_all, a.offline,
                                          interval=a.interval)
    except (alphavantage.AlphaVantageError, facts.FactsError) as exc:
        print(f"Screener build STOPPED: {exc}")
        return 2
    gaps = Path(a.workspace) / "screener" / "gaps.md"
    if code:
        print(f"Screener build FAILED with {len(findings)} finding(s); no page written. See {gaps}")
        for f in findings[:20]:
            print(" -", f)
    else:
        print(f"Screener build PASS: {page_path}  (gaps: {gaps})")
    return code


if __name__ == "__main__":
    sys.exit(main())
