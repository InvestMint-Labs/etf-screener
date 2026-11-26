# Open ETF Screener

Screen and compare every ETF listed on the TSX by cost, yield, assets, returns and risk. It runs on your own machine
and produces one HTML page.

- **The fund facts are open data** (`data/fund_facts.csv`, CC BY 4.0). It lists about 1,790 TSX-listed ETF series.
  For each one it gives the cost the issuer publishes, the page that figure was read from, and the date it was read.
- **Prices are fetched with your own key.** Returns, volatility and drawdown are computed on your machine from Alpha
  Vantage's dividend-adjusted daily closes. No price is ever stored in this repository.
- **It is general information, not advice.** You filter on the funds' own facts. Nothing about you is an input: no
  risk profile, no horizon, no questionnaire. [Why](#the-line-it-stays-on).

## Quick start

Python 3.10 or newer.

```bash
git clone https://github.com/InvestMint-Labs/etf-screener
cd etf-screener
pip install -e ".[test]"
export ALPHAVANTAGE_API_KEY=your-key        # Windows PowerShell: $env:ALPHAVANTAGE_API_KEY = "your-key"
python -m etf_screener build --symbols XIU.TO,ZAG.TO,VFV.TO,XBB.TO,ZEB.TO,CASH.TO,XEI.TO,VDY.TO,ZSP.TO,XSP.TO
```

Then open `workspace/screener/site/index.html`. Get a free key at https://www.alphavantage.co/support/#api-key.

To build the whole list, leave out `--symbols`:

```bash
python -m etf_screener build
```

### How long the first full build takes

The free key allows **25 requests a day**. The screener needs one request per fund, and each answer is cached for 7
days under `workspace/external/alphavantage/`.

- Each run fetches until Alpha Vantage says the day's allowance is used up, then stops and keeps what it has.
- `workspace/screener/gaps.md` lists the funds still to fetch.
- No page is written until prices cover at least 95% of the funds, so a page built on a fraction of the market
  cannot appear.

On the free key a full first build takes weeks. A premium key, or Alpha Vantage's unlimited access for verified
open-source projects, does it in one run.

### Optional: categories, assets and yields

The dataset carries costs, not categories, assets or distribution yields. To add those, download the TSX ETF
screener's export yourself from tsx.com and pass it with `--tsx-export`:

```bash
python -m etf_screener build --tsx-export ~/Downloads/etf-screener.csv
```

- Reading `.xlsx` needs `pip install -e ".[xlsx]"`.
- The export is read in place and never copied into this repository, because its terms are the TMX Group's.
- With the export, the TSX's own flags decide which funds are leveraged, inverse or single-stock.
- Without the export, the asset class is inferred from each fund's name, and the page says so on hover.

### Daily or weekly prices

Alpha Vantage's daily adjusted closes are a premium endpoint. The free key has **weekly** adjusted closes: full
history, adjusted for distributions.

By default (`--interval auto`) the screener asks for daily closes once. If your plan refuses, it builds the whole page
on weekly closes and remembers that for 30 days (`workspace/external/alphavantage/plan.json`). A build never mixes the
two. `--interval daily` or `--interval weekly` fixes the choice.

On weekly closes:
- returns are the same to within a few days at each end of the window;
- volatility is annualized over 52 weeks;
- the maximum fall is measured between weekly closes, so a fall that recovered within a week is missed.

The page's sources and its note on the figures say which interval was used.

## What you get

```text
workspace/screener/
  dataset.json     every fund row, each figure with its source
  gaps.md          what is missing (no MER yet, too little history, no prices yet) and the build's findings
  site/index.html  the page, written only when the build passes
```

On the page:
- Filter by asset class, category, issuer, cost, yield, assets, 1-year and 3-year return, volatility, maximum fall
  and duration.
- Sort by any column.
- Compare up to five funds side by side.
- Hover over a figure to see its source.
- A dash means the figure is not available. It is never shown as a zero.

### Commands and options

| Command | |
|---|---|
| `python -m etf_screener build` | Build the page |
| `--symbols XIU.TO,ZAG.TO` | Build only these funds |
| `--limit N` | Build only the first N funds |
| `--include-all` | Keep leveraged, inverse and single-stock funds (left out by default) |
| `--offline` | Use cached prices only |
| `--interval auto\|daily\|weekly` | Daily closes (premium) or weekly (free key); `auto` falls back to weekly |
| `--workspace PATH` | Where the cache and output go (default `./workspace`) |
| `python -m etf_screener check-data` | Check `data/fund_facts.csv` against its rules |

## How the figures are computed

| Figure | Source and rule |
|---|---|
| Cost | The issuer's published MER, with its page and date. Where no MER is published yet, the management fee is shown and marked *fee*; the MER, which adds the fund's other costs, is higher. A blank means unknown, not free. |
| 1, 3 and 5-year return | Total return from adjusted closes, annualized over three and five years, before any adviser fee and before tax. If a fund's history does not reach back far enough for a window, that figure is blank. A shorter window is never shown under the longer label. |
| 3-year volatility, max fall | Annualized volatility of daily returns (252 days a year) or weekly returns (52 weeks), and the largest peak-to-trough fall between closes over the same three years. |
| Duration | The issuer's effective duration, where it is in the dataset. |

**Checks.** A build fails, and no page is written, if any of these happen:
- a figure appears without a source;
- a value is outside its plausible range (for example a MER written as `65` instead of `0.65`);
- prices are missing for more than 5% of the funds;
- the list shrinks more than 10% from the previous build.

If one fund's prices produce implausible returns, its return and risk figures are left blank and the fund is named in
`gaps.md`.

## The line it stays on

In Canada, a publisher that is not registered may give advice only where it is not tailored to the person receiving
it (NI 31-103 s.8.25; CSA Staff Notice 31-369). The screener is built to stay on that line:

- **Closed filter list.** `screen.FILTERS` names fund attributes only. An unknown filter is refused, not ignored.
- **The page gate** (`gate.py`) refuses to write a page that:
  - uses tailored or promotional phrasing ("suitable for you", "top pick");
  - lacks the disclosure, the data source or the date;
  - carries a filter outside the closed list.
- **One filter logic.** The browser runs the same filter code as Python, and the tests require both to give the same
  answer.

If you change the page, keep it general.

## Data terms

- **Alpha Vantage.** Alpha Vantage's terms allow personal, non-commercial use. Running this screener with your own key
  for yourself is that. Publishing pages built from Alpha Vantage data as a business needs Alpha Vantage's written
  permission (https://www.alphavantage.co/terms_of_service/).
- **The fund facts.** CC BY 4.0. Credit the dataset as `data/LICENSE.md` says.
- **The code.** MIT (`LICENSE`).

## Contributing

- **Fund facts.** A correction is a pull request that changes the row and gives the issuer's page and the date you
  read it. See `data/README.md`.
- **Code.** Run `pytest` and `python -m etf_screener check-data` before you open a pull request. The CI runs both.

Maintained by InvestMint Inc. Nothing in this repository is an offer, a solicitation or a recommendation to buy or
sell any security.
