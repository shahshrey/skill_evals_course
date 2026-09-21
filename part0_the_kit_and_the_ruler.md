# Part 0: The kit and the ruler

**Cost:** Free

---

Before any chapter runs, two files set up the machinery everyone else borrows.

## The kit

`eval_kit.py` does four things:

1. **Runs the agent.** Copies your skill into a fresh temp folder, starts the real Claude Code, types your prompt, and records everything that happens.
2. **Records what happened.** Final text, every tool call, tokens in and out, cost, duration. All of it saved, so later chapters can re-read without re-running.
3. **Checks whether the skill loaded.** Either through the Skill tool or by reading `SKILL.md` directly. Both count. Every chapter uses this one definition.
4. **Displays results.** Colored log lines, tables, side-by-side comparisons.

The four configuration cells at the top of the notebook are the only things you change to test a different skill:

```python
eval_kit.SKILL_DIR = HERE / "skills" / "commit-message"
eval_kit.AGENT_MODEL = "claude-opus-5"
eval_kit.JUDGE_MODEL = "claude-sonnet-5"
eval_kit.DEFAULT_TOOLS = ["Skill", "Read", "Bash"]
```

## The ruler

`commit_message_checks.py` is the measuring stick that parts 5, 6, 8, and 10 pick up. It holds:

- **Checks.** Ordinary functions. Text in, pass or fail out. Same answer every time, forever. No AI anywhere.
- **Cases.** The four test inputs, each with a known right type and scope.

Every check reports its own name and a short note on what it saw. "subject_max_50 failed: 61 characters" tells you which line to edit. "score 0.7" does not.

Both files are imported in the notebook's first cells. Start the notebook from this folder so the imports find them.

## Why drive the real program

These chapters drive the real Claude Code instead of calling an API. That's slower. Here's why it's worth it.

The model doesn't choose the skill. The software around it does. Claude Code reads every installed skill's description, decides which one fits, and only then shows the model the instructions inside. Paste your SKILL.md straight into an API prompt and you skip that decision. You'll never find out whether your description is good enough to get picked.

A skill that never gets picked is not a skill. It's a file.

## Pydantic models

Every record is a Pydantic model with a description on each field. The skill, an agent run and its tool calls, a check result, a lint or scan finding, the reply shapes the judge must return, and the row each chapter writes to `results/`.

The descriptions are the documentation for those files. The judge's reply model is the JSON schema the API enforces. A row that doesn't match its model fails loudly instead of silently.

---

## Run it

Open `skill_evals.ipynb` and run the first few cells. They import the kit and ruler, set the configuration, and print the skill under test.

---

[Next: Part 1 - Can the skill even load?](part1_can_the_skill_even_load.md)
