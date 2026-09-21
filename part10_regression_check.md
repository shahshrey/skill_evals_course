# Part 10: Regression check

**Cost:** Free

---

Part 9 told you whether today's result was real. It said nothing about tomorrow.

Skills go off. A description that triggered reliably in March stops triggering in June, because the software underneath changed how it picks skills. A rule you tightened in the body breaks a case that used to sail through. Nobody spots either one. Nobody goes back and runs the tests a second time.

## What this does

Takes the numbers from the last run you were happy with, holds today's up against them, and makes a scene when something has fallen.

## Telling two situations apart

No single pass rate could do this. This chapter can.

**You edited the skill and a number dropped.** That's the ordinary price of changing something. You get a warning. Whether the trade was worth it stays your call.

**You touched nothing and a number dropped anyway.** Something underneath you moved. The model, or the software running it. You found out from a test rather than from a colleague. That's an error, and it stops the build.

It tells the two apart by fingerprinting the skill folder. Same fingerprint, same skill. Any drop belongs to somebody else.

## The baseline

```python
BASELINE_PATH = RESULTS_DIR / "baseline.json"
TOLERANCE = 0.25  # a fall of this much or more counts as a real drop
```

The first run with no baseline saves today's numbers. Every run after that compares.

## What gets compared

- Trigger precision (from part 4)
- Trigger recall (from part 4)
- Pass rate with skill (from part 6)
- Pass rate without skill (from part 6)
- Skill lift (the difference)

## What the stored run found

No baseline existed, so the first run saved one. Subsequent runs would compare against it.

---

## Run it

```python
configure_logging("10_regression_check")
# ... reads results from parts 4, 5, and 6
```

Logs go to `logs/10_regression_check.log`. Nothing runs. Refreshing the source files is where all the money went.

One question is left. Your skill works and holds up. What is it costing you every time it runs? Part 11 asks.

---

[Previous: Part 9 - Is the lift real?](part9_is_the_lift_real.md) | [Next: Part 11 - What it costs](part11_what_it_costs.md)
