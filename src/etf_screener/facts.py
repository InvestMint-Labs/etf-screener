"""The fund list and each fund's facts: ``src/etf_screener/data/fund_facts.csv``, and optionally your own TSX screener export.

``fund_facts.csv`` is the open dataset this repository publishes (CC BY 4.0, see ``data/README.md`` beside it): one row per
ETF series listed on the TSX, with the issuer's published MER and management fee, the period the MER covers, and the
page it was read from and when. ``check`` holds every row to that: a cost without its page and date is refused.

The TSX's own ETF screener export (https://www.tsx.com/listings/listing-with-us/sector-and-product-profiles/etfs,
downloaded by you) adds what the dataset does not carry: the category, the asset class, assets, the distribution yield
and the inception date. It is read when you pass it and never copied into this repository, because its terms are the
TMX Group's, not ours. Without it, the asset class is inferred from the fund's name and labelled as such.
"""
from __future__ import annotations

import csv
import os
import re
from itertools import islice
from pathlib import Path
from typing import Any

import pandas as pd

DATA_FILE = Path(os.environ.get("ETF_SCREENER_FACTS", Path(__file__).resolve().parent / "data" / "fund_facts.csv"))
COLUMNS = ["symbol", "name", "issuer", "currency", "mer_pct", "mer_as_of", "mgmt_fee_pct", "duration_years",
           "structure", "url", "read_on", "reviewed", "note", "duration_source"]
STRUCTURES = ("", "leveraged", "inverse", "single_stock")
SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9\-]*\.TO$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
COST_RANGE = (0.0, 12.0)         # a percentage number: 0.65 means 0.65%; 0 is a waived fee


class FactsError(RuntimeError):
    """The dataset or the export cannot be read: the build stops."""


def _text(v: Any) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()


def _num(v: Any) -> float | None:
    try:
        out = float(v)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(out) else out


def load(path: Path | str = DATA_FILE) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.is_file():
        raise FactsError(f"no fund facts at {path} (run from a clone of the repository, or set ETF_SCREENER_FACTS)")
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [c for c in COLUMNS if c not in frame.columns]
    if missing:
        raise FactsError(f"{path} lacks the column(s) {missing}")
    rows = []
    for r in frame.to_dict("records"):
        row = {c: _text(r.get(c)) for c in COLUMNS}
        for c in ("mer_pct", "mgmt_fee_pct", "duration_years"):
            row[c] = _num(row[c])
        rows.append(row)
    return rows


def check(rows: list[dict[str, Any]]) -> list[str]:
    """Every row's problems: a malformed symbol, a cost out of range, a figure without its page or date."""
    findings: list[str] = []
    seen: set[str] = set()
    for r in rows:
        s = r["symbol"]
        if not SYMBOL.match(s):
            findings.append(f"{s or '?'}: symbol is not a TSX ticker in Yahoo-style form (XIU.TO, ZWB-U.TO)")
        if s in seen:
            findings.append(f"{s}: listed twice")
        seen.add(s)
        for c in ("name", "issuer"):
            if not r[c]:
                findings.append(f"{s}: no {c}")
        for c in ("mer_pct", "mgmt_fee_pct"):
            v = r[c]
            if v is not None and not COST_RANGE[0] <= v <= COST_RANGE[1]:
                findings.append(f"{s}: {c} {v} outside {COST_RANGE} (a percentage number: 0.65 means 0.65%)")
        if (r["mer_pct"] is not None or r["mgmt_fee_pct"] is not None) and not (
                r["url"].startswith("https://") and DATE.match(r["read_on"])):
            findings.append(f"{s}: a cost with no https page or no read_on date")
        if r["mer_as_of"] and not DATE.match(r["mer_as_of"]):
            findings.append(f"{s}: mer_as_of {r['mer_as_of']!r} is not a date")
        if r["duration_years"] is not None and (not 0 <= r["duration_years"] <= 40 or not r["duration_source"]):
            findings.append(f"{s}: duration out of range or with no source")
        if r["structure"] not in STRUCTURES:
            findings.append(f"{s}: structure {r['structure']!r} not one of {STRUCTURES}")
        if r["reviewed"] not in ("yes", "no"):
            findings.append(f"{s}: reviewed must be yes or no")
    return findings


# -- the TSX screener export (your own download) -----------------------------------------------------------------
TSX_COLUMNS = {"Fund Name", "AUM ($)", "Mgmt Fee (%)"}
HEADER_SCAN_ROWS = 30


def tsx_to_symbol(symbol: str) -> str:
    """A TSX ticker in the export (``ZWB.U``) to this dataset's form (``ZWB-U.TO``)."""
    s = str(symbol).strip().upper()
    return s if s.endswith(".TO") else s.replace(".", "-") + ".TO"


def _number(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")
    text = series.astype(str).str.replace(r"[$,%\s]", "", regex=True).replace({"": None, "N/A": None, "nan": None})
    return pd.to_numeric(text, errors="coerce")


def read_tsx_export(path: Path | str) -> dict[str, dict[str, Any]]:
    """Your downloaded TSX ETF screener export (CSV or XLSX), keyed by symbol."""
    path = Path(path)
    excel = path.suffix.lower() in (".xlsx", ".xls")
    if excel:
        head = pd.read_excel(path, header=None, nrows=HEADER_SCAN_ROWS, dtype=object)
        lines = [[str(c) for c in r if pd.notna(c)] for r in head.itertuples(index=False)]
    else:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            lines = list(islice(csv.reader(fh), HEADER_SCAN_ROWS))
    at = next((n for n, cells in enumerate(lines) if "Symbol" in {c.strip().lstrip("﻿") for c in cells}), 0)
    raw = pd.read_excel(path, skiprows=at) if excel else pd.read_csv(path, encoding="utf-8-sig", skiprows=at)
    raw.columns = [str(c).strip().lstrip("﻿") for c in raw.columns]
    if not TSX_COLUMNS <= set(raw.columns):
        raise FactsError(f"{path.name} is not a TSX ETF screener export: expected the columns {sorted(TSX_COLUMNS)}")
    asset = raw["Asset Class"].astype(str)
    style = raw["Investment Style"].astype(str)
    out = pd.DataFrame({
        "symbol": raw["Symbol"].map(tsx_to_symbol),
        "category": raw["Investment Style"], "asset_class": raw["Asset Class"],
        "aum": _number(raw["AUM ($)"]),
        "mgmt_fee_pct": _number(raw["Mgmt Fee (%)"]),
        "yield": _number(raw["Distribution Yield (%)"]) / 100 if "Distribution Yield (%)" in raw else None,
        "inception": pd.to_datetime(raw.get("Inception Date"), errors="coerce").dt.date.astype("string"),
        "currency": raw.get("Currency"),
        "structure": [("inverse" if "Inverse" in st else "leveraged") if (a == "Leverage/Inverse" or "Leverage" in st)
                      else "single_stock" if a == "Single Stock ETF" else ""
                      for a, st in zip(asset, style)],
    })
    out["export"] = f"TSX ETF screener export ({path.name})"
    return {r["symbol"]: r for r in out.drop_duplicates("symbol").to_dict("records")}
