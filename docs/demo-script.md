# Demo script (3 minutes)

The video has to explain the agent and cover neatlogs, Entire and cfo.ai: the architecture, implementation, runtime, reasoning and result for each. Every number below comes from a stored run or score file. Re-check them against the latest run before recording.

## 0:00 to 0:20, the problem

Show ECF 54, the *Mata v. Avianca* sanctions opinion.

> In 2023, lawyers in Mata v. Avianca filed a brief citing cases that don't exist. The other side spent weeks proving it. Gainsay is an agent that reads the other side's filings off the public docket and checks every case they cite, before you have to answer them.

## 0:20 to 1:20, the agent on ECF 21

Run the UI (`.venv/bin/uvicorn gainsay.web.app:app`) and open the latest ECF 21 run.

1. The opening sentence ("12 of 16 citations have a problem") and the strip: one bar per citation in filing order. Short bars are citations inside passages the filing quotes from another case.
2. Open *Varghese*: "Not found in searched sources". Show the reasons: CourtListener's name search found nothing, and the Caselaw Access Project's volume list shows the cited page, 925 F.3d 1339, is in the middle of *J.D. v. Azar*.
3. Open *Kaiser Steel*: the case exists, but Claude read the whole opinion and found it is about abstaining for a New Mexico state-law question, not the bankruptcy stay. The pincite flag shows page 598 is past the opinion's last page, 595.
4. Open *Tseng*: "Quote not in opinion". The quoted words score 57 out of 100 against the closest text in the opinion.
5. Open *Ehrlich*: "Wrong case". Nothing exists at 360 N.J. Super. 360. The real case is 360 F.3d 366 (2d Cir. 2004).

> Scored against the court's own findings in ECF 54, which Gainsay never sees while checking: it calls 5 of the 7 cases the court found don't exist "Not found", and no real case. The other two are cited only to Westlaw, which free sources can't see, so it says "Unverifiable: outside free sources" rather than accuse. Its status matches the court on 10 of 13 cases. (`scoring/results/run-47-score.json`)

## 1:20 to 1:50, running on its own

Show `scripts/watch_docket.py` output and the docket config.

> Point it at a docket and it polls for new entries, picks out the other side's filings by who filed them, and checks each one. It found 17 opposing filings on the Mata docket. CourtListener allows a limited number of calls, so when it hits the limit it pauses, and the next run resumes from the ledger without repeating work. Everything it has fetched is cached, so a rerun of ECF 21 costs zero calls.

Show the live panel by running `scripts/check_citations.py --entry 21 --simulate-outage-after 5` with the run page open: the sentence, the next three citations and the quota countdown, then rerun to resume.

Also mention that it learned from the other side's real memorandum (ECF 45): the first pass flagged 36 of 54 citations, mostly tables of contents, record citations and unpublished cases, and the fixes brought it to 15 of 51, 8 of which are the memo naming cases the court found don't exist.

Then the control, Avianca's own memorandum (ECF 18, run 46): 29 of 50 Verified, no CourtListener calls because the quota was spent and CAP supplied the opinions. One of its flags is a real miscite in Avianca's own brief: *Vumbaca* cited at 859 F. Supp. 343, which is a different case; it's at 859 F. Supp. 2d 343.

## 1:50 to 2:20, neatlogs

Show the neatlogs dashboard.

- **Architecture:** one trace per run attempt. A `gainsay.check_run` workflow span, with one `gainsay.check_citation` span per citation carrying each check's outcome, and the Claude calls inside.
- **Runtime:** open the trace for the latest ECF 21 run, run 47 (`9dd695203cf90724f40ffc8ede51fa4c`, also on its run page).
- **Recovery:** a paused attempt records the 429 on the run span, and the next attempt's trace finishes the run.
- **Result, before and after:** run 6 (commit `2dd81a3`) against run 7 (commit `c8ceff1`). The single-quote and wrong-case fixes took existence precision from 0.88 to 1.00 and agreement with the court from 11 to 12 of 13 (`scoring/results/run-6-score.json`, `run-7-score.json`).

## 2:20 to 2:40, Entire

Show `entire status` and `git log` with the `Entire-Checkpoint` trailers.

> Every commit carries an Entire checkpoint with the agent session behind it: the reasoning, the dead ends, and the measured numbers in the commit body. That is how the context carried across sessions, including when one coding agent ran out of tokens and another picked up the work.

Optional, if time allows: LePhantomCite. On the development subset Gainsay beats Claude with no tools on citation errors (F1 0.916 against 0.787); on the held-out subset Claude is ahead (0.837 against 0.616), partly because those runs were offline with no CourtListener name search. The difference that matters to a lawyer: each Gainsay flag comes with the opinion text or record it rests on.

## 2:40 to 3:00, cfo.ai

Show the revised cfo.ai plan (`docs/cfo-ai/gainsay-revised-plan.xlsx`), on its operating forecast sheet.

> The plan is built on measured costs: about 2.6 cents of Claude per citation checked, and nothing for CourtListener. At $29 a docket a month, 39 dockets cover the fixed budget. The first version had no monthly forecast. Once it was added, cash dipped $53 below zero in July 2027, so cfo.ai now recommends $8,500 of opening cash. At the conservative API rate, the default CourtListener budget runs out in January 2027, before the cash does. (`docs/cfo-ai-plan.md`)

Close on the repo URL.
