# Open ETF Screener — working notes

Read `README.md` first. This repository may become public; write everything in it as if it already is.

## Standing rules

- **No prices, no keys, no client data, ever.** The price cache and builds live in `workspace/` (gitignored).
  Alpha Vantage's data is for each user's own use; committing it would redistribute it. A key is read from
  `ALPHAVANTAGE_API_KEY`, or from the user's own config file outside any repository (`local.py`, written by `setup`,
  readable by that user only where the system allows). It is never printed, logged, cached or committed
  (`alphavantage._redact`).
- **Every cost in `src/etf_screener/data/fund_facts.csv` carries its issuer page and read date.** `check-data` refuses a row without
  them; never loosen the check to admit a row. A figure from a vendor, broker or news article is not an issuer figure.
- **Alpha Vantage's written condition (2026-11-27): no licence while the project stays free and open source
  with each user bringing their own key; a hosted service on InvestMint's own website using their data needs the
  commercial licence.** So the web screener is served from this project's GitHub Pages address only, never
  investmintapp.com, and nothing in this repository fetches Alpha Vantage data with a key that is not the user's.
- **The screener describes and compares; it never recommends.** Whatever the user gives it, including their own
  holdings, it may describe and compare; it never ranks funds for the user, recommends one or proposes a change.
- **The TSX export is read, never committed.** Its terms are the TMX Group's.
- **The screener stays general information.** Filters are fund attributes only (`screen.FILTERS`, closed); the gate
  refuses tailored or promotional phrasing. No risk profile, horizon or questionnaire.
- **A missing figure is a dash, never a zero or a shorter window under a longer label.**
- **Nothing here quotes a performance figure as a result, names a client, or describes a service.** It is a
  general-information tool and stays one.
- `pytest` and `python -m etf_screener check-data` pass before any push; CI runs both.
- Develop on a `claude/*` branch and open a draft PR; never push to `main`.

## Where the data came from

`fund_facts.csv` is compiled from the issuers' own fund pages, fact sheets and product lists, each row with the page
and the date it was read. Nothing else is here: no prices, no vendor data, no account or holdings data. A refresh is a
pull request that changes rows with their pages and dates.

The owner's terminal is Windows PowerShell 5.1: one command per line, never `&&`; full `https://` links.
