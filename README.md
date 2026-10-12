# Gainsay

Gainsay watches a public federal court docket and checks every case citation in the other side's filings. For each citation it records five findings with their evidence: does the case exist, does the cite point to it, are the quoted words in the opinion, does the opinion support what the filing says, and is the pincite inside the opinion. It re-checks only filings it hasn't checked, pauses when the CourtListener quota runs out, and resumes from its ledger without repeating work. Unresolved evidence stays unresolved: it never calls a case missing just because a free source doesn't have it.

Built for neatHack (October 10 to 12, 2026). [Evidence for judges](docs/evidence.md) maps each item the organizers asked for to a file or trace.

**Live:** [gainsay.vercel.app](https://gainsay.vercel.app) serves a read-only snapshot of the ledger. Checks run where the API keys and quota are.

## Result on Mata v. Avianca

The test case is the affirmation in opposition filed in *Mata v. Avianca, Inc.*, No. 1:22-cv-01461 (S.D.N.Y.), ECF 21. The court's sanctions opinion (ECF 54) later said which of its cases do not exist and which real ones were misused. The agent's fetch path refuses ECF 54. It is used only afterwards, to score the run.

Run 47 on commit `97938cb`, from [`scoring/results/run-47-score.json`](scoring/results/run-47-score.json):

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

The Caselaw Access Project, a second free source added since run 43, now gives the evidence for two of them from its own volume lists: the cited pages of *Varghese* and *Zicherman* fall inside *J.D. v. Azar* and *Miccosukee Tribe of Indians v. United States*. CourtListener resolves *Miller*'s cite to *Greenleaf v. Garlock*. Run 47 took no CourtListener calls; every request was answered from the ledger.

Two rules were changed after scoring an earlier run against this same answer key (nested single quotes, and "Wrong case" for a case found elsewhere). Every score is in [`scoring/results/`](scoring/results/), and the commit messages say what each change was measured against.

## The rest of the Mata docket

The watcher found 17 filings by the plaintiff's side and checked them all. Notable runs:

- **ECF 29**, the affidavit annexing the cases (run 13, before the Westlaw rule): 12 of 13 citations "Not found", all to the cases the court found don't exist.
- **ECF 45**, the sanctions memorandum by the plaintiff's new counsel: the first pass flagged 36 of 54 citations, mostly tables of contents, record cites, subsequent history and unpublished decisions. Fixing those general bugs brought it to 15 of 51 (run 31), of which 8 are the memo naming Varghese, Zicherman and Miller. Real unpublished S.D.N.Y. decisions now read "Unverifiable" with their RECAP docket as evidence.
- **ECF 18**, Avianca's own memorandum, is the healthy control. The first runs stopped at 7 of 50 citations when the daily quota ran out (runs 41 and 42). With the Caselaw Access Project supplying opinion text, run 46 checked all 50 with no CourtListener calls: 29 Verified, 14 Unverifiable, 7 flagged. One flag is a real miscite in Avianca's brief: it cites *Vumbaca v. Terminal One Group Ass'n* at 859 F. Supp. 343, which is *Chilcote v. Federal Bureau of Prisons*; *Vumbaca* is at 859 F. Supp. 2d 343. One is a two-word quote matched at 88 of a required 95. The other five are statements the model found narrower in the opinion than in the brief, such as a rationale for refusing tolling that *Campbell v. Air Jamaica* doesn't give. Each flag shows the passages it was judged on. The control also drove fixes: a footnote number on a period, two abbreviations, and a rule for cases decided under the Warsaw Convention article that a Montreal Convention article carries forward (`97938cb`).

## LePhantomCite

[LePhantomCite](https://arxiv.org/abs/2606.21155) labels five kinds of citation error in real brief excerpts: a case that doesn't exist, a case name that doesn't match its cite, a wrong pincite, a misquote, and a statement the case doesn't support. Gainsay runs its own checks on every citation in an excerpt and is scored with the paper's matching rules against two baselines: a CourtListener lookup alone, and Claude with no tools, which answers from memory. Development happened on one 100-excerpt subset; a disjoint 100-excerpt subset was held out.

| F1 (precision / recall) | Gainsay | Claude, no tools | Lookup only |
|---|---|---|---|
| Development, citation errors | **0.916** (0.921 / 0.912) | 0.787 (0.811 / 0.765) | 0.000 |
| Development, all five types | **0.729** (0.674 / 0.794) | 0.720 (0.778 / 0.670) | |
| Held out, citation errors | 0.616 (0.562 / 0.680) | **0.837** (0.833 / 0.840) | 0.034 |
| Held out, all five types | 0.469 (0.394 / 0.578) | **0.767** (0.833 / 0.711) | |

The held-out subset was scored once on commit `84a9ef3`, and it is the number to trust: on it Claude with no tools is ahead. Gainsay's held-out citation-error F1 rose from 0.503 under the first harness to 0.616, but the development gains mostly didn't carry over. Two things explain most of the gap:

- **The runs were offline.** CourtListener's daily quota was spent, so these runs answered only from the ledger and the Caselaw Access Project. With no name search, a fabricated case outside CAP's coverage can't be called missing. Claude recognized all 13 fabricated cases on the held-out subset from memory; Gainsay found 9.
- **Real briefs vary more than the development subset did.** The held-out errors included reporter series that can't exist ("Mass. App. 4th"), prose and record cites folded into case names, and agency acronyms. Those were fixed in `d0974db`, after the held-out scoring, so they can't be credited to it.

Claude with no tools answers from what it remembers; Gainsay answers from the record and keeps it. Every flag above links to the opinion text, CAP volume list or CourtListener response it rests on. The 190 excerpts no run has touched are the next test, scored once with CourtListener live when the quota allows. Files: [`scoring/results/lephantomcite-*.json`](scoring/results/).

## How a citation is checked

1. **Fetch.** The filing's PDF comes from RECAP through CourtListener. A scanned PDF falls back to CourtListener's OCR text.
2. **Extract.** [eyecite](https://github.com/freelawproject/eyecite) finds the citations. Gainsay groups parallel cites, resolves *Id.* and *supra*, skips tables of contents and record cites, keeps docket numbers, marks subsequent history, and flags cites to reporter series that don't exist ("475 F.6th 972"). Each citation keeps the sentence it supports and any quotation it introduces.
3. **Check.** One CourtListener lookup resolves all of a filing's cites, 60 a minute. A cite it misses is read from the [Caselaw Access Project](https://static.case.law)'s volume lists, which cost no quota: the named case starting at the cited page passes, a different case there fails identity. Then comes a search by name, court and year, then by RECAP docket. Every cite in a parallel set has to point at the same case. A short cite with no full cite in the filing ("*Torrao*, 923 F.2d at 234") is checked against the case that holds its page. Opinion text comes from CAP when it holds the case and from CourtListener otherwise. Quotes are matched against it with [rapidfuzz](https://github.com/rapidfuzz/RapidFuzz). Claude judges the proposition from passages the code picks; it sees only the filing's sentence and those passages, both marked as data. Pincites are checked against star pagination.
4. **Status.** The first failure, in order: Not found in searched sources, Wrong case, Quote not in opinion, Doesn't support the proposition; then Unverifiable; then Verified. A failed pincite is a flag next to the status.

Every finding is stored in a SQLite ledger with its reason and the CourtListener response or CAP file it rests on. An entry's exhibits are checked as filings of their own ("ECF 29-1") with `watch_docket.py --exhibits`.

## Running on its own

- **Budget.** One client keeps a call log on disk: 5 calls a minute, 50 an hour, 125 a day. Hitting a limit or a server 429 pauses the run, and the run page shows when the quota refills. A dropped connection or a 5xx is retried three times with backoff.
- **Recovery.** A paused or crashed run resumes from the findings already recorded. `--simulate-outage-after N` and `--simulate-crash-after N` force both, labelled "simulated" in the ledger, the run page and the trace. Runs 36 and 37 show each.
- **Replay.** A rerun of a settled filing costs zero CourtListener and zero Claude calls (run 43). `check_citations.py --courtlistener offline` answers every CourtListener request from the ledger and records a miss in the finding instead of calling, so a filing can be rechecked with CAP while the quota is spent (runs 44 to 47).
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

cfo.ai modeled Gainsay as legal software priced per watched docket, using the measured Claude cost of about 2.6 cents per citation. At $29 a docket a month, 39 dockets cover a fixed budget of $1,010.60.

Its forecast first turns a monthly profit in August 2027. It recommends $8,500 of opening cash. The default CourtListener budget runs out between January and July 2027, depending on calls per citation.

Both exports are in `docs/cfo-ai/`, and `docs/cfo-ai-plan.md` sums them up.

## Limits

- Westlaw and Lexis cites stay Unverifiable unless a free source confirms them. That rule costs two of the 13 Mata findings, and it's deliberate: a missing free copy isn't evidence a case doesn't exist.
- A party name misspelled by a letter or two ("Plyer v. Doe") passes, so OCR slips in real filings don't read as wrong cases. LePhantomCite counts those as errors.
- CourtListener allows 125 calls a day per account. Exhibit checking, the untouched 190-excerpt test and a second sanctioned docket wait on it; everything above was run with the quota spent.

## Layout

```
gainsay/        extraction, checks, ledger, scoring, benchmark, web UI (tests next to each module)
scripts/        fetch, extract, check, score, watch, export, benchmark
dockets/        watched docket configs
scoring/        the Mata answer key and every stored score
docs/           evidence for judges, Entire output, cfo.ai inputs and plan, demo script
```
