# Part 9: Is the lift real?

**Cost:** Free

---

Part 6 ended on a headline. Something like "the skill changed the pass rate by plus fifty percent", in a color meant to look like good news. Eight comparisons produced that figure.

This chapter asks an uncomfortable question: are eight comparisons allowed to produce a figure at all?

## The problem

An AI agent won't give you the same answer twice. Same prompt, same model, same afternoon. One attempt passes, the next fails. Nothing changed except the weather inside the model.

So when the skill wins six of eight, you don't know whether you have a good skill or a good afternoon.

People publish before checking this. Then the result that looked solid on the first run falls apart on the fifth, and the number has to be taken back in public. Ten free minutes here would have caught it.

## Three letters

```text
n  how many attempts you ran for one case
c  how many of those attempts passed
k  how many tries you would give the agent in real life
```

## Four questions

### If it gets k tries, does at least one work?

Written **pass@k**. The number that matters when a human reviews the output anyway. One good attempt out of several counts as a win.

The arithmetic is `1 - C(n-c, k) / C(n, k)`, where C counts the ways to choose. The tempting shortcut, `1 - (1 - c/n)^k`, flatters small samples. Small samples are all you have.

### If it gets k tries, do all of them work?

Written **pass^k**. The one to watch when the skill has to work every time, because nobody downstream is checking.

### How far would the answer move if you ran the whole thing again?

You can't afford to. So take the results you have, draw from them at random a couple of thousand times, and watch how far the average wanders. Report the middle 95 percent of where it landed.

That's a **bootstrap confidence interval**. If the range includes zero, you haven't shown the skill helps. It may well. This data can't say.

### What are the odds this is just luck?

Suppose your skill does nothing. Then each comparison is a coin flip, and a win is as likely as a loss. Count how many of the possible coin-flip patterns would come out at least as lopsided as the one you got.

That share is the **p-value**, from a sign-flip test. Below 0.05 is the usual bar for "probably not luck".

## What the stored run found

The A/B lift is +1.00 over 8 pairs. The bootstrap interval is [0.75, 1.00]. The p-value is below 0.01.

Part 9's verdict: the result is real.

It also adds: at 8 pairs, anything under about 0.35 would have been noise. The threshold moves with your sample size.

## The honest bit most write-ups skip

With pass-or-fail outcomes and small samples, noise is measured in tenths. You need hundreds of runs to see a five-point effect with confidence.

Published benchmarks put the average skill at a few points. Most add nothing measurable. If your A/B says "placebo", the eval may be working fine.

---

## Run it

```python
configure_logging("09_statistics")
# ... reads results from part 6, computes pass@k, intervals, p-values
```

Logs go to `logs/09_statistics.log`. Nothing runs. Nothing here costs a thing.

Part 10 asks whether anything got worse since the last run you trusted.

---

[Previous: Part 8 - Trajectory eval](part8_trajectory_eval.md) | [Next: Part 10 - Regression check](part10_regression_check.md)
