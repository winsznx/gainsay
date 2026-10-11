# Gainsay

Gainsay checks the case citations in the other side's filings on a public federal docket. For every citation it records whether the case exists, whether the cite points to it, whether quoted words appear in the opinion, whether the opinion supports what the filing says it holds, and whether the pincite falls inside the opinion. It keeps the evidence for each answer, and when it watches a docket it only checks filings it hasn't checked before.

## Result on Mata v. Avianca

The test case is the affirmation in opposition filed in *Mata v. Avianca, Inc.*, No. 1:22-cv-01461 (S.D.N.Y.), ECF 21. The court's sanctions opinion (ECF 54) later said which of its cases do not exist and which real ones were misused. Gainsay never sees ECF 54 while checking. It is used only afterwards to score the run.

Run 7 (commit `c8ceff1`), from [`scoring/results/run-7-score.json`](scoring/results/run-7-score.json):

| Case cited in ECF 21 | What ECF 54 found | Gainsay's status |
|---|---|---|
| *Ashcroft v. Iqbal* | supports | Verified |
| *Doe v. United States* | supports in part | Verified |
| *Shaboon v. Egyptair* | does not exist | Not found in searched sources |
| *Peterson v. Iran Air* | does not exist | Not found in searched sources |
| *Ehrlich v. American Airlines, Inc.* | does not support | Wrong case |
| *Martinez v. Delta Airlines, Inc.* | does not exist | Not found in searched sources |
| *Estate of Durden v. KLM Royal Dutch Airlines* | does not exist | Not found in searched sources |
| *Varghese v. China Southern Airlines Co., Ltd.* | does not exist | Not found in searched sources |
| *Kaiser Steel Corp. v. W. S. Ranch Co.* | does not support | Doesn't support the proposition |
| *Zicherman v. Korean Air Lines Co., Ltd.* | does not exist as cited | Not found in searched sources |
| *El Al Israel Airlines, Ltd. v. Tsui Yuan Tseng* | quoted language not in opinion | Quote not in opinion |
| *Miller v. United Airlines, Inc.* | does not exist | Not found in searched sources |
| *In re Air Crash Disaster Near New Orleans, La.* | does not support | Doesn't support the proposition |

Gainsay said "Not found" for all 7 cases the court found do not exist, and for no other case (precision 1.00, recall 1.00). Its status matches the court's full finding for 12 of the 13 cases. The exception is *Ehrlich*: nothing exists at the cited 360 N.J. Super. 360, and CourtListener has the case at 360 F.3d 366 (2d Cir. 2004), so Gainsay leads with "Wrong case". Its proposition check, run against that real opinion, agrees with the court that the case doesn't support the filing.

Read these numbers with two limits in mind. They come from one filing with 13 cases. And two rules were changed after scoring an earlier run against this same answer key: nested single quotes are now read as quotations (a gap noted before scoring), and a case found under the cited name in another court is reported as "Wrong case" (chosen after scoring). The scores for every run are in `scoring/results/`, and the commit messages say what each change was measured against.

## How a citation is checked

1. **Fetch.** The filing's PDF comes from RECAP through CourtListener. A scanned PDF with no text layer falls back to CourtListener's OCR text, and the manifest records which one was used.
2. **Extract.** [eyecite](https://github.com/freelawproject/eyecite) finds the citations. Gainsay groups parallel cites, resolves *Id.*, and records the sentence each citation supports, any quotation it introduces, and whether it sits inside a passage the filing quotes from another case.
3. **Check.** Five findings per citation:
   - **existence** and **identity**: all reporter cites go to CourtListener's citation lookup in one request. A cite that misses is followed by a search by name, court and year.
   - **quotation**: quoted text is matched against the opinion with [rapidfuzz](https://github.com/rapidfuzz/RapidFuzz), passage by passage.
   - **proposition**: Claude judges whether the opinion supports the filing's sentence. The code picks the opinion passages. The model sees only that sentence and those passages, both marked as data it must not take instructions from.
   - **pincite**: the cited pages are checked against CourtListener's star pagination.
4. **Status.** The primary status is the first failure in this order: Not found in searched sources, Wrong case, Quote not in opinion, Doesn't support the proposition, then Unverifiable, then Verified. A failed pincite is shown as a flag beside the status.

Every finding is stored in a SQLite ledger with the reason and the evidence it rests on, including the exact CourtListener response. No status is a guess. When a source can't answer, the finding says Unverifiable and why.

## Running it

Requires Python 3.13 (neatlogs needs a version below 3.14) and [uv](https://docs.astral.sh/uv/).

```
uv sync
cp .env.example .env    # then fill in the three keys
```

| Key | Used for |
|---|---|
| `COURTLISTENER_TOKEN` | Docket, document and opinion lookups. Get one under Profile, API on courtlistener.com. |
| `ANTHROPIC_API_KEY` | The proposition check. |
| `NEATLOGS_API_KEY` | Tracing. Runs work without it. |

Load the keys only for the command you run, so they don't leak into the rest of your shell:

```
(set -a; source .env; set +a; .venv/bin/python scripts/fetch_filing.py --entry 21)
.venv/bin/python scripts/extract_citations.py --entry 21
(set -a; source .env; set +a; .venv/bin/python scripts/check_citations.py --entry 21)
(set -a; source .env; set +a; .venv/bin/python scripts/score_run.py RUN_ID)
.venv/bin/uvicorn gainsay.web.app:app
```

To watch the docket and check the other side's new filings:

```
(set -a; source .env; set +a; .venv/bin/python scripts/watch_docket.py)
```

The docket config in [`dockets/mata-v-avianca.json`](dockets/mata-v-avianca.json) names the opposing party and counsel. A docket entry counts as theirs only when they filed it, judged from the "Document filed by" clause and the filing attorney ECF appends to the entry. Court orders never count.

## Limits it works within

- **CourtListener budget.** Every request goes through one client that keeps a call log on disk and stays under 5 calls a minute, 50 an hour and 125 a day. Hitting the hour or day limit, or a 429 from the server, pauses the run. The next run resumes it, and responses already in the ledger cost nothing.
- **The answer key stays out of the agent.** The agent's fetch path refuses ECF 54. Only the scoring code fetches it, without the agent's cache, and every label in [`scoring/mata_answer_key.json`](scoring/mata_answer_key.json) carries the court's own words, which scoring verifies against the opinion text before it runs.
- **Sources.** CourtListener is the only source. A real case it doesn't hold comes back as "Not found in searched sources", which is literally what the status says. Westlaw cites can't be resolved there, so their identity check is Unverifiable.

## Known gaps

- Headings without a period run into the next sentence, so a proposition can start with a section heading.
- OCR slips in case names ("Al Israel Airlines" for *El Al*) make name search weaker. Scoring matches cases by reporter cite for that reason.
- Only the main document of a docket entry is checked, not its exhibits.
- neatlogs receives the traces, but its processing currently fails on its side: the smoke trace ended in `finalizationStatus: "dlq"`.

## Layout

```
gainsay/        extraction, checks, ledger, scoring, web UI (tests sit next to each module)
scripts/        fetch, extract, check, score, watch
dockets/        watched docket configs
scoring/        the Mata answer key and stored score reports
data/           filings, ledger, caches (not committed)
```
