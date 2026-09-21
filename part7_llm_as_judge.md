# Part 7: LLM as judge

**Cost:** Judge calls + Jev calls

---

Four chapters have now marked the agent's final answer. Code checks in parts 5 and 6. But some rules can't be checked with code.

"The subject line should be imperative mood" can be pattern-matched. "The body should explain why, not just what" cannot. Only a reader can tell.

So bring in a reader.

## Part 7a: The big judge

A large model reads each answer and checks it against a rubric. Each assertion asks about one thing:

```python
ASSERTIONS = [
    "The subject line is in imperative mood (e.g., 'Add' not 'Added' or 'Adds')",
    "The body explains WHY the change was made, not just WHAT changed",
    "The commit message is self-contained and does not reference the skill instructions",
]
```

### Pydantic reply models

The judge must return structured JSON. Pydantic models define the shape:

```python
class AssertionVerdict(BaseModel):
    assertion_number: int
    passed: bool
    reasoning: str

class RubricReply(BaseModel):
    verdicts: list[AssertionVerdict]
```

The API enforces the schema. A judge that rambles instead of answering fails to parse.

### Pairwise comparison

After the rubric, the judge compares pairs. "Which of these two commit messages better follows this house style?" The order is randomized. If the judge picks the same winner regardless of order, it meant it.

### Proving the judge

Same as part 5. Show it a known-good and known-bad answer. If it passes the bad one or fails the good one, the judge is broken.

### Spot-check the failures

An earlier version of the judge had a fourth assertion, "no commentary outside the commit message". It failed 7 of 8 with-skill outputs. Reading those outputs showed the judge counting the ```text fence itself as commentary. The assertion was dropped.

The lesson: spot-check the failures. Some of them are grader bugs.

### What the stored run found

Both markers picked the with-skill answer 8 times out of 8 and never contradicted themselves on the pairwise comparison.

---

## Part 7b: The fast judge (Jev)

Part 7a sat a large model down with each answer and waited while it wrote out reasoning. That works. It takes seconds per answer and costs real money. So a marker like that usually gets pointed at a handful of cases once, then quietly retired.

Jev does the same job differently. You hand it text and a yes-or-no question. It hands back a probability. A tenth of a second, a fraction of a penny. All three questions across all sixteen answers finish before the big model has gotten through its first one.

### Why cheap marking changes things

**You stop rationing it.** A checklist that costs nothing runs on every change, forever, without anyone deciding it's worth it.

**You get a number instead of a verdict.** 0.95 and 0.55 both round to yes. They're nowhere near the same answer. Keep the number. Put the threshold in your own code.

### Cross-checking against the big judge

Run both markers on the same answers. The last column of the results table is the share where they agreed. Two markers built on different technology reaching the same conclusion is better evidence than either alone.

Where they disagree, one of them is wrong. The only way to find out which is to read the answer yourself.

### What the stored run found

Jev agreed with the big judge on every verdict.

---

## Run it

### Big judge

```python
configure_logging("07_llm_judge")
sanity_check_judge()
# ... grades each answer from part 6
```

Results go to `results/07_judge.jsonl`. Logs go to `logs/07_llm_judge.log`.

### Fast judge (Jev)

Needs `TYPESAFE_API_KEY` in your environment or `.env` file.

```python
configure_logging("07b_fast_judge")
# ... same answers, scored by Jev
```

Results go to `results/07b_fast_judge.jsonl`. Logs go to `logs/07b_fast_judge.log`.

Both markers have now told you whether the writing is good. Neither looked at what the agent did to produce it. Part 8 is where that matters.

---

[Previous: Part 6 - Paired A/B comparison](part6_paired_ab_comparison.md) | [Next: Part 8 - Trajectory eval](part8_trajectory_eval.md)
