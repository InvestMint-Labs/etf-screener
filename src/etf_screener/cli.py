"""The ETF screener: set it up once, keep your watchlist fresh, build the page, check the dataset.

    etf-screener setup            your free key, a starter watchlist, the first page, opened in your browser
    etf-screener schedule         a daily update with the system's own scheduler (--off removes it)
    etf-screener update           what the schedule runs: fetch today's allowance for the watchlist, rebuild the page
    etf-screener watch add XIU.TO ZAG.TO  /  watch remove …  /  watch list
    etf-screener status           key, plan, watchlist freshness, the page, the schedule
    etf-screener open             open the latest page
    etf-screener build [--symbols A.TO,B.TO] [--tsx-export FILE] …   the build itself (all funds priced)
    etf-screener web --out site   the static web page (prices fetched in the reader's browser)
    etf-screener check-data       the fund-facts CSV against its rules

``build`` writes ``screener/dataset.json``, ``screener/gaps.md`` and, only when the dataset checks and the page gate
both pass, ``screener/site/index.html``. A failing build exits 1 and removes any earlier page, so the folder never
holds a page that would not pass today. Prices come from Alpha Vantage with your key (``ALPHAVANTAGE_API_KEY``).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import alphavantage, dataset, facts, funds, gate, local, page

DEFAULT_WORKSPACE = local.workspace()
CALL_SPACING = 12.0          # seconds between live calls: a free key allows 5 a minute


def build(workspace: Path = DEFAULT_WORKSPACE, facts_file: Path | str = facts.DATA_FILE,
          tsx_export: Path | None = None, limit: int | None = None, symbols: list[str] | None = None,
          include_all: bool = False, offline: bool = False, client: alphavantage.Client | None = None,
          interval: str = "auto", priced: list[str] | None = None,
          key: str | None = None) -> tuple[int, Path, list[str]]:
    """``priced`` lists the funds to fetch prices for (a watchlist): the page still lists every fund with its facts,
    and the coverage check counts the watched funds only. Without it every listed fund is priced."""
    # a trial (--limit or --symbols) writes beside the real build, never over it: its page is not the page, and its
    # count is not the baseline the next build's shrink check compares against
    trial = bool(limit or symbols)
    out = Path(workspace) / ("screener-trial" if trial else "screener")
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
    listed = {f["symbol"] for f in universe}
    tickers = sorted(listed & {s.upper() for s in priced}) if priced is not None else [f["symbol"] for f in universe]
    client = client or alphavantage.Client(Path(workspace), key=key or local.key(), offline=offline,
                                           sleep=CALL_SPACING, interval=interval)
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
    findings = dataset.check(built, len(tickers), failed, previous=0 if trial else dataset.previous_count(out))
    if not findings:
        html = page.render(data)
        findings = gate.check(html)
        if not findings:
            page_path.parent.mkdir(parents=True, exist_ok=True)
            page_path.write_text(html, encoding="utf-8")
    dataset.write(out, data, findings, failed)
    if not findings and not trial:
        dataset.record_pass(out, data)
    return (1 if findings else 0), page_path, findings


def _open(path: Path) -> None:
    import webbrowser

    webbrowser.open(path.resolve().as_uri())


def _update(open_page: bool = False) -> int:
    """Fetch today's allowance for the watchlist (stalest first is the cache's own order) and rebuild the page."""
    watch = local.watchlist() or local.STARTER
    if not local.watchlist():
        local.save_watchlist(watch)
    try:
        code, page_path, findings = build(local.workspace(), priced=watch)
    except (alphavantage.AlphaVantageError, facts.FactsError) as exc:
        print(f"Update STOPPED: {exc}")
        return 2
    fresh = local.fresh_prices(watch)
    print(f"Watchlist: {len(fresh)} of {len(watch)} funds have this week's prices.")
    if code:
        print(f"No page yet: {findings[0] if findings else 'see gaps.md'}")
        if len(fresh) < len(watch):
            print("The rest are fetched on the next run (a free key allows 25 a day): `etf-screener schedule` runs it "
                  "daily for you.")
    else:
        print(f"Page: {page_path}")
        if open_page:
            _open(page_path)
    return code


def _setup(new_key: bool, open_page: bool) -> int:
    import getpass

    print(f"The screener keeps its files in {local.home()}")
    value = None if new_key else local.key()
    if not value:
        url = "https://www.alphavantage.co/support/#api-key"
        print(f"Prices come from Alpha Vantage with your own free key. Get one at {url}")
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 (no browser is fine: the URL is printed)
            pass
        value = getpass.getpass("Paste your Alpha Vantage key (it is not shown): ").strip()
        if not value:
            print("No key entered; nothing changed.")
            return 2
    try:
        answer = local.check_key(value)
    except alphavantage.AlphaVantageError as exc:
        print(f"Setup STOPPED: {exc}")
        return 2
    if not alphavantage.key_from_env():
        print(f"Key saved for your user in {local.save_key(value)}")
    if answer == "limit":
        print("The key works, but its allowance for today is used; the first prices arrive on the next run.")
    if not local.watchlist():
        local.save_watchlist(local.STARTER)
        print(f"Starter watchlist: {len(local.STARTER)} broad ETFs (change it with `etf-screener watch`).")
    code = _update(open_page)
    print("Next: `etf-screener schedule` keeps the watchlist fresh every day.")
    return 0 if code in (0, 1) else code


def _status() -> int:
    watch = local.watchlist()
    plan = alphavantage.Client(local.workspace(), offline=True).active if local.key() else "-"
    fresh = local.fresh_prices(watch)
    print(f"Folder:     {local.home()}")
    print(f"Key:        {'set' if local.key() else 'not set: run `etf-screener setup`'}"
          + (f" ({plan} prices)" if local.key() else ""))
    print(f"Watchlist:  {len(watch)} funds, {len(fresh)} with this week's prices")
    if plan == "weekly" and len(watch) > local.FREE_CAPACITY:
        print(f"            a free key keeps about {local.FREE_CAPACITY} funds fresh; the rest will lag")
    page_file = local.page_path()
    print(f"Page:       {page_file if page_file.exists() else 'not built yet'}")
    try:
        on = local.scheduled()
    except OSError:
        on = False
    print(f"Schedule:   {'daily' if on else 'off: run `etf-screener schedule`'}")
    return 0


def _watch(action: str, symbols: list[str]) -> int:
    current = set(local.watchlist())
    known = {r["symbol"] for r in facts.load()}
    if action == "list":
        print("\n".join(sorted(current)) or "The watchlist is empty: `etf-screener watch add XIU.TO`")
        return 0
    wanted = [local.normalise(s) for s in symbols]
    unknown = [s for s in wanted if s not in known]
    if unknown:
        print("Not in the fund list: " + ", ".join(unknown))
    wanted = [s for s in wanted if s in known]
    current = current | set(wanted) if action == "add" else current - set(wanted)
    local.save_watchlist(sorted(current))
    print(f"Watchlist: {len(current)} funds.")
    if len(current) > local.FREE_CAPACITY:
        print(f"A free key keeps about {local.FREE_CAPACITY} funds fresh (25 requests a day, prices kept 7 days).")
    return 0


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
    p = argparse.ArgumentParser(prog="etf-screener", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="build the screener page")
    b.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE,
                   help=f"where the price cache and the output go (default: {DEFAULT_WORKSPACE})")
    b.add_argument("--facts", type=Path, default=facts.DATA_FILE, help="the fund-facts CSV (default: data/)")
    b.add_argument("--tsx-export", type=Path, help="your downloaded TSX ETF screener export (CSV or XLSX)")
    b.add_argument("--limit", type=int, help="the first N funds only (a trial)")
    b.add_argument("--symbols", help="only these funds, comma-separated (XIU.TO,ZAG.TO)")
    b.add_argument("--include-all", action="store_true", help="keep leveraged, inverse and single-stock funds")
    b.add_argument("--offline", action="store_true", help="use cached prices only")
    b.add_argument("--interval", choices=("auto", "daily", "weekly"), default="auto",
                   help="daily adjusted closes (a premium plan) or weekly (the free key); auto asks for daily and "
                        "falls back to weekly when the plan refuses")
    w = sub.add_parser("web", help="build the web screener (one static page; prices are fetched in the reader's browser)")
    w.add_argument("--out", type=Path, default=Path("site"))
    w.add_argument("--facts", type=Path, default=facts.DATA_FILE)
    s = sub.add_parser("setup", help="your key, a starter watchlist and the first page")
    s.add_argument("--new-key", action="store_true", help="enter a new key even if one is saved")
    s.add_argument("--no-open", action="store_true", help="do not open the page in a browser")
    sub.add_parser("update", help="fetch today's prices for the watchlist and rebuild the page")
    wl = sub.add_parser("watch", help="the funds whose returns and risk are kept fresh")
    wl.add_argument("action", choices=("add", "remove", "list"))
    wl.add_argument("symbols", nargs="*", help="tickers, XIU or XIU.TO")
    sc = sub.add_parser("schedule", help="run the update daily with the system's scheduler")
    sc.add_argument("--at", default="06:30", help="the time, HH:MM (default 06:30)")
    sc.add_argument("--off", action="store_true", help="remove the schedule")
    sub.add_parser("status", help="key, plan, watchlist, page and schedule")
    sub.add_parser("open", help="open the latest page")
    sub.add_parser("forget-key", help="remove the saved key from this machine")
    c = sub.add_parser("check-data", help="check the fund-facts CSV")
    c.add_argument("--facts", type=Path, default=facts.DATA_FILE)
    a = p.parse_args(argv)
    if a.command == "setup":
        return _setup(a.new_key, not a.no_open)
    if a.command == "update":
        return _update()
    if a.command == "watch":
        return _watch(a.action, a.symbols)
    if a.command == "schedule":
        try:
            print(local.unschedule() if a.off else local.schedule(a.at))
        except (RuntimeError, OSError, ValueError) as exc:
            print(f"Schedule not changed: {exc}")
            return 2
        return 0
    if a.command == "status":
        return _status()
    if a.command == "open":
        if not local.page_path().exists():
            print("No page yet: run `etf-screener setup` or `etf-screener update`.")
            return 1
        _open(local.page_path())
        return 0
    if a.command == "forget-key":
        local.forget_key()
        print("Saved key removed (a key set in ALPHAVANTAGE_API_KEY is not affected).")
        return 0
    if a.command == "check-data":
        return check_data(a.facts)
    if a.command == "web":
        from . import web
        found = web.build_site(a.out, a.facts)
        for f in found[:20]:
            print(" -", f)
        print(f"Web screener {'FAILED' if found else 'PASS'}: {a.out / 'index.html'}")
        return 1 if found else 0
    try:
        code, page_path, findings = build(a.workspace, a.facts, a.tsx_export, a.limit,
                                          a.symbols.split(",") if a.symbols else None, a.include_all, a.offline,
                                          interval=a.interval)
    except (alphavantage.AlphaVantageError, facts.FactsError) as exc:
        print(f"Screener build STOPPED: {exc}")
        return 2
    gaps = page_path.parent.parent / "gaps.md"
    if code:
        print(f"Screener build FAILED with {len(findings)} finding(s); no page written. See {gaps}")
        for f in findings[:20]:
            print(" -", f)
    else:
        print(f"Screener build PASS: {page_path}  (gaps: {gaps})")
    return code


if __name__ == "__main__":
    sys.exit(main())
