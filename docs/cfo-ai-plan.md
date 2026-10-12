# The cfo.ai business plan

cfo.ai built a driver model for Gainsay from the measured costs in [`cfo-ai-inputs.md`](cfo-ai-inputs.md). It treats Gainsay as a legal-software business priced per watched docket. The export, Main Scenario, is [`cfo-ai/gainsay-drivers.xlsx`](cfo-ai/gainsay-drivers.xlsx), unedited.

## What the model says

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

Every formula in the workbook gives the same values when recomputed from its inputs.

Claude is a small cost line. At 35 citations a filing it takes about 6% of a docket's monthly price, and even a 50-citation brief costs $1.30.

## What the model doesn't cover

The workbook has the drivers and the unit economics but no month-by-month projection. I ran its own inputs forward, with active dockets each month equal to last month's less 3% churn plus that month's new dockets, and brief sales growing 5% a month as the demand sheet sets them.

| Month | Active dockets | Monthly result | CourtListener calls a day |
|---|---|---|---|
| 2026-10 | 3.0 | −$857 | 79 |
| 2027-01 | 12.4 | −$601 | 136 |
| 2027-07 | 33.4 | −$23 | 263 |
| 2027-08 | 37.3 | +$84 | 286 |
| 2027-12 | 54.2 | +$550 | 389 |

Three things follow.

1. **Cash is $53 short before break-even.** Losses from October 2026 through July 2027 add up to about $4,553. Opening cash of $5,000, less the $500 launch cost, leaves $4,500. On these inputs the business needs a buffer on top of the placeholder opening cash.
2. **The API budget runs out first.** The model counts 2 CourtListener calls per citation and one docket poll a day. That passes Gainsay's default budget of 125 calls a day in January 2027, and reaches about 258 a day at 39 dockets. The input is conservative. On ECF 21, Gainsay made about 13 calls for 16 citations, because one lookup request resolves up to 60 citations at once. At that measured rate the docket polls become the larger load. Either way the default budget has to rise as dockets grow, and the model has no line for that yet.
3. **The data fee swings break-even by 32 dockets.** The data-fee test sheet lists three annual fees without results. Run through the same formula they give 30 dockets with no fee, 39 at $3,000, and 62 at $10,000.

These three come from the workbook's inputs, using the method above. They aren't cfo.ai output.
