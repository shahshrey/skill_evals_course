# Part 6: Paired A/B comparison

**Cost:** Agent runs (the most expensive chapter)

---

Part 5 told you how many rules the agent got right with your skill installed. It couldn't tell you the only thing that matters: did it need your skill to do that?

Maybe a plain agent writes the same message. Maybe the model already knew. You can't tell, because you never asked with the skill taken away.

So ask.

## The method

The same request, twice. Once with the skill installed. Once in an identical empty folder with no skill anywhere. Mark both the same way. Read the gap.

Every serious benchmark of this kind is this loop wearing a longer paper.

```python
AB_REPS = 2  # attempts per case on each side
```

## Three rules that keep it honest

**Change one thing.** Same model, same request, same tools, same empty starting folder. The only difference is whether the skill's files are present. Switching the skill off with a flag doesn't count. The files are still there, and the agent can read a file.

**Compare like with like.** Each case runs twice on each side. The two sides of one attempt stay together as a pair. Paired results are steadier than two separate averages. Part 9 leans on that pairing hard. Break it here and you quietly invalidate that chapter too.

**Report the gap, never the headline alone.** "The skill scores 100 percent" means nothing if the plain agent was already at 95. Published figures for the average software engineering skill sit at a few percentage points. A good number land on zero. Be ready for that. A skill that changes nothing is a real result. Finding out costs less than maintaining it for a year.

## Marking

Done by the free code checks from `commit_message_checks.py`. Every penny here goes on agent runs, none on marking.

## What the stored run found

The A/B lift is +1.00 over 8 pairs. With skill: 8/8. Without: 0/8.

The baseline never produced the Refs trailer or the code fence. That's the point of a made-up house style: the model can't know it.

Broken down by rule:

| Check | With skill | Without | Lift |
|-------|------------|---------|------|
| has_code_fence | 1.00 | 0.00 | +1.00 |
| has_refs_trailer | 1.00 | 0.00 | +1.00 |
| subject_max_50 | 1.00 | 0.75 | +0.25 |
| type_in_set | 1.00 | 0.88 | +0.12 |

The checks the plain agent already passes are not where your skill adds value.

## This is the source for everything downstream

The answers saved here get marked again by a model in part 7, tested in part 9, compared against last month in part 10, and priced in part 11.

You pay for these runs once. Five chapters live off them.

---

## Run it

```python
configure_logging("06_ab_comparison")
# ... starts Claude Code 16 times (4 cases × 2 reps × 2 arms)
```

Results go to `results/06_ab_runs.jsonl`. Logs go to `logs/06_ab_comparison.log`.

Part 7 goes after the rules code can't check.

---

[Previous: Part 5 - Grading with code](part5_grading_with_code.md) | [Next: Part 7 - LLM as judge](part7_llm_as_judge.md)
