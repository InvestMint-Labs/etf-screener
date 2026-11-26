"""Alpha Vantage client: daily dividend-adjusted closes for each fund, with your own key.

Alpha Vantage's terms grant personal, non-commercial use of its data. Running this screener with your own key for
yourself is that; publishing pages built from Alpha Vantage data as a business needs Alpha Vantage's written
permission. Nothing here writes a price anywhere but your own cache, and no price is ever committed to this
repository.

- The key comes from ``ALPHAVANTAGE_API_KEY`` (or ``ALPHA_VANTAGE_API_KEY``) and is never written to a cache, a log
  line or an error message: ``_redact`` strips it from anything that could be printed.
- A TSX symbol (``XIU.TO``) is ``XIU.TRT`` at Alpha Vantage; a US symbol has no suffix.
- Every response is cached under ``<workspace>/external/alphavantage/daily/<YYYYMMDD>/`` and reused for
  ``PRICE_MAX_AGE_DAYS``. The free key allows 25 requests a day, so a first build of the whole list fills the cache
  over many days: when Alpha Vantage says the day's allowance is spent, the client stops asking, keeps what it has
  and names how many funds are still to fetch.
- An endpoint the key's plan does not include raises ``AlphaVantageError`` naming it, rather than a build quietly
  computing returns from closes that were not adjusted for distributions.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd

BASE_URL = "https://www.alphavantage.co/query"
KEY_ENV = ("ALPHAVANTAGE_API_KEY", "ALPHA_VANTAGE_API_KEY")
FUNCTION = "TIME_SERIES_DAILY_ADJUSTED"
SERIES_KEY = "Time Series (Daily)"
ADJUSTED = "5. adjusted close"
PRICE_MAX_AGE_DAYS = 7           # a weekly screener; lets a free key fill its cache over several days
RETRIES = 3
SUFFIX = {"TO": "TRT"}           # register exchange suffix -> Alpha Vantage's


class AlphaVantageError(RuntimeError):
    """The whole build stops: no key, a missing plan entitlement, or offline with nothing cached."""


class DailyLimit(RuntimeError):
    """Alpha Vantage says this key's allowance is spent for now; the build keeps what it has."""


def key_from_env() -> str | None:
    for name in KEY_ENV:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def av_symbol(symbol: str) -> str:
    """``XIU.TO`` -> ``XIU.TRT``; a symbol without a known suffix is sent as it is."""
    base, _, suffix = symbol.upper().rpartition(".")
    if base and suffix in SUFFIX:
        return f"{base}.{SUFFIX[suffix]}"
    return symbol.upper()


def _redact(text: str, key: str | None) -> str:
    return text.replace(key, "***") if key else text


def _message(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    return str(data.get("Information") or data.get("Note") or data.get("Error Message") or "")


def classify(data: Any) -> str:
    """``ok``, ``limit`` (allowance spent), ``plan`` (endpoint not in the key's plan), ``symbol`` (not found) or
    ``unknown``, from an Alpha Vantage JSON response."""
    if isinstance(data, dict) and isinstance(data.get(SERIES_KEY), dict):
        return "ok"
    text = _message(data).lower()
    if "premium" in text:
        return "plan"
    if "rate limit" in text or "requests per day" in text or "api call frequency" in text or "call frequency" in text:
        return "limit"
    if isinstance(data, dict) and data.get("Error Message"):
        return "symbol"
    return "unknown"


def parse_adjusted(data: dict[str, Any]) -> pd.Series:
    rows = data.get(SERIES_KEY) or {}
    series = pd.Series({pd.Timestamp(day): float(v[ADJUSTED]) for day, v in rows.items() if v.get(ADJUSTED)},
                       dtype=float).sort_index()
    return series[series > 0]


@dataclass
class Client:
    workspace: Path
    key: str | None = None
    offline: bool = False
    today: date = field(default_factory=date.today)
    sleep: float = 0.0                              # seconds between live calls (the free key's per-minute limit)
    max_age_days: int = PRICE_MAX_AGE_DAYS
    http: Callable[[str], Any] | None = None        # url -> parsed JSON; tests replace it
    errors: list[str] = field(default_factory=list)
    calls: int = 0

    def __post_init__(self) -> None:
        self.workspace = Path(self.workspace)
        if self.key is None:
            self.key = key_from_env()
        if not self.offline and not self.key:
            raise AlphaVantageError(f"No Alpha Vantage key: set {KEY_ENV[0]} (a free key: "
                                    "https://www.alphavantage.co/support/#api-key), or run offline on a cached download.")

    def _dir(self, day: date | None = None) -> Path:
        return self.workspace / "external" / "alphavantage" / "daily" / (day or self.today).strftime("%Y%m%d")

    def _cached(self, name: str) -> Path | None:
        root = self.workspace / "external" / "alphavantage" / "daily"
        if not root.exists():
            return None
        oldest = self.today - timedelta(days=self.max_age_days)
        for folder in sorted((p for p in root.iterdir() if p.is_dir()), reverse=True):
            try:
                day = date(int(folder.name[:4]), int(folder.name[4:6]), int(folder.name[6:8]))
            except ValueError:
                continue
            if day < oldest:
                break
            if (folder / name).exists():
                return folder / name
        return None

    def _fetch(self, url: str) -> Any:
        if self.http is not None:
            return self.http(url)
        last = ""
        for attempt in range(RETRIES):
            try:
                with urllib.request.urlopen(url, timeout=60) as response:   # noqa: S310 (fixed https host)
                    return json.loads(response.read().decode("utf-8"))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last = _redact(str(exc), self.key)
                time.sleep(2 ** attempt)
        raise AlphaVantageError(f"Alpha Vantage did not answer: {last}")

    def adjusted(self, symbol: str) -> pd.Series:
        """The fund's dividend-adjusted daily closes, from the cache or one live call."""
        name = av_symbol(symbol).replace("/", "_") + ".json"
        cached = self._cached(name)
        if cached is not None:
            return parse_adjusted(json.loads(cached.read_text(encoding="utf-8")))
        if self.offline:
            raise KeyError(symbol)
        if self.calls and self.sleep:
            time.sleep(self.sleep)
        query = urllib.parse.urlencode({"function": FUNCTION, "symbol": av_symbol(symbol), "outputsize": "full",
                                        "apikey": self.key})
        data = self._fetch(f"{BASE_URL}?{query}")
        self.calls += 1
        kind = classify(data)
        if kind == "plan":
            raise AlphaVantageError(f"Alpha Vantage refused {FUNCTION} for this key (its plan does not include it): "
                                    + _redact(_message(data), self.key))
        if kind == "limit":
            raise DailyLimit(_redact(_message(data), self.key))
        if kind != "ok":
            raise KeyError(f"{symbol}: {_redact(_message(data), self.key) or 'no prices from Alpha Vantage'}")
        folder = self._dir()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(json.dumps(data), encoding="utf-8")
        return parse_adjusted(data)

    def fetch_all(self, symbols: list[str]) -> tuple[dict[str, pd.Series], list[str]]:
        """Adjusted closes for every symbol it can get; the rest named in the returned errors. On the daily limit
        it stops asking (the cache keeps what it has) and names how many are left for the next run."""
        out: dict[str, pd.Series] = {}
        failed: list[str] = []
        for i, symbol in enumerate(symbols):
            try:
                series = self.adjusted(symbol)
            except DailyLimit as exc:
                left = symbols[i:]
                failed += [f"{s}: not fetched yet (Alpha Vantage allowance spent; run again tomorrow)" for s in left]
                self.errors.append(f"Alpha Vantage allowance spent after {self.calls} call(s); {len(left)} fund(s) "
                                   f"left for the next run ({exc})")
                break
            except KeyError as exc:
                failed.append(str(exc).strip("'\""))
                continue
            if series.empty:
                failed.append(f"{symbol}: no prices from Alpha Vantage")
            else:
                out[symbol] = series
        return out, failed
