"""Filter, sort and compare: the screener's whole decision logic, and nothing else.

**This is where the screener stays general information.** In Canada, a publisher that is not registered may give
advice only where it is not tailored to the person receiving it (NI 31-103 s.8.25; CSA Staff Notice 31-369). So the
screener takes *filters the user picks over the funds' own facts* and nothing about the user: ``FILTERS`` is a
closed list, every key names a fund attribute, and an unknown key is refused rather than ignored. A risk profile, a
horizon, an age or a questionnaire answer has no key to arrive through.

The page runs the same filters in the browser from the same ``FILTERS`` list, which is carried in its payload; the
test suite runs both on the same funds and requires the same answer, so the two cannot drift.
"""
from __future__ import annotations

from typing import Any, Iterable

# key -> (fund field, operator). min/max compare numbers; "in" takes a list; "text" searches symbol and name.
FILTERS: dict[str, tuple[str, str]] = {
    "asset_class": ("asset_class", "in"),
    "category": ("category", "in"),
    "issuer": ("issuer", "in"),
    "currency": ("currency", "in"),
    "cost_max": ("cost_pct", "max"),
    "yield_min": ("yield", "min"),
    "aum_min": ("aum", "min"),
    "duration_min": ("duration", "min"),
    "duration_max": ("duration", "max"),
    "return_1y_min": ("return_1y", "min"),
    "return_3y_min": ("return_3y", "min"),
    "return_5y_min": ("return_5y", "min"),
    "volatility_max": ("volatility_3y", "max"),
    "drawdown_max": ("max_drawdown_3y", "max"),
    "text": ("symbol,name", "text"),
}

SORTABLE = ("symbol", "name", "issuer", "category", "asset_class", "cost_pct", "yield", "aum", "duration",
            "return_1y", "return_3y", "return_5y", "volatility_3y", "max_drawdown_3y")
COMPARE_MAX = 5


class ScreenError(ValueError):
    pass


def _passes(fund: dict[str, Any], field: str, op: str, value: Any) -> bool:
    if op == "text":
        needle = str(value).strip().lower()
        return not needle or any(needle in str(fund.get(f) or "").lower() for f in field.split(","))
    have = fund.get(field)
    if op == "in":
        wanted = list(value) if isinstance(value, (list, tuple, set)) else [value]
        return not wanted or have in wanted
    if have is None:          # a fund missing the figure cannot be shown to meet a bound on it
        return False
    return have >= float(value) if op == "min" else have <= float(value)


def screen(funds: Iterable[dict[str, Any]], filters: dict[str, Any] | None = None, sort: str = "aum",
           descending: bool = True, limit: int | None = None) -> list[dict[str, Any]]:
    filters = {k: v for k, v in (filters or {}).items() if v is not None and v != "" and v != []}
    unknown = sorted(set(filters) - set(FILTERS))
    if unknown:
        raise ScreenError(f"unknown filter(s) {unknown}: the screener filters on fund attributes only "
                          f"({', '.join(FILTERS)})")
    if sort not in SORTABLE:
        raise ScreenError(f"cannot sort by {sort!r}")
    out = [f for f in funds if all(_passes(f, *FILTERS[k], v) for k, v in filters.items())]
    present = [f for f in out if f.get(sort) is not None]
    missing = [f for f in out if f.get(sort) is None]       # funds without the figure always sort last
    # ties fall back to the symbol, A to Z, in both directions: sort by symbol, then (stably) by the field
    present.sort(key=lambda f: f["symbol"])
    present.sort(key=lambda f: f[sort].lower() if isinstance(f[sort], str) else f[sort], reverse=descending)
    ranked = present + sorted(missing, key=lambda f: f["symbol"])
    return ranked[:limit] if limit else ranked


def compare(funds: Iterable[dict[str, Any]], symbols: list[str]) -> list[dict[str, Any]]:
    if not symbols:
        raise ScreenError("name at least one fund to compare")
    if len(symbols) > COMPARE_MAX:
        raise ScreenError(f"compare at most {COMPARE_MAX} funds at a time")
    by_symbol = {f["symbol"].upper(): f for f in funds}
    missing = [s for s in symbols if s.upper() not in by_symbol]
    if missing:
        raise ScreenError(f"not in the screener: {missing}")
    return [by_symbol[s.upper()] for s in symbols]
