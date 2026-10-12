# The cfo.ai business plan

cfo.ai built Gainsay's plan in two passes from the measured costs in [`cfo-ai-inputs.md`](cfo-ai-inputs.md). It treats Gainsay as a legal-software business priced per watched docket. Both exports are in [`cfo-ai/`](cfo-ai/), unedited:

- `gainsay-drivers.xlsx` is the first pass: drivers and unit economics.
- `gainsay-revised-plan.xlsx` is the revision. It adds a monthly forecast, a cash buffer, a CourtListener capacity check and results for the data-fee tests, and keeps every original input.

## Unit economics

| Driver | Value | Where it comes from |
|---|---|---|
| Claude cost per citation | $0.026 | measured, `cfo-ai-inputs.md` |
| Price per watched docket | $29 a month | assumption |
| Price per one-off brief check | $9 | assumption |
| New filings per docket | 2 a month | assumption |
| Citations per paid filing | 35 | assumption (ECF 21 has 16, ECF 45 has 51) |
| Claude cost per average filing | $0.91 | 35 × $0.026 |
| Contribution per docket | $26.04 a month | price less 2.9% + $0.30 card fees, less two filings of Claude |
| Contribution per brief | $7.53 | same, for one filing |
| Fixed cash budget | $1,010.60 a month | $500 founder draw, $250 data fee ($3,000 a year), $100 legal reserve, $100 marketing, $30 tools, $15 hosting, $15.60 of free checks |
| Dockets to cover the fixed budget | 39 | $1,010.60 ÷ $26.04, rounded up |

Claude is a small cost line. At 35 citations a filing it takes about 6% of a docket's monthly price, and even a 50-citation brief costs $1.30.

## Forecast

From the revised workbook's operating forecast, with the data fee reserved monthly and the existing $5,000 opening cash:

| Month | Active dockets | Monthly result | Cash | Calls a day at 2 per citation | Calls a day at 0.8 per citation |
|---|---|---|---|---|---|
| 2026-10 | 3.0 | −$857.19 | $3,642.81 | 79 | 34 |
| 2027-01 | 12.4 | −$601.00 | $1,579.65 | 136 | 62 |
| 2027-06 | 29.7 | −$126.89 | −$29.89 | 240 | 114 |
| 2027-07 | 33.4 | −$23.31 | −$53.20 | 263 | 125 |
| 2027-08 | 37.3 | +$83.66 | $30.46 | 286 | 137 |
| 2027-12 | 54.2 | +$150.12 | $1,110.74 | 389 | 188 |

**Cash.** Losses before the first positive month add up to $4,553.20, but opening cash less the $500 launch cost is $4,500. Cash goes negative in June 2027 and bottoms out at −$53.20 in July. To hold three months of the fixed budget ($3,031.80) in reserve every month, cfo.ai recommends $8,500 of opening cash if the data fee is reserved monthly, or $10,500 if the fee is paid upfront each October.

**Contractor.** A $400-a-month contractor starts at 50 dockets, which is why December's result is lower than November's ($427.23).

**CourtListener capacity.** Gainsay's default budget is 125 calls a day. At the model's conservative 2 calls per citation the plan passes it in January 2027. At the measured rate it passes it in July 2027. The measured rate is about 0.8, from 13 calls for 16 citations on ECF 21, since one lookup request resolves up to 60 citations. At 39 dockets the conservative case needs 258 calls a day without brief checks, or 281 with 10 a month. The cost of raised API access is in the model at $0, labeled unquoted, until Free Law Project prices it.

## Data-fee tests

| Annual data fee | Dockets to cover the fixed budget | First positive month | Lowest cash |
|---|---|---|---|
| $0 | 30 | May 2027 | $2,074.28, April 2027 |
| $3,000 | 39 | August 2027 | −$53.20, July 2027 |
| $10,000 | 62 | none through December 2027 | −$7,639.26, December 2027 |

At $10,000 the threshold rises to 77 dockets once the contractor cost is included, before brief revenue.

## How the plan was checked

The first export had drivers and unit economics but no monthly projection. Running its inputs forward showed the cash shortfall and the early API crossing. cfo.ai was then asked to add a forecast, a cash buffer, a capacity check with the measured API rate, and results for its data-fee tests. Every figure on this page was recomputed independently from the workbook inputs and matches to the cent.

That review also corrected two errors in the first version of this page:
- It left out the $400 contractor cost from 50 dockets.
- It said docket polls would outweigh citation calls at the measured rate. At 39 dockets, citation calls are about 88 a day against 39 polls.

Two inputs are still unquoted: the annual data fee and the price of raised API access.
