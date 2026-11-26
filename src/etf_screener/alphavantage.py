"""Alpha Vantage client: dividend-adjusted closes for each fund, with your own key.

Alpha Vantage's terms grant personal, non-commercial use of its data. Running this screener with your own key for
yourself is that; publishing pages built from Alpha Vantage data as a business needs Alpha Vantage's written
permission. Nothing here writes a price anywhere but your own cache, and no price is ever committed to this
repository.

- The key comes from ``ALPHAVANTAGE_API_KEY`` (or ``ALPHA_VANTAGE_API_KEY``) and is never written to a cache, a log
  line or an error message: ``_redact`` strips it from anything that could be printed.
- A TSX symbol (``XIU.TO``) is ``XIU.TRT`` at Alpha Vantage; a US symbol has no suffix.
- Every response is cached under ``<workspace>/external/alphavantage/<daily|weekly>/<YYYYMMDD>/`` and reused for
  ``PRICE_MAX_AGE_DAYS``. The free key allows 25 requests a day, so a first build of the whole list fills the cache
  over many days: when Alpha Vantage says the day's allowance is spent, the client stops asking, keeps what it has
  and names how many funds are still to fetch.
- **Daily or weekly.** Daily adjusted closes (``TIME_SERIES_DAILY_ADJUSTED``) are a premium endpoint; the free key
  has weekly adjusted closes (``TIME_SERIES_WEEKLY_ADJUSTED``, full history, adjusted for distributions). With
  ``interval="auto"`` the client asks for daily, and on the plan's refusal switches the whole run to weekly and records
  the answer in ``external/alphavantage/plan.json`` so later runs do not spend a call asking again (re-checked after
  ``PLAN_RECHECK_DAYS``). One build never mixes the two: ``active`` names the interval every series came from.
- An endpoint the key's plan does not include raises ``AlphaVantageError`` naming it (when the interval was fixed),
  rather than a build quietly computing returns from closes that were not adjusted for distributions.
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
FUNCTIONS = {"daily": ("TIME_SERIES_DAILY_ADJUSTED", "Time Series (Daily)"),
             "weekly": ("TIME_SERIES_WEEKLY_ADJUSTED", "Weekly Adjusted Time Series")}
FUNCTION, SERIES_KEY = FUNCTIONS["daily"]
ADJUSTED = "5. adjusted close"
PERIODS_PER_YEAR = {"daily": 252, "weekly": 52}
PLAN_RECHECK_DAYS = 30
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
    if isinstance(data, dict) and any(isinstance(data.get(key), dict) for _, key in FUNCTIONS.values()):
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
    rows = next((data[key] for _, key in FUNCTIONS.values() if isinstance(data.get(key), dict)), {})
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
    interval: str = "auto"                          # "daily", "weekly", or "auto" (daily if the plan has it)
    errors: list[str] = field(default_factory=list)
    calls: int = 0
    active: str = ""                                # the interval this run's series come from

    def __post_init__(self) -> None:
        self.workspace = Path(self.workspace)
        if self.key is None:
            self.key = key_from_env()
        if not self.offline and not self.key:
            raise AlphaVantageError(f"No Alpha Vantage key: set {KEY_ENV[0]} (a free key: "
                                    "https://www.alphavantage.co/support/#api-key), or run offline on a cached download.")
        if self.interval not in ("auto", *FUNCTIONS):
            raise AlphaVantageError(f"interval {self.interval!r} is not auto, daily or weekly")
        self.active = self.interval if self.interval != "auto" else self._remembered()

    @property
    def periods_per_year(self) -> int:
        return PERIODS_PER_YEAR[self.active]

    def _plan_file(self) -> Path:
        return self.workspace / "external" / "alphavantage" / "plan.json"

    def _remembered(self) -> str:
        """``weekly`` if a recent run found the key's plan without daily adjusted closes, else ``daily``."""
        try:
            plan = json.loads(self._plan_file().read_text(encoding="utf-8"))
            checked = date.fromisoformat(plan["checked"])
        except (OSError, ValueError, KeyError, TypeError):
            return "daily"
        if plan.get("daily_adjusted") is False and (self.today - checked).days <= PLAN_RECHECK_DAYS:
            return "weekly"
        return "daily"

    def _remember(self, daily: bool) -> None:
        path = self._plan_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"daily_adjusted": daily, "checked": self.today.isoformat()}), encoding="utf-8")

    def _dir(self, day: date | None = None) -> Path:
        return self.workspace / "external" / "alphavantage" / self.active / (day or self.today).strftime("%Y%m%d")

    def _cached(self, name: str) -> Path | None:
        root = self.workspace / "external" / "alphavantage" / self.active
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
        function = FUNCTIONS[self.active][0]
        params = {"function": function, "symbol": av_symbol(symbol), "apikey": self.key}
        if self.active == "daily":
            params["outputsize"] = "full"
        data = self._fetch(f"{BASE_URL}?{urllib.parse.urlencode(params)}")
        self.calls += 1
        kind = classify(data)
        if kind == "plan" and self.interval == "auto" and self.active == "daily":
            self._remember(False)
            self.active = "weekly"
            self.errors.append("Alpha Vantage: this key's plan has no daily adjusted closes; using weekly adjusted "
                               f"closes (re-checked after {PLAN_RECHECK_DAYS} days)")
            return self.adjusted(symbol)
        if kind == "plan":
            raise AlphaVantageError(f"Alpha Vantage refused {function} for this key (its plan does not include it): "
                                    + _redact(_message(data), self.key))
        if kind == "limit":
            raise DailyLimit(_redact(_message(data), self.key))
        if kind != "ok":
            raise KeyError(f"{symbol}: {_redact(_message(data), self.key) or 'no prices from Alpha Vantage'}")
        if self.interval == "auto" and self.active == "daily" and not self._plan_file().exists():
            self._remember(True)
        folder = self._dir()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(json.dumps(data), encoding="utf-8")
        return parse_adjusted(data)

    def fetch_all(self, symbols: list[str]) -> tuple[dict[str, pd.Series], list[str]]:
        """Adjusted closes for every symbol it can get; the rest named in the returned errors. On the daily limit
        it stops asking (the cache keeps what it has) and names how many are left for the next run."""
        out: dict[str, pd.Series] = {}
        failed: list[str] = []
        start = self.active
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
            if self.active != start and out:
                # the plan changed mid-run (a premium key lapsed): start again so every series has one interval
                return self.fetch_all(symbols)
            if series.empty:
                failed.append(f"{symbol}: no prices from Alpha Vantage")
            else:
                out[symbol] = series
        return out, failed
