"""The one-command setup and the daily schedule, offline: the key, the watchlist, the scheduler commands, the update."""
from __future__ import annotations

import json
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from etf_screener import alphavantage as av
from etf_screener import cli, local


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("ETF_SCREENER_HOME", str(tmp_path / "home"))
    for name in av.KEY_ENV:
        monkeypatch.delenv(name, raising=False)
    return tmp_path / "home"


def _weekly(seed=0):
    days = pd.bdate_range("2018-01-05", "2026-11-13")
    rng = np.random.default_rng(seed)
    path = 20 * np.cumprod(1 + 0.0003 + rng.normal(0, 0.006, len(days)))
    return {"Weekly Adjusted Time Series": {d.date().isoformat(): {"5. adjusted close": f"{p:.4f}"}
                                            for d, p in zip(days, path) if d.weekday() == 4}}


def _free_plan(url):
    if "DAILY_ADJUSTED" in url:
        return {"Information": "Thank you for using Alpha Vantage! This is a premium endpoint."}
    return _weekly(len(url) % 5)


def test_the_key_is_saved_for_the_user_never_printed_and_the_environment_wins(home, monkeypatch, capsys):
    assert local.key() is None
    path = local.save_key("  SECRET-KEY-123  ")
    assert local.key() == "SECRET-KEY-123" and path.parent == home
    if sys.platform != "win32":
        assert oct(path.stat().st_mode & 0o777) == "0o600"
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "FROM-ENV")
    assert local.key() == "FROM-ENV"
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY")
    local.forget_key()
    assert local.key() is None
    assert "SECRET-KEY-123" not in capsys.readouterr().out


def test_check_key_spends_its_one_call_on_a_starter_fund(home):
    asked = []
    assert local.check_key("K", http=lambda url: asked.append(url) or _free_plan(url)) == "ok"
    assert all("XIU.TRT" in u for u in asked) and local.fresh_prices(["XIU.TO"]) == ["XIU.TO"]
    assert local.check_key("K2", ws=home / "w2", http=lambda url: {"Information": "25 requests per day"}) == "limit"
    with pytest.raises(av.AlphaVantageError, match="did not accept"):
        local.check_key("BAD", ws=home / "w3",
                        http=lambda url: {"Error Message": "the parameter apikey is invalid or missing"})


def test_the_watchlist_takes_bare_or_full_tickers_and_refuses_unknown_ones(capsys):
    assert local.watchlist() == []
    assert cli.main(["watch", "add", "xiu", "ZAG.TO", "NOPE"]) == 0
    assert local.watchlist() == ["XIU.TO", "ZAG.TO"] and "Not in the fund list: NOPE.TO" in capsys.readouterr().out
    cli.main(["watch", "remove", "XIU"])
    assert local.watchlist() == ["ZAG.TO"]
    assert local.normalise("zwb.u") == "ZWB-U.TO"


def test_update_lists_every_fund_and_prices_the_watchlist(home, monkeypatch):
    local.save_watchlist(local.STARTER)
    monkeypatch.setattr(av.Client, "_fetch", lambda self, url: _free_plan(url))
    monkeypatch.setattr(cli, "CALL_SPACING", 0.0)
    local.save_key("K")
    assert cli.main(["update"]) == 0
    data = json.loads((local.workspace() / "screener" / "dataset.json").read_text())
    priced = {f["symbol"] for f in data["funds"] if f["return_1y"] is not None}
    assert len(data["funds"]) > 1000 and priced == set(local.STARTER)
    assert data["price_interval"] == "weekly" and local.page_path().exists()
    assert local.fresh_prices(local.STARTER) == sorted(local.STARTER)


def _runner(log, crontab=""):
    def run(args):
        log.append(args)
        if args[:2] == ["crontab", "-l"]:
            return subprocess.CompletedProcess(args, 0 if crontab else 1, crontab, "")
        return subprocess.CompletedProcess(args, 0, "", "")
    return run


def test_windows_schedule_is_one_task_scheduler_entry():
    log = []
    line = local.schedule("07:05", run=_runner(log), platform="win32")
    assert log[0][:6] == ["schtasks", "/Create", "/F", "/SC", "DAILY", "/TN"] and "07:05" in log[0]
    assert log[0][log[0].index("/TR") + 1].endswith("update") and "07:05" in line
    local.unschedule(run=_runner(log), platform="win32")
    assert log[-1] == ["schtasks", "/Delete", "/F", "/TN", local.TASK_NAME]


def test_cron_schedule_keeps_the_users_other_entries_and_replaces_its_own(home):
    log = []
    existing = "0 1 * * * backup.sh\n5 6 * * * old " + local.CRON_MARK + "\n"
    local.schedule("06:30", run=_runner(log, existing), platform="linux")
    written = (home / "crontab.txt").read_text().splitlines()
    assert written[0] == "0 1 * * * backup.sh" and len(written) == 2
    assert written[1].startswith("30 6 * * * ") and "update" in written[1] and written[1].endswith(local.CRON_MARK)
    assert log[-1] == ["crontab", str(home / "crontab.txt")]
    assert local.unschedule(run=_runner(log, "\n".join(written)), platform="linux") == "Schedule removed."
    assert (home / "crontab.txt").read_text().splitlines() == ["0 1 * * * backup.sh"]


def test_status_names_what_is_missing(capsys, monkeypatch):
    monkeypatch.setattr(local, "scheduled", lambda: False)
    cli.main(["status"])
    out = capsys.readouterr().out
    assert "not set: run `etf-screener setup`" in out and "not built yet" in out and "off: run" in out
