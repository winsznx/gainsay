# Inputs for the cfo.ai business plan

Measured numbers come from the Gainsay ledger on October 12, 2026. Everything under "Assumptions" is a starting point for cfo.ai to model, not a measurement.

## Measured costs

| Item | Measured | Source |
|---|---|---|
| Claude proposition checks run | 26 | `llm_responses` table |
| Tokens per check, average | 4,619 input, 360 output | `llm_responses.usage` |
| Cost per check at `claude-opus-5-5` list price ($4 / $20 per million tokens) | about $0.026 | computed from the two rows above |
| Total Claude spend so far | about $0.67 | same |
| CourtListener API cost | $0 (free, rate limited) | CourtListener terms |
| Repeat checks of the same passage | $0 | cached in the ledger |

Per filing, in this hackathon's runs:

| Filing | Case citations | Claude checks | CourtListener calls |
|---|---|---|---|
| Mata v. Avianca ECF 21 (affirmation, 10 pages) | 16 | 7 | about 13 |
| Mata v. Avianca ECF 45 (memorandum, 24 pages) | 54 | still running | still running |

Only citations whose case was found get a Claude check, so a filing full of nonexistent cases costs less, not more.

## Assumptions for cfo.ai to model

- **Customer:** litigation teams at small and mid-size firms who answer the other side's briefs.
- **Unit:** one filing checked, or one docket watched for a month.
- **Pricing to test:** a monthly fee per watched docket, with a set number of filings included, plus a per-filing price above that.
- **Variable cost per filing:** Claude spend scales with case citations found. Use $0.026 per found citation as the base and stress-test at 3x for long briefs.
- **Fixed costs:** one small server for the ledger and web UI, plus CourtListener rate limits, which cap throughput per API token at 125 calls a day under Gainsay's default budget.
- **Main risk:** source coverage. A real case CourtListener doesn't hold comes back "Not found in searched sources", so paid sources (Westlaw, Lexis) would be a cost line for a production version.
