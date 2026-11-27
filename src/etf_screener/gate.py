"""The page gate: a screener page that fails it is not written.

What it holds the page to, and why:

- **No tailored or promotional phrasing.** The screener is general information (``screen.py`` explains the line);
  copy that speaks to the reader's situation ("suitable for you", "your risk profile") or ranks a fund as a pick
  ("top pick", "strong buy") would cross it in words even where the logic does not.
- **The disclosure, the data source and the date are on the page**, where the reader meets the figures.
- **The filters are the closed list.** The payload's filter keys must be exactly ``screen.FILTERS``, so a key about
  the reader cannot reach the page by being added to the payload alone.
- **The web screener ships no price and reaches only Alpha Vantage.** Its payload carries no computed figure, and its
  Content-Security-Policy allows connections to ``www.alphavantage.co`` and nothing else, so the reader's key and
  prices cannot be sent anywhere by the page.
- **Every fund with a figure names its source** (``dataset.check`` already refused the dataset otherwise; checked again
  here on what is actually embedded).
"""
from __future__ import annotations

import json
import re
from typing import Any

from . import screen
from .page import DISCLOSURE

BANNED = (
    "suitable for you", "right for you", "best for you", "recommended for you", "we recommend", "you should buy",
    "you should sell", "your risk profile", "your risk tolerance", "your goals", "your situation", "top pick",
    "strong buy", "buy rating", "guaranteed", "risk-free", "can't lose",
)
PAYLOAD = re.compile(r"<script>const D=(.*?);</script>", re.S)


def check(page: str) -> list[str]:
    findings: list[str] = []
    match = PAYLOAD.search(page)
    if not match:
        return ["no payload (const D) in the page"]
    data: dict[str, Any] = json.loads(match.group(1).replace("<\\/", "</"))
    visible = PAYLOAD.sub("", page)
    lower = visible.lower()
    for phrase in BANNED:
        if phrase in lower:
            findings.append(f"tailored or promotional phrasing on the page: {phrase!r}")
    if DISCLOSURE not in visible.replace("&#x27;", "'"):
        findings.append("the disclosure is missing from the page")
    for needle in (data.get("data_source") or "\x00", data.get("as_of") or "\x00"):
        if needle not in visible:
            findings.append(f"the page does not state {needle!r}")
    if data.get("web"):
        # the web screener ships no price and may reach nothing but Alpha Vantage, from the reader's own browser
        csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', page)
        if not csp or "connect-src https://www.alphavantage.co;" not in csp.group(1) + ";" or "default-src 'none'" \
                not in csp.group(1):
            findings.append("web page: the Content-Security-Policy must allow connections to Alpha Vantage only")
        priced = [f.get("symbol") for f in data.get("funds", []) for p in
                  ("return_1y", "return_3y", "return_5y", "volatility_3y", "max_drawdown_3y") if f.get(p) is not None]
        if priced:
            findings.append(f"web page ships computed price figures for {sorted(set(priced))[:5]}: it must ship none")
    if set(data.get("filters", {})) != set(screen.FILTERS):
        findings.append(f"payload filters {sorted(data.get('filters', {}))} are not screen.FILTERS")
    for f in data.get("funds", []):
        for field, key in (("cost_pct", "cost"), ("yield", "yield"), ("aum", "aum"), ("duration", "duration")):
            if f.get(field) is not None and not f.get("sources", {}).get(key):
                findings.append(f"{f.get('symbol')}: {field} shown with no source")
    return findings
