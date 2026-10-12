# Gainsay

Gainsay watches a public federal court docket and checks every case citation in the other side's filings. For each citation it records five findings with their evidence: does the case exist, does the cite point to it, are the quoted words in the opinion, does the opinion support what the filing says, and is the pincite inside the opinion. It re-checks only filings it hasn't checked, pauses when the CourtListener quota runs out, and resumes from its ledger without repeating work. Unresolved evidence stays unresolved: it never calls a case missing just because a free source doesn't have it.

Built for neatHack (October 10 to 12, 2026). [Evidence for judges](docs/evidence.md) maps each item the organizers asked for to a file or trace.

## Result on Mata v. Avianca

The test case is the affirmation in opposition filed in *Mata v. Avianca, Inc.*, No. 1:22-cv-01461 (S.D.N.Y.), ECF 21. The court's sanctions opinion (ECF 54) later said which of its cases do not exist and which real ones were misused. The agent's fetch path refuses ECF 54. It is used only afterwards, to score the run.

Run 43 on commit `04e8da0`, from [`scoring/results/run-43-score.json`](scoring/results/run-43-score.json):

| Case cited in ECF 21 | What ECF 54 found | Gainsay's status |
|---|---|---|
| *Ashcroft v. Iqbal* | supports | Verified |
| *Doe v. United States* | supports in part | Verified |
| *Shaboon v. Egyptair* | does not exist | Not found in searched sources |
| *Peterson v. Iran Air* | does not exist | Not found in searched sources |
| *Ehrlich v. American Airlines, Inc.* | does not support | Wrong case |
| *Martinez v. Delta Airlines, Inc.* | does not exist | Unverifiable |
| *Estate of Durden v. KLM Royal Dutch Airlines* | does not exist | Unverifiable |
| *Varghese v. China Southern Airlines Co., Ltd.* | does not exist | Not found in searched sources |
| *Kaiser Steel Corp. v. W. S. Ranch Co.* | does not support | Doesn't support the proposition |
| *Zicherman v. Korean Air Lines Co., Ltd.* | does not exist as cited | Not found in searched sources |
| *El Al Israel Airlines, Ltd. v. Tsui Yuan Tseng* | quoted language not in opinion | Quote not in opinion |
| *Miller v. United Airlines, Inc.* | does not exist | Not found in searched sources |
| *In re Air Crash Disaster Near New Orleans, La.* | does not support | Doesn't support the proposition |

Gainsay calls "Not found" 5 of the 7 cases the court found don't exist, and no real case (existence precision 1.00, recall 0.71). Its status matches the court on 10 of 13 cases. The three it doesn't:

- *Martinez* and *Durden* are cited only to Westlaw, which free sources can't see, so they read "Unverifiable: outside free sources" instead of "Not found". That is the product's wording rule. Before that rule (run 33, commit `eee7aba`), all 7 came back "Not found" and 12 of 13 matched.
- *Ehrlich*: nothing exists at the cited 360 N.J. Super. 360, and CourtListener has the case at 360 F.3d 366 (2d Cir. 2004), so Gainsay leads with "Wrong case". Its proposition check, run against that real opinion, agrees with the court that it doesn't support the filing.

Two rules were changed after scoring an earlier run against this same answer key (nested single quotes, and "Wrong case" for a case found elsewhere). Every score is in [`scoring/results/`](scoring/results/), and the commit messages say what each change was measured against.

## The rest of the Mata docket

The watcher found 17 filings by the plaintiff's side and checked them all. Notable runs:

- **ECF 29**, the affidavit annexing the cases (run 13, before the Westlaw rule): 12 of 13 citations "Not found", all to the cases the court found don't exist.
- **ECF 45**, the sanctions memorandum by the plaintiff's new counsel: the first pass flagged 36 of 54 citations, mostly tables of contents, record cites, subsequent history and unpublished decisions. Fixing those general bugs brought it to 15 of 51 (run 31), of which 8 are the memo naming Varghese, Zicherman and Miller. Real unpublished S.D.N.Y. decisions now read "Unverifiable" with their RECAP docket as evidence.
- **ECF 18**, Avianca's own memorandum, is the healthy control. Its first partial run called *Bell Atlantic Corp. v. Twombly* "Not found" because "Bell Atl." didn't match "Bell Atlantic"; that was fixed (`04e8da0`). On the fixed code, the 7 of 50 citations checked before the daily quota ran out are 5 Verified and 2 Unverifiable (Westlaw cites), with no flags. The other 43 resume when the quota refills.

## LePhantomCite

[LePhantomCite](https://arxiv.org/abs/2606.21155) labels five error types in brief excerpts. It ships no opinion text, so checking quotes, propositions and pincites would need an opinion for nearly every citation: over 1,000 CourtListener calls against a quota of 125 a day. Gainsay was scored on the two citation-level types (non-existent citation, case-name mismatch) on a 100-excerpt subset, with the paper's released matching rules, against a lookup-only baseline and Claude with no tools. Fixes were made on a development subset, and a disjoint held-out subset was scored once.

| Held-out, 100 excerpts | Precision | Recall | F1 |
|---|---|---|---|
| Gainsay | 0.415 | 0.640 | 0.503 |
| CourtListener lookup only | 0.030 | 0.040 | 0.034 |
| Claude, no tools | 0.833 | 0.840 | 0.837 |

Gainsay beats the lookup baseline but not the no-tools model, so under the PRD's kill rule **no quality claim is made from this benchmark**. Gainsay's arm skipped its name-search fallback to save quota, and the check for reporter series that don't exist was added after reading labels from this split. Files: [`scoring/results/lephantomcite-*.json`](scoring/results/).

## How a citation is checked

1. **Fetch.** The filing's PDF comes from RECAP through CourtListener. A scanned PDF falls back to CourtListener's OCR text.
2. **Extract.** [eyecite](https://github.com/freelawproject/eyecite) finds the citations. Gainsay groups parallel cites, resolves *Id.* and *supra*, skips tables of contents and record cites, keeps docket numbers, marks subsequent history, and flags cites to reporter series that don't exist ("475 F.6th 972"). Each citation keeps the sentence it supports and any quotation it introduces.
3. **Check.** One CourtListener lookup resolves all of a filing's cites, 60 a minute. A cite that misses gets a search by name, court and year, then by RECAP docket. Quotes are matched against the opinion with [rapidfuzz](https://github.com/rapidfuzz/RapidFuzz). Claude judges the proposition from passages the code picks; it sees only the filing's sentence and those passages, both marked as data. Pincites are checked against star pagination.
4. **Status.** The first failure, in order: Not found in searched sources, Wrong case, Quote not in opinion, Doesn't support the proposition; then Unverifiable; then Verified. A failed pincite is a flag next to the status.

Every finding is stored in a SQLite ledger with its reason and the CourtListener response it rests on.

## Running on its own

- **Budget.** One client keeps a call log on disk: 5 calls a minute, 50 an hour, 125 a day. Hitting a limit or a server 429 pauses the run, and the run page shows when the quota refills. A dropped connection or a 5xx is retried three times with backoff.
- **Recovery.** A paused or crashed run resumes from the findings already recorded. `--simulate-outage-after N` and `--simulate-crash-after N` force both, labelled "simulated" in the ledger, the run page and the trace. Runs 36 and 37 show each.
- **Replay.** A rerun of a settled filing costs zero CourtListener and zero Claude calls (run 43).
- **Watching.** `scripts/watch_docket.py` polls the docket, picks the other side's filings by who filed them, and checks only those without a finished run.
- **Live view.** While a run is active, its page shows one sentence built from its latest findings, the next three citations, and the quota countdown.
- **Tracing.** Each attempt is one neatlogs trace, with a span per citation tagged by run version. Trace IDs are on each run page and in each report.

## Running it

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/).

```
uv sync
cp .env.example .env    # COURTLISTENER_TOKEN, ANTHROPIC_API_KEY, NEATLOGS_API_KEY
(set -a; source .env; set +a; .venv/bin/python scripts/fetch_filing.py --entry 21)
.venv/bin/python scripts/extract_citations.py --entry 21
(set -a; source .env; set +a; .venv/bin/python scripts/check_citations.py --entry 21)
(set -a; source .env; set +a; .venv/bin/python scripts/score_run.py RUN_ID)
(set -a; source .env; set +a; .venv/bin/python scripts/watch_docket.py)
.venv/bin/uvicorn gainsay.web.app:app
```

Loading `.env` inside parentheses keeps the keys out of the rest of your shell. Each run page links a Markdown report (`/runs/{id}/report.md`, or `scripts/export_report.py`).

## Business model

cfo.ai modeled Gainsay as legal software priced per watched docket, using the measured Claude cost of about 2.6 cents per citation. At $29 a docket a month, 39 dockets cover a fixed budget of $1,010.60. The export is in `docs/cfo-ai/`, and `docs/cfo-ai-plan.md` checks it and lists what it leaves out.

## Known gaps

- CourtListener is the only source. Westlaw and Lexis cites stay Unverifiable unless a free source confirms them.
- Headings without a period run into the next sentence, so a proposition can start with a heading.
- Only the main document of a docket entry is checked, not its exhibits.
- A second sanctioned docket and the full LePhantomCite run were out of reach of the daily quota before the deadline.

## Layout

```
gainsay/        extraction, checks, ledger, scoring, benchmark, web UI (tests next to each module)
scripts/        fetch, extract, check, score, watch, export, benchmark
dockets/        watched docket configs
scoring/        the Mata answer key and every stored score
docs/           evidence for judges, Entire output, cfo.ai inputs and plan, demo script
```
