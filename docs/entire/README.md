# Entire evidence

Every commit in this repository except the first two, which installed Entire, carries an `Entire-Checkpoint` trailer. The checkpoint stores the agent session behind the change, with secrets redacted, under `refs/entire/checkpoints/` in the author's repository. `git log --format='%h %(trailers:key=Entire-Checkpoint,valueonly) %s'` lists the pairs.

The checkpoint refs themselves aren't published here: the session transcripts quote the private product brief, which stays private. Session pushing is off in `.entire/settings.json`. The files below are Entire's own output from those checkpoints.

| File | What it shows |
|---|---|
| `checkpoint-list.txt` | `entire checkpoint list`: each checkpoint, its commit and the prompt that started it |
| `graph-checkpoint-69fddb1.txt` | `entire graph checkpoint`: what changed, by symbol, in the commit that turned Ehrlich from "Not found" into "Wrong case" after scoring run 6 against ECF 54 |
| `graph-checkpoint-9c6bb19.txt` | The same for the fixes ECF 45 exposed: verifying unpublished decisions by docket, history, cross-references and bracketed quotes |
| `graph-checkpoint-7bd84c5.txt` | The same for the reporter-series check prompted by LePhantomCite |
| `graph-impact-check_authority.txt` | `entire graph impact`: callers, callees and co-changing files for the existence and identity check, the function most fixes touched |

How it was used: each fix started from a measured failure (a score against ECF 54, a false flag in a real memorandum, a benchmark label), landed as one commit with the measured numbers in its body, and was rerun. The checkpoint keeps the reasoning and dead ends behind each one, which carried the context across sessions when one coding agent ran out of tokens and another picked up the work.
