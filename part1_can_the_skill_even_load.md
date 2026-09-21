# Part 1: Can the skill even load?

**Cost:** Free

---

This one costs nothing and finishes in milliseconds. No AI runs. Nothing goes over the network. It asks a smaller question than the one you care about: is this SKILL.md well-formed enough that the software can pick it up at all?

You'll want to skip it. Everyone wants to skip it. Then they meet the failures.

## The failures nobody sees

A skill whose name doesn't match its folder never loads. A description that never says when to use the skill never gets picked. One code fence you forgot to close swallows every instruction below it.

None of these prints an error. The skill sits there doing nothing while you reread your prompt, convinced the model has stopped listening. The model never saw your skill. You typed a hyphen where the folder had an underscore.

So check the boring things first. The boring things fail silently.

## What gets checked

The rules come from the [Agent Skills specification](https://agentskills.io), plus a few extra for the mistakes people make in practice.

### In the settings block at the top

- It parses as YAML at all
- Name and description are both present
- The name is lowercase letters, digits, and single hyphens, no longer than 64 characters, and matches the folder name
- The description is under 1024 characters and says when to use the skill
- No settings that aren't in the specification

### In the instructions below

- They aren't empty
- Under 500 lines
- Every ``` fence has a matching close
- Every file the instructions point at actually exists

## What this doesn't tell you

Whether the skill is any good. It tells you the door opens.

A perfectly formatted file can still tell the agent to read your SSH keys. That's what part 2 is for. It costs nothing either.

---

## Run it

In `skill_evals.ipynb`, find the chapter one cells. They run `lint_skill()` on your skill folder and `lint_report()` to print the results.

The chapter also runs on `fixtures/bad_skills/sneaky-helper`, which is malformed and hostile on purpose. Watching it fail proves the checks catch something.

```python
lint_report(SKILL_DIR)
lint_report(FIXTURES_DIR / "bad_skills" / "sneaky-helper")
```

Logs go to `logs/01_structural_lint.log`.

---

[Previous: Part 0 - The kit and the ruler](part0_the_kit_and_the_ruler.md) | [Next: Part 2 - Is the skill hostile?](part2_is_the_skill_hostile.md)
