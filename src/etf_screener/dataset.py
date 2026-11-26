"""The screener's dataset: the fund rows, what is missing from them, and the checks a build must pass.

``check`` returns findings; any finding fails the build (no page is written).

- **Units.** A MER outside 0-12 (percentage number), a yield outside 0-25% (fraction), a volatility above 150% or a
  drawdown above 100% is a scale mistake.
- **Sources.** Every figure on a row has a named source in ``sources``; a figure with none is a finding.
- **Coverage.** Prices missing for more than ``MAX_FAILED`` of the funds (an outage, or a free key's cache still
  filling), or a list that shrank more than ``MAX_SHRINK`` against the previous build, is a partial download, not a
  smaller market.

What is *missing* is not a finding. A fund with no MER on file, or too little history for a three-year figure, is
listed with a dash and counted in ``gaps`` (on the page and in ``gaps.md``).
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from . import screen

MAX_FAILED = 0.05
MAX_SHRINK = 0.10
# A fund whose computed figures are implausible has a broken price series. Its return and risk columns are blanked
# and it is named in gaps.md; the page is still built. More than this share is a broken download and stops the build.
MAX_BROKEN_PRICES = 0.02
MIN_BROKEN_ALLOWED = 3
MIN_FUNDS = 10
SOURCE_FIELDS = {"cost_pct": "cost", "yield": "yield", "aum": "aum", "duration": "duration"}
PERF_FIELDS = ("return_1y", "return_3y", "return_5y", "volatility_3y", "max_drawdown_3y")
RANGES = {"cost_pct": (0.0, 12.0), "yield": (0.0, 0.25), "volatility_3y": (0.0, 1.5), "max_drawdown_3y": (0.0, 1.0),
          "duration": (0.0, 40.0), "aum": (0.0, 1e13), "return_1y": (-0.95, 5.0), "return_3y": (-0.95, 3.0),
          "return_5y": (-0.95, 2.0)}
DATA_NOTE = ("Funds, issuers and costs from this project's open fund-facts dataset: each issuer's published MER, "
             "with the page it was read from and the date, or the management fee marked “fee” where no "
             "MER is published yet (the MER, which adds the fund's other costs, is higher). Returns, volatility and "
             "drawdown are computed from Alpha Vantage's dividend-adjusted daily closes: total returns, annualized "
             "over three and five years, before any adviser fee.")
RISK_NOTES = {
    "daily": ("3 yr vol is annualized volatility of daily returns; 3 yr max fall is the largest peak-to-trough "
              "decline over the same three years."),
    "weekly": ("3 yr vol is annualized volatility of weekly returns; 3 yr max fall is the largest decline between "
               "weekly closes over the same three years, so a fall that recovered within a week is not counted."),
}
EXPORT_NOTE = " Categories, assets and distribution yields from the TSX ETF screener export."
DATA_SOURCE = "Alpha Vantage"


def gaps(funds: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "funds": len(funds),
        "no_mer": sum(1 for f in funds if f.get("cost_kind") != "MER"),
        "fee_only": sum(1 for f in funds if f.get("cost_kind") == "management fee"),
        "no_yield": sum(1 for f in funds if f.get("yield") is None),
        "under_1y": sum(1 for f in funds if f.get("return_1y") is None),
        "under_3y": sum(1 for f in funds if f.get("return_3y") is None),
        "under_5y": sum(1 for f in funds if f.get("return_5y") is None),
        "broken_prices": sum(1 for f in funds if f.get("price_problem")),
    }


def quarantine(funds: list[dict[str, Any]]) -> list[str]:
    """Blank the computed figures of every fund whose figures are implausible, in place; one line per fund."""
    lines = []
    for f in funds:
        bad = [p for p in PERF_FIELDS if f.get(p) is not None and not RANGES[p][0] <= f[p] <= RANGES[p][1]]
        if bad:
            shown = ", ".join(f"{p} {f[p]:.2f}" for p in bad)
            for p in PERF_FIELDS:
                f[p] = None
            f["sources"].pop("performance", None)
            f["price_problem"] = f"implausible figures from its prices ({shown}); returns and risk left blank"
            lines.append(f"{f['symbol']}: {f['price_problem']}")
    return lines


def check(funds: list[dict[str, Any]], listed: int, failed: list[str], previous: int = 0) -> list[str]:
    findings: list[str] = []
    broken = [f for f in funds if f.get("price_problem")]
    allowed = max(MIN_BROKEN_ALLOWED, int(MAX_BROKEN_PRICES * len(funds)))
    if len(broken) > allowed:
        findings.append(f"{len(broken)} of {len(funds)} funds have implausible figures from their prices (more than "
                        f"{allowed}): a broken download, not a few bad series")
    if len(funds) < MIN_FUNDS:
        findings.append(f"only {len(funds)} funds built (minimum {MIN_FUNDS})")
    if listed and len(failed) / listed > MAX_FAILED:
        findings.append(f"{len(failed)} of {listed} funds have no prices yet (more than {MAX_FAILED:.0%}): "
                        + "; ".join(failed[:5]))
    if previous > 0 and len(funds) < int(previous * (1 - MAX_SHRINK)):
        findings.append(f"{len(funds)} funds against {previous} in the previous build: more than a "
                        f"{MAX_SHRINK:.0%} drop is a partial download, not a smaller market")
    seen: set[str] = set()
    for f in funds:
        sym = f.get("symbol") or "?"
        if sym in seen:
            findings.append(f"{sym}: listed twice")
        seen.add(sym)
        if not f.get("name"):
            findings.append(f"{sym}: no name")
        for field, (lo, hi) in RANGES.items():
            v = f.get(field)
            if v is not None and not lo <= v <= hi:
                findings.append(f"{sym}: {field} {v!r} outside {lo}-{hi} (a unit mistake?)")
        for field, key in SOURCE_FIELDS.items():
            if f.get(field) is not None and not f["sources"].get(key):
                findings.append(f"{sym}: {field} has no source")
        if any(f.get(p) is not None for p in PERF_FIELDS) and not f["sources"].get("performance"):
            findings.append(f"{sym}: performance figures have no source")
    return findings


def payload(funds: list[dict[str, Any]], as_of: str, with_export: bool = False,
            interval: str = "daily") -> dict[str, Any]:
    """Everything the page needs, including the filter list it must apply exactly as ``screen.py`` does."""
    def options(field: str) -> list[str]:
        return sorted({f[field] for f in funds if f.get(field)}, key=str.lower)

    return {
        "exchange": "TO",
        "as_of": as_of,
        "funds": funds,
        "filters": {k: list(v) for k, v in screen.FILTERS.items()},
        "sortable": list(screen.SORTABLE),
        "compare_max": screen.COMPARE_MAX,
        "options": {k: options(k) for k in ("asset_class", "category", "issuer", "currency")},
        "gaps": gaps(funds),
        "data_note": DATA_NOTE.replace("daily closes", f"{interval} closes") + (EXPORT_NOTE if with_export else ""),
        "risk_note": RISK_NOTES[interval],
        "price_interval": interval,
        "data_source": DATA_SOURCE,
    }


def write(out_dir: Path, data: dict[str, Any], findings: list[str], failed: list[str]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "dataset.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    g = data["gaps"]
    lines = [f"# Screener build, as of {data['as_of']}", "",
             f"- Funds: {g['funds']}",
             f"- MER on file: {g['funds'] - g['no_mer']}",
             f"- No MER on file: {g['no_mer']} (management fee shown: {g['fee_only']})",
             f"- No distribution yield: {g['no_yield']}",
             f"- Less than 1 / 3 / 5 years of history: {g['under_1y']} / {g['under_3y']} / {g['under_5y']}",
             f"- Returns and risk left blank for broken prices: {g['broken_prices']}",
             f"- Funds without prices yet: {len(failed)}", ""]
    broken = [f"- {f['symbol']}: {f['price_problem']}" for f in data["funds"] if f.get("price_problem")]
    if broken:
        lines += ["## Funds with broken prices", ""] + broken + [""]
    if failed:
        lines += ["## Funds without prices", ""] + [f"- {x}" for x in failed] + [""]
    lines += ["## Findings", ""] + ([f"- {x}" for x in findings] or ["None."])
    (out_dir / "gaps.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def previous_count(out_dir: Path) -> int:
    path = out_dir / "dataset.json"
    if not path.exists():
        return 0
    try:
        return len(json.loads(path.read_text(encoding="utf-8")).get("funds", []))
    except (ValueError, OSError):
        return 0


def today() -> str:
    return date.today().isoformat()
