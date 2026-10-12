# Demo script (3 minutes)

The neatHack video has to show the problem, the agent, how cfo.ai and Entire were part of the build, and how neatlogs identified and resolved incidents. Every number below comes from a stored run, trace or score file, named next to it.

Before recording, open these tabs:

1. The *Mata v. Avianca* sanctions opinion (ECF 54) on CourtListener.
2. The live site, [gainsay.vercel.app](https://gainsay.vercel.app), on run 47 (Mata ECF 21) and run 50 (Gauthier ECF 41).
3. The neatlogs dashboard, with the traces in the neatlogs section below ready to paste into its search.
4. A terminal in the repo, for `git log` and the watcher.
5. `docs/cfo-ai/gainsay-revised-plan.xlsx` on its operating forecast sheet.

## 0:00 to 0:20, the problem

Show ECF 54.

> In 2023, lawyers in Mata v. Avianca filed a brief citing cases that don't exist. The other side spent weeks proving it, and courts have found the same thing in many filings since. Gainsay reads the other side's filings off the public docket and checks every case they cite, before you have to answer them.

## 0:20 to 1:15, the agent on two sanctioned filings

Open run 47, Mata ECF 21.

1. The opening sentence, "12 of 16 citations have a problem", and the strip: one bar per citation in filing order.
2. *Varghese*: Not found in searched sources. CourtListener's name search found nothing, and the Caselaw Access Project's volume list shows 925 F.3d 1339 is a page in the middle of *J.D. v. Azar*.
3. *Kaiser Steel*: the case is real, but Claude, reading passages the code pulled from it, found it's about abstention on a New Mexico question, not the bankruptcy stay. The pincite flag says 391 U.S. 593 ends at page 595, and the filing cites page 598.
4. *El Al v. Tseng*: Quote not in opinion. The closest text in the decision scores 57 out of 100.

> Scored against the court's own findings, which Gainsay is blocked from reading: it matches the court on 10 of 13 cases, calls 5 of the 7 missing cases Not found, and calls no real case Not found. The other two are cited only to Westlaw, so it says Unverifiable instead of guessing. (`scoring/results/run-47-score.json`)

Open run 50, Gauthier ECF 41.

> A second sanctioned filing, from Texas in 2024. The court found two cases that don't exist and six misquotes. Gainsay catches all six misquotes and marks none of the eight Verified. It also flags *Higginbotham*: the brief says the case is about falsified testing records, and page 412 of the opinion says it's about hiding overstated profits from an auditor. (`scoring/results/run-50-score.json`)

## 1:15 to 1:35, running on its own

Show `dockets/mata-v-avianca.json` and the watcher's output.

> Point it at a docket and it polls for new entries, picks the other side's filings by who filed them, and checks only the ones it hasn't finished. On the Mata docket it found 17 filings by the plaintiff's side. Everything it fetches is kept, so a rerun costs zero CourtListener calls and zero Claude calls (run 43).

## 1:35 to 2:15, neatlogs: incidents found and fixed

Each run attempt is one `gainsay.check_run` trace, with a `gainsay.check_citation` span per citation carrying the five outcomes, and the Claude calls inside.

1. **A real outage.** Paste run 42's trace, `8e1c90fdb9909ea2f1d6cdcd6737754d`. The healthy control (Avianca's own brief, ECF 18) stopped after 7 of 50 citations: the run span ends paused with "CourtListener day budget exhausted". The spans show what had settled and nothing was lost.
2. **The fix.** Paste run 46's trace, `1c61776418e5d0b1a5bb160207b778ea`. Rerun with `--courtlistener offline`, answering from the ledger and the Caselaw Access Project: all 50 citations, no CourtListener calls. One of its 7 flags is a real miscite in Avianca's brief, *Vumbaca* at 859 F. Supp. 343 instead of 859 F. Supp. 2d 343.
3. **Recovery, forced.** Run 36 paused on a simulated outage after 5 citations (`03f424545ef1a0c86acb77b2ada29f0b`), and the next attempt (`c6cb21331eeb15d38cce665043584055`) resumed without repeating a call. Run 37 was killed mid-run and resumed the same way. Both are labelled "simulated" in the ledger, the run page and the trace.
4. **Quality regressions.** The same control before and after its fixes: run 45 flagged 10 of 50 (`87606e6faca34cda955a327f68069c34`), run 46 flagged 7.

## 2:15 to 2:35, Entire

Run `git log -3` in the terminal.

> Every commit after the two that set Entire up carries an Entire checkpoint trailer linking the coding session behind it: what was tried, what failed, and the numbers that drove the change, which also sit in each commit body. That's how the work carried across sessions, including when one coding agent ran out of context and another picked it up. `docs/entire/` has Entire's symbol-level analysis of the main fixes.

## 2:35 to 2:55, cfo.ai

Show the operating forecast sheet.

> cfo.ai modeled the business on measured costs: about 2.6 cents of Claude per citation and nothing for CourtListener. At $29 a watched docket a month, 39 dockets cover the fixed budget. The first plan had no monthly forecast. Once cfo.ai added one, cash dipped $53 below zero in July 2027, so it now recommends $8,500 of opening cash. (`docs/cfo-ai-plan.md`)

## 2:55 to 3:00, close

> Gainsay. Every flag comes with the decision text it rests on. The repo is github.com/winsznx/gainsay.
