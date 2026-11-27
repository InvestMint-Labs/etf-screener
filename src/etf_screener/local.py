"""Everything the screener keeps on your own machine: your key, your watchlist, your price cache and your page.

One folder holds it all, outside any repository: ``%LOCALAPPDATA%\\etf-screener`` on Windows,
``~/Library/Application Support/etf-screener`` on macOS, ``~/.local/share/etf-screener`` elsewhere
(``ETF_SCREENER_HOME`` overrides it):

    config.json     your Alpha Vantage key (readable by your user only, where the system allows), never printed
    watchlist.txt   the funds whose returns and risk are kept fresh, one ticker a line
    workspace/      the price cache and the built page (workspace/screener/site/index.html)
    update.log      what the scheduled run did

**Why a watchlist.** A price is reused for ``PRICE_MAX_AGE_DAYS`` (7), and a free key allows 25 requests a day, so a
free key keeps at most about 175 funds' prices fresh. The page always lists every fund with its costs; returns and
risk are added for the watched funds. ``STARTER`` is twenty broad, widely held ETFs; ``watch`` adds or removes.
A key with a higher allowance (premium, or Alpha Vantage's open-source programme) can watch the whole list.

**The schedule.** ``schedule`` registers one daily run of ``etf-screener update`` with the system's own scheduler
(Task Scheduler on Windows, cron elsewhere), and ``schedule --off`` removes it. Nothing runs in the background
otherwise, and the run only ever uses your own key against your own allowance.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

from . import alphavantage

STARTER = ["XIU.TO", "XIC.TO", "ZCN.TO", "VCN.TO", "XEQT.TO", "VEQT.TO", "ZEQT.TO", "XBAL.TO", "VBAL.TO", "XGRO.TO",
           "VGRO.TO", "ZAG.TO", "XBB.TO", "VAB.TO", "VFV.TO", "XUS.TO", "ZSP.TO", "XEF.TO", "XAW.TO", "CASH.TO"]
FREE_CALLS_PER_DAY = 25
FREE_CAPACITY = FREE_CALLS_PER_DAY * alphavantage.PRICE_MAX_AGE_DAYS      # funds a free key keeps fresh
TASK_NAME = "ETF Screener update"
CRON_MARK = "# etf-screener update"
Runner = Callable[[list[str]], subprocess.CompletedProcess]


def home() -> Path:
    if os.environ.get("ETF_SCREENER_HOME"):
        return Path(os.environ["ETF_SCREENER_HOME"])
    if sys.platform.startswith("win"):
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "etf-screener"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "etf-screener"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "etf-screener"


def workspace() -> Path:
    return home() / "workspace"


def page_path() -> Path:
    return workspace() / "screener" / "site" / "index.html"


# -- the key --------------------------------------------------------------------------------------------------------
def _config_path() -> Path:
    return home() / "config.json"


def _config() -> dict[str, Any]:
    try:
        return json.loads(_config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def key() -> str | None:
    """The key from the environment first (``ALPHAVANTAGE_API_KEY``), then from this machine's config."""
    return alphavantage.key_from_env() or (_config().get("alphavantage_key") or None)


def save_key(value: str) -> Path:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = _config()
    cfg["alphavantage_key"] = value.strip()
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)                       # your user only, on systems that honour it
    except OSError:
        pass
    return path


def forget_key() -> None:
    cfg = _config()
    if cfg.pop("alphavantage_key", None) is not None:
        _config_path().write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def check_key(value: str, ws: Path | None = None, http: Callable[[str], Any] | None = None) -> str:
    """Try the key with one request (XIU.TO, which the starter watchlist needs anyway, so the call is not wasted).
    Returns ``ok`` or ``limit`` (valid, but today's allowance is used); raises ``AlphaVantageError`` if refused."""
    client = alphavantage.Client(ws or workspace(), key=value, http=http)
    try:
        client.adjusted("XIU.TO")
    except alphavantage.DailyLimit:
        return "limit"
    except KeyError as exc:
        text = str(exc).lower()
        if "apikey" in text or "api key" in text or "invalid" in text:
            raise alphavantage.AlphaVantageError("Alpha Vantage did not accept that key") from None
        raise alphavantage.AlphaVantageError(f"Alpha Vantage did not answer as expected: {exc}") from None
    return "ok"


# -- the watchlist --------------------------------------------------------------------------------------------------
def _watch_path() -> Path:
    return home() / "watchlist.txt"


def watchlist() -> list[str]:
    try:
        lines = _watch_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return sorted({ln.strip().upper() for ln in lines if ln.strip() and not ln.startswith("#")})


def save_watchlist(symbols: list[str]) -> None:
    path = _watch_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    head = "# Funds whose returns and risk the screener keeps fresh, one ticker a line (XIU.TO form).\n"
    path.write_text(head + "\n".join(sorted({s.strip().upper() for s in symbols if s.strip()})) + "\n",
                    encoding="utf-8")


def normalise(symbol: str) -> str:
    s = symbol.strip().upper()
    return s if s.endswith(".TO") else s.replace(".", "-") + ".TO"


# -- freshness ------------------------------------------------------------------------------------------------------
def fresh_prices(symbols: list[str], today: date | None = None) -> list[str]:
    """The watched funds whose cached prices are inside the reuse window (any interval)."""
    today = today or date.today()
    root = workspace() / "external" / "alphavantage"
    found = set()
    for interval in ("daily", "weekly"):
        base = root / interval
        if not base.exists():
            continue
        for folder in base.iterdir():
            try:
                day = datetime.strptime(folder.name, "%Y%m%d").date()
            except ValueError:
                continue
            if (today - day).days > alphavantage.PRICE_MAX_AGE_DAYS:
                continue
            for s in symbols:
                if (folder / (alphavantage.av_symbol(s).replace("/", "_") + ".json")).exists():
                    found.add(s)
    return sorted(found)


# -- the schedule ---------------------------------------------------------------------------------------------------
def command() -> list[str]:
    """How the scheduler starts the update: the installed ``etf-screener`` command, else this Python."""
    exe = shutil.which("etf-screener")
    return [exe, "update"] if exe else [sys.executable, "-m", "etf_screener", "update"]


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)        # noqa: S603 (fixed system commands)


def _quote(args: list[str]) -> str:
    return " ".join(f'"{a}"' if " " in a else a for a in args)


def schedule(at: str = "06:30", run: Runner = _run, platform: str = sys.platform) -> str:
    """Register the daily update; returns a line saying what was done."""
    hh, mm = (int(x) for x in at.split(":"))
    cmd = command()
    if platform.startswith("win"):
        done = run(["schtasks", "/Create", "/F", "/SC", "DAILY", "/TN", TASK_NAME, "/ST", f"{hh:02d}:{mm:02d}",
                    "/TR", _quote(cmd)])
        if done.returncode:
            raise RuntimeError(f"Task Scheduler refused: {(done.stderr or done.stdout).strip()}")
        return f"Scheduled: “{TASK_NAME}” runs daily at {hh:02d}:{mm:02d} (Task Scheduler)."
    log = home() / "update.log"
    line = f"{mm} {hh} * * * {_quote(cmd)} >> {_quote([str(log)])} 2>&1 {CRON_MARK}"
    current = run(["crontab", "-l"])
    kept = [ln for ln in (current.stdout or "").splitlines() if CRON_MARK not in ln] if current.returncode == 0 else []
    done = _install_crontab(kept + [line], run)
    if done.returncode:
        raise RuntimeError(f"cron refused: {(done.stderr or done.stdout).strip()}")
    return f"Scheduled: daily at {hh:02d}:{mm:02d} (cron); the log is {log}."


def _install_crontab(lines: list[str], run: Runner) -> subprocess.CompletedProcess:
    """Replace the user's crontab with ``lines`` (their other entries kept), through a file in the screener's folder."""
    path = home() / "crontab.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return run(["crontab", str(path)])


def unschedule(run: Runner = _run, platform: str = sys.platform) -> str:
    if platform.startswith("win"):
        done = run(["schtasks", "/Delete", "/F", "/TN", TASK_NAME])
        return "Schedule removed." if done.returncode == 0 else "There was no schedule to remove."
    current = run(["crontab", "-l"])
    if current.returncode != 0 or CRON_MARK not in (current.stdout or ""):
        return "There was no schedule to remove."
    _install_crontab([ln for ln in current.stdout.splitlines() if CRON_MARK not in ln], run)
    return "Schedule removed."


def scheduled(run: Runner = _run, platform: str = sys.platform) -> bool:
    if platform.startswith("win"):
        return run(["schtasks", "/Query", "/TN", TASK_NAME]).returncode == 0
    current = run(["crontab", "-l"])
    return current.returncode == 0 and CRON_MARK in (current.stdout or "")
