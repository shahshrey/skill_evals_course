# Skill evals, one file per eval type

Eleven small Python files. Each one shows a different way to evaluate an
agent skill: a folder with a `SKILL.md` that a harness such as Claude Code
loads on demand. (The harness is the program around the model: it decides
which skills the model can see, runs the tools, and keeps the conversation
going. Skills are a harness feature, which matters for how you test them.)
All eleven files evaluate the same sample skill, `skills/commit-message`,
so you can read them in order and watch one skill get tested from every
angle.

## The files

| File | Question it answers | Needs a model? |
|---|---|---|
| `01_structural_lint.py` | Is the SKILL.md well-formed enough to load? | no |
| `02_security_scan.py` | Does the skill try to do something hostile? | no |
| `03_routing_offline.py` | Does the description contain the words users type, without colliding with neighbours? | no |
| `03b_routing_semantic.py` | Same question by meaning: a fast typed model (Jev) picks a skill from the catalog, with probabilities that expose collisions | Jev calls only |
| `04_trigger_eval.py` | Does the real harness load the skill when it should, and only then? | yes |
| `05_deterministic_grading.py` | Does the output follow the rules we can check with code? | yes |
| `06_ab_comparison.py` | How much better is the agent with the skill than without? | yes |
| `07_llm_judge.py` | What about the rules only a reader can check? | judge calls only |
| `07b_fast_judge.py` | Same questions to a fast typed-judgment model (Jev), with probabilities and a cross-check against 07 | Jev calls only |
| `08_trajectory_eval.py` | Did the agent follow the procedure and respect the prohibitions? | yes |
| `09_statistics.py` | Is the lift real or noise? | no |
| `10_regression_check.py` | Did anything get worse since the last run you trusted? | no |
| `11_efficiency_eval.py` | What does the improvement cost in tokens, dollars and time? | no |

The numbering groups the files by cost: three that are free, five that run
the real agent, three that only analyse saved rows. If you would rather
follow one thread, read 09 straight after 06, since it exists to interpret
06's numbers, and read 10 last, since it snapshots what all the others saved.

Every record in the course is a Pydantic model with a description on
each field: the skill, an agent run and its tool calls, a check result, a
lint or scan finding, the reply shapes the judge must return, and the row
each live script writes to `results/`. The descriptions are the
documentation for those files, the judge's reply model is the JSON schema
the API enforces, and a row that does not match its model fails loudly
instead of silently.

Every script that touches the skill opens with a "skill under test" panel:
its name, its folder, and the description the harness routes on. The live scripts then show the exact prompt each case sends
and the agent's reply in a box before grading it; 06 shows the two arms'
replies side by side. The three demo scripts (06 with 09, 07b, and 08)
also narrate themselves as they run, in yellow boxes titled "what happens
next", "what this means" and "how to read this", with the meaning written
from the actual outcome. Set `SKILL_EVAL_EXPLAIN=0`
to silence them once you know the material.

Every file marks the exact line where something real happens. Search for
`>>> LIVE CALL` to find where the Claude Code CLI or a model is invoked,
and `>>> NO LIVE CALL` in the files that only compute over saved rows.

Two support modules:

- `skill_eval_common.py` runs the agent in a throwaway project with or
  without the skill installed, and records everything an eval might grade:
  final text, every tool call, tokens, cost, duration. Read this first.
- `commit_message_checks.py` holds the deterministic checks and the case
  list for the sample skill. Everything specific to commit messages is here,
  so swapping in your own skill means editing this file and the fixtures.

## Running

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Free. Run each on the sample skill, then on the deliberately broken one,
# so you see what a failure looks like.
python 01_structural_lint.py
python 01_structural_lint.py fixtures/bad_skills/sneaky-helper
python 02_security_scan.py
python 02_security_scan.py fixtures/bad_skills/sneaky-helper
python 03_routing_offline.py
python 03b_routing_semantic.py        # needs TYPESAFE_API_KEY; about 2 seconds

# Real agent runs from here on.
python 04_trigger_eval.py
python 05_deterministic_grading.py
python 06_ab_comparison.py            # saves results/06_ab_runs.jsonl
python 07_llm_judge.py                # grades 06's saved rows; judge calls only
python 07b_fast_judge.py              # same rows through Jev; needs TYPESAFE_API_KEY
python 08_trajectory_eval.py

# No model calls of their own: these read what 04, 05 and 06 saved, and run
# those scripts first if the rows are missing.
python 09_statistics.py
python 11_efficiency_eval.py
python 10_regression_check.py --save-baseline   # then re-run 04-06 later and
python 10_regression_check.py                   # compare against the snapshot
```

The live files drive Claude Code through the official `claude-agent-sdk`,
which works with a Claude Code login and needs no API key. The two
exceptions are the "b" variants, `03b_routing_semantic.py` and
`07b_fast_judge.py`, which call TypeSafe's Jev and read `TYPESAFE_API_KEY`
from the environment or a `.env` file. Jev returns typed judgments with
probabilities in about a tenth of a second, so those two run on every edit
where their full-size counterparts run once. That choice is
deliberate. Skills are loaded by the harness, not the model, so pasting a
SKILL.md into a raw API system prompt would never tell you whether the
description triggers. Here the skill is copied into `.claude/skills/` in a
fresh temp folder, exactly as a user would install it.

Every script logs what it is doing as it goes: which case is running,
whether the skill was installed, each tool call the agent makes, each
grading decision, and where results were saved. On the terminal the logs
are coloured (via the rich library): green for passes, red for failures,
cyan for tool calls, magenta for the with and without arms, yellow for case
names. The same lines go to `logs/<script>.log` as plain text.

The output has landmarks so you can find things: a labelled rule opens each
phase and each case, so one run's tool calls do not blur into the next; the
results come as tables; and the one number to take away sits in a box at
the end, green when it is good news and red when it is not. Logs go to
stderr and results to stdout, so `python 06_ab_comparison.py > results.txt`
keeps the tables and drops the play-by-play. Set `SKILL_EVAL_LOG=debug` to also see full prompts,
tool inputs and judge replies. The printed tables at the end are the
results; the log lines are how they came about.

Each live run costs a real agent turn. The defaults are tiny (four cases,
one or two reps) so a full pass stays cheap. `09_statistics.py` will tell
you, correctly, that eight pairs cannot resolve a twenty-point effect. That
is the lesson, not a bug: raise `REPS` when you need a number you can defend.

## Words the files use

- An arm is one side of a comparison: the with-skill arm and the
  without-skill arm.
- An oracle is a hand-written answer that should pass every check; a null
  is one that should fail. Both are used to prove a grader before trusting
  it.
- A trajectory is the ordered list of tool calls an agent made on the way
  to its answer.
- pass@k is the chance that at least one of k attempts passes; pass^k is
  the chance that all k do.
- A bootstrap interval is a range for a metric, found by re-sampling your
  own rows many times. A sign-flip test asks how often pure chance would
  produce a lift as large as the one you saw.
- Skill lift is the with-skill pass rate minus the without-skill pass rate.

## The sample skill

`skills/commit-message/SKILL.md` writes commit messages in a made-up house
style: a fixed set of types and scopes, a 50-character subject, a required
`Refs: ACME-1234` trailer, output only inside a ```text fence, and never run
`git commit`. It is made up on purpose. A skill for something the model
already knows (plain Conventional Commits) shows almost no lift, so you
learn nothing from the A/B. The rule is: make the task not answerable from
memory.

Every rule in the skill maps to an eval: the format rules to
`commit_message_checks.py`, the "why not what" rule to the judge, the "read
the diff first" step and the git prohibition to the trajectory eval.

## Fixtures

- `fixtures/diffs/` are the four inputs, each with a known right type and scope.
- `fixtures/bad_skills/sneaky-helper/` is a deliberately hostile and
  malformed skill so 01 and 02 have a known-bad case. Do not install it.
- `fixtures/catalog/` are three decoy skills that overlap with ours on
  vocabulary, so 03 has something to collide with.

## What every good eval setup agrees on

The same handful of rules keeps coming back, whoever builds the harness.

1. Test the description before the body. A skill that does not trigger
   cannot help. Run positives and negatives, several times each.
2. Grade with code wherever you can, and prove the grader on a known-good
   and a known-bad answer before trusting it. Use a judge only for what
   code cannot see, and calibrate the judge the same way.
3. Pair the with and without runs, hold everything else fixed, and report
   the delta with an interval. One run is an anecdote.
4. Grade the end state and the tool log, not the transcript's narration.
5. Keep the skill files physically absent from the baseline workspace. A
   flag is not enough; the agent can go and read them.
6. Save every raw row. 09 and 11 re-read what 06 saved, 10 re-reads what
   04, 05 and 06 saved, and 07 grades 06's saved outputs, so none of them
   pays for a new agent run.

One thing worth knowing before you start: published benchmarks put the
average software engineering skill at a few points of lift, and find that
most add nothing measurable. If your A/B says "placebo", the eval may be
working fine.

## What the sample runs found

Every file runs on its own. The offline ones (07, 07b, 09, 10, 11) analyse
rows that a live script saved to `results/`; when those rows are missing
they run the producing script first, then continue. `results/` is not
committed (it is in `.gitignore`, next to `.env`), so the first offline
file you run will spend the agent runs to fill it, and every one after that
reuses them. That is the habit the course teaches: pay for agent runs once,
analyse them as often as you like. The first full pass surfaced four things
worth knowing before you run your own.

- The offline routing test caught a real vocabulary gap. "summarise these
  changes for git" routed to the git-help decoy because the description
  never said "changes". Adding the word fixed it. The live trigger eval then
  scored precision 1.00 and recall 1.00 over 14 runs.
- The A/B lift was +1.00 over 8 pairs (with skill 8/8, without 0/8). The
  baseline never produced the Refs trailer or the fence, which is the point
  of a made-up house style: the model cannot know it. The bootstrap interval
  is tight only because the effect is total; with 8 pairs the noise floor is
  about 0.35.
- An earlier version of the judge had a
  third assertion, "no commentary outside the commit message", and it
  failed 7 of 8 with-skill outputs. Reading those outputs showed the judge
  counting the ```text fence itself as commentary. The assertion was
  replaced, and the lesson stayed in a comment at the top of the file:
  spot-check the failures, because some of them are grader bugs.
- The trajectory eval found a boundary the skill does not hold. When the
  user says "go ahead and commit them", the agent loads the skill, then runs
  `git commit` anyway. The skill's rule 7 is not strong enough against a
  direct request. That is a finding about the skill, and the eval that
  found it is the only one of the eleven that could have.

The efficiency eval classifies the skill as a TRADEOFF: pass rate up from 0
to 1, cost roughly doubled. The cost comes from turns, not from the
skill body: a with-skill run takes three turns (load the skill, read the
result, answer) where the baseline takes one, and each turn re-reads the
whole context.

## Swapping in your own skill

Point `SKILL_DIR` in `skill_eval_common.py` at your folder, rewrite
`commit_message_checks.py` with checks and cases for your skill, and replace
the fixtures. Then edit the prompts that are specific to commit messages:
the positive and negative prompts and the decoy catalog in
`03_routing_offline.py`, the negative prompts in `04_trigger_eval.py`, the
assertions at the top of `07_llm_judge.py`, and the trajectory checks in
`08_trajectory_eval.py`. Files 01, 02, 05, 06, 09, 10 and 11 need no
changes.
