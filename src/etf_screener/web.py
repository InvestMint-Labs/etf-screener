"""The web screener: one static page for the project's GitHub Pages address.

    python -m etf_screener web --out site

The page carries the fund facts for every fund (``src/etf_screener/data/fund_facts.csv``) and no price. Returns and risk are computed in
the reader's own browser from Alpha Vantage closes fetched with the reader's own key (``page.PRICES_JS``). Alpha
Vantage confirmed in writing on 2026-11-27 that this needs no licence while the project stays free and open source;
the page is built for the project's own GitHub Pages address, never a company website. The gate runs on the page
before it is written, as for the command-line build.
"""
from __future__ import annotations

from pathlib import Path

from . import dataset, facts, funds, gate, page

WEB_COLUMNS = ["symbol", "name", "issuer", "asset_class", "cost_pct", "return_1y", "return_3y", "return_5y",
               "volatility_3y", "max_drawdown_3y", "duration", "cost_url"]
WEB_NOTE = ("Funds, issuers and costs from this project's open fund-facts dataset: each issuer's published MER, with "
            "the page it was read from and the date, or the management fee marked “fee” where no MER is "
            "published yet (the MER, which adds the fund's other costs, is higher). Returns, volatility and drawdown "
            "are computed in your browser from Alpha Vantage's dividend-adjusted closes, fetched with your own key: "
            "daily closes on a premium key, weekly on a free one (each figure's hover says which). Total returns, "
            "annualized over three and five years, before any adviser fee.")
WEB_RISK_NOTE = ("3 yr vol is annualized volatility of daily or weekly returns; 3 yr max fall is the largest decline "
                 "between closes over the same three years (on weekly closes, a fall that recovered within a week is "
                 "not counted).")


def build_site(out: Path, facts_file: Path | str = facts.DATA_FILE, include_all: bool = False) -> list[str]:
    """Write ``out/index.html`` when the dataset and the page pass; return the findings (empty on success)."""
    rows = facts.load(facts_file)
    bad = facts.check(rows)
    if bad:
        return [f"fund facts: {b}" for b in bad]
    universe = funds.eligible(rows, None, include_all)
    built = [funds.fund_row(f, None) for f in universe]
    as_of = max((f["read_on"] for f in universe if f["read_on"]), default=dataset.today())
    data = dataset.payload(built, as_of)
    data.update(data_note=WEB_NOTE, risk_note=WEB_RISK_NOTE, columns=WEB_COLUMNS, default_sort="symbol", web=True,
                price_interval=None)
    findings = dataset.check(built, 0, [])
    if findings:
        return findings
    html = page.render_web(data)
    findings = gate.check(html)
    if findings:
        return findings
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return []
