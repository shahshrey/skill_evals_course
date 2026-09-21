# Part 5: Grading with code

**Cost:** Agent runs

---

The skill turns up. Now: is the work any good?

This chapter grades the agent's output using the deterministic checks from `commit_message_checks.py`. Text in, pass or fail out. No AI anywhere. Free, instant, same answer every time.

## Proving the grader first

Before trusting a grader, prove it works on known inputs.

### The oracle

A hand-written answer that should pass every check. If the marker rejects this, the marker is broken.

```python
ORACLE_REPLY = """```text
feat(api): Add pagination to user list endpoint

Implement cursor-based pagination for the /users endpoint to handle
large datasets efficiently. Adds limit and cursor query parameters
with sensible defaults.

Refs: ACME-1234
```"""
```

### The null

An answer that looks fine for about two seconds and breaks four rules. If the marker accepts this, it's not checking hard enough.

```python
NULL_REPLY = "Docs(readme): Documented the environment variables."
```

No code fence. Subject over 50 characters. Wrong type casing. Missing trailer. The grader should catch all four.

## Why one attempt per case

This chapter runs one attempt per case, on purpose. The goal isn't to estimate a pass rate. The goal is to prove the grader by running it on real agent output and spot-checking the verdicts.

## The checks

For the commit-message skill, the checks include:

- `has_code_fence`: Output is wrapped in ```text
- `subject_max_50`: Subject line is 50 characters or less
- `type_in_set`: Type is one of feat, fix, docs, style, refactor, test, chore
- `scope_in_set`: Scope is one of api, cli, web, docs, config
- `has_refs_trailer`: Ends with `Refs: ACME-1234` or similar
- `imperative_mood`: Subject uses imperative ("Add" not "Added")

Each check returns its name, pass/fail, and a note explaining what it saw.

## What the stored run found

The grader passed the oracle. The grader failed the null on exactly the four rules it should have. Real agent outputs varied. The chapter shows which checks passed and failed, with the notes.

---

## Run it

```python
configure_logging("05_deterministic_grading")
sanity_check_grader()  # oracle and null
# ... then runs the agent on each case
```

Results go to `results/05_deterministic_runs.jsonl`. Logs go to `logs/05_deterministic_grading.log`.

This tells you how many rules the agent got right with your skill installed. It can't tell you the only thing that matters: did it need your skill to do that? Maybe a plain agent writes the same message. That's part 6.

---

[Previous: Part 4 - Does the real harness trigger it?](part4_does_the_real_harness_trigger_it.md) | [Next: Part 6 - Paired A/B comparison](part6_paired_ab_comparison.md)
