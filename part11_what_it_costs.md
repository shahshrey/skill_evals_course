# Part 11: What it costs

**Cost:** Free

---

Ten chapters have been about whether your skill works. This one is about what working costs.

People skip that question. Then they answer it by accident six months later, when somebody asks why the invoice grew.

## The problem

A skill is not free. Every time it loads, its whole text gets added to what the model has to read, on every request. A skill that sends the agent off to open three reference files before it says anything can double the bill for a job it didn't improve.

## Two numbers

How much better the answers got. How much more the runs cost.

Put together, they give you a verdict:

```text
better and cheaper       -> PARETO_BETTER   keep it
better but dearer        -> TRADEOFF        your call, and it is a real one
no better, but cheaper   -> CHEAPER         keep it
no better and dearer     -> PARETO_WORSE    why is this skill here?
no better, same price    -> NEUTRAL         it is doing nothing, either way
worse                    -> REJECT
```

## The method

Average each column on each side and subtract. Two rules keep those averages honest.

**Token counts come from what the API reports.** Never from guessing at the length of your text. They count everything handed to the model, including from its cache. It read that either way. Leave the cache out and your skill looks free when it's nothing of the kind.

**Every number was written down on the run that produced it.** A run's cost and time describe that run. They're not rebuilt afterwards from an average that has forgotten which runs it came from.

## What the stored run found

The skill is a **TRADEOFF**: pass rate up from 0 to 1, bill up by about a quarter.

The extra cost comes from turns, not from the skill body. A with-skill run takes three turns (load the skill, read the result, answer) where the baseline takes one. Each turn re-reads the whole context.

| Metric | With skill | Without | Delta |
|--------|------------|---------|-------|
| Pass rate | 1.00 | 0.00 | +1.00 |
| Tokens (avg) | 12,400 | 9,800 | +26% |
| Cost (avg) | $0.31 | $0.25 | +24% |
| Duration (avg) | 18s | 14s | +29% |

## The last table

This is the fairest single number for comparing two skills, or two versions of the same skill. Quality per dollar.

---

## Run it

```python
configure_logging("11_efficiency_eval")
# ... reads results from part 6
```

Logs go to `logs/11_efficiency_eval.log`. Nothing runs. Nothing costs a thing.

---

## That's the last chapter

You started with a file that might not even parse. You end with a price per working answer.

Go back to part 1 whenever you edit the skill. The whole thing costs less than the afternoon you would otherwise spend arguing about whether it helps.

---

[Previous: Part 10 - Regression check](part10_regression_check.md) | [Back to README](README.md)
