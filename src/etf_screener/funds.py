"""One screener row per fund: its facts, the issuer's cost, and returns computed from adjusted closes.

Three rules:

1. **Returns and risk are computed, never read.** Trailing returns, volatility and drawdown come from the
   dividend-adjusted daily closes. A window the fund's history does not cover is ``None`` ("not enough history"),
   never a shorter window labelled as the longer one.
2. **The cost says what it is.** The issuer's MER where the dataset has it; otherwise the management fee, labelled a
   fee (``cost_kind``), because the MER adds the fund's other costs and is higher. A blank is *unknown*, not *free*.
3. **Every figure carries its source.** ``sources`` names where each field came from, so the page can show it and
   the gate can refuse a figure with none.

Units: yields and returns as decimal fractions, the MER as a percentage number (0.65 = 0.65%), assets in dollars of
the fund's currency, duration in years.
"""
from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

TRADING_DAYS = 252
WINDOWS = {"1y": 1, "3y": 3, "5y": 5}
RISK_WINDOW = "3y"
START_TOLERANCE_DAYS = 7          # a fund whose first close is within a week of the window start covers it
MIN_CLOSES = 60                   # fewer closes than this and the fund is listed with no computed figures
PERF_SOURCES = {"daily": "Computed from Alpha Vantage dividend-adjusted daily closes",
                "weekly": "Computed from Alpha Vantage dividend-adjusted weekly closes"}
PERF_SOURCE = PERF_SOURCES["daily"]
PERIODS_PER_YEAR = {"daily": TRADING_DAYS, "weekly": 52}
NAME_SOURCE = "Inferred from the fund's name"

# (pattern on the name, asset class): the first that matches wins; used only without a TSX export
NAME_CLASSES = [
    (r"\b(?:bitcoin|ether(?:eum)?|solana|xrp|crypto)", "Crypto"),
    (r"\b(?:money market|cash|savings|t-bill|treasury bill|high interest)", "Cash"),
    (r"\b(?:balanced|portfolio|asset allocation|all-equity|all equity)\b", "Multi-asset"),
    (r"\b(?:bond|fixed income|treasury|mortgage|aggregate|credit|floating rate|income fund)\b", "Fixed income"),
    (r"\b(?:gold|silver|oil|natural gas|commodit|uranium|copper|bullion)", "Commodity"),
]


def name_class(name: str) -> str:
    for pattern, label in NAME_CLASSES:
        if re.search(pattern, name or "", re.I):
            return label
    return "Equity"


def window_measures(closes: pd.Series, years: int, periods_per_year: int = TRADING_DAYS) -> dict[str, float] | None:
    """Annual return, volatility annualized over ``periods_per_year`` (252 for daily closes, 52 for weekly) and
    maximum fall over the trailing window, or None if the history does not reach its start. On weekly closes the
    maximum fall is the largest fall between weekly closes and misses one that recovered inside a week."""
    min_closes = max(12, MIN_CLOSES * periods_per_year // TRADING_DAYS)
    if len(closes) < min_closes:
        return None
    end = closes.index[-1]
    start = end - pd.DateOffset(years=years)
    if closes.index[0] > start + pd.Timedelta(days=START_TOLERANCE_DAYS):
        return None
    window = closes[closes.index >= closes[closes.index <= start].index[-1]] if (closes.index <= start).any() \
        else closes
    daily = window.pct_change().dropna().to_numpy()
    if len(daily) < min_closes:
        return None
    path = np.cumprod(1 + daily)
    peak = np.maximum.accumulate(path)
    total = float(window.iloc[-1] / window.iloc[0] - 1)
    return {"return": (1 + total) ** (1 / years) - 1 if years > 1 else total,
            "volatility": float(daily.std() * np.sqrt(periods_per_year)),
            "max_drawdown": float(abs(((path - peak) / (peak + 1e-8)).min())),
            "trading_days": int(len(daily))}


def performance(series: pd.Series, interval: str = "daily") -> dict[str, Any]:
    perf: dict[str, Any] = {}
    for label, years in WINDOWS.items():
        m = window_measures(series, years, PERIODS_PER_YEAR[interval])
        perf[f"return_{label}"] = None if m is None else m["return"]
        if label == RISK_WINDOW:
            perf["volatility_3y"] = None if m is None else m["volatility"]
            perf["max_drawdown_3y"] = None if m is None else m["max_drawdown"]
    return perf


def _cost(fact: dict[str, Any], export: dict[str, Any] | None) -> tuple[float | None, str | None, str | None]:
    page = f"read {fact['read_on']} from {fact['url']}"
    who = fact["issuer"] or "Issuer"
    if fact["mer_pct"] is not None:
        period = f"as of {fact['mer_as_of']}" if fact["mer_as_of"] else "with no period stated"
        return fact["mer_pct"], "MER", f"{who} (MER {period}, {page})"
    if fact["mgmt_fee_pct"] is not None:
        return (fact["mgmt_fee_pct"], "management fee",
                f"{who} (management fee; the MER is higher and not yet published, {page})")
    fee = (export or {}).get("mgmt_fee_pct")
    if fee is not None and not pd.isna(fee):
        return float(fee), "management fee", f"{export['export']} (management fee; the MER is higher)"
    return None, None, None


def fund_row(fact: dict[str, Any], adjusted: pd.Series | None, export: dict[str, Any] | None = None,
             interval: str = "daily") -> dict[str, Any]:
    symbol = fact["symbol"]
    page = f"{fact['issuer'] or 'Issuer'} ({fact['url']})"
    sources: dict[str, str] = {"name": page, "issuer": page}
    cost, cost_kind, cost_source = _cost(fact, export)
    if cost_source:
        sources["cost"] = cost_source

    def num(field: str) -> float | None:
        v = (export or {}).get(field)
        return None if v is None or pd.isna(v) or float(v) <= 0 else float(v)

    distribution_yield, aum = num("yield"), num("aum")
    if distribution_yield is not None:
        sources["yield"] = export["export"] + " (distribution yield)"
    if aum is not None:
        sources["aum"] = export["export"]
    if export:
        cls, category = str(export.get("asset_class") or "").strip() or name_class(fact["name"]), export.get("category")
        sources["category"] = export["export"]
    else:
        cls, category = name_class(fact["name"]), None
        sources["asset_class"] = NAME_SOURCE
    duration = fact["duration_years"]
    if duration is not None:
        sources["duration"] = fact["duration_source"]
    series = pd.Series(dtype=float) if adjusted is None else adjusted.dropna()
    series = series[series > 0].sort_index()
    perf = performance(series, interval)
    if any(v is not None for v in perf.values()):
        sources["performance"] = PERF_SOURCES[interval]

    def text(v: Any) -> str | None:
        return None if v is None or (isinstance(v, float) and pd.isna(v)) or not str(v).strip() else str(v).strip()

    return {
        "symbol": symbol, "code": symbol.split(".")[0], "exchange": "TO",
        "name": fact["name"] or symbol, "issuer": fact["issuer"] or None, "category": text(category),
        "asset_class": cls, "currency": (text((export or {}).get("currency")) or fact["currency"] or "").upper() or None,
        "inception": text((export or {}).get("inception")), "cost_pct": cost, "cost_kind": cost_kind,
        "cost_url": fact["url"] if cost is not None and fact["url"].startswith("https://") and "export" not in
        (cost_source or "").lower() else None,
        "yield": distribution_yield, "aum": aum, "duration": duration, **perf,
        "last_close": None if series.empty else series.index[-1].date().isoformat(),
        "history_days": int(len(series)), "sources": sources,
    }


def eligible(facts: list[dict[str, Any]], exports: dict[str, dict[str, Any]] | None = None,
             include_all: bool = False) -> list[dict[str, Any]]:
    """The funds the screener lists: no leveraged, inverse or single-stock fund unless ``include_all``. The TSX
    export's own flags win over the dataset's, which are read from the fund's name. With an export, a fund it does
    not list (delisted, or not yet listed) is left out."""
    out = []
    for f in facts:
        e = (exports or {}).get(f["symbol"])
        if exports is not None and e is None:
            continue
        structure = e["structure"] if e else f["structure"]
        if include_all or not structure:
            out.append(f)
    return sorted(out, key=lambda f: f["symbol"])
