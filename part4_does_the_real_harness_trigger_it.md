# Part 4: Does the real harness trigger it?

**Cost:** Agent runs (this is where the bill starts)

---

Everything so far has been you and a text file. Part 3 gave you two educated guesses about whether your description would win the request. Both were arithmetic standing in for a decision they never watched happen.

Now you stop guessing. This installs the skill in a fresh folder, starts the real Claude Code, types a real request, and watches.

## What's under test

Still that one line of description. When you ask Claude Code for something, it doesn't read your instructions. It reads each installed skill's name and description, picks the one that looks relevant, and only then opens what you wrote. Everything below the description is a prize. The description has to win it alone.

This is the test you re-run every time you touch that sentence.

## The method

Some requests that ought to load the skill, some that ought not to, each run a few times, and a count of what happened.

```python
TRIGGER_REPS = 2  # three is common. More attempts, less noise, larger bill.

TRIGGER_POSITIVES = [
    ("add_paging", commit_prompt(read_fixture("diffs/add_paging_to_api_client.diff"))),
    # ...
]

TRIGGER_NEGATIVES = [
    ("rebase_help", "How do I rebase my branch onto main?"),
    # ...
]
```

## Two mistakes almost everyone makes

**Only testing the requests that should work.** Write "use this for anything git related" and it will load for every commit message you ask for. It will also barge in on rebases, pull request descriptions, and changelogs. You'll never see it, because you only tested the cases you wanted to pass.

**Running each request once.** The decision is not repeatable. Ask the same question twice and you can get two different answers. One run tells you almost nothing. Run each a few times and take a majority.

## Counting correctly

Whether the skill was installed and whether the agent went and read it are two different questions. `skill_was_loaded()` in the kit counts both routes: the Skill tool and reading `SKILL.md` directly. Either way your description did its job.

## Two ways of being wrong

**Firing when it shouldn't.** The description is greedy. It's claiming requests that belong elsewhere.

**Missing requests it should catch.** The description lacks the words people type.

They pull in opposite directions. That's what makes writing a description harder than writing the skill.

## What the stored run found

Precision 1.00, recall 1.00 over 14 runs. Every positive loaded the skill. Every negative didn't.

---

## Run it

```python
configure_logging("04_trigger_eval")
# ... starts Claude Code 14 times
```

Results go to `results/04_trigger_runs.jsonl` and `results/04_trigger_summary.json`. Logs go to `logs/04_trigger_eval.log`.

This proves the skill turns up. It says nothing about whether the output is any good. That's part 5.

---

[Previous: Part 3 - Does the description route?](part3_does_the_description_route.md) | [Next: Part 5 - Grading with code](part5_grading_with_code.md)
