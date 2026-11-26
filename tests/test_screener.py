"""The screener end to end on synthetic data: the dataset's rules, fund rows, the closed filter list, the checks, the
page gate, the browser's filter logic held to the Python one, and the Alpha Vantage client. Nothing touches the
network."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from etf_screener import alphavantage as av
from etf_screener import cli, dataset, facts, funds, gate, page, screen

REPO = Path(__file__).resolve().parents[1]


def _closes(start: str, end: str = "2026-11-17", growth: float = 0.08, seed: int = 0, noise: float = 0.004):
    days = pd.bdate_range(start, end)
    rng = np.random.default_rng(seed)
    daily = (1 + growth) ** (1 / 252) - 1
    path = 20 * np.cumprod(1 + daily + rng.normal(0, noise, len(days)))
    return days, path


def _av_response(seed: int = 0, start: str = "2018-01-02") -> dict:
    days, path = _closes(start, growth=0.05, seed=seed)
    return {"Meta Data": {"2. Symbol": "X"},
            "Time Series (Daily)": {d.date().isoformat(): {"4. close": f"{p:.4f}", "5. adjusted close": f"{p:.4f}"}
                                    for d, p in zip(days, path)}}


def _facts_file(tmp_path: Path, n: int = 12) -> Path:
    rows = []
    for i in range(n):
        rows.append({"symbol": f"T{i:02d}.TO", "name": f"Test {'Bond' if i % 3 == 0 else 'Equity'} Fund {i}",
                     "issuer": "Issuer One" if i % 2 else "Issuer Two", "currency": "CAD",
                     "mer_pct": "" if i == 1 else f"{0.1 + i / 100:.2f}", "mer_as_of": "2026-06-30",
                     "mgmt_fee_pct": "0.05" if i == 1 else "", "duration_years": "6.5" if i == 0 else "",
                     "structure": "", "url": f"https://issuer.example/{i}", "read_on": "2026-11-25",
                     "reviewed": "no", "note": "", "duration_source": "Issuer (https://issuer.example/0)" if i == 0 else ""})
    rows.append({**rows[-1], "symbol": "LEV.TO", "name": "Test 2x Daily Bull ETF", "structure": "leveraged"})
    path = tmp_path / "facts.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _client(tmp_path: Path) -> av.Client:
    return av.Client(tmp_path / "ws", key="K", http=lambda url: _av_response(len(url) % 7))


# -- the open dataset --------------------------------------------------------------------------------------------
def test_the_committed_dataset_passes_its_own_check():
    rows = facts.load(REPO / "data" / "fund_facts.csv")
    assert len(rows) > 1000 and facts.check(rows) == []
    assert all(r["url"].startswith("https://") for r in rows if r["mer_pct"] is not None)


def test_a_cost_without_its_page_or_date_is_refused(tmp_path):
    rows = facts.load(_facts_file(tmp_path))
    rows[0]["url"], rows[2]["mer_pct"], rows[3]["symbol"] = "", 65.0, "XIU"
    found = " ".join(facts.check(rows))
    assert "T00.TO: a cost with no https page" in found and "T02.TO: mer_pct 65.0" in found and "XIU: symbol" in found


def test_the_tsx_export_is_read_and_its_flags_win(tmp_path):
    export = tmp_path / "tsx.csv"
    export.write_text("Note line\nSymbol,Fund Name,Asset Class,Investment Style,AUM ($),Mgmt Fee (%),"
                      "Distribution Yield (%),Inception Date,Currency\n"
                      "T00,Test Bond,Fixed Income,Canadian Bond,\"$1,200,000\",0.10,3.5,2015-01-02,CAD\n"
                      "T02,Test Equity,Single Stock ETF,Single,5000000,0.40,1.0,2020-01-02,CAD\n"
                      "ZWB.U,X,Equity,Large Cap,1,0.1,1,2020-01-02,USD\n", encoding="utf-8")
    e = facts.read_tsx_export(export)
    assert e["T00.TO"]["aum"] == 1_200_000 and e["T00.TO"]["yield"] == pytest.approx(0.035)
    assert e["T02.TO"]["structure"] == "single_stock" and "ZWB-U.TO" in e
    kept = funds.eligible(facts.load(_facts_file(tmp_path)), e)
    assert [f["symbol"] for f in kept] == ["T00.TO"]      # T02 is single-stock per the TSX; the rest are not listed


# -- fund rows ---------------------------------------------------------------------------------------------------
def test_returns_are_computed_on_the_window_named():
    days, path = _closes("2019-01-02", growth=0.10, noise=0.0)
    m3 = funds.window_measures(pd.Series(path, index=days), 3)
    assert m3["return"] == pytest.approx(0.10, abs=0.005) and m3["max_drawdown"] == pytest.approx(0.0, abs=1e-9)
    days, path = _closes("2025-03-03")
    assert funds.window_measures(pd.Series(path, index=days), 3) is None     # not enough history: blank, not shorter


def test_cost_says_what_it_is_and_carries_its_page(tmp_path):
    rows = facts.load(_facts_file(tmp_path))
    mer = funds.fund_row(rows[0], None)
    fee = funds.fund_row(rows[1], None)
    assert mer["cost_kind"] == "MER" and "as of 2026-06-30" in mer["sources"]["cost"]
    assert "https://issuer.example/0" in mer["sources"]["cost"] and mer["duration"] == 6.5
    assert fee["cost_kind"] == "management fee" and "MER is higher" in fee["sources"]["cost"]
    assert mer["asset_class"] == "Fixed income" and mer["sources"]["asset_class"] == funds.NAME_SOURCE
    assert funds.fund_row(rows[2], None)["asset_class"] == "Equity"


@pytest.mark.parametrize("key", ["risk_profile", "horizon", "age", "risk_tolerance", "goal"])
def test_nothing_about_the_reader_can_be_a_filter(key):
    with pytest.raises(screen.ScreenError, match="fund attributes only"):
        screen.screen([], {key: "x"})


# -- the build ---------------------------------------------------------------------------------------------------
def test_build_writes_a_gated_page_with_its_sources(tmp_path):
    code, page_path, findings = cli.build(tmp_path / "ws", _facts_file(tmp_path), client=_client(tmp_path))
    assert code == 0 and findings == [] and page_path.exists()
    html = page_path.read_text(encoding="utf-8")
    assert gate.check(html) == [] and "Alpha Vantage" in html
    data = json.loads((tmp_path / "ws" / "screener" / "dataset.json").read_text())
    assert "LEV.TO" not in {f["symbol"] for f in data["funds"]}             # leveraged funds are left out
    t3 = next(f for f in data["funds"] if f["symbol"] == "T03.TO")
    assert t3["sources"]["performance"] == funds.PERF_SOURCE and t3["return_3y"] is not None


def test_a_cache_still_filling_holds_the_page_back(tmp_path):
    answers = iter([_av_response(1)] * 3 + [{"Information": "25 requests per day"}])
    client = av.Client(tmp_path / "ws", key="K", http=lambda url: next(answers))
    code, page_path, findings = cli.build(tmp_path / "ws", _facts_file(tmp_path), client=client)
    assert code == 1 and not page_path.exists() and "have no prices yet" in findings[0]
    assert "run again tomorrow" in (tmp_path / "ws" / "screener" / "gaps.md").read_text()


def test_gate_refuses_tailored_copy_and_a_missing_disclosure(tmp_path):
    cli.build(tmp_path / "ws", _facts_file(tmp_path), client=_client(tmp_path))
    html = (tmp_path / "ws" / "screener" / "site" / "index.html").read_text(encoding="utf-8")
    assert any("suitable for you" in f for f in gate.check(html.replace("<h1>", "<h1>Suitable for you ")))
    assert any("disclosure" in f for f in gate.check(html.replace(page.DISCLOSURE[:40], "")))


def test_browser_filter_logic_matches_python(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    cli.build(tmp_path / "ws", _facts_file(tmp_path), client=_client(tmp_path))
    data = json.loads((tmp_path / "ws" / "screener" / "dataset.json").read_text())
    cases = [({}, "aum", True), ({"cost_max": 0.15}, "cost_pct", False), ({"issuer": ["Issuer One"]}, "symbol", False),
             ({"return_3y_min": 0.0, "text": "equity"}, "return_3y", True)]
    expected = [[f["symbol"] for f in screen.screen(data["funds"], c, s, d)] for c, s, d in cases]
    script = (f"const D={json.dumps(data)};\n{page.JS}\n"
              f"console.log(JSON.stringify({json.dumps(cases)}.map(([c,s,d]) => screenFunds(D.funds,c,s,d).map(f => f.symbol))));")
    js = tmp_path / "parity.js"
    js.write_text(script, encoding="utf-8")
    done = subprocess.run([node, str(js)], capture_output=True, text=True, check=True)
    assert json.loads(done.stdout) == expected


# -- Alpha Vantage -----------------------------------------------------------------------------------------------
def test_alpha_vantage_maps_tsx_symbols_classifies_answers_and_never_prints_the_key():
    assert av.av_symbol("XIU.TO") == "XIU.TRT" and av.av_symbol("ZWB-U.TO") == "ZWB-U.TRT" and av.av_symbol("SPY") == "SPY"
    assert av.classify(_av_response()) == "ok"
    assert av.classify({"Information": "Thank you for using Alpha Vantage! This is a premium endpoint."}) == "plan"
    assert av.classify({"Information": "our standard API rate limit is 25 requests per day"}) == "limit"
    assert av.classify({"Error Message": "Invalid API call."}) == "symbol"
    assert av._redact("https://x?apikey=SECRET123", "SECRET123") == "https://x?apikey=***"
    s = av.parse_adjusted(_av_response())
    assert len(s) > 1000 and s.index.is_monotonic_increasing and (s > 0).all()


def test_alpha_vantage_stops_at_the_daily_limit_keeps_the_cache_and_names_what_is_left(tmp_path, monkeypatch):
    answers = iter([_av_response(1), _av_response(2), {"Information": "25 requests per day"}])
    asked = []

    def http(url):
        asked.append(url)
        return next(answers)

    client = av.Client(tmp_path, key="SECRET123", http=http)
    got, failed = client.fetch_all(["A.TO", "B.TO", "C.TO", "D.TO"])
    assert set(got) == {"A.TO", "B.TO"} and len(asked) == 3          # D was never asked for
    assert [f.split(":")[0] for f in failed] == ["C.TO", "D.TO"] and "tomorrow" in failed[0]
    assert "SECRET123" not in " ".join(client.errors + failed)
    again = av.Client(tmp_path, key="SECRET123", http=lambda url: (_ for _ in ()).throw(AssertionError(url)))
    assert set(again.fetch_all(["A.TO", "B.TO"])[0]) == {"A.TO", "B.TO"}   # from the cache, no call

    plan = av.Client(tmp_path / "p", key="K", http=lambda url: {"Information": "This is a premium endpoint."})
    with pytest.raises(av.AlphaVantageError, match="plan does not include"):
        plan.adjusted("XIU.TO")
    for name in av.KEY_ENV:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(av.AlphaVantageError, match="ALPHAVANTAGE_API_KEY"):
        av.Client(tmp_path / "n")


def test_the_cli_stops_without_a_key_and_says_how_to_get_one(tmp_path, monkeypatch, capsys):
    for name in av.KEY_ENV:
        monkeypatch.delenv(name, raising=False)
    assert cli.main(["build", "--workspace", str(tmp_path), "--facts", str(_facts_file(tmp_path))]) == 2
    assert "alphavantage.co/support/#api-key" in capsys.readouterr().out


# -- the free key: weekly adjusted closes ------------------------------------------------------------------------
def _av_weekly(seed: int = 0) -> dict:
    days, path = _closes("2018-01-05", growth=0.05, seed=seed)
    return {"Meta Data": {"2. Symbol": "X"},
            "Weekly Adjusted Time Series": {d.date().isoformat(): {"5. adjusted close": f"{p:.4f}"}
                                            for d, p in zip(days, path) if d.weekday() == 4}}


def _free_plan(asked):
    def http(url):
        asked.append(url)
        if "TIME_SERIES_DAILY_ADJUSTED" in url:
            return {"Information": "Thank you for using Alpha Vantage! This is a premium endpoint."}
        return _av_weekly(len(url) % 7)
    return http


def test_a_free_key_falls_back_to_weekly_closes_and_remembers_it(tmp_path):
    asked: list[str] = []
    client = av.Client(tmp_path, key="K", http=_free_plan(asked))
    got, failed = client.fetch_all(["A.TO", "B.TO"])
    assert set(got) == {"A.TO", "B.TO"} and failed == [] and client.active == "weekly"
    assert ["DAILY" in u for u in asked] == [True, False, False]          # one refused daily call, then weekly
    again: list[str] = []
    later = av.Client(tmp_path, key="K", http=_free_plan(again))
    assert later.active == "weekly" and set(later.fetch_all(["A.TO", "B.TO", "C.TO"])[0]) == {"A.TO", "B.TO", "C.TO"}
    assert len(again) == 1 and "WEEKLY" in again[0]                       # no daily call; A and B from the cache
    with pytest.raises(av.AlphaVantageError, match="plan does not include"):
        av.Client(tmp_path / "f", key="K", http=_free_plan([]), interval="daily").adjusted("XIU.TO")


def test_weekly_closes_are_annualized_over_52_weeks_and_the_page_says_weekly(tmp_path):
    days = pd.bdate_range("2019-01-04", "2026-11-13")
    rng = np.random.default_rng(5)
    daily = pd.Series(20 * np.cumprod(1 + 0.0003 + rng.normal(0, 0.008, len(days))), index=days)
    weekly = daily[daily.index.weekday == 4]
    d3, w3 = funds.window_measures(daily, 3), funds.window_measures(weekly, 3, 52)
    assert w3["return"] == pytest.approx(d3["return"], abs=0.01)
    assert w3["volatility"] == pytest.approx(d3["volatility"], rel=0.2)    # same scale, not five times larger
    assert w3["max_drawdown"] <= d3["max_drawdown"] + 1e-9                 # weekly closes miss intra-week falls

    client = av.Client(tmp_path / "ws", key="K", http=_free_plan([]))
    code, page_path, findings = cli.build(tmp_path / "ws", _facts_file(tmp_path), client=client)
    assert code == 0 and findings == []
    data = json.loads((tmp_path / "ws" / "screener" / "dataset.json").read_text())
    assert data["price_interval"] == "weekly" and "weekly closes" in data["data_note"]
    t3 = next(f for f in data["funds"] if f["symbol"] == "T03.TO")
    assert t3["sources"]["performance"] == funds.PERF_SOURCES["weekly"] and 0 < t3["volatility_3y"] < 0.5
    html = page_path.read_text(encoding="utf-8")
    assert "volatility of weekly returns" in html and gate.check(html) == []


def test_a_trial_build_never_moves_the_real_build_or_its_baseline(tmp_path):
    facts_file = _facts_file(tmp_path)
    code, page_path, _ = cli.build(tmp_path / "ws", facts_file, client=_client(tmp_path))
    assert code == 0 and dataset.previous_count(tmp_path / "ws" / "screener") == 12
    code, trial, findings = cli.build(tmp_path / "ws", facts_file, symbols=["T00.TO", "T03.TO"],
                                      client=_client(tmp_path))
    assert code == 1 and any("minimum" in f for f in findings) and not any("last build" in f for f in findings)
    assert trial.parent.parent.name == "screener-trial" and page_path.exists()
    assert dataset.previous_count(tmp_path / "ws" / "screener") == 12
    assert any("last build that passed" in f for f in dataset.check([], 0, [], previous=12))
