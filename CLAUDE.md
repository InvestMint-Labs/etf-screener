# Open ETF Screener — working notes

Read `README.md` first. This repository may become public; write everything in it as if it already is.

## Standing rules

- **No prices, no keys, no client data, ever.** The price cache and builds live in `workspace/` (gitignored).
  Alpha Vantage's data is for each user's own use; committing it would redistribute it. A key is read from
  `ALPHAVANTAGE_API_KEY` and is never written anywhere (`alphavantage._redact`).
- **Every cost in `data/fund_facts.csv` carries its issuer page and read date.** `check-data` refuses a row without
  them; never loosen the check to admit a row. A figure from a vendor, broker or news article is not an issuer figure.
- **The TSX export is read, never committed.** Its terms are the TMX Group's.
- **The screener stays general information.** Filters are fund attributes only (`screen.FILTERS`, closed); the gate
  refuses tailored or promotional phrasing. No risk profile, horizon or questionnaire.
- **A missing figure is a dash, never a zero or a shorter window under a longer label.**
- **Nothing here names InvestMint Wealth or its services, or quotes a performance figure as a result.** The package
  rules in `InvestMint-Labs/investor-package` (`CLAUDE.md`) apply to anything InvestMint publishes from this.
- `pytest` and `python -m etf_screener check-data` pass before any push; CI runs both.
- Develop on a `claude/*` branch and open a draft PR; never push to `main`.

## Where the data came from

The first `fund_facts.csv` (2026-11-26) merged three files from InvestMint's private core
(`clients/etf_optimizer/config/`): `issuer_mers.csv` (the issuer sweep), `fund_facts.json` (TSX funds reviewed fund
by fund; they win, except PMIF.TO, whose reviewed MER came from a fund-listing site and was left out) and
`issuer_facts.csv` (durations). Nothing else from the core is here: no register, no Yahoo
loader, no client or mandate data, no Morningstar figures. When the core's issuer files are refreshed, carry the
change here as a pull request with its pages and dates.

The owner's terminal is Windows PowerShell 5.1: one command per line, never `&&`; full `https://` links.
