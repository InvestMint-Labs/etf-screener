# Fund facts

`fund_facts.csv`: one row per ETF series listed on the TSX, with the cost its issuer publishes and where that figure
was read. Licence: CC BY 4.0 (`LICENSE.md` in this folder).

| Column | Meaning |
|---|---|
| `symbol` | The ticker in Yahoo-style form: `XIU.TO`; a class or currency series takes a dash (`ZWB-U.TO`) |
| `name`, `issuer` | As the issuer names them |
| `currency` | The series' trading currency (`-U` series are USD) |
| `mer_pct` | The management expense ratio as a percentage number (`0.65` means 0.65%); blank when the issuer publishes none yet |
| `mer_as_of` | The period end the MER covers, when the issuer states one |
| `mgmt_fee_pct` | The management fee, a percentage number. It is lower than the MER, which adds the fund's other costs; the screener shows it, marked *fee*, only where no MER is published. `0` is a fee the issuer waives |
| `duration_years` | Effective duration for bond funds, where the issuer publishes it; `duration_source` names the page |
| `structure` | `leveraged`, `inverse` or `single_stock`, read from the fund's name; blank for everything else. The screener leaves these out unless asked (`--include-all`) |
| `url`, `read_on` | The issuer page or document the cost was read from, and the date it was read |
| `reviewed` | `yes` where the row was checked fund by fund against the issuer's fund page; `no` where it came from the issuer's lineup page or MER list |
| `note` | What the page said that a column cannot: no period given, a waiver, a series the issuer lists without an MER |

## The rules a row is held to

`python -m etf_screener check-data` (and the CI on every pull request) refuses:

- a cost without an `https` page and a `read_on` date;
- a cost outside 0-12 (a percentage number, so `65` for 0.65% is caught);
- a symbol not in `XIU.TO` form, or listed twice;
- a duration without its source.

## Correcting or adding a fund

Open a pull request that changes the row and gives the issuer's page in `url` and today's date in `read_on`. A figure
from a data vendor, a broker or a news article is not accepted: the dataset is the issuers' own figures, each with
its page. Where two of the issuer's pages disagree, keep the later-dated one and say so in `note`.

## Where it came from

First compiled 2026-11-25 from each issuer's own lineup pages, MER lists and ETF Facts documents (30 issuers), with
22 funds reviewed fund by fund between 2026-11-10 and 2026-11-24. MERs change once or twice a year as issuers publish
annual and semi-annual reports; the `mer_as_of` column says which report a figure comes from.
