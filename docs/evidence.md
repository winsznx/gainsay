# Evidence for judges

Each item the neatHack organizers asked for, and where to check it. Trace IDs can be pasted into the neatlogs dashboard search. Run numbers refer to the ledger and to the score files in `scoring/results/`.

## The agent improved

Before and after on the same filing, Mata v. Avianca ECF 21, scored against the court's own findings (ECF 54):

| Run | Commit | Change | Existence precision / recall | Matches the court |
|---|---|---|---|---|
| 6 | `2dd81a3` | before | 0.88 / 1.00 | 11 of 13 |
| 7 | `c8ceff1` | nested single quotes become quotations; a case found under the cited name elsewhere is "Wrong case" | 1.00 / 1.00 | 12 of 13 |

Files: `scoring/results/run-6-score.json`, `run-7-score.json`. Those runs were traced to neatlogs before trace IDs were stored per run; find them under `gainsay.check_run` with `run_id` 6 and 7 (October 11, about 23:11 and 23:19 UTC).

On a real memorandum with no answer key, ECF 45, the first pass flagged 36 of 54 citations and the fixes brought it to 15 of 51 (runs 22 and 31; commits `0b2fba9`, `4b4c71c`, `9c6bb19`, `eee7aba`). On LePhantomCite, the harness first scored only citation errors with a lookup: development F1 0.612, held-out 0.503. With the Caselaw Access Project and Gainsay's full checks, development reached 0.916 on citation errors and 0.729 on all five types, and the same held-out subset, scored once afterwards, rose to 0.616 on citation errors. Claude with no tools is still ahead on held-out (0.837), and the README gives the reasons (`scoring/results/lephantomcite-*.json`).

The healthy control drove fixes too: run 45 flagged 10 of Avianca’s 50 citations, and after the footnote, abbreviation and Warsaw/Montreal fixes run 46 flagged 7, one of them a real miscite in Avianca's brief (commit `97938cb`).

## You used neatlogs

One trace per run attempt, a `gainsay.check_run` workflow span with one `gainsay.check_citation` span per citation carrying each check's outcome, and the Claude calls inside.

| Run | What it is | Trace |
|---|---|---|
| 47 | Final ECF 21 run, with the Caselaw Access Project as a second source and no CourtListener calls | `9dd695203cf90724f40ffc8ede51fa4c` |
| 46 | Healthy control ECF 18, all 50 citations, after the control's fixes | `1c61776418e5d0b1a5bb160207b778ea` |
| 45 | Healthy control ECF 18 before those fixes | `87606e6faca34cda955a327f68069c34` |
| 43 | ECF 21 replayed from the ledger, zero calls | `2dcdf212e63c0af29abea54ff3acbe8f` |
| 36 | Simulated outage after 5 citations, then the resumed attempt | `03f424545ef1a0c86acb77b2ada29f0b`, `c6cb21331eeb15d38cce665043584055` |
| 37 | Simulated crash after 6 citations, then the resumed attempt | `d23f57a558dc28b262565cda5d4b44a4`, `5bab4ca29c1738f3cea38ffc5d19463d` |
| 42 | Healthy control ECF 18, paused by the real daily quota | `8e1c90fdb9909ea2f1d6cdcd6737754d` |

The simulated crash kills the process, so its attempt's trace may never have been exported; its ledger row says "crashed (simulated)". The setup and the smoke trace are in commit `50b254d`.

## You used Entire

Every commit carries an `Entire-Checkpoint` trailer. `docs/entire/` holds the checkpoint list, entire-graph's symbol-level analysis of three checkpointed fixes, and the impact map of the existence check. See `docs/entire/README.md`.

## You used cfo.ai

`docs/cfo-ai-inputs.md` holds the measured costs the plan is built on. `docs/cfo-ai/` holds cfo.ai's two exports.
- The first is the driver model: at $29 a docket a month, 39 dockets cover the fixed budget.
- Checking it showed it had no monthly projection, so cfo.ai was asked to revise it. The second export adds a monthly forecast, a cash buffer, a CourtListener capacity check and data-fee results.

The forecast has cash bottoming out at −$53.20 in July 2027 and turning positive in August. cfo.ai recommends $8,500 of opening cash. `docs/cfo-ai-plan.md` sums up both exports, and every figure in it was recomputed independently from the workbook inputs.

## The agent recovers from failures

- **Simulated outage:** run 36 paused after 5 citations ("simulated CourtListener outage"), and the next attempt resumed from the ledger with zero repeat calls.
- **Simulated crash:** run 37's process was killed after 6 citations; the next attempt resumed the same run.
- **Real quota:** the watcher paused at CourtListener's hourly limit and resumed on the next attempt; the healthy control paused at the daily limit (runs 41 and 42) with the refill time on its run page. With the quota spent, run 46 was started with `--courtlistener offline` and finished all 50 control citations from the ledger and the Caselaw Access Project, with no CourtListener calls.
- **Real network failure:** the held-out benchmark run lost its connection mid-lookup; the client now retries dropped connections and 5xx errors three times with backoff (`232a7d3`), and the rerun finished.

## You built in public

Posts tagged #neatHack, linked in the submission.

## You wrote the code during the hackathon

Every commit is dated October 10 to 12, 2026: `git log --format='%h %ad %s' --date=iso`.
